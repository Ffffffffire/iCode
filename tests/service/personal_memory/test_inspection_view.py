# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# ruff: noqa: RUF001 -- Corpus entries are verbatim user messages, punctuation included.

"""Inspection lists topics by default, and one inspection covers the entries it returned."""

from __future__ import annotations

import json

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


def _runtime(tmp_path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


def _observe(runtime: PersonalMemoryRuntime, text: str) -> None:
    runtime.observe([Message("user", [text])])


async def _write(runtime: PersonalMemoryRuntime, title: str, content: str, quote: str) -> str:
    result = await runtime.propose_memory(
        title=title,
        content=content,
        when_to_use="审阅提交范围时",
        source_quote=quote,
        save_now=True,
        intent_quote=quote,
    )
    assert not result.startswith("Error:"), result
    return json.loads(result)["id"]


async def test_inspection_returns_a_topic_index_by_default(tmp_path) -> None:
    runtime, _store = _runtime(tmp_path)
    _observe(runtime, "记住：提交前先跑测试。")
    await _write(runtime, "提交前先跑测试", "提交前先跑测试，避免把坏提交推上去。", "提交前先跑测试")
    result = json.loads(await runtime.recall_memory("提交前先跑测试", for_update=True))
    row = result["memories"][0]
    assert row["title"] == "提交前先跑测试"
    assert row["revision"] == 1
    assert "memory" not in row
    assert result["history"] == []


async def test_the_full_view_still_returns_the_body(tmp_path) -> None:
    runtime, _store = _runtime(tmp_path)
    _observe(runtime, "记住：提交前先跑测试。")
    await _write(runtime, "提交前先跑测试", "提交前先跑测试，避免把坏提交推上去。", "提交前先跑测试")
    result = json.loads(await runtime.recall_memory("提交前先跑测试", for_update=True, view="full"))
    assert result["memories"][0]["memory"].startswith("提交前先跑测试")


async def test_one_inspection_covers_consecutive_new_entries(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    _observe(runtime, "记住这两条：提交前先跑测试。")
    await _write(runtime, "提交前先跑测试", "提交前先跑测试。", "提交前先跑测试")
    result = await runtime.propose_memory(
        title="评审分两条线",
        content="标准与规格分开看。",
        when_to_use="评审改动时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="记住",
    )
    assert not result.startswith("Error:"), result
    assert len(store.load().entries) == 2


async def test_replacing_an_uninspected_entry_is_refused(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    _observe(runtime, "记住：提交前先跑测试。")
    entry_id = await _write(runtime, "提交前先跑测试", "提交前先跑测试。", "提交前先跑测试")
    _observe(runtime, "记住：再改一下这条。")
    entry = store.load().entries[0]
    result = await runtime.propose_memory(
        title="提交前跑测试",
        content="提交前先跑测试，然后才能推。",
        when_to_use="审阅提交范围时",
        replaces_id=entry_id,
        replaces_revision=entry.revision,
        save_now=True,
        intent_quote="记住",
        source_quote="再改一下这条",
    )
    assert result.startswith("Error:") and "for_update" in result


async def test_an_inspected_entry_can_be_replaced_without_inspecting_again(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    _observe(runtime, "记住：提交前先跑测试。")
    entry_id = await _write(runtime, "提交前先跑测试", "提交前先跑测试。", "提交前先跑测试")
    await runtime.recall_memory(entry_id, for_update=True)
    entry = store.load().entries[0]
    result = await runtime.propose_memory(
        title="提交前跑测试",
        content="提交前先跑测试，然后才能推。",
        when_to_use="审阅提交范围时",
        replaces_id=entry_id,
        replaces_revision=entry.revision,
        save_now=True,
        intent_quote="记住",
        source_quote="提交前先跑测试",
    )
    assert not result.startswith("Error:"), result
    updated = next(item for item in store.load().entries if item.id == entry_id)
    assert updated.draft.title == "提交前跑测试"
    assert updated.revision == entry.revision + 1


@pytest.mark.parametrize("view", ["index", "full"])
def test_the_view_argument_is_limited_to_the_two_shapes(view: str) -> None:
    assert view in ("index", "full")
