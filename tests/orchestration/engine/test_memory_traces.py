# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory traces become trajectory rows with codes and counts, never titles."""

from __future__ import annotations

from typing import Any

import pytest

from chrys.foundation.events.personal_memory import PersonalMemoryTrace
from chrys.foundation.trajectory.context import TrajectoryContext, main_actor
from chrys.foundation.trajectory.envelope import EventDraft
from chrys.orchestration.engine.memory_traces import memory_trace_draft


class _Sink:
    def __init__(self) -> None:
        self.drafts: list[EventDraft] = []

    async def emit(self, draft: EventDraft, *, payload_factory: Any = None) -> None:
        self.drafts.append(draft)


class _Double:
    """Minimal recorder double: the adapter only needs the session's recording scope."""

    def __init__(self, context: TrajectoryContext | None) -> None:
        self._context = context

    def context(self) -> TrajectoryContext | None:
        return self._context

    async def __call__(self, event: PersonalMemoryTrace) -> None:
        context = self._context
        if context is None:
            return
        await memory_trace_draft(context, event)


@pytest.mark.asyncio
async def test_a_save_rejection_records_its_code_and_nothing_else() -> None:
    sink = _Sink()
    recorder = _Double(TrajectoryContext(sink=sink, session_id="s", actor=main_actor("s"), turn_id="t1"))  # type: ignore[arg-type]
    await recorder(
        PersonalMemoryTrace(kind="save_rejected", code="memory_consent_span_pasted", session_id="s"),
    )
    (draft,) = sink.drafts
    assert draft.event_type == "memory.save.rejected"
    assert draft.payload == {
        "code": "memory_consent_span_pasted",
        "view": "",
        "entries": 0,
        "characters": 0,
        "outcome": "",
    }


@pytest.mark.asyncio
async def test_a_recall_records_counts_and_the_view() -> None:
    sink = _Sink()
    recorder = _Double(TrajectoryContext(sink=sink, session_id="s", actor=main_actor("s"), turn_id="t1"))  # type: ignore[arg-type]
    await recorder(PersonalMemoryTrace(kind="recall_served", entries=3, characters=512, view="index", session_id="s"))
    (draft,) = sink.drafts
    assert draft.event_type == "memory.recall.served"
    assert draft.payload == {"code": "", "view": "index", "entries": 3, "characters": 512, "outcome": ""}


@pytest.mark.asyncio
async def test_without_a_recording_scope_nothing_is_written() -> None:
    sink = _Sink()
    recorder = _Double(None)
    await recorder(PersonalMemoryTrace(kind="save_committed", session_id="s"))
    assert sink.drafts == []
