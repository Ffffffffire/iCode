# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Separate the user's decision from lexical overlap and previously supplied evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryRelation, MemorySource, PersonalMemory
from chrys.kernel import Agent, Message
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.tools.kinds import tool


def _runtime(store: PersonalMemoryStore, workspace: str = "") -> PersonalMemoryRuntime:
    return PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=workspace, store=store)


def _slides(store: PersonalMemoryStore) -> PersonalMemory:
    return store.save(
        MemoryDraft("技术 PPT 版式", "技术汇报优先密集的架构图和图文结合。", "制作技术 PPT 或 PowerPoint slides"),
        MemorySource(),
    )


def test_excluding_a_delivered_match_does_not_admit_a_weak_match(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    correct = store.save(
        MemoryDraft(
            "Parser invalidation contract",
            "Compare persisted parser versions before changing behavior.",
            "Cache parser invalidation.",
        ),
        MemorySource(),
    )
    store.save(
        MemoryDraft(
            "Cache report formatting",
            "Use the reporting layout for weekly service metrics.",
            "Drafting a cache report.",
        ),
        MemorySource(),
    )
    query = "Change cache parser invalidation behavior"
    assert [entry.id for entry, _ in store.recall(query, "", session_id="one", turn_id="turn")] == [correct.id]
    receipt = store.receipts_path.read_bytes()
    assert not store.recall(
        query,
        "",
        session_id="one",
        turn_id="turn",
        layer="L2",
        novel_only=True,
        extend_record=True,
    )
    assert store.receipts_path.read_bytes() == receipt


def test_independent_decisions_do_not_share_a_relative_score_floor(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    rollback = store.save(
        MemoryDraft(
            "Rollback drill",
            "Verify that the previous artifact can be restored.",
            "Before a release, confirm rollback.",
        ),
        MemorySource(),
    )
    environment = store.save(
        MemoryDraft(
            "Staging configuration environment identity variables destinations",
            "Confirm all values target the same staging environment.",
            "Verify staging configuration environment identity variables and destinations.",
        ),
        MemorySource(),
    )
    query = (
        "Before release, check rollback and verify staging configuration environment identity variables destinations"
    )
    assert {entry.id for entry, _ in store.recall(query, "", record=False)} == {rollback.id, environment.id}


def test_counting_format_mentions_does_not_activate_a_creation_preference(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    slides = _slides(store)
    assert store.recall("请制作技术 PPT", "", record=False)[0][0].id == slides.id
    assert not store.recall("不要制作 PPT。只统计提供的文字中出现了多少次 PowerPoint。", "", record=False)
    rollback = store.save(MemoryDraft("回滚检查", "验证上一版本能恢复。", "检查回滚"), MemorySource())
    assert [entry.id for entry, _ in store.recall("不要制作 PPT\uff0c先检查回滚", "", record=False)] == [rollback.id]


def test_standing_preferences_do_not_expand_a_link_in_an_unrelated_task(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    language = store.save(
        MemoryDraft("中文交流", "默认用中文沟通。", "日常协作", kind="preference", use="always"), MemorySource()
    )
    slides = store.save(
        MemoryDraft(
            "架构图的中文标注",
            "技术 PPT 的架构图优先用中文标注关键步骤。",
            "制作技术 PPT",
            relations=(MemoryRelation(language.id, language.revision, "derived_from", "把协作语言应用到图示。"),),
        ),
        MemorySource(),
    )
    assert [entry.id for entry, _ in store.recall("修复数据库连接池死锁。", "", record=False)] == [language.id]
    assert slides.id in {entry.id for entry, _ in store.recall("制作技术 PPT", "", record=False)}


def test_recall_adds_linked_evidence_and_only_applicable_format_exceptions(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    policy = store.save(MemoryDraft("Font contrast", "Contrast was legible in a reading test.", ""), MemorySource())
    exception = store.save(
        MemoryDraft(
            "Projection exception", "Use larger labels at projection distance.", "Projecting PowerPoint slides"
        ),
        MemorySource(),
    )
    diagrams = store.save(
        MemoryDraft(
            "Architecture diagrams",
            "Label the decisions and transitions.",
            "Preparing architecture diagrams.",
            relations=(
                MemoryRelation(policy.id, policy.revision, "supports", "Contrast supports legibility."),
                MemoryRelation(exception.id, exception.revision, "exception", "Projection changes label sizing."),
            ),
        ),
        MemorySource(),
    )
    results = {entry.id: match.routes for entry, match in store.recall("Make architecture diagrams", "", record=False)}
    assert results.keys() == {diagrams.id, policy.id}
    assert results[policy.id] == ("association",)


@pytest.mark.parametrize(
    "content",
    [
        "Supported file extension: PowerPoint (read only).",
        "# Supported formats\nReading PowerPoint is supported.",
    ],
)
async def test_reference_in_a_write_payload_does_not_defer_the_write(tmp_path: Path, content: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    _slides(store)
    runtime = _runtime(store)
    user = Message("user", ["Document the supported input formats."])
    await runtime.prepare([user])
    effects = []

    @tool(kind="filesystem.write")
    def write_file(path: str, content: str) -> str:
        """Write text to a file."""
        effects.append(path)
        return content

    client = MockChatClient(
        [
            MockResponse(tool_calls=[("write_file", "write", {"path": "usage.md", "content": content})]),
            MockResponse(text="Done"),
        ]
    )
    async with Agent(client=client, tools=[write_file], middleware=runtime.middleware()) as agent:
        await agent.run([user])
    assert effects == ["usage.md"]
    assert store.load().recalls[-1].searches == 0


async def test_change_of_deliverable_at_the_same_path_checks_the_new_decision(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    memory = _slides(store)
    runtime = _runtime(store)
    user = Message("user", ["Complete the requested deliverable."])
    await runtime.prepare([user])
    effects = []

    @tool(kind="filesystem.write")
    def write_file(path: str, content: str) -> str:
        """Write text to a file."""
        effects.append(content)
        return path

    client = MockChatClient(
        [
            MockResponse(
                tool_calls=[("write_file", "draft", {"path": "artifact.md", "content": "Draft placeholder."})]
            ),
            MockResponse(
                tool_calls=[
                    (
                        "write_file",
                        "slides",
                        {
                            "path": "artifact.md",
                            "content": "# PowerPoint slides for a system architecture presentation",
                        },
                    )
                ]
            ),
            MockResponse(text="Stopped for review"),
        ]
    )
    async with Agent(client=client, tools=[write_file], middleware=runtime.middleware()) as agent:
        await agent.run([user])
    assert effects == ["Draft placeholder."]
    assert memory.id in str([message.to_dict() for message in client.call_history[-1][0]])


async def test_bounded_query_reformulation_recovers_a_lesson_in_the_same_scope(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    workspace = str(tmp_path / "current")
    entry = store.save(
        MemoryDraft("轨迹 IR 的消费方", "验证下游消费后再增加字段。", "轨迹 IR 新增字段", workspace=workspace),
        MemorySource(),
    )
    store.save(
        MemoryDraft("其他项目的轨迹 IR", "依赖私有接口。", "轨迹 IR 新增字段", workspace=str(tmp_path / "other")),
        MemorySource(),
    )
    runtime = _runtime(store, workspace)
    query = "每层都多产出一些供下一层处理的数据\uff0c怎么判断哪些值得做"
    await runtime.prepare([Message("user", [query])])
    assert store.load().recalls[-1].matches == ()
    result = await runtime.recall_memory(query, alternatives=["轨迹 IR 新增字段", "IR 消费方"])
    assert [json.loads(line)["id"] for line in result.splitlines()] == [entry.id]
    receipt = store.load().recalls[-1]
    assert receipt.searches == 1
    assert receipt.matches[0].layer == "L3"
