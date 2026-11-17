# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Real engine tests for memory reaching requests and suggestions reaching persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from chrys.foundation.config.settings import Settings
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.events.types import SessionNew, UserMessage
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryFollowUp, MemorySource
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


async def test_real_engine_records_use_and_user_completion_without_extra_model(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore()
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft(
            "Release drill",
            "Verify rollback",
            "release rollback",
            kind="intention",
            follow_up=MemoryFollowUp(next_step="Run staging rollback"),
        ),
        MemorySource(),
    )
    quote = "The release rollback drill is completed."
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    (
                        "review_memory",
                        "applied",
                        {
                            "memory_id": entry.id,
                            "revision": 1,
                            "outcome": "applied",
                            "reason": "Located the user's open commitment",
                        },
                    )
                ]
            ),
            MockResponse(
                tool_calls=[
                    (
                        "update_follow_up",
                        "done",
                        {"memory_id": entry.id, "revision": 1, "status": "completed", "source_quote": quote},
                    )
                ]
            ),
            MockResponse(text="Marked the release drill completed."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=quote))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    snapshot = await asyncio.to_thread(store.load)
    assert snapshot.entries[0].draft.follow_up.status == "completed"
    applied = next(e for e in snapshot.activity if e.action == "applied")
    assert applied.turn_id and applied.actor == "agent"
    assert len(client.call_history) == 3


async def test_ordinary_task_with_capture_enabled_makes_only_the_main_model_call(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = MockChatClient([MockResponse(text="Here is the requested technical report.")])
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    store = PersonalMemoryStore()
    await asyncio.to_thread(store.configure, "auto", True, auto_save=True)
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text="Prepare a technical report about the memory implementation."))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    assert len(client.call_history) == 1
    assert (await asyncio.to_thread(store.load)).entries == ()


async def test_enabled_capture_uses_the_main_agents_tool_without_a_second_extractor(
    agent_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    preference = "I prefer dense diagrams for technical slides."
    proposal = {
        "title": "Technical slides",
        "content": "Prefer dense diagrams.",
        "when_to_use": "Technical slides",
        "kind": "preference",
        "project_only": False,
        "source_quote": preference,
        "basis": "stated",
    }
    client = MockChatClient(
        [
            MockResponse(tool_calls=[("propose_memory", "save-choice", proposal)]),
            MockResponse(text="Remembered the technical-slide preference."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    store = PersonalMemoryStore()
    await asyncio.to_thread(store.configure, "auto", True)
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(_profile())
    await bus.publish(UserMessage(text=preference))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    (entry,) = (await asyncio.to_thread(store.load)).entries
    assert entry.source.quote == preference and entry.draft.content == proposal["content"]
    assert entry.draft.workspace == "" and entry.state == "active"
    assert len(client.call_history) == 2


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


async def test_profile_lesson_keeps_the_rule_and_check_in_a_new_session(
    agent_engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = tmp_path / "Explore.yaml"
    profile.write_text(
        "sub_agent_only: true\n"
        "instructions: |\n"
        "  Return a read-only investigation with path:line references to the caller.\n"
        "tools:\n"
        "  builtins: [filesystem.read, search, shell]\n",
        encoding="utf-8",
    )
    request = "以 iCode 默认 Agent 的配置为范例，总结专业 Agent 的设计方法，并将其记住。"  # noqa: RUF001
    lesson = (
        "Design a specialist by choosing its caller and permissions before writing its instructions. "
        "For an investigation child, set sub_agent_only: true and expose filesystem.read and search, "
        "without filesystem.write. If shell is needed, name the allowed read operations and require approval "
        "in modes that enforce it. Omit shell when the child must be unable to change files. "
        "Tell the child its result goes to the calling agent. Lead with findings, provide path:line references "
        "and exact definitions, and list the locations searched when evidence is missing. "
        "Keep zero-hit queries, remaining leads, and the investigation boundary in compaction.last_words_template. "
        "Use Explore.yaml as the reference when changing the profile or checking which responsibilities it delegates."
    )
    application = (
        "Check the loaded tool list for the absence of write tools. Give the child a read-only configuration "
        "investigation and verify that the caller receives a finding with a navigable path:line and no file changes."
    )
    source_quote = "sub_agent_only: true"
    client = MockChatClient(
        [
            MockResponse(tool_calls=[("read_file", "profile-source", {"path": str(profile)})]),
            MockResponse(
                tool_calls=[
                    (
                        "propose_memory",
                        "save-lesson",
                        {
                            "title": "只读调查子代理的权限和交付",
                            "content": lesson,
                            "application": application,
                            "when_to_use": "设计给调用方返回证据的只读调查子代理",
                            "reconsider_when": "Agent 需要写入或工具与审批机制发生变化",
                            "source_quote": source_quote,
                            "kind": "lesson",
                            "save_now": True,
                            "aliases": ["只读审查 Agent"],
                        },
                    )
                ]
            ),
            MockResponse(text="已保存调查子代理的设计经验。"),
            MockResponse(text="检查加载的工具和调用方收到的路径与行号。"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(replace(_profile(), tools=ToolsConfig(builtins=["filesystem.read"])))
    original_session = engine.session_id
    await bus.publish(UserMessage(text=request))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)

    (entry,) = (await asyncio.to_thread(PersonalMemoryStore().load)).entries
    assert entry.state == "active"
    assert entry.source.role == "tool" and entry.source.quote == source_quote
    assert entry.source.session_id == original_session
    assert entry.draft.content == f"{lesson}\n\n{application}"

    await bus.publish(SessionNew())
    assert engine.session_id != original_session
    await bus.publish(UserMessage(text="我要加一个只读审查 Agent，给主 Agent 交回配置调查结果，怎样验收？"))  # noqa: RUF001
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)

    latest = "\n".join(message.text or "" for message in client.call_history[-1][0])
    (delivered,) = [json.loads(line) for line in latest.splitlines() if line.startswith(f'{{"id": "{entry.id}"')]
    assert delivered["memory"] == entry.draft.content
    assert delivered["source"]["quote"] == source_quote
    assert request not in latest


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
            MockResponse(tool_calls=[("recall_memory", "inspect-memory", {"query": old.id, "for_update": True})]),
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
