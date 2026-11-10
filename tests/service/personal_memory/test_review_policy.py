# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Review signals retain uncertain knowledge and remain visible to explicit searches."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory import store as store_module
from chrys.service.personal_memory.store import PersonalMemoryStore


def test_weekly_review_can_be_disabled_and_dismissed_without_repeating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instant = datetime(2026, 11, 10, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(store_module, "datetime", Clock)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for i in range(3):
        store.save(MemoryDraft(f"Slides {i}", f"Use diagrams {i}", "technical slides", topics=("PPT",)), MemorySource())
    assert store.maintain().review_notice is None
    store.set_buddy_notifications(True)
    notice = store.maintain(workspace="").review_notice
    assert notice and notice.topic == "PPT" and len(notice.memory_ids) == 3
    store.dismiss_review()
    assert PersonalMemoryStore(store.path).maintain().review_notice is None
    instant += timedelta(days=7)
    assert store.maintain().review_notice.created_at != notice.created_at


def test_unrecorded_queries_keep_layer_provenance_without_creating_receipts(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    assert store.recall("technical slides", "", automatic=False, record=False)[0][1].layer == "L3"
    assert store.recall("technical slides", "", layer="L2", record=False)[0][1].layer == "L2"
    assert store.load().recalls == ()


def test_corrections_from_three_sessions_can_request_a_single_topic_review(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Comments", "Prefer concise Chinese comments", "editing code", topics=("comments",)),
        MemorySource("initial"),
    )
    for index in range(3):
        entry = store.save(
            replace(entry.draft, content=f"Prefer concise Chinese comments with rationale {index}"),
            MemorySource(f"correction-{index}", quote="Keep Chinese comments concise and explain the rationale"),
            memory_id=entry.id,
            revision=entry.revision,
            turn_id=f"turn-{index}",
        )
    store.set_buddy_notifications(True)
    state = PersonalMemoryStore(store.path).maintain()
    assert len(state.entries) == 1
    assert state.review_notice is not None and state.review_notice.topic == "comments"
    assert state.review_notice.memory_ids == (entry.id,)


def test_unreviewed_candidate_expires_but_old_active_memory_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instant = datetime(2026, 10, 1, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(store_module, "datetime", Clock)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    active = store.save(MemoryDraft("Active", "A low-frequency useful fact", "release"), MemorySource())
    pending = store.save(
        MemoryDraft("Pending", "An inferred habit", "review"), MemorySource(role="assistant"), candidate=True
    )
    instant += timedelta(days=31)
    entries = {e.id: e for e in store.maintain().entries}
    assert entries[active.id].state == "active"
    assert entries[pending.id].state == "archived"
    assert entries[pending.id].review_reason == "candidate_expired"


def test_lexically_near_write_names_existing_entry_but_new_conditions_are_allowed(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Slides", "For technical slides, use dense diagrams with annotated callouts.", "technical slides"),
        MemorySource(),
    )
    draft = replace(
        entry.draft, title="Technical decks", content="For technical slides, use dense diagrams and annotated callouts."
    )
    with pytest.raises(ValueError, match=entry.id):
        store.save(draft, MemorySource(), authorization="request")
    assert store.save(
        replace(draft, when_to_use="Distant projection with technical slides"), MemorySource(), authorization="request"
    )


def test_explicit_correction_can_reactivate_a_stale_fact(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    for i in range(3):
        store.recall("technical slides", "", session_id="one", turn_id=str(i))
        store.feedback(entry.id, 1, "not_applicable", session_id="one", turn_id=str(i))
    stale = store.maintain().entries[0]
    corrected = store.save(
        stale.draft,
        MemorySource("one", quote="Keep this preference; it still applies to technical slides"),
        memory_id=stale.id,
        revision=stale.revision,
        authorization="request",
    )
    assert corrected.state == "active" and not corrected.review_reason


def test_three_distinct_skipped_turns_request_review_without_deleting(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    for index in range(3):
        store.recall("technical slides", "", session_id="one", turn_id=str(index))
        store.feedback(
            entry.id, 1, "not_applicable", session_id="one", turn_id=str(index), source=MemorySource(role="user")
        )
    state = store.maintain()
    item = state.entries[0]
    assert item.state == "stale" and item.review_reason == "repeated_mismatch"
    assert store.recall("technical slides", "") == ()
    assert store.recall("technical slides", "", automatic=False)[0][0].id == entry.id
    store.set_state(item.id, item.revision, "active")
    assert store.maintain().entries[0].state == "active"


def test_five_provided_turns_without_feedback_request_review_but_helpful_prevents_it(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    for index in range(5):
        store.recall("technical slides", "", session_id="one", turn_id=str(index))
    assert store.maintain().entries[0].review_reason == "no_helpful_feedback"
    item = store.load().entries[0]
    store.set_state(item.id, item.revision, "active")
    for index in range(5, 10):
        store.recall("technical slides", "", session_id="one", turn_id=str(index))
    current = store.load().entries[0]
    store.feedback(
        current.id, current.revision, "helpful", session_id="one", turn_id="9", source=MemorySource(role="user")
    )
    assert store.maintain().entries[0].state == "active"
