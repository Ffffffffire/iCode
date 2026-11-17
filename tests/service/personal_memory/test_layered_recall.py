# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Layered recall reaches the agent at the stage where its cue becomes available."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Agent, Message
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.tools.kinds import tool


@pytest.mark.parametrize(
    "path",
    [
        "src/chrys/kernel/retry_policy.py",
        "src/chrys/kernel/RetryPolicy.py",
        "RetryPolicy",
        "HTTPRetryPolicy",
        "src/retry-policy.py",
        r"D:\work\retry_policy.py",
    ],
)
async def test_action_file_identifier_recalls_the_natural_language_decision(tmp_path: Path, path: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft("Retry policy", "Keep wire and validation retries independent", "Changing retry policy"),
        MemorySource(),
    )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    message = Message("user", ["Fix the failure"])
    opening = await runtime.prepare([message])
    assert entry.id not in opening

    @tool(kind="filesystem.write")
    def edit_file(path: str) -> str:
        """Apply the requested edit."""
        return "Completed " + path

    client = MockChatClient(
        [
            MockResponse(tool_calls=[("edit_file", "edit", {"path": path})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=client, tools=[edit_file], middleware=runtime.middleware()) as agent:
        await agent.run([message])

    wire = json.dumps([m.to_dict() for m in client.call_history[-1][0]])
    assert entry.id in wire
    assert entry.draft.content in wire
    state = await asyncio.to_thread(store.load)
    assert [(m.memory_id, m.layer) for m in state.recalls[0].matches] == [(entry.id, "L2")]
    assert len(client.call_history) == 2


def test_casefolded_queries_with_different_identifier_boundaries_do_not_share_cached_results(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Retry policy", "Keep retry lanes independent", "Changing retry policy"), MemorySource()
    )
    assert store.recall("retrypolicy", "", record=False) == ()
    assert [e.id for e, _ in store.recall("RetryPolicy", "", record=False)] == [entry.id]
    assert store.recall("retrypolicy", "", record=False) == ()


@pytest.mark.parametrize("title", ["RetryPolicy", "retry_policy.py", "HTTPRetryPolicy"])
def test_natural_language_query_finds_a_memory_named_by_its_code_identifier(tmp_path: Path, title: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft(title, "Keep wire and validation lanes independent", "Changing this component"), MemorySource()
    )
    assert [e.id for e, _ in store.recall("retry policy", "", record=False)] == [entry.id]


@pytest.mark.parametrize(
    "query", ["deepseek-v4-flash", "DeepSeek-v4-flash", "other.py", "C# code", "plain net service"]
)
def test_identifier_expansion_preserves_distinct_technical_names(tmp_path: Path, query: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for title in ("Deep", "Flash", "Python", "C++", ".NET"):
        store.save(MemoryDraft(title, "Check its specific runtime contract", "Changing " + title), MemorySource())
    assert store.recall(query, "", record=False) == ()


@pytest.mark.parametrize("filename", ["PowerPoint.md", "build_PowerPoint.py"])
def test_known_alias_in_a_filename_is_not_split_into_unrelated_words(tmp_path: Path, filename: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft(filename, "Use dense diagrams", "Preparing slides"), MemorySource())
    assert [e.id for e, _ in store.recall("PowerPoint", "", record=False)] == [entry.id]
    assert store.recall("power controls", "", record=False) == ()


def test_product_name_does_not_turn_into_a_generic_coding_cue(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("iCode TUI", "Reuse native components", "Extending iCode TUI"), MemorySource())
    assert [e.id for e, _ in store.recall("iCode TUI", "", record=False)] == [entry.id]
    assert store.recall("Write code", "", record=False) == ()
