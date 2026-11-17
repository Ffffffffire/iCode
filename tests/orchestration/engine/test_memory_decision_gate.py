# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""New decision evidence reaches the model before local actions leave effects."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from chrys.foundation.config.settings import Settings
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.types import ApprovalRequest, ApprovalResponse, UserMessage
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.orchestration.engine.build import builder
from chrys.service.approval.policy import ApprovalMode
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.profiles.agents.schema import (
    AgentProfile,
    ApprovalConfig,
    CompactionConfig,
    SkillsConfig,
    ToolsConfig,
)
from chrys.service.profiles.models.registry import ModelProfileRegistry
from chrys.service.profiles.models.schema import ModelProfile
from chrys.service.tools.kinds import tool
from tests.support.tool_packs import install_tools
from tests.support.waiting import await_run_task_chain


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("approval", ["bypass", "allow", "deny"])
async def test_entire_action_batch_waits_for_new_memory_before_any_write(
    agent_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: bool, approval: str
) -> None:
    store = PersonalMemoryStore()
    for title in ("Cache keys", "Cache artifacts"):
        await asyncio.to_thread(store.save, MemoryDraft(title, title, "cache"), MemorySource())
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft("Shell configuration", "Explain the impact before editing", "Changing bashrc"),
        MemorySource(),
    )
    writes: list[str] = []

    @tool(kind="filesystem.write")
    def write_file(path: str, content: str) -> str:
        """Write the requested file."""
        writes.append(content)
        Path(path).write_text(content, encoding="utf-8")
        return "Written"

    install_tools(monkeypatch, [write_file])
    first = str(tmp_path / ".bashrc")
    other = str(tmp_path / "other.txt")
    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[
                    ("write_file", "parallel", {"path": other, "content": "UNREVIEWED"}),
                    ("write_file", "first", {"path": first, "content": "UNREVIEWED"}),
                ]
            ),
            MockResponse(tool_calls=[("write_file", "reviewed", {"path": first, "content": "REVIEWED"})]),
            MockResponse(text="Done"),
        ]
    )
    monkeypatch.setattr(builder, "create_client", create_autospec(builder.create_client, return_value=client))
    bus = EventBus()
    requests: list[ApprovalRequest] = []

    async def decide(event: ApprovalRequest) -> None:
        requests.append(event)
        await bus.publish(ApprovalResponse(request_id=event.request_id, approved=approval == "allow"))

    await bus.subscribe(ApprovalRequest, decide)
    models = ModelProfileRegistry()
    models.register(ModelProfile(id="memory-model", name="mock", provider="mock", model_id="mock", stream=stream))
    engine = agent_engine(
        bus,
        settings=Settings(model_profile="memory-model"),
        model_registry=models,
        initial_approval_mode=ApprovalMode.BYPASS if approval == "bypass" else ApprovalMode.MANUAL,
    )
    await engine.start(
        AgentProfile(
            name="MemoryDecisions",
            instructions="Help the user.",
            tools=ToolsConfig(builtins=[]),
            skills=SkillsConfig(auto_load_user_agents_skills=False),
            compaction=CompactionConfig(enabled=False),
            approval=ApprovalConfig(default="require"),
        )
    )
    await bus.publish(UserMessage(text="Fix the cache failure"))
    await await_run_task_chain(engine, turn_state=engine.turns.turn_state)

    assert writes == ([] if approval == "deny" else ["REVIEWED"])
    assert len(requests) == (0 if approval == "bypass" else 1)
    assert not Path(other).exists()
    wire = json.dumps([m.to_dict() for m in client.call_history[1][0]])
    assert entry.draft.content in wire
    assert "NOT EXECUTED" in wire
    assert len(client.call_history) == 3
    results = [c for m in client.call_history[1][0] for c in m.contents if c.type == "function_result"]
    assert sum("<personal_memory_action>" in str(c.result) for c in results) == 1
    assert (await asyncio.to_thread(store.load)).recalls[0].searches == 1
