# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Automatic action recall is bounded and shares the existing receipt."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.foundation.tool_kinds import set_tool_kind
from chrys.kernel import Agent, FunctionTool, Message
from chrys.kernel.middleware import FunctionInvocationContext
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.tools.kinds import tool


@pytest.mark.parametrize("mode", ["auto", "manual", "off"])
@pytest.mark.parametrize(
    "kind", ["filesystem.write", "shell", "web_search", "web_fetch", "doc_converter", "filesystem.read", "context"]
)
async def test_action_kind_and_mode_gate_the_single_supplement(tmp_path: Path, mode: str, kind: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save, MemoryDraft("Slides", "Use dense diagrams", "technical slides"), MemorySource()
    )
    await asyncio.to_thread(store.configure, mode, False)
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    message = Message("user", ["Fix the failure"])
    await runtime.prepare([message])

    @tool(kind=kind)
    def action(path: str) -> str:
        """Complete the requested action."""
        return "Completed " + path

    client = MockChatClient(
        [
            MockResponse(tool_calls=[("action", "first", {"path": "technical-slides.md"})]),
            MockResponse(tool_calls=[("action", "second", {"path": "technical-slides.md"})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=client, tools=[action], middleware=[runtime]) as agent:
        await agent.run([message])
    wire = json.dumps([m.to_dict() for m in client.call_history[-1][0]])
    expected = mode == "auto" and kind not in ("filesystem.read", "context")
    assert (entry.id in wire) is expected
    results = [str(c.result) for m in client.call_history[-1][0] for c in m.contents if c.type == "function_result"]
    assert sum(r.count("<personal_memory_action>") for r in results) == int(expected)
    assert len(client.call_history) == 3


async def test_two_opening_hits_suppress_action_recall(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for title in ("Slides", "Audience"):
        await asyncio.to_thread(store.save, MemoryDraft(title, title + " diagrams", "technical slides"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    message = Message("user", ["Prepare technical slides"])
    await runtime.prepare([message])

    @tool(kind="filesystem.write")
    def action(path: str) -> str:
        """Complete an action."""
        return path

    client = MockChatClient(
        [MockResponse(tool_calls=[("action", "first", {"path": "technical-slides.md"})]), MockResponse(text="Done")]
    )
    async with Agent(client=client, tools=[action], middleware=[runtime]) as agent:
        await agent.run([message])
    wire = json.dumps([m.to_dict() for m in client.call_history[-1][0]])
    assert "<personal_memory_action>" not in wire


async def test_parallel_actions_share_one_recall_and_do_not_persist_raw_arguments(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save, MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource()
    )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    await runtime.prepare([Message("user", ["Fix the failure"])])
    function = FunctionTool(name="write_file", func=lambda: "done")
    set_tool_kind(function, "filesystem.write")
    contexts = [
        FunctionInvocationContext(
            function, {"path": "technical-slides.pptx", "content": "x" * 100000, "token": "PRIVATE-ARGUMENT-MARKER"}
        )
        for _ in range(2)
    ]
    ready = asyncio.Event()
    started = 0

    async def complete(context: FunctionInvocationContext) -> None:
        nonlocal started
        started += 1
        if started == 2:
            ready.set()
        await ready.wait()
        context.result = "done"

    async def run(context: FunctionInvocationContext) -> None:
        async def call() -> None:
            await complete(context)

        await runtime.process(context, call)

    await asyncio.gather(*(run(c) for c in contexts))
    assert sum("<personal_memory_action>" in str(c.result) for c in contexts) == 1
    state = await asyncio.to_thread(store.load)
    assert len(state.recalls[0].matches) == 1 and state.recalls[0].matches[0].memory_id == entry.id
    assert "PRIVATE-ARGUMENT-MARKER" not in store.receipts_path.read_text(encoding="utf-8")


async def test_cancelled_action_does_not_start_a_supplementary_recall(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.save, MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    await runtime.prepare([Message("user", ["Fix the failure"])])
    before = await asyncio.to_thread(store.load)
    function = FunctionTool(name="write_file", func=lambda: "done")
    set_tool_kind(function, "filesystem.write")
    ready, release = asyncio.Event(), asyncio.Event()

    async def complete() -> None:
        ready.set()
        await release.wait()

    task = asyncio.create_task(runtime.process(FunctionInvocationContext(function, {"path": "slides.pptx"}), complete))
    try:
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await asyncio.to_thread(store.load)).generation == before.generation
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_failed_action_recall_keeps_the_completed_tool_and_reports_unavailability(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.save, MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource())
    bus = EventBus()
    errors = []

    async def receive(event: PersonalMemoryChanged) -> None:
        if event.error:
            errors.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    runtime = PersonalMemoryRuntime(bus=bus, session_id="one", workspace=str(tmp_path), store=store)
    await runtime.prepare([Message("user", ["Fix the failure"])])
    await asyncio.to_thread(atomic_write_owner_only_text, store.path, "invalid")
    function = FunctionTool(name="write_file", func=lambda: "Completed")
    set_tool_kind(function, "filesystem.write")
    context = FunctionInvocationContext(function, {"path": "slides.pptx"})

    async def complete() -> None:
        context.result = "Completed"

    await runtime.process(context, complete)
    assert context.result == "Completed"
    assert len(errors) == 1 and errors[0].error_code == "memory_unavailable"
