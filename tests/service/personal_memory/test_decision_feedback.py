# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Unknown effect and contextual mismatches never establish a false memory."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory.activity import recent_usage
from chrys.service.personal_memory.lifecycle import condition_review_ids
from chrys.service.personal_memory.store import PersonalMemoryStore


def test_silence_after_repeated_provision_keeps_the_memory_available(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    for number in range(5):
        store.recall("technical slides", "", session_id="one", turn_id=str(number))

    state = store.maintain()

    assert state.entries[0].state == "active"
    assert state.entries[0].revision == entry.revision
    assert [e.id for e, _ in store.recall("technical slides", "", record=False)] == [entry.id]


def test_repeated_user_mismatch_suppresses_only_that_context(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    for number in range(3):
        store.recall("technical slides for distant projection", "", session_id="one", turn_id=str(number))
        store.feedback(
            entry.id,
            entry.revision,
            "not_applicable",
            session_id="one",
            turn_id=str(number),
            source=MemorySource(role="user"),
        )

    state = store.maintain()
    assert state.entries[0].state == "active" and state.entries[0].revision == 1
    assert store.recall("technical slides for distant projection", "", record=False) == ()
    assert [e.id for e, _ in store.recall("technical slides for architecture review", "", record=False)] == [entry.id]
    assert store.recall("technical slides for distant projection", "", automatic=False, record=False)


def test_agent_mismatch_does_not_train_a_user_preference_or_retire_a_fact(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    for number in range(3):
        store.recall("technical slides", "", session_id="one", turn_id=str(number))
        store.feedback(entry.id, 1, "not_applicable", session_id="one", turn_id=str(number))
    assert store.maintain().entries[0].state == "active"
    assert store.recall("technical slides", "", record=False)


@pytest.mark.parametrize("long_query", [False, True])
def test_context_exclusion_preserves_negation_while_normalizing_case_and_spacing(
    tmp_path: Path, long_query: bool
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    prefix = "technical slides context " * 160 if long_query else ""
    suffix = " diagram review" * 200 if long_query else ""
    for number, query in enumerate(
        (
            "Do NOT use dense technical slides",
            "do not use dense    technical slides",
            "DO NOT USE DENSE TECHNICAL SLIDES",
        )
    ):
        assert store.recall(prefix + query + suffix, "", session_id="one", turn_id=str(number))
        store.feedback(
            entry.id, 1, "not_applicable", session_id="one", turn_id=str(number), source=MemorySource(role="user")
        )
    assert not store.recall(prefix + "do not use dense technical slides" + suffix, "", record=False)
    assert store.recall(prefix + "use dense technical slides" + suffix, "", record=False)


def test_explicit_incorrect_feedback_still_stops_recall(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    store.recall("technical slides", "", session_id="one", turn_id="first")
    state = store.feedback(
        entry.id,
        1,
        "incorrect",
        session_id="one",
        turn_id="first",
        source=MemorySource(role="user", quote="This memory is wrong"),
    )
    assert state.entries[0].state == "archived"
    assert state.entries[0].review_reason == "incorrect"
    assert store.recall("technical slides", "", record=False) == ()


def test_each_new_recall_has_unknown_effect_until_the_user_reports_it(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    store.recall("technical slides", "", session_id="one", turn_id="1")
    store.feedback(entry.id, 1, "applied", session_id="one", turn_id="1")
    assert recent_usage(store.load(), entry.id, 1).effect == "unknown"
    store.feedback(entry.id, 1, "helpful", session_id="one", turn_id="1", source=MemorySource(role="user"))
    assert recent_usage(store.load(), entry.id, 1).effect == "helpful"
    store.recall("technical slides", "", session_id="two", turn_id="2")
    assert recent_usage(store.load(), entry.id, 1).effect == "unknown"
    store.feedback(entry.id, 1, "not_applicable", session_id="two", turn_id="2", source=MemorySource(role="user"))
    assert recent_usage(store.load(), entry.id, 1).effect == "not_applicable"


def test_context_suppression_survives_restart_but_not_revision_or_workspace_changes(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource())
    first_workspace, other_workspace = str(tmp_path / "first"), str(tmp_path / "other")
    for number in range(3):
        store.recall("technical slides", first_workspace, session_id="one", turn_id=str(number))
        store.feedback(
            entry.id, 1, "not_applicable", session_id="one", turn_id=str(number), source=MemorySource(role="user")
        )
    reopened = PersonalMemoryStore(store.path)
    assert reopened.recall("technical slides", first_workspace, record=False) == ()
    assert reopened.recall("technical slides", other_workspace, record=False)
    reopened.set_buddy_notifications(True)
    reviewed = reopened.maintain(workspace=first_workspace)
    assert reviewed.review_notice is not None and reviewed.review_notice.memory_ids == (entry.id,)
    assert condition_review_ids(reviewed) == {entry.id}
    reopened.save(
        replace(entry.draft, content="Use diagrams only for architecture reviews"),
        MemorySource(),
        memory_id=entry.id,
        revision=1,
    )
    assert reopened.recall("technical slides", first_workspace, record=False)
    assert not condition_review_ids(reopened.load())


@pytest.mark.parametrize("reason", ["repeated_mismatch", "no_helpful_feedback"])
def test_legacy_automatic_quarantines_restore_but_explicit_pauses_remain(tmp_path: Path, reason: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    active = store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    paused = store.save(MemoryDraft("Comments", "Use Chinese comments", "editing Python"), MemorySource())
    store.pause(paused.id, paused.revision, MemorySource(role="user", quote="This is obsolete"), "")
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["entries"][0].update(state="stale", review_reason=reason, revision=2)
    atomic_write_owner_only_text(store.path, json.dumps(payload))
    entries = {entry.id: entry for entry in PersonalMemoryStore(store.path).maintain().entries}
    assert entries[active.id].state == "active" and not entries[active.id].review_reason
    assert entries[active.id].revision == 3
    assert entries[paused.id].state == "archived"


def test_old_receipts_without_context_keys_remain_readable(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    store.recall("technical slides", "", session_id="one", turn_id="1")
    payload = json.loads(store.receipts_path.read_text(encoding="utf-8"))
    for receipt in payload["recalls"]:
        for match in receipt["matches"]:
            match.pop("context_key", None)
    for use in payload["uses"]:
        use.pop("excluded_contexts", None)
        for exposure in (*use["exposures"], *use["skips"]):
            exposure.pop("context_key", None)
    atomic_write_owner_only_text(store.receipts_path, json.dumps(payload))
    assert PersonalMemoryStore(store.path).load().recalls[0].matches[0].context_key == ""
