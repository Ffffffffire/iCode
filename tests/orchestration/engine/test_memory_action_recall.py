# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Action-specific memories reach the real model/tool loop without extra inference."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from chrys.foundation.config.settings import Settings
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.types import UserMessage
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.orchestration.engine.build import builder
from chrys.service.approval.policy import ApprovalMode
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.profiles.agents.schema import AgentProfile, CompactionConfig, SkillsConfig, ToolsConfig
from tests.support.waiting import await_run_task_chain


async def test_first_write_recovers_memory_missing_from_the_opening_query(
    agent_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore()
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft("Slide layout", "Use dense diagrams", "technical slides", kind="preference"),
        MemorySource(),
    )
    target = tmp_path / "technical-slides.md"
    client = MockChatClient(
        [
            MockResponse(tool_calls=[("write_file", "write", {"path": str(target), "content": "# technical slides"})]),
            MockResponse(text="Done."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(
        AgentProfile(
            name="MemoryAction",
            instructions="Help the user.",
            tools=ToolsConfig(builtins=["filesystem.write"]),
            skills=SkillsConfig(auto_load_user_agents_skills=False),
            compaction=CompactionConfig(enabled=False),
        )
    )
    await bus.publish(UserMessage(text="Fix the failure, please."))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)
    assert len(client.call_history) == 2
    before = json.dumps([message.to_dict() for message in client.call_history[0][0]])
    after = json.dumps([message.to_dict() for message in client.call_history[1][0]])
    assert target.read_text(encoding="utf-8").strip() == "# technical slides"
    assert entry.id not in before
    assert entry.id in after
    state = await asyncio.to_thread(store.load)
    assert state.recalls[0].matches[0].layer == "L2"


async def test_all_four_layers_reach_the_model_and_share_one_versioned_receipt(
    agent_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore()
    drafts = (
        MemoryDraft("Collaboration", "Lead with evidence", "", kind="preference", use="always"),
        MemoryDraft("Cache invalidation", "Check the parser version", "Fixing cache failures"),
        MemoryDraft("Slide layout", "Use dense diagrams", "Preparing technical slides", kind="preference"),
        MemoryDraft("Release checklist", "Verify the release artifact", "Publishing a release"),
    )
    standing, opening, action, explicit = [
        await asyncio.to_thread(store.save, draft, MemorySource()) for draft in drafts
    ]
    target = tmp_path / "technical-slides.md"
    client = MockChatClient(
        [
            MockResponse(tool_calls=[("write_file", "write", {"path": str(target), "content": "# slides"})]),
            MockResponse(tool_calls=[("recall_memory", "lookup", {"query": explicit.id})]),
            MockResponse(text="Done."),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    engine = agent_engine(bus, settings=Settings(), initial_approval_mode=ApprovalMode.BYPASS)
    await engine.start(
        AgentProfile(
            name="MemoryLayers",
            instructions="Help the user.",
            tools=ToolsConfig(builtins=["filesystem.write"]),
            skills=SkillsConfig(auto_load_user_agents_skills=False),
            compaction=CompactionConfig(enabled=False),
        )
    )
    await bus.publish(UserMessage(text="Fix the cache failure."))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)

    assert len(client.call_history) == 3
    requests = [json.dumps([m.to_dict() for m in call[0]]) for call in client.call_history]
    assert all(e.id in requests[0] for e in (standing, opening))
    assert all(e.id not in requests[0] for e in (action, explicit))
    assert action.id in requests[1] and explicit.id not in requests[1]
    assert all(e.id in requests[2] for e in (standing, opening, action, explicit))
    state = await asyncio.to_thread(store.load)
    assert len(state.recalls) == 1
    receipt = state.recalls[0]
    assert [(m.memory_id, m.revision, m.layer) for m in receipt.matches] == [
        (standing.id, 1, "L0"),
        (opening.id, 1, "L1"),
        (action.id, 1, "L2"),
        (explicit.id, 1, "L3"),
    ]
    assert target.read_text(encoding="utf-8").strip() == "# slides"
