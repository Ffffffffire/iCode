# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""A memory trace reaches the session log and the report reads it back."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.memory_traffic_report import main, render, session_events, summarize

from chrys.foundation.events.personal_memory import PersonalMemoryTrace
from chrys.foundation.trajectory.context import TrajectoryContext, main_actor
from chrys.foundation.trajectory.envelope import EventDraft
from chrys.foundation.trajectory.event_types import EventType
from chrys.orchestration.engine.memory_traces import memory_trace_draft

SESSION_ID = "0123456789abcdef0123456789abcdef"
AGENT_FP = "a" * 64
MODEL_FP = "b" * 64


class _Sink:
    def __init__(self) -> None:
        self.drafts: list[EventDraft] = []

    async def emit(self, draft: EventDraft, *, payload_factory: object = None) -> None:
        self.drafts.append(draft)


@pytest.mark.asyncio
async def test_what_the_adapter_writes_is_what_the_report_reads() -> None:
    """Close the loop between the adapter and the report on the row shape they share."""
    sink = _Sink()
    context = TrajectoryContext(sink=sink, session_id=SESSION_ID, actor=main_actor(SESSION_ID), turn_id="t1")  # type: ignore[arg-type]
    await memory_trace_draft(context, PersonalMemoryTrace(kind="save_rejected", code="memory_request_missing"))
    await memory_trace_draft(
        context, PersonalMemoryTrace(kind="recall_served", entries=2, characters=320, view="index")
    )
    rows = [{"event_type": draft.event_type, "payload": dict(draft.payload)} for draft in sink.drafts]

    report = summarize([rows])
    assert (report.rejected, report.committed) == (1, 0)
    assert report.rejections == {"memory_request_missing": 1}
    assert (report.recalls, report.recalled_entries, report.recalled_characters) == (1, 2, 320)
    assert report.views == {"index": 1}
    assert render(report).splitlines()[1].startswith("writes: 0 committed")


@pytest.mark.asyncio
async def test_the_report_counts_a_committed_save_and_its_recall(tmp_path: Path) -> None:
    directory = tmp_path / SESSION_ID
    (directory / "trajectory").mkdir(parents=True)
    rows = [
        {"event_type": EventType.MEMORY_SAVE_COMMITTED, "payload": {"outcome": "new"}},
        {"event_type": EventType.MEMORY_SAVE_COMMITTED, "payload": {"outcome": "unchanged"}},
        {"event_type": EventType.MEMORY_RECALL_SERVED, "payload": {"entries": 3, "characters": 900, "view": "index"}},
        {"event_type": EventType.MEMORY_RECALL_SERVED, "payload": {"entries": 1, "characters": 100, "view": "recall"}},
        {"event_type": EventType.MEMORY_CONSENT_RESOLVED, "payload": {"outcome": "confirmed"}},
        {"event_type": EventType.MEMORY_CONSENT_RESOLVED, "payload": {"outcome": "declined"}},
        {"event_type": EventType.TURN_STARTED, "payload": {}},
    ]
    import json

    (directory / "trajectory" / "events.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n{not json}\n", encoding="utf-8"
    )

    report = summarize([session_events(directory)])
    assert (report.committed, report.unchanged, report.rejected) == (2, 1, 0)
    assert (report.recalls, report.recalled_entries, report.recalled_characters) == (2, 4, 1000)
    assert report.views == {"index": 1, "recall": 1}
    assert (report.consent_confirmed, report.consent_declined) == (1, 1)
    assert report.recalls_per_commit == 1.0
    assert main(["--root", str(tmp_path)]) == 0


@pytest.mark.asyncio
async def test_a_session_with_no_memory_events_reports_zero_and_no_division() -> None:
    report = summarize([[{"event_type": EventType.TURN_STARTED, "payload": {}}]])
    assert report.events == 0
    assert report.failure_rate == 0.0
    assert report.recalls_per_commit == 0.0
