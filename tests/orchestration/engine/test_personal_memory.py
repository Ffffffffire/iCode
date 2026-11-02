# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Real engine tests for memory reaching requests and suggestions reaching persistence."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import create_autospec

import pytest

from chrys.foundation.config.settings import Settings
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.events.types import UserMessage
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
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


def _extraction_response(quote: str, content: str, **fields) -> MockResponse:
    return MockResponse(
        text=json.dumps(
            {
                "memories": [
                    {
                        "title": "Reusable choice",
                        "content": content,
                        "when_to_use": "Similar future tasks",
                        "source_quote": quote,
                        "basis": "request",
                        **fields,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )


async def test_enabled_capture_extracts_without_a_memory_tool_call(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    preference = "我做技术汇报更习惯用图讲清楚结构，信息可以密一点，别整页都是文字。"  # noqa: RUF001
    extracted = {
        "memories": [
            {
                "title": "技术汇报版式",
                "content": "技术汇报偏好图形化、信息密度较高的版式，避免整页纯文字。",  # noqa: RUF001
                "when_to_use": "制作技术汇报 PPT",
                "kind": "preference",
                "project_only": False,
                "source_quote": preference,
                "basis": "stated",
            }
        ]
    }
    client = MockChatClient(
        [MockResponse(text=json.dumps(extracted, ensure_ascii=False)), MockResponse(text="会按这个风格制作。")]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    store = PersonalMemoryStore()
    await asyncio.to_thread(store.configure, "auto", True)
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=preference))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    entries = (await asyncio.to_thread(store.load)).entries
    assert len(entries) == 1
    assert entries[0].source.quote == preference
    assert entries[0].draft.content == extracted["memories"][0]["content"]
    assert entries[0].draft.workspace == ""
    assert entries[0].state == "active"


async def test_followup_save_uses_the_earlier_user_preference_as_evidence(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    preference = "我更喜欢图文结合、信息密度较高的技术 PPT 版面。"
    client = MockChatClient(
        [
            MockResponse(text="这次技术 PPT 会按这个偏好制作。"),
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "save-preference",
                        {
                            "title": "技术 PPT 版式偏好",
                            "content": "技术 PPT 使用图文结合、信息密度较高的版式。",
                            "when_to_use": "制作技术 PPT",
                            "source_quote": preference,
                            "kind": "preference",
                            "project_only": False,
                            "save_now": True,
                        },
                    )
                ]
            ),
            _extraction_response(
                preference, "技术 PPT 使用图文结合、信息密度较高的版式。", kind="preference", project_only=False
            ),
            MockResponse(text="已记住这条技术 PPT 偏好。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=preference))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    assert (await asyncio.to_thread(PersonalMemoryStore().load)).entries == ()
    await bus.publish(UserMessage(text="润色后帮我记住这条偏好"))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    state = await asyncio.to_thread(PersonalMemoryStore().load)
    assert len(state.entries) == 1 and state.entries[0].state == "active"
    assert state.entries[0].source.quote == preference
    assert state.entries[0].source.role == "user"
    assert state.entries[0].source.session_id == engine.session_id
    assert state.entries[0].draft.workspace == ""
    assert state.capture is False


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
            MockResponse(text='{"memories": []}'),
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
            _extraction_response(
                quote,
                "客户宣讲优先解释应用价值与落地路径。",
                kind="preference",
                basis="stated",
                project_only=False,
                when_to_use="制作客户宣讲材料",
            ),
            MockResponse(text="已提出一条记忆建议。等待确认。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(
        PersonalMemoryCommand(
            action="settings", mode="auto", capture=True, auto_save=False, session_id=engine.session_id
        )
    )
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


async def test_explicit_user_request_saves_without_suggestion_review(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = "请记住: 报告缓存仍旧时, 先检查持久化产物版本。"
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "save-now",
                        {
                            "title": "报告缓存排查",
                            "content": "报告缓存仍旧时, 先检查持久化产物版本。",
                            "when_to_use": "报告缓存仍旧",
                            "source_quote": request,
                            "kind": "lesson",
                            "save_now": True,
                        },
                    )
                ]
            ),
            _extraction_response(
                request, "报告缓存仍旧时, 先检查持久化产物版本。", title="报告缓存排查", when_to_use="报告缓存仍旧"
            ),
            MockResponse(text="已经记住。"),
            MockResponse(text="先检查产物版本。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=request))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    state = await asyncio.to_thread(PersonalMemoryStore().load)
    assert state.capture is False
    assert len(state.entries) == 1 and state.entries[0].state == "active"
    assert state.entries[0].source.quote == request
    await bus.publish(UserMessage(text="报告缓存仍旧, 接下来查什么?"))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    latest = "\n".join(message.text or "" for message in client.call_history[-1][0])
    assert "报告缓存排查" in latest


@pytest.mark.parametrize("prompt", ["请比较报告缓存的排查方案。", "我在设计记住用户偏好的按钮, 请比较文案。"])
async def test_unrequested_direct_save_is_rejected(agent_engine, monkeypatch: pytest.MonkeyPatch, prompt: str) -> None:
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "unrequested-save",
                        {
                            "title": "报告缓存",
                            "content": "总是先删缓存。",
                            "when_to_use": "报告缓存异常",
                            "source_quote": prompt,
                            "save_now": True,
                        },
                    )
                ]
            ),
            MockResponse(text='{"memories": []}'),
            MockResponse(text="未保存。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=prompt))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    assert (await asyncio.to_thread(PersonalMemoryStore().load)).entries == ()


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


async def test_chat_correction_replaces_the_memory_in_the_next_request(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await asyncio.to_thread(
        PersonalMemoryStore().save,
        MemoryDraft("Report cache", "Delete cache before investigation", "stale report cache"),
        MemorySource(quote="Earlier advice"),
    )
    correction = "Update this memory: inspect artifact versions before deleting report cache."
    client = MockChatClient(
        [
            MockResponse(text="Earlier advice was offered."),
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "correct-memory",
                        {
                            "title": "Report cache",
                            "content": "Inspect artifact versions before deleting report cache",
                            "when_to_use": "stale report cache",
                            "source_quote": correction,
                            "save_now": True,
                            "replaces_id": old.id,
                            "replaces_revision": old.revision,
                        },
                    )
                ]
            ),
            _extraction_response(
                correction,
                "Inspect artifact versions before deleting report cache",
                replaces_id=old.id,
                replaces_revision=old.revision,
                when_to_use="stale report cache",
            ),
            MockResponse(text="Corrected the existing memory."),
            MockResponse(text="Inspect artifact versions first."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    for prompt in ("How do I investigate stale report cache?", correction, "The report cache is stale again."):
        await bus.publish(UserMessage(text=prompt))
        await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    last_user = [message for message in client.call_history[-1][0] if message.role == "user"][-1]
    latest = last_user.text or ""
    assert "Inspect artifact versions before deleting report cache" in latest
    assert "Delete cache before investigation" not in latest
    assert f'"id": "{old.id}"' in latest and '"revision": 2' in latest
    state = await asyncio.to_thread(PersonalMemoryStore().load)
    assert len(state.entries) == 1 and state.entries[0].draft.workspace == ""
    assert state.entries[0].previous[0].draft.content == "Delete cache before investigation"
