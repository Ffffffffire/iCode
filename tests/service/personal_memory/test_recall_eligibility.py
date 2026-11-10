# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Unavailable high-scoring records must not consume a recall candidate window."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import (
    FollowUpStatus,
    MemoryDraft,
    MemoryFollowUp,
    MemoryRelation,
    MemorySource,
)
from chrys.service.personal_memory.store import PersonalMemoryStore


@pytest.mark.parametrize("automatic", [True, False])
def test_outdated_derived_hits_cannot_hide_the_available_fact(tmp_path: Path, automatic: bool) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(MemoryDraft("Evidence", "Original evidence", "review evidence"), MemorySource())
    for index in range(40):
        store.save(
            MemoryDraft(
                f"Cache parser rule {index}",
                f"Use parser approach {index}",
                "cache parser",
                relations=(MemoryRelation(source.id, source.revision, "derived_from", "Source evidence"),),
            ),
            MemorySource(),
        )
    valid = store.save(MemoryDraft("Cache", "Version the cache key", "cache"), MemorySource())
    store.save(
        replace(source.draft, content="Corrected evidence"),
        MemorySource(),
        memory_id=source.id,
        revision=source.revision,
    )

    found = store.recall("cache parser", "", automatic=automatic)

    assert [entry.id for entry, _ in found] == [valid.id]


@pytest.mark.parametrize("status", ["completed", "cancelled", "snoozed"])
def test_unavailable_followups_do_not_consume_the_shortlist(tmp_path: Path, status: FollowUpStatus) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    for index in range(40):
        store.save(
            MemoryDraft(
                f"Cache parser task {index}",
                f"Complete parser task {index}",
                "cache parser",
                kind="intention",
                follow_up=MemoryFollowUp(status=status, remind_at=future),
            ),
            MemorySource(),
        )
    valid = store.save(MemoryDraft("Cache", "Version the cache key", "cache"), MemorySource())

    assert [entry.id for entry, _ in store.recall("cache parser", "")] == [valid.id]


def test_turn_exclusions_change_ranking_without_poisoning_the_next_turn_cache(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    broad = store.save(MemoryDraft("Cache", "Choose cache keys carefully", "cache"), MemorySource())
    specific = store.save(
        MemoryDraft("Cache parser invalidation", "Include the parser version", "cache parser invalidation"),
        MemorySource(),
    )
    query = "cache parser invalidation"
    assert [e.id for e, _ in store.recall(query, "", session_id="one", turn_id="first")] == [specific.id]
    store.feedback(specific.id, specific.revision, "not_applicable", session_id="one", turn_id="first")

    assert [e.id for e, _ in store.recall(query, "", session_id="one", turn_id="first")] == [broad.id]
    assert [e.id for e, _ in store.recall(query, "", session_id="one", turn_id="next")] == [specific.id]


def test_filtered_cache_remains_private_to_its_workspace(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    workspace = str(tmp_path / "project")
    other = str(tmp_path / "other")
    personal = store.save(MemoryDraft("Cache", "Version the cache key", "cache"), MemorySource())
    private = store.save(
        MemoryDraft("Cache parser invalidation", "Private project policy", "cache parser", workspace=workspace),
        MemorySource(),
    )

    assert [e.id for e, _ in store.recall("cache parser", other)] == [personal.id]
    assert [e.id for e, _ in store.recall("cache parser", workspace)] == [private.id]
    assert [e.id for e, _ in store.recall("cache parser", other)] == [personal.id]
