# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Decision recall protects the first effect and survives interrupted delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.trajectory.metadata import ensure_analytics_item_id
from chrys.kernel import Agent, ChatContext, ChatMiddleware, Message
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import MemoryRecallBudgetExceeded, PersonalMemoryStore
from chrys.service.tools.kinds import tool


@pytest.mark.parametrize("rebuild", [False, True])
@pytest.mark.parametrize("call_id", ["", "same-id"])
async def test_cancelled_preflight_replays_unseen_evidence_before_execution(
    tmp_path: Path, rebuild: bool, call_id: str
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Shell", "Explain the impact", "Changing bashrc"), MemorySource())
    message = Message("user", ["Fix the failure"])
    ensure_analytics_item_id(message.additional_properties)
    writes: list[str] = []

    @tool(kind="filesystem.write")
    def write_file(path: str) -> str:
        """Write the requested file."""
        writes.append(path)
        return "Written"

    class InterruptAfterPreflight(ChatMiddleware):
        async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
            await call_next()
            raise asyncio.CancelledError

    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    await runtime.prepare([message])
    first = MockChatClient([MockResponse(tool_calls=[("write_file", call_id, {"path": ".bashrc"})])])
    async with Agent(
        client=first, tools=[write_file], middleware=[InterruptAfterPreflight(), *runtime.middleware()]
    ) as agent:
        with pytest.raises(asyncio.CancelledError):
            await agent.run([message])
    assert not writes
    assert store.load().recalls[0].searches == 1
    if rebuild:
        runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
        await runtime.prepare([message])
    second = MockChatClient(
        [
            MockResponse(tool_calls=[("write_file", call_id, {"path": ".bashrc"})]),
            MockResponse(tool_calls=[("write_file", call_id, {"path": ".bashrc"})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=second, tools=[write_file], middleware=runtime.middleware()) as agent:
        await agent.run([message])
    assert writes == [".bashrc"]
    assert entry.draft.content in str([m.to_dict() for m in second.call_history[1][0]])
    assert store.load().recalls[0].searches == 1


async def test_invalid_call_without_an_id_is_left_to_kernel_validation(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Shell", "Explain the impact", "Changing bashrc"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    message = Message("user", ["Fix the failure"])
    await runtime.prepare([message])
    writes: list[str] = []

    @tool(kind="filesystem.write")
    def write_file(path: str) -> str:
        """Write the requested file."""
        writes.append(path)
        return "Written"

    client = MockChatClient([MockResponse(tool_calls=[("write_file", None, {"path": ".bashrc"})])])
    async with Agent(client=client, tools=[write_file], middleware=runtime.middleware()) as agent:
        with pytest.raises(KeyError, match="missing call_id"):
            await agent.run([message])
    assert not writes
    assert store.load().recalls[0].searches == 0


async def test_later_decision_is_checked_despite_two_opening_hits(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for name in ("Cache keys", "Cache artifacts"):
        store.save(MemoryDraft(name, name, "cache"), MemorySource())
    entry = store.save(MemoryDraft("Shell", "Explain the impact", "Changing bashrc"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    user = Message("user", ["Fix the cache failure"])
    await runtime.prepare([user])
    writes: list[str] = []

    @tool(kind="filesystem.write")
    def write_file(path: str, content: str) -> str:
        """Write the requested file."""
        writes.append(path)
        return content

    client = MockChatClient(
        [
            MockResponse(tool_calls=[("write_file", "first", {"path": "cache.txt", "content": "One"})]),
            MockResponse(tool_calls=[("write_file", "repeat", {"path": "cache.txt", "content": "Two"})]),
            MockResponse(tool_calls=[("write_file", "later", {"path": ".bashrc", "content": "Unsafe"})]),
            MockResponse(tool_calls=[("write_file", "reviewed", {"path": ".bashrc", "content": "Reviewed"})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=client, tools=[write_file], middleware=runtime.middleware()) as agent:
        await agent.run([user])
    assert writes == ["cache.txt", "cache.txt", ".bashrc"]
    assert entry.draft.content in str([m.to_dict() for m in client.call_history[3][0]])
    receipt = store.load().recalls[0]
    assert receipt.searches == 1
    assert next(m.layer for m in receipt.matches if m.memory_id == entry.id) == "L2"
    # Automatic decisions leave one search available for an intentional query.
    assert store.recall("Changing bashrc", str(tmp_path), automatic=False, session_id="one", turn_id=receipt.turn_id)
    assert store.recall("Changing bashrc", str(tmp_path), automatic=False, session_id="one", turn_id=receipt.turn_id)
    with pytest.raises(MemoryRecallBudgetExceeded):
        store.recall("Changing bashrc", str(tmp_path), automatic=False, session_id="one", turn_id=receipt.turn_id)


async def test_unrelated_diagnostics_do_not_exhaust_recall_before_the_first_write(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Shell", "Explain the impact", "Changing bashrc"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    message = Message("user", ["Fix the failure"])
    await runtime.prepare([message])
    effects: list[str] = []

    @tool(kind="shell")
    def inspect(command: str) -> str:
        """Run a diagnostic command."""
        effects.append(command)
        return "Diagnostic result"

    @tool(kind="filesystem.write")
    def write_file(path: str, content: str) -> str:
        """Write the requested file."""
        effects.append(content)
        return "Written"

    client = MockChatClient(
        [
            MockResponse(tool_calls=[("inspect", "pwd", {"command": "pwd"})]),
            MockResponse(tool_calls=[("inspect", "list", {"command": "ls src"})]),
            MockResponse(tool_calls=[("write_file", "first", {"path": ".bashrc", "content": "UNREVIEWED"})]),
            MockResponse(tool_calls=[("write_file", "reviewed", {"path": ".bashrc", "content": "REVIEWED"})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=client, tools=[inspect, write_file], middleware=runtime.middleware()) as agent:
        await agent.run([message])
    assert effects == ["pwd", "ls src", "REVIEWED"]
    assert entry.draft.content in str([m.to_dict() for m in client.call_history[3][0]])
    assert store.load().recalls[0].searches == 1


def test_action_misses_do_not_write_receipts_or_consume_supplement_budget(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Shell", "Explain the impact", "Changing bashrc"), MemorySource())
    store.recall("Fix the failure", "", session_id="one", turn_id="turn")
    before = store.receipts_path.read_bytes()
    for command in ("pwd", "ls src", "git status"):
        assert not store.recall(
            command, "", session_id="one", turn_id="turn", layer="L2", novel_only=True, extend_record=True
        )
    assert store.receipts_path.read_bytes() == before


def test_relevant_supplements_still_share_a_bound_and_reserve_deliberate_recall(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for name in ("PostgreSQL", "Redis", "Nginx"):
        store.save(MemoryDraft(name, "Inspect " + name + " configuration", "Changing " + name), MemorySource())
    store.recall("Fix the failure", "", session_id="one", turn_id="turn")
    for name in ("PostgreSQL", "Redis"):
        assert store.recall(name, "", session_id="one", turn_id="turn", layer="L2", novel_only=True, extend_record=True)
    with pytest.raises(MemoryRecallBudgetExceeded):
        store.recall("Nginx", "", session_id="one", turn_id="turn", layer="L2", novel_only=True, extend_record=True)
    assert store.load().recalls[0].searches == 2
    assert store.recall("Nginx", "", session_id="one", turn_id="turn", automatic=False)
    assert store.load().recalls[0].searches == 3
