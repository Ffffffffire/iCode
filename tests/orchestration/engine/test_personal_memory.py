# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Real engine tests for memory reaching requests and suggestions reaching persistence."""

from __future__ import annotations

import asyncio
from unittest.mock import create_autospec

import pytest

from chrys.foundation.config.settings import Settings
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.events.types import UserMessage
from chrys.foundation.models.personal_memory import MemoryDraft
from chrys.orchestration.engine.build import builder
from chrys.service.approval.policy import ApprovalMode
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.profiles.agents.schema import AgentProfile, CompactionConfig, SkillsConfig, ToolsConfig
from tests.support.waiting import await_run_task_chain


def _profile() -> AgentProfile:
    return AgentProfile(
        name="MemoryTest",
        instructions="Answer the user.",
        tools=ToolsConfig(builtins=[]),
        skills=SkillsConfig(auto_load_user_agents_skills=False),
        compaction=CompactionConfig(enabled=False),
    )


async def test_actual_engine_recalls_scoped_memory_then_withdraws_when_off(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MockChatClient(
        [MockResponse(text="Check the report artifact version."), MockResponse(text="Memory is off.")]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    replies: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        replies.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    await bus.publish(
        PersonalMemoryCommand(
            action="save",
            draft=MemoryDraft(
                "Stale report cache",
                "Check persisted artifact versions before changing the parser again.",
                "report cache remains stale",
            ),
            session_id=engine.session_id,
        ),
        raise_handler_errors=True,
    )
    assert replies[-1].snapshot is not None
    await bus.publish(UserMessage(text="The report cache remains stale. What should I inspect?"))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    first = "\n".join(message.text or "" for message in client.call_history[0][0])
    assert "Check persisted artifact versions" in first
    assert '"when_to_use": "report cache remains stale"' in first
    assert '"source"' in first
    await bus.publish(PersonalMemoryCommand(action="settings", mode="off", capture=False, session_id=engine.session_id))
    await bus.publish(UserMessage(text="What about the report cache now?"))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    last_user = [message for message in client.call_history[-1][0] if message.role == "user"][-1]
    assert "Previously recalled personal memories are withdrawn" in (last_user.text or "")
    assert "Check persisted artifact versions" not in (last_user.text or "")


async def test_model_suggestion_has_quote_and_waits_for_confirmation(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    quote = "客户宣讲要突出价值和落地。"
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "memory-one",
                        {
                            "title": "客户宣讲",
                            "content": "客户宣讲优先解释应用价值与落地路径。",
                            "when_to_use": "制作客户宣讲材料",
                            "source_quote": quote,
                            "kind": "preference",
                            "project_only": False,
                        },
                    )
                ]
            ),
            MockResponse(text="已提出一条记忆建议。等待确认。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=quote))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    state = await asyncio.to_thread(PersonalMemoryStore().load)
    assert len(state.entries) == 1
    entry = state.entries[0]
    assert entry.state == "candidate"
    assert entry.source.quote == quote and entry.source.role == "user"
    assert entry.source.session_id == engine.session_id
    assert await asyncio.to_thread(PersonalMemoryStore().recall, "客户宣讲材料", "") == ()
    await bus.publish(
        PersonalMemoryCommand(
            action="state", memory_id=entry.id, revision=entry.revision, state="active", session_id=engine.session_id
        )
    )
    recalled = await asyncio.to_thread(PersonalMemoryStore().recall, "客户宣讲材料", "")
    assert recalled[0][0].id == entry.id


async def test_suggestion_rejects_fabricated_evidence(agent_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "bad-source",
                        {
                            "title": "Unfounded preference",
                            "content": "User always wants SQLite",
                            "when_to_use": "storage design",
                            "source_quote": "I always want SQLite",
                        },
                    )
                ]
            ),
            MockResponse(text="No supported memory saved."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text="Compare local storage options."))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    assert (await asyncio.to_thread(PersonalMemoryStore().load)).entries == ()
