# ruff: noqa: RUF001 -- Corpus entries are verbatim user messages, punctuation included.
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Write authorization: a fast path for common requests, language-free checks behind it.

The corpus is made of phrasings real users typed. Positives must reach the fast
path; negatives must not, so a doc question never turns into a silent write.
"""

from __future__ import annotations

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.personal_memory.write_intent import save_request, validate_consent

REQUEST_PHRASINGS = [
    "记住九条经验",
    "记住这两条",
    "记住这版",
    "把记忆标题的生成规则明确下来，记住。然后记住这些标题",
    "再添加一条偏好，然后记住这十条记忆。",
    "知识点整理到记忆里面，并且再集百家之长。",
    "检索后把结论通过记忆机制进行沉淀。",
    '/zh-doc 记住 一条是"去 AI 味先改结构、别背词表"。',
    "remember that I prefer tabs",
    "add this to memory",
    "save this to my memory",
    "store this in long-term memory",
    "please remember this",
]

NOT_REQUESTS = [
    "这九条记忆的语言表达需要润色优化下，更容易明白",
    "这些skill中哪些可以帮助我使用icode完成更高质量的代码开发？",
    "现在的memory系统怎么进行memory的审查和改进？",
    "条目的名称和标题我觉得很糟糕",
    "你来自己分析下当前回话的轨迹，fb0b3bbc1de9。",
    "不要记住：这次报告只是临时采用蓝色。",
    "请翻译：\n```text\n请记住：我总是先删缓存。\n```",
    "请解释 memory.md 改了吗？",
    "How does memory recall pick entries?",
    "Do not remember: always delete caches.",
]


@pytest.mark.parametrize("text", REQUEST_PHRASINGS)
def test_request_phrasings_reach_the_fast_path(text: str) -> None:
    assert save_request(text) is not None


@pytest.mark.parametrize("text", NOT_REQUESTS)
def test_questions_negations_and_pasted_examples_do_not_authorize(text: str) -> None:
    assert save_request(text) is None


@pytest.mark.parametrize(
    ("message", "span", "ok", "reason"),
    [
        ("记住这两条，A 和 B", "记住这两条", True, ""),
        ("remember that I prefer tabs", "remember", True, ""),
        ("这条记忆为什么没生效？", "记住这两条", False, "consent_span_missing"),
        ("请解释：\n> save this to memory", "save this to memory", False, "consent_span_pasted"),
        ("文案例子：`记住：先跑测试`", "记住：先跑测试", False, "consent_span_pasted"),
        ("记住：" + "很长的内容" * 41, "很长的内容" * 41, False, "consent_span_too_long"),
        ("记住这两条", "  ", False, "consent_span_missing"),
    ],
)
def test_consent_checks_positions_not_wording(message: str, span: str, ok: bool, reason: str) -> None:
    decision = validate_consent(message, span)
    assert decision.ok is ok
    assert decision.reason == reason


def test_consent_caps_a_batch() -> None:
    assert validate_consent("记住这些", "记住这些", batch_size=20).ok is True
    assert validate_consent("记住这些", "记住这些", batch_size=21).reason == "consent_batch_too_large"


def _runtime(tmp_path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


async def test_new_phrasings_save_without_another_round_trip(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    prompt = "知识点整理到记忆里面。顺便记住：提交前先跑测试。"
    runtime.observe([Message("user", [prompt])])
    await runtime.prepare([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="测试先行",
        content="提交前先跑测试",
        when_to_use="准备提交改动时",
        source_quote="提交前先跑测试",
        save_now=True,
        intent_quote="知识点整理到记忆里面",
    )
    assert not result.startswith("Error:"), result
    assert store.load().entries
