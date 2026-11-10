# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Recall examples exercise selection through the same store used by the agent."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.store import PersonalMemoryStore


@pytest.fixture
def slide_memory(tmp_path: Path):
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft(
            "PPT 版式偏好",
            "用户偏好形状较多、图文结合、信息密度较高的技术版面。以绘图说明原理和效果。",
            "制作技术 PPT 时",
            kind="preference",
        ),
        MemorySource(),
    )
    return store, entry


@pytest.mark.parametrize("query", ["Help me prepare PowerPoint slides", "帮我制作技术幻灯片", "做一份演示文稿"])
def test_presentation_topic_bridges_language_and_wording(slide_memory, query: str) -> None:
    store, entry = slide_memory
    assert [item.id for item, _ in store.recall(query, "")] == [entry.id]


def test_generic_words_do_not_recall_a_slide_preference(slide_memory) -> None:
    store, _ = slide_memory
    assert store.recall("记忆系统如何追踪效果? 用户是否给予肯定?", "") == ()


def test_generic_creation_verbs_are_not_an_application_context(slide_memory) -> None:
    store, _ = slide_memory
    assert store.recall("帮我制作数据库连接池", "") == ()


def test_english_function_words_do_not_select_an_unrelated_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Ownership", "Name the consumer first", "In reusable abstractions"), MemorySource())
    assert store.recall("Can it be in the folder?", "") == ()


def test_ambiguous_prefix_is_not_an_identity_hit(slide_memory) -> None:
    from chrys.service.personal_memory.retrieval import MemoryRetriever

    _, entry = slide_memory
    first = replace(entry, id="12345678aaaaaaaa")
    second = replace(entry, id="12345678bbbbbbbb")
    index = MemoryRetriever()
    assert index.search((first, second), "12345678", "", automatic=False) == ()
    matches = index.search((first, second), f"slides {second.id}", "", automatic=False)
    assert matches[0].memory_id == second.id and "identity" in matches[0].routes


def test_body_matches_do_not_override_a_different_application(slide_memory) -> None:
    store, _ = slide_memory
    assert store.recall("实现一个图文结合、信息密度较高的网页", "") == ()


def test_absence_of_a_format_is_not_evidence_of_incompatibility(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Python conventions", "Prefer typed interfaces", "When writing Python"), MemorySource()
    )
    assert [item.id for item, _ in store.recall("Implement a Python helper", "")] == [entry.id]


def test_explicit_identity_can_locate_a_memory_without_keyword_overlap(slide_memory) -> None:
    store, entry = slide_memory
    assert [item.id for item, _ in store.recall(entry.id, "", automatic=False)] == [entry.id]
    assert [item.id for item, _ in store.recall(entry.id[:10], "", automatic=False)] == [entry.id]
    assert [item.id for item, _ in store.recall(f"查看记忆{entry.id}", "", automatic=False)] == [entry.id]


def test_a_specific_short_chinese_topic_is_searchable(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("绘图", "优先使用可编辑矢量图。", "绘图时"), MemorySource())
    assert [item.id for item, _ in store.recall("绘图", "")] == [entry.id]


@pytest.mark.parametrize(("title", "query"), [("中文交流习惯", "请用中文回答"), ("时序表达", "补充时序细节")])
def test_meaningful_chinese_words_keep_their_first_character(tmp_path: Path, title: str, query: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft(title, "Use the agreed presentation", "协作时"), MemorySource())
    assert [item.id for item, _ in store.recall(query, "")] == [entry.id]


def test_distinctive_english_typo_has_a_bounded_fallback(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Observability", "Start from the failing span.", "Debugging observability"), MemorySource()
    )
    assert [item.id for item, _ in store.recall("debug observabilty", "")] == [entry.id]


def test_continuation_uses_only_the_supplied_task_context(slide_memory) -> None:
    store, entry = slide_memory
    assert store.recall("继续", "") == ()
    assert [item.id for item, _ in store.recall("继续", "", context="制作技术 PPT")] == [entry.id]
    assert store.recall("设计一个数据库连接池", "", context="制作技术 PPT") == ()


def test_hot_query_observes_corrections_pause_deletion_and_other_writers(slide_memory) -> None:
    store, entry = slide_memory
    assert store.recall("PPT", "")
    other = PersonalMemoryStore(store.path)
    revised = other.save(
        replace(entry.draft, content="技术 PPT 使用适中的信息密度。"),
        entry.source,
        memory_id=entry.id,
        revision=entry.revision,
    )
    assert store.recall("PPT", "")[0][0] == revised
    other.set_state(revised.id, revised.revision, "archived")
    assert store.recall("PPT", "") == ()
    paused = other.load().entries[0]
    other.forget(paused.id, paused.revision)
    assert store.recall("PPT", "") == ()


def test_every_route_respects_scope_and_modes(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    workspace = str(tmp_path / "private-project")
    entry = store.save(MemoryDraft("PPT", "Use diagrams", "PPT", workspace=workspace), MemorySource())
    for query in (entry.id, "slides", "PPT"):
        assert store.recall(query, str(tmp_path / "other")) == ()
        assert store.recall(query, workspace)
    store.configure("manual", False)
    assert store.recall("slides", workspace) == ()
    assert store.recall("slides", workspace, automatic=False)
    store.configure("off", False)
    assert store.recall(entry.id, workspace, automatic=False) == ()


def test_hot_queries_reuse_index_even_when_recall_records_change(slide_memory, monkeypatch: pytest.MonkeyPatch) -> None:
    from chrys.service.personal_memory import retrieval

    store, entry = slide_memory
    store.recall("PPT", "", session_id="one")

    def unexpected_tokenization(_text: str):
        pytest.fail("An unchanged hot query should not tokenize or rebuild its index")

    monkeypatch.setattr(retrieval, "_tokens", unexpected_tokenization)
    assert store.recall("PPT", "", session_id="two")[0][0].id == entry.id


def test_title_matching_does_not_match_inside_an_english_word(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Git", "Keep commits small", "Git changes"), MemorySource())
    assert store.recall("design a digital clock", "") == ()


def test_routes_survive_reload_without_becoming_confidence_scores(slide_memory) -> None:
    store, entry = slide_memory
    ((_, match),) = store.recall("slides", "", session_id="one")
    assert "topic" in match.routes
    assert store.load().recalls[0].matches == (match,)
    ((_, direct),) = store.recall(entry.id, "")
    assert "identity" in direct.routes
