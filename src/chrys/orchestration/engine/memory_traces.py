# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Turn memory tool outcomes into trajectory rows.

The memory runtime lives in ``service`` and cannot reach the recorder, so it publishes
:class:`PersonalMemoryTrace` on the bus; this adapter owns the recorder and writes the
event. Payloads keep counts and codes only: titles and bodies never reach the log.
"""

from __future__ import annotations

from chrys.foundation.events.personal_memory import PersonalMemoryTrace
from chrys.foundation.trajectory.context import TrajectoryContext
from chrys.foundation.trajectory.event_types import EventType

_EVENT_TYPES = {
    "save_committed": EventType.MEMORY_SAVE_COMMITTED,
    "save_rejected": EventType.MEMORY_SAVE_REJECTED,
    "recall_served": EventType.MEMORY_RECALL_SERVED,
    "consent_asked": EventType.MEMORY_CONSENT_ASKED,
    "consent_resolved": EventType.MEMORY_CONSENT_RESOLVED,
}


async def memory_trace_draft(context: TrajectoryContext, event: PersonalMemoryTrace) -> None:
    """Write one memory trace under the given recording scope."""
    payload = {
        "code": event.code,
        "view": event.view,
        "entries": event.entries,
        "characters": event.characters,
        "outcome": event.outcome,
    }
    await context.sink.emit(context.draft(_EVENT_TYPES[event.kind], payload=payload))
