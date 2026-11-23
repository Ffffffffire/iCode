# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# ruff: noqa: RUF001 -- Corpus entries are verbatim user messages, punctuation included.

"""Every tool outcome leaves one trace row: counts and codes, never titles or bodies."""

from __future__ import annotations

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryTrace
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


class _Collector:
    def __init__(self) -> None:
        self.traces: list[PersonalMemoryTrace] = []

    async def __call__(self, event: PersonalMemoryTrace) -> None:
        self.traces.append(event)


async def _runtime(tmp_path) -> tuple[PersonalMemoryRuntime, _Collector]:
    bus = EventBus()
    collector = _Collector()
    await bus.subscribe(PersonalMemoryTrace, collector)
    runtime = PersonalMemoryRuntime(
        bus=bus, session_id="trace", workspace=str(tmp_path), store=PersonalMemoryStore(tmp_path / "memory.json")
    )
    return runtime, collector


@pytest.mark.asyncio
async def test_a_committed_save_records_one_trace(tmp_path) -> None:
    runtime, collector = await _runtime(tmp_path)
    runtime.observe([Message("user", ["记住：提交前先跑测试。"])])
    await runtime.propose_memory(
        title="提交前先跑测试",
        content="提交前先跑测试，避免把坏提交推上去。",
        when_to_use="审阅提交范围时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="记住",
    )
    assert [(trace.kind, trace.outcome) for trace in collector.traces] == [("save_committed", "new")]


@pytest.mark.asyncio
async def test_a_rejected_save_records_its_code(tmp_path) -> None:
    runtime, collector = await _runtime(tmp_path)
    runtime.observe([Message("user", ["这段代码为什么这么写？"])])
    await runtime.propose_memory(
        title="提交前先跑测试",
        content="提交前先跑测试。",
        when_to_use="审阅提交范围时",
        source_quote="这段代码",
        save_now=True,
        intent_quote="记住",
    )
    assert [(trace.kind, trace.code) for trace in collector.traces] == [("save_rejected", "memory_request_missing")]


@pytest.mark.asyncio
async def test_recall_reports_entries_and_characters(tmp_path) -> None:
    runtime, collector = await _runtime(tmp_path)
    runtime.observe([Message("user", ["记住：提交前先跑测试。"])])
    await runtime.propose_memory(
        title="提交前先跑测试",
        content="提交前先跑测试。",
        when_to_use="审阅提交范围时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="记住",
    )
    collector.traces.clear()
    await runtime.recall_memory("提交前先跑测试")
    (trace,) = collector.traces
    assert trace.kind == "recall_served"
    assert trace.entries == 1
    assert trace.characters > 0
    assert trace.view == "recall"


@pytest.mark.asyncio
async def test_the_index_view_records_its_own_shape(tmp_path) -> None:
    runtime, collector = await _runtime(tmp_path)
    runtime.observe([Message("user", ["记住：提交前先跑测试。"])])
    await runtime.propose_memory(
        title="提交前先跑测试",
        content="提交前先跑测试。",
        when_to_use="审阅提交范围时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="记住",
    )
    collector.traces.clear()
    await runtime.recall_memory("提交前先跑测试", for_update=True)
    (trace,) = collector.traces
    assert trace.kind == "recall_served"
    assert trace.view == "index"
    assert trace.entries == 1
