# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Observable memory use, cross-session follow-ups and source-based consolidation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import (
    MemoryDraft,
    MemoryFollowUp,
    MemoryRelation,
    MemorySnapshot,
    MemorySource,
)
from chrys.service.personal_memory import activity
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore


def test_oversized_activity_is_rejected_before_commit_and_does_not_block_future_writes(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    initial = store.save(MemoryDraft("Original", "Keep this fact", "review"), MemorySource())
    before = store.path.read_bytes()
    with pytest.raises(MemoryStoreError, match="activity record exceeds"):
        store.save(MemoryDraft("Too large", "Short content", "review"), MemorySource(item_id="x" * 40000))
    assert store.path.read_bytes() == before
    assert [e.id for e in store.load().entries] == [initial.id]
    saved = store.save(MemoryDraft("Next", "Another fact", "another review"), MemorySource())
    assert saved.id in {e.id for e in store.load().entries}
    rows = [json.loads(line) for line in store.activity_path.read_text(encoding="utf-8").splitlines()]
    assert [row["memory_id"] for row in rows] == [initial.id, saved.id]


def test_standing_preference_and_topic_are_distinct_recall_routes(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    preference = store.save(
        MemoryDraft("Answer style", "Lead with the conclusion", "", kind="preference", use="always"), MemorySource()
    )
    lesson = store.save(
        MemoryDraft(
            "Downstream contract", "Validate its consumer", "Designing representations", topics=("trajectory",)
        ),
        MemorySource(),
    )
    assert [e.id for e, _ in store.recall("fix the parser", "")] == [preference.id]
    assert lesson.id in {e.id for e, _ in store.recall("trajectory", "")}
    with pytest.raises(MemoryStoreError, match="preferences"):
        store.save(replace(lesson.draft, use="always"), MemorySource())


def test_use_history_is_turn_bound_and_exclusion_does_not_pause_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Report", "Use diagrams", "technical report"), MemorySource("origin", "quote", quote="diagrams")
    )
    store.recall("technical report", "", session_id="one", turn_id="turn-a")
    store.feedback(entry.id, entry.revision, "applied", session_id="one", turn_id="turn-a", reason="Changed the layout")
    store.feedback(
        entry.id, entry.revision, "not_applicable", session_id="one", turn_id="turn-a", source=MemorySource(role="user")
    )
    assert store.recall("technical report", "", session_id="one", turn_id="turn-a") == ()
    assert store.load().entries[0].state == "active"
    assert store.recall("technical report", "", session_id="one", turn_id="turn-b")
    rows = [json.loads(line) for line in store.activity_path.read_text(encoding="utf-8").splitlines()]
    assert [(r["turn_id"], r["revision"]) for r in rows if r["action"] == "provided"] == [("turn-a", 1), ("turn-b", 1)]
    assert next(r for r in rows if r["action"] == "applied")["actor"] == "agent"
    assert next(r for r in rows if r["action"] == "not_applicable")["actor"] == "user"


def test_due_follow_up_survives_reopen_and_completion_stops_recall(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = PersonalMemoryStore(path)
    item = store.save(
        MemoryDraft(
            "Finish migration",
            "Resume the migration",
            "Working on persistence",
            kind="intention",
            workspace=str(tmp_path),
            follow_up=MemoryFollowUp(next_step="Check the pending migration", remind_at="2020-01-01T00:00:00+00:00"),
        ),
        MemorySource(),
    )
    reopened = PersonalMemoryStore(path)
    assert reopened.recall("a different task", str(tmp_path))[0][0].id == item.id
    assert reopened.recall("a different task", str(tmp_path / "other")) == ()
    closed = reopened.save(
        replace(item.draft, follow_up=replace(item.draft.follow_up, status="completed")),
        MemorySource(quote="It is done"),
        memory_id=item.id,
        revision=item.revision,
    )
    assert reopened.recall("migration", str(tmp_path)) == ()
    assert reopened.inspect("migration", str(tmp_path))[1][0][0].id == closed.id


def test_snoozed_and_candidate_follow_ups_do_not_interrupt(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    draft = MemoryDraft(
        "Migration",
        "Resume migration",
        "migration",
        kind="intention",
        follow_up=MemoryFollowUp(status="snoozed", remind_at="2099-01-01T00:00:00+00:00"),
    )
    store.save(draft, MemorySource())
    store.save(
        replace(draft, title="Alternative", content="Inspect a different migration", follow_up=MemoryFollowUp()),
        MemorySource(),
        candidate=True,
    )
    assert store.recall("migration", "") == ()


def test_derived_method_requires_review_and_stale_sources_stop_it(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(MemoryDraft("IR", "Validate consumers", "representation"), MemorySource())
    draft = MemoryDraft(
        "Design method",
        "Confirm who consumes each new field",
        "schema design",
        relations=(
            MemoryRelation(source.id, source.revision, "derived_from", "The unused IR showed missing consumers"),
        ),
    )
    method = store.save(draft, MemorySource(), candidate=True, authorization="request")
    assert store.recall("schema design", "") == ()
    state = store.set_state(method.id, method.revision, "active")
    assert method.id in {e.id for e, _ in store.recall("schema design", "")}
    store.save(
        replace(source.draft, content="A regulated schema is required even before a consumer exists"),
        MemorySource(),
        memory_id=source.id,
        revision=source.revision,
    )
    assert method.id not in {e.id for e, _ in store.recall("schema design", "")}
    assert next(e for e in state.entries if e.id == method.id).state == "active"


def test_relations_cannot_leak_project_memory_or_accept_an_old_source(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(
        MemoryDraft("Private", "Private project fact", "project", workspace=str(tmp_path)), MemorySource()
    )
    draft = MemoryDraft(
        "Method", "General conclusion", "design", relations=(MemoryRelation(source.id, 1, "derived_from", "Evidence"),)
    )
    with pytest.raises(MemoryStoreError, match="scope"):
        store.save(draft, MemorySource(), candidate=True, authorization="request")
    revised = store.save(replace(source.draft, content="Corrected"), MemorySource(), memory_id=source.id, revision=1)
    with pytest.raises(MemoryStoreError, match="changed elsewhere"):
        store.save(replace(draft, workspace=str(tmp_path)), MemorySource(), candidate=True, authorization="request")
    assert revised.revision == 2


def test_merge_is_atomic_and_forget_removes_derived_content_from_journal(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first = store.save(MemoryDraft("IR", "Private detail A", "representation"), MemorySource())
    second = store.save(MemoryDraft("Schema", "Private detail B", "schema"), MemorySource())
    before = store.load()
    draft = MemoryDraft("Design", "Private detail A and B", "representation design")
    with pytest.raises(MemoryStoreError, match="changed elsewhere"):
        store.merge(((first.id, 1), (second.id, 8)), draft, MemorySource())
    assert store.load() == before
    combined = store.merge(((first.id, 1), (second.id, 1)), draft, MemorySource())
    assert combined.id == first.id and combined.revision == 2
    assert sum(e.state == "active" for e in store.load().entries) == 1
    store.forget(second.id, 2)
    assert store.load().entries == ()
    for file in (store.path, store.activity_path):
        assert "Private detail" not in file.read_text(encoding="utf-8")


def test_journal_recovers_committed_events_after_append_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    real_sync = activity.synchronize
    attempts = 0

    def fail_once(path: Path, state: MemorySnapshot) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("disk unavailable")
        real_sync(path, state)

    monkeypatch.setattr(activity, "synchronize", fail_once)
    item = store.save(MemoryDraft("IR", "Validate consumers", "representation"), MemorySource())
    assert store.load().entries[0] == item
    store.recall("representation", "", session_id="one", turn_id="t1")
    rows = [json.loads(line) for line in store.activity_path.read_text(encoding="utf-8").splitlines()]
    assert [r["sequence"] for r in rows] == [1, 2]
    assert [r["action"] for r in rows] == ["created", "provided"]


def test_forget_reports_incomplete_cleanup_and_retry_finishes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Private detail", "Sensitive experience", "future decision"), MemorySource())
    purge = activity._purge

    def failed_purge(path: Path, removed: set[str]) -> None:
        raise OSError("file busy")

    monkeypatch.setattr(activity, "_purge", failed_purge)
    with pytest.raises(MemoryStoreError, match="cleanup is pending"):
        store.forget(entry.id, 1)
    assert not store.load().entries
    monkeypatch.setattr(activity, "_purge", purge)
    store.forget(entry.id, 1)
    assert "Sensitive experience" not in store.activity_path.read_text(encoding="utf-8")
