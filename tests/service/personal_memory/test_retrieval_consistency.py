# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Index maintenance and receipts remain correct across edits, scopes and writers."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory import retrieval
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore
from tests.service.personal_memory.test_retrieval_quality import CORPUS, memory


def test_one_edit_does_not_retokenize_the_unchanged_library(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = tuple(memory(i, f"Component {i}", f"Inspect component {i}", "Cache invalidation") for i in range(500))
    retriever = retrieval.MemoryRetriever()
    assert len(retriever.search(entries, "cache", "", automatic=True)) == 32
    tokenized: list[str] = []
    original = retrieval._tokens

    def observed(text: str):
        tokenized.append(text)
        return original(text)

    monkeypatch.setattr(retrieval, "_tokens", observed)
    revised = replace(entries[0], revision=2, draft=replace(entries[0].draft, content="Use the updated cache key"))
    retriever.search((revised, *entries[1:]), "cache", "", automatic=True)
    assert tokenized == [revised.draft.title, revised.draft.when_to_use, revised.draft.content, "cache"]
    tokenized.clear()
    retriever.search((revised, *entries[1:]), "cache", "", automatic=True)
    assert tokenized == []


def test_private_vocabulary_does_not_change_another_workspaces_typo_lookup() -> None:
    public = CORPUS[6]
    private = memory(99, "xbservability", "A project-specific identifier", "xbservability")
    private = replace(private, draft=replace(private.draft, workspace="private"))
    retriever = retrieval.MemoryRetriever()
    assert [
        match.memory_id for match in retriever.search((public, private), "xbservability", "other", automatic=True)
    ] == [public.id]


def test_eviction_and_removal_leave_no_obsolete_postings() -> None:
    retriever = retrieval.MemoryRetriever()
    entry = CORPUS[6]
    for workspace in range(8):
        for query in range(70):
            assert retriever.search((entry,), f"observability {query}", str(workspace), automatic=True)
    assert len(retriever._index.views) == 4
    assert all(len(view.cache) == 64 for view in retriever._index.views.values())
    assert retriever.search((), "xbservability", "0", automatic=True) == ()
    assert not retriever._index.postings
    assert not retriever._index.anchors
    assert not retriever._index.spellings
    assert not retriever._index.identities
    assert not retriever._index.titles


def test_shared_retriever_does_not_mix_parallel_workspace_results() -> None:
    entries = tuple(replace(entry, draft=replace(entry.draft, workspace=str(i))) for i, entry in enumerate(CORPUS))
    retriever = retrieval.MemoryRetriever()

    def search(i: int) -> None:
        entry = entries[i % len(entries)]
        matches = retriever.search(entries, entry.id, entry.draft.workspace, automatic=True)
        assert [match.memory_id for match in matches] == [entry.id]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(search, range(80)))


def test_cached_snapshot_observes_atomic_replacement_with_same_size_and_mtime(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache", "Version A", "cache"), MemorySource())
    assert store.load().entries == (entry,)
    before = store.path.stat()
    raw = store.path.read_text(encoding="utf-8").replace("Version A", "Version B")
    atomic_write_owner_only_text(store.path, raw)
    os.utime(store.path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert store.path.stat().st_size == before.st_size
    assert store.recall("cache", "")[0][0].draft.content == "Version B"
    atomic_write_owner_only_text(store.path, "invalid")
    with pytest.raises(MemoryStoreError, match="invalid"):
        store.recall("cache", "")
    store.path.unlink()
    assert store.recall("cache", "") == ()


def test_cached_reads_still_enforce_secure_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chrys.service.personal_memory import store as store_module

    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Cache", "Check versions", "cache"), MemorySource())
    store.load()

    def denied(_path):
        raise PermissionError("owner check rejected")

    monkeypatch.setattr(store_module, "secure_open_owner_only_binary", denied)
    with pytest.raises(MemoryStoreError, match="safely"):
        store.recall("cache", "")


@pytest.mark.parametrize("change", ["correct", "pause", "forget", "off"])
def test_receipt_uses_the_state_inside_the_write_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    reader = PersonalMemoryStore(tmp_path / "memory.json")
    writer = PersonalMemoryStore(reader.path)
    entry = writer.save(MemoryDraft("Cache", "Old advice", "cache"), MemorySource())
    original = reader._update_receipts

    def intervening_writer(edit):
        if change == "correct":
            writer.save(
                replace(entry.draft, content="Corrected advice"),
                entry.source,
                memory_id=entry.id,
                revision=entry.revision,
            )
        elif change == "pause":
            writer.set_state(entry.id, entry.revision, "archived")
        elif change == "forget":
            writer.forget(entry.id, entry.revision)
        else:
            writer.configure("off", False)
        return original(edit)

    monkeypatch.setattr(reader, "_update_receipts", intervening_writer)
    matches = reader.recall("cache", "", session_id="one")
    if change == "correct":
        assert matches[0][0].draft.content == "Corrected advice"
        assert matches[0][1].revision == 2
        assert reader.load().recalls[0].matches == (matches[0][1],)
    else:
        assert matches == ()
        assert all(not recall.matches for recall in reader.load().recalls)
