# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Consolidation proposals preserve sources until an explicit confirmation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryRelation, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory import store as store_module
from chrys.service.personal_memory.runtime import MemoryReference, PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


@pytest.mark.parametrize("changed_source", [False, True])
async def test_merge_proposal_is_pending_and_confirmation_retires_sources_atomically(
    tmp_path: Path, changed_source: bool
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first = await asyncio.to_thread(
        store.save,
        MemoryDraft("Labels", "Use annotated diagrams", "technical slides", kind="preference"),
        MemorySource(),
    )
    second = await asyncio.to_thread(
        store.save,
        MemoryDraft("Density", "Keep useful information dense", "technical slides", kind="preference"),
        MemorySource(),
    )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    quote = "Review my slide habits and propose a consolidation."
    runtime.observe([Message("user", [quote])])
    await runtime.recall_memory("technical slides", for_update=True)
    response = await runtime.organize_memory(
        "propose_merge",
        [MemoryReference(memory_id=first.id, revision=1), MemoryReference(memory_id=second.id, revision=1)],
        "Both describe technical presentation layout",
        title="Technical presentation layout",
        content="Use dense annotated diagrams for technical slides.",
        when_to_use="When preparing technical slides for close reading",
        source_quote=quote,
        source_decisions=["Absorb the use of annotations", "Absorb the density preference"],
    )
    result = json.loads(response)
    proposal = next(e for e in (await asyncio.to_thread(store.load)).entries if e.id == result["id"])
    assert proposal.state == "candidate"
    assert all(
        e.state == "active" for e in (await asyncio.to_thread(store.load)).entries if e.id in (first.id, second.id)
    )
    if changed_source:
        await asyncio.to_thread(
            store.save,
            replace(first.draft, content="Use diagrams only when they explain a technical relationship"),
            MemorySource(),
            memory_id=first.id,
            revision=first.revision,
        )
        before = await asyncio.to_thread(store.load)
        with pytest.raises(ValueError, match=r"changed|Refresh"):
            await asyncio.to_thread(store.set_state, proposal.id, proposal.revision, "active")
        assert await asyncio.to_thread(store.load) == before
        return
    state = await asyncio.to_thread(store.set_state, proposal.id, proposal.revision, "active")
    assert {e.id for e in state.entries if e.state == "active"} == {proposal.id}
    assert all(
        r.kind == "merged_from" and r.revision == 2
        for r in next(e for e in state.entries if e.id == proposal.id).draft.relations
    )


@pytest.mark.parametrize("prior_state", ["candidate", "paused", "expired"])
def test_restoring_a_merge_proposal_keeps_atomic_source_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior_state: str
) -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(store_module, "datetime", Clock)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    sources = [
        store.save(MemoryDraft(title, content, "technical slides"), MemorySource())
        for title, content in (("Labels", "Use diagrams"), ("Density", "Keep useful information dense"))
    ]
    proposal = store.save(
        MemoryDraft(
            "Technical presentation layout",
            "Use dense annotated diagrams.",
            "technical slides",
            relations=tuple(MemoryRelation(e.id, e.revision, "merged_from", "Absorb the source") for e in sources),
        ),
        MemorySource(quote="Propose a consolidation of my slide habits"),
        candidate=True,
        authorization="request",
    )
    if prior_state == "expired":
        instant += timedelta(days=31)
        store.maintain()
    elif prior_state == "paused":
        store.set_state(proposal.id, proposal.revision, "archived")
    proposal = next(e for e in store.load().entries if e.id == proposal.id)
    state = store.set_state(proposal.id, proposal.revision, "active")
    assert {e.id for e in state.entries if e.state == "active"} == {proposal.id}
    accepted = next(e for e in state.entries if e.id == proposal.id)
    assert not accepted.review_reason and all(r.revision == 2 for r in accepted.draft.relations)
    paused = store.set_state(accepted.id, accepted.revision, "archived")
    current = next(e for e in paused.entries if e.id == accepted.id)
    restored = store.set_state(current.id, current.revision, "active")
    assert {e.id for e in restored.entries if e.state == "active"} == {proposal.id}
    assert all(e.revision == 2 for e in restored.entries if e.id in {s.id for s in sources})


async def test_conversation_confirmation_requires_an_existing_proposal_and_a_later_turn(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first = await asyncio.to_thread(
        store.save, MemoryDraft("Labels", "Use diagrams", "technical slides"), MemorySource()
    )
    second = await asyncio.to_thread(
        store.save, MemoryDraft("Density", "Keep density high", "technical slides"), MemorySource()
    )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    quote = "Review these habits and propose a consolidation."
    runtime.observe([Message("user", [quote])])
    await runtime.recall_memory("technical slides", for_update=True)
    refs = [MemoryReference(memory_id=e.id, revision=1) for e in (first, second)]
    result = json.loads(
        await runtime.organize_memory(
            "propose_merge",
            refs,
            "Shared scenario",
            title="Slides method",
            content="Use dense annotated diagrams.",
            when_to_use="technical slides",
            source_quote=quote,
            source_decisions=["Retain annotations", "Retain density"],
        )
    )
    await runtime.recall_memory("technical slides", for_update=True)
    premature = await runtime.organize_memory(
        "merge", refs, "Confirm proposal", replaces_id=result["id"], replaces_revision=1, source_quote=quote
    )
    assert premature.startswith("Error:")
    runtime.observe([Message("user", ["Confirm the proposed consolidation."])])
    await runtime.recall_memory("technical slides", for_update=True)
    confirmed = json.loads(
        await runtime.organize_memory(
            "merge",
            refs,
            "User approved",
            replaces_id=result["id"],
            replaces_revision=1,
            source_quote="Confirm the proposed consolidation.",
        )
    )
    assert confirmed["id"] == result["id"] and confirmed["state"] == "active"
    saved = next(e for e in (await asyncio.to_thread(store.load)).entries if e.id == result["id"])
    assert saved.source.quote == "Confirm the proposed consolidation."


async def test_direct_inspection_supplies_bounded_revision_evidence_for_review(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft("Comments", "Prefer Chinese comments", "editing code", kind="preference"),
        MemorySource("session-0", quote="Write comments in Chinese"),
    )
    for i in range(3):
        entry = await asyncio.to_thread(
            store.save,
            replace(entry.draft, content=f"Prefer Chinese comments with concise rationale {i}"),
            MemorySource(f"session-{i + 1}", quote="Keep comments concise and in Chinese"),
            memory_id=entry.id,
            revision=entry.revision,
            turn_id=f"turn-{i}",
        )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="review", workspace=str(tmp_path), store=store)
    runtime.observe([Message("user", ["Review my recurring corrections about comments"])])
    result = json.loads(await runtime.recall_memory(entry.id, for_update=True))
    assert result["history"][0]["draft"]["content"] == "Prefer Chinese comments with concise rationale 1"
    assert {r["source"]["session_id"] for r in result["history"]} == {"session-0", "session-1", "session-2"}
