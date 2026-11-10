# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Labeled retrieval regressions: unrelated near matches are errors, not useful recall."""

from __future__ import annotations

from dataclasses import replace

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource, PersonalMemory
from chrys.service.personal_memory.retrieval import MemoryRetriever


def memory(number: int, title: str, content: str, situation: str) -> PersonalMemory:
    return PersonalMemory(
        f"{number:016x}",
        1,
        MemoryDraft(title, content, situation),
        MemorySource(),
        "active",
        "2026-01-01",
        "2026-01-01",
    )


CORPUS = (
    memory(1, "技术 PPT 版式", "图文结合; 多使用图形结构。", "制作技术 PPT"),
    memory(2, "Git rebase", "先核实共享分支是否允许改写历史。", "Before git rebase"),
    memory(3, "缓存失效", "修改识别逻辑后检查持久化缓存版本。", "修改缓存识别逻辑"),
    memory(4, "Python tests", "Run focused tests before the broad suite.", "Running Python tests"),
    memory(5, "C++ ownership", "Prefer explicit RAII ownership.", "Writing C++"),
    memory(6, "C# project", "Keep nullable references enabled.", "Writing C#"),
    memory(7, "Observability", "Inspect the failed span before changing instrumentation.", "Debugging observability"),
    memory(8, "中文交流", "优先使用中文解释设计。", "中文交流"),
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("帮我制作技术幻灯片", {1}),
        ("Prepare PowerPoint slides", {1}),
        ("制作网页; 用图形结构展示系统", set()),
        ("用户是否肯定了记忆的效果", set()),
        ("帮我制作数据库连接池", set()),
        ("git rebase this branch", {2}),
        ("git diff 查看变更", set()),
        ("修改缓存识别逻辑", {3}),
        ("Run Python tests", {4}),
        ("讲解线性回归原理", set()),
        ("Writing C++ ownership code", {5}),
        ("Writing C# code", {6}),
        ("debug observabilty", {7}),
        ("xbservability", {7}),
        ("请用中文交流", {8}),
    ],
)
def test_labeled_queries_retrieve_only_applicable_memories(query: str, expected: set[int]) -> None:
    matches = MemoryRetriever().search(CORPUS, query, "", automatic=True)
    assert {int(match.memory_id, 16) for match in matches[:5]} == expected


def test_auto_drops_weak_shared_topics_while_manual_search_keeps_them() -> None:
    generic = memory(1, "Cache", "Choose cache keys carefully.", "Caching")
    specific = memory(2, "Cache invalidation", "Include the parser version.", "Cache parser invalidation")
    matches = MemoryRetriever().search((generic, specific), "cache parser invalidation", "", automatic=True)
    assert [match.memory_id for match in matches] == [specific.id]
    manual = MemoryRetriever().search((generic, specific), "cache parser invalidation", "", automatic=False)
    assert [match.memory_id for match in manual] == [specific.id, generic.id]


def test_a_named_component_is_not_diluted_by_499_shared_topic_matches() -> None:
    entries = tuple(
        memory(i, f"Component {i} cache policy", f"Inspect component {i}", f"Cache invalidation for component {i}")
        for i in range(500)
    )
    matches = MemoryRetriever().search(entries, "component 250 cache policy", "", automatic=True)
    assert [match.memory_id for match in matches] == [entries[250].id]


def test_retelling_a_fact_does_not_increase_its_relevance() -> None:
    entry = CORPUS[2]
    other = memory(9, "缓存版本", "检查版本", "修改缓存")
    repeated = replace(entry, draft=replace(entry.draft, content=(entry.draft.content + " ") * 30))
    original = MemoryRetriever().search((entry, other), "缓存版本", "", automatic=True)
    expanded = MemoryRetriever().search((repeated, other), "缓存版本", "", automatic=True)
    assert original[0].memory_id == expanded[0].memory_id == other.id


@pytest.mark.parametrize("platform_word", ["Agent", "Agents", "智能体"])
def test_platform_context_alone_does_not_inject_unrelated_authoring_preferences(platform_word: str) -> None:
    profile = memory(1, f"{platform_word} Profile", "Declare dedicated skills", f"Configure a {platform_word} Profile")
    skill = memory(2, "Skill boundaries", "Do not redefine responsibilities", f"Design a {platform_word} Skill")
    retriever = MemoryRetriever()
    entries = (profile, skill)
    assert retriever.search(entries, f"Graph Learning 与 {platform_word} Harness 的结合", "", automatic=True) == ()
    assert {m.memory_id for m in retriever.search(entries, platform_word, "", automatic=False)} == {
        profile.id,
        skill.id,
    }
    assert (
        retriever.search(entries, f"Configure {platform_word} Profile", "", automatic=True)[0].memory_id == profile.id
    )
    assert retriever.search(entries, f"Design {platform_word} Skill", "", automatic=True)[0].memory_id == skill.id
