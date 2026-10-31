# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory boundaries: applicability, correction, forgotten data and storage limits."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.store import MAX_CONTEXT_CHARS, MemoryStoreError, PersonalMemoryStore, render_memory


def test_recall_excludes_candidates_other_projects_archived_and_unrelated(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    draft = MemoryDraft(
        "报告缓存", "识别逻辑改变后检查持久化报告的版本失效。", "统计已修复但报告仍旧", workspace=str(tmp_path)
    )
    active = store.save(draft, MemorySource(quote="统计已修复但报告仍旧"))
    store.save(replace(draft, title="未确认的报告缓存"), MemorySource(), candidate=True)
    store.save(replace(draft, title="另一个项目的缓存", workspace=str(tmp_path / "other")), MemorySource())
    archived = store.save(replace(draft, title="已结束的报告缓存"), MemorySource())
    store.set_state(archived.id, archived.revision, "archived")
    matches = store.recall("统计逻辑已修复但报告仍然是旧的", str(tmp_path))
    assert [entry.id for entry, _ in matches] == [active.id]
    assert matches[0][1].terms
    assert store.recall("明天适合去哪里徒步", str(tmp_path)) == ()


def test_revision_keeps_original_evidence_and_recall_identity(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    old = store.save(
        MemoryDraft("Report cache", "Old explanation", "Report cache stays stale"), MemorySource(quote="original")
    )
    store.recall("report cache", str(tmp_path), session_id="session-a")
    new = store.save(
        replace(old.draft, content="Check artifact version before cache deletion"),
        MemorySource(quote="correction"),
        memory_id=old.id,
        revision=old.revision,
    )
    snapshot = store.load()
    assert new.revision == 2
    assert new.previous[0].source.quote == "original"
    assert snapshot.recalls[0].matches[0].revision == 1
    assert snapshot.entries[0].source.quote == "correction"
    with pytest.raises(MemoryStoreError, match="changed elsewhere"):
        store.save(old.draft, old.source, memory_id=old.id, revision=old.revision)


def test_suggested_correction_requires_acceptance_and_rechecks_parent_revision(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    old = store.save(MemoryDraft("IR design", "Old rationale", "Designing trajectory IR"), MemorySource())
    suggestion = store.save(
        replace(old.draft, content="First identify the downstream consumer"),
        MemorySource(quote="consumer missing"),
        candidate=True,
        replaces_id=old.id,
        replaces_revision=old.revision,
    )
    assert store.recall("trajectory IR", str(tmp_path))[0][0].draft.content == "Old rationale"
    state = store.set_state(suggestion.id, suggestion.revision, "active")
    assert len(state.entries) == 1
    assert state.entries[0].id == old.id
    assert state.entries[0].revision == 2
    assert state.entries[0].previous[0].draft.content == "Old rationale"
    stale = store.save(
        replace(old.draft, content="Another correction"),
        MemorySource(),
        candidate=True,
        replaces_id=old.id,
        replaces_revision=2,
    )
    store.save(replace(old.draft, content="User correction"), MemorySource(), memory_id=old.id, revision=2)
    with pytest.raises(MemoryStoreError, match="changed elsewhere"):
        store.set_state(stale.id, stale.revision, "active")


def test_forget_removes_revisions_pending_corrections_and_recall_references(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    entry = store.save(MemoryDraft("Report cache", "Old fact", "report cache"), MemorySource())
    revised = store.save(
        replace(entry.draft, content="New fact"), MemorySource(), memory_id=entry.id, revision=entry.revision
    )
    store.save(
        replace(entry.draft, content="Pending fact"),
        MemorySource(),
        candidate=True,
        replaces_id=entry.id,
        replaces_revision=revised.revision,
    )
    store.recall("report cache", str(tmp_path), session_id="one")
    state = store.forget(entry.id, revised.revision)
    assert state.entries == ()
    assert all(not recall.matches for recall in state.recalls)
    raw = store.path.read_text(encoding="utf-8")
    assert "Old fact" not in raw and "New fact" not in raw and "Pending fact" not in raw


def test_manual_off_and_capture_controls_are_independent(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    draft = MemoryDraft("Report cache", "Check versions", "report cache")
    store.save(draft, MemorySource())
    store.configure("manual", False)
    assert store.recall("report cache", str(tmp_path)) == ()
    assert store.recall("report cache", str(tmp_path), automatic=False)
    with pytest.raises(MemoryStoreError, match="disabled"):
        store.save(replace(draft, title="Suggestion"), MemorySource(), candidate=True)
    store.configure("off", True)
    assert store.recall("report cache", str(tmp_path), automatic=False) == ()


def test_no_match_does_not_create_store_and_large_matches_obey_context_budget(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    assert store.recall("report cache", str(tmp_path), session_id="one") == ()
    assert not store.path.exists()
    for index in range(8):
        store.save(MemoryDraft(f"Report cache {index}", "details " * 280, "report cache"), MemorySource())
    matches = store.recall("report cache", str(tmp_path))
    assert 0 < len(matches) <= 5
    assert sum(len(render_memory(entry, match.terms)) for entry, match in matches) <= MAX_CONTEXT_CHARS


@pytest.mark.parametrize(
    "invalid",
    [
        "{invalid",
        '{"version":1,"mode":"auto","capture":true,"entries":[],"generation":"broken"}',
        '{"version":1,"mode":"auto","capture":true,"entries":[],"generation":-1}',
    ],
)
def test_corrupt_store_is_not_silently_replaced(tmp_path: Path, invalid: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memories.json")
    store.configure("off", False)
    from chrys.foundation.platform.files import atomic_write_owner_only_text

    atomic_write_owner_only_text(store.path, invalid)
    with pytest.raises(MemoryStoreError, match="not been overwritten"):
        store.save(MemoryDraft("Report cache", "Check versions", "report cache"), MemorySource())
    assert store.path.read_text(encoding="utf-8") == invalid
