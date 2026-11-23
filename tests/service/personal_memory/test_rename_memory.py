# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# ruff: noqa: RUF001 -- Titles and spans are user-visible Chinese, punctuation included.

"""A rename changes the topic line only: content, evidence and revision history stay."""

from __future__ import annotations

import json

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.personal_memory.titles import MAX_TITLE_CHARS, title_problem


@pytest.mark.parametrize(
    ("title", "ok"),
    [
        ("偶发 bug：先建失败复现", True),
        ("提交前先跑测试", True),
        ("Review: two axes", True),
        ("", False),
        ("提交前先跑测试。", False),
        ("提交前先跑测试，再推送。", False),
        ("字" * (MAX_TITLE_CHARS + 1), False),
        ("两行\n标题", False),
    ],
)
def test_title_lint_keeps_titles_topical(title: str, ok: bool) -> None:
    assert (title_problem(title) == "") is ok


def _runtime(tmp_path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


async def _saved(runtime: PersonalMemoryRuntime, store: PersonalMemoryStore):
    prompt = "记住：提交前先跑测试。"
    runtime.observe([Message("user", [prompt])])
    await runtime.prepare([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="测试先行",
        content="提交前先跑测试",
        when_to_use="准备提交改动时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="记住",
    )
    assert not result.startswith("Error:"), result
    return store.load().entries[0]


async def test_renaming_keeps_content_and_bumps_the_revision(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    entry = await _saved(runtime, store)
    payload = json.loads(await runtime.rename_memory(entry.id, entry.revision, "提交前跑测试"))
    assert payload["title"] == "提交前跑测试"
    assert payload["revision"] == entry.revision + 1
    updated = next(item for item in store.load().entries if item.id == entry.id)
    assert updated.draft.title == "提交前跑测试"
    assert updated.draft.content == entry.draft.content
    assert updated.draft.when_to_use == entry.draft.when_to_use
    assert updated.source.quote == entry.source.quote


async def test_a_bad_title_is_refused_before_any_write(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    entry = await _saved(runtime, store)
    result = await runtime.rename_memory(entry.id, entry.revision, "提交前先跑测试。")
    assert result.startswith("Error:") and "punctuation" in result
    assert next(item for item in store.load().entries if item.id == entry.id).draft.title == "测试先行"


async def test_a_stale_revision_is_refused(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    entry = await _saved(runtime, store)
    await runtime.rename_memory(entry.id, entry.revision, "提交前跑测试")
    result = await runtime.rename_memory(entry.id, entry.revision, "测试先行")
    assert result.startswith("Error:") and "revision" in result


async def test_an_unknown_id_is_refused(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    await _saved(runtime, store)
    result = await runtime.rename_memory("missing", 1, "提交前跑测试")
    assert result.startswith("Error:") and "recall_memory" in result
