# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Large catalogs, independent recall commits and recoverable history."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemoryRevision, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory import activity
from chrys.service.personal_memory import store as store_module
from chrys.service.personal_memory.store import PersonalMemoryStore


def test_recall_does_not_rewrite_the_catalog_and_survives_reopening(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    before = store.path.read_bytes()
    first = store.recall("technical slides", "", session_id="one", turn_id="a")
    assert first[0][0].id == entry.id
    assert store.path.read_bytes() == before
    reopened = PersonalMemoryStore(store.path)
    assert reopened.load().recalls[0].matches[0].memory_id == entry.id
    assert any(e.action == "provided" for e in reopened.history())


def test_old_revisions_are_available_after_hot_history_is_compacted(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Version 0", "technical slides"), MemorySource())
    for index in range(1, 8):
        entry = store.save(
            replace(entry.draft, content=f"Version {index}"),
            MemorySource(),
            memory_id=entry.id,
            revision=entry.revision,
        )
    assert len(store.load().entries[0].previous) == 1
    versions = PersonalMemoryStore(store.path).revisions(entry.id)
    assert [r.draft.content for r in versions] == [f"Version {i}" for i in range(6, -1, -1)]


def test_more_than_5000_memories_keep_the_same_recall_budget(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    base = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["entries"] = [
        asdict(replace(base, id=f"{i:016x}", draft=replace(base.draft, title=f"Slides {i}"))) for i in range(5001)
    ]
    atomic_write_owner_only_text(store.path, json.dumps(data))
    state = store.load()
    assert len(state.entries) == 5001
    assert len(store.recall("technical slides", "", session_id="one", turn_id="a")) == 5


@pytest.mark.parametrize("interrupted", [False, True])
def test_many_expired_candidates_are_archived_without_overflowing_the_activity_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    store.set_buddy_notifications(True)
    base = store.save(MemoryDraft("Slides", "An inferred habit", "technical slides"), MemorySource(), candidate=True)
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["entries"] = [
        asdict(replace(base, id=f"{i:016x}", created_at="2020-01-01T00:00:00+00:00")) for i in range(200)
    ]
    atomic_write_owner_only_text(store.path, json.dumps(data))
    if interrupted:
        original = store_module.atomic_write_owner_only_text
        failed = False

        def interrupted_write(path, payload):
            nonlocal failed
            if path == store.path and not failed:
                archived = sum(e["state"] == "archived" for e in json.loads(payload)["entries"])
                if archived == 200:
                    failed = True
                    raise OSError("simulated interrupted maintenance")
            return original(path, payload)

        monkeypatch.setattr(store_module, "atomic_write_owner_only_text", interrupted_write)
        with pytest.raises(OSError, match="simulated interrupted maintenance"):
            store.maintain()
        partial = PersonalMemoryStore(store.path).load()
        assert 0 < sum(e.state == "archived" for e in partial.entries) < 200
        store = PersonalMemoryStore(store.path)
    state = store.maintain()
    assert len(state.entries) == 200 and all(e.state == "archived" for e in state.entries)
    assert state.review_notice is not None and state.review_notice.archived_candidates == 200
    rows = []
    page = store.history()
    while page:
        rows.extend(page)
        page = store.history(before=page[0].sequence)
    assert sum(e.action == "candidate_expired" for e in rows) == 200
    assert sum(e.action == "review_digest" for e in rows) == 1
    assert PersonalMemoryStore(store.path).maintain() == state


def test_independent_windows_share_ordered_receipts_without_losing_feedback(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())

    def recall(index: int) -> None:
        window = PersonalMemoryStore(store.path)
        window.recall("technical slides", "", session_id=str(index), turn_id="a")
        window.feedback(entry.id, 1, "applied", session_id=str(index), turn_id="a")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(recall, range(8)))
    state = store.load()
    assert len(state.recalls) == 8
    assert len([e for e in store.history() if e.action == "applied"]) == 8


def test_legacy_import_failure_retains_catalog_and_can_resume_without_history_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Old 1", "technical slides"), MemorySource(quote="Evidence 1"))
    old = tuple(
        MemoryRevision(
            i, replace(entry.draft, content=f"Old {i}"), MemorySource(quote=f"Evidence {i}"), entry.updated_at
        )
        for i in (1, 2)
    )
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["version"] = 3
    data["entries"] = [asdict(replace(entry, draft=replace(entry.draft, content="Current"), revision=3, previous=old))]
    atomic_write_owner_only_text(store.path, json.dumps(data))
    before = store.path.read_bytes()
    original = activity.synchronize
    failed = False

    def interrupted(path, state):
        nonlocal failed
        if not failed and any(e.action == "revision_imported" for e in state.activity):
            failed = True
            raise OSError("simulated interrupted journal append")
        return original(path, state)

    monkeypatch.setattr(activity, "synchronize", interrupted)
    with pytest.raises(ValueError, match=r"history|History|cleanup"):
        store.configure("auto", True)
    assert store.path.read_bytes() == before
    reopened = PersonalMemoryStore(store.path)
    reopened.configure("auto", True)
    assert len(reopened.load().entries[0].previous) == 1
    assert [(r.revision, r.source.quote) for r in reopened.revisions(entry.id)] == [
        (2, "Evidence 2"),
        (1, "Evidence 1"),
    ]


def test_history_keeps_fact_evidence_separate_from_the_reason_it_was_paused(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = MemorySource("s", quote="My original preference")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), source)
    paused = store.pause(entry.id, 1, MemorySource("s", quote="Pause this while I reconsider"), "")
    for i in range(3):
        paused = store.save(
            replace(paused.draft, content=f"Revised {i}"), source, memory_id=paused.id, revision=paused.revision
        )
    versions = store.revisions(entry.id)
    assert next(r for r in versions if r.revision == 2).source.quote == "My original preference"
