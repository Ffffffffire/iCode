# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Chat writes require the user's own request and keep corrections attributable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


def _runtime(tmp_path: Path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


@pytest.mark.parametrize(
    ("prompt", "quote"),
    [
        ("不要记住\uff1a我总是先删缓存。", "记住\uff1a我总是先删缓存。"),
        ("Do not remember: always delete caches.", "remember: always delete caches."),
        ("请评审这个例子\uff1a\n```text\n请记住\uff1a我总是先删缓存。\n```", "请记住\uff1a我总是先删缓存。"),
        ("请翻译\uff1a\n> Remember: always delete caches.", "Remember: always delete caches."),
        ('请翻译\uff1a\n"Remember: always delete caches."', "Remember: always delete caches."),
        ("文案例子\uff1a`请记住\uff1a我总是先删缓存。`", "请记住\uff1a我总是先删缓存。"),
    ],
)
async def test_quote_cannot_turn_negation_or_example_into_save_permission(
    tmp_path: Path, prompt: str, quote: str
) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Cache", content="Always delete caches", when_to_use="stale cache", source_quote=quote, save_now=True
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


@pytest.mark.parametrize(
    "prompt",
    [
        "请记住\uff1a报告缓存仍旧时\uff0c先查产物版本。",
        "请帮我记住\uff1a报告缓存仍旧时\uff0c先查产物版本。",
        "麻烦你记住\uff1a报告缓存仍旧时\uff0c先查产物版本。",
        'Please remember: "check cache versions first".',
        "Can you please remember: check cache versions first?",
        "Remember: don't save secrets when checking cache versions.",
        "请记住\uff1a排查缓存版本时不要保存密码。",
    ],
)
async def test_explicit_request_can_save_quoted_content_without_enabling_suggestions(
    tmp_path: Path, prompt: str
) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [prompt])])
    result = json.loads(
        await runtime.propose_memory(
            title="Cache",
            content="Check cache versions first",
            when_to_use="stale cache",
            source_quote=prompt,
            save_now=True,
        )
    )
    assert result["state"] == "active"
    assert result["revision"] == 1
    assert result["memory"]["memory"] == "Check cache versions first"
    assert store.load().capture is False


@pytest.mark.parametrize(
    "prompt",
    [
        "不要记住\uff1a这次报告只是临时采用蓝色。",
        "请不要保存到记忆\uff1a这次报告只是临时采用蓝色。",
        "Please do not remember: this report uses blue just this once.",
    ],
)
async def test_enabled_suggestions_still_respect_an_explicit_request_not_to_remember(
    tmp_path: Path, prompt: str
) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Report colour",
        content="Use blue for reports",
        when_to_use="Preparing reports",
        source_quote=prompt,
        kind="preference",
        project_only=False,
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


async def test_declined_message_cannot_be_reused_as_a_candidate_in_a_later_turn(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    declined = "不要记住\uff1a这次报告只是临时采用蓝色。"
    runtime.observe([Message("user", [declined]), Message("user", ["继续整理报告。"])])
    result = await runtime.propose_memory(
        title="Report colour",
        content="Use blue for reports",
        when_to_use="Preparing reports",
        source_quote=declined,
        kind="preference",
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


@pytest.mark.parametrize(
    "prompt", ["更新这条记忆\uff1a缓存问题先查版本。", "Please update this memory: check cache versions first."]
)
async def test_update_without_target_does_not_silently_append(tmp_path: Path, prompt: str) -> None:
    runtime, store = _runtime(tmp_path)
    old = store.save(MemoryDraft("Cache", "Old advice", "stale cache"), MemorySource())
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="New cache title",
        content="Check cache versions first",
        when_to_use="stale cache",
        source_quote=prompt,
        save_now=True,
    )
    assert result.startswith("Error:") and "recall_memory" in result
    assert store.load().entries == (old,)


@pytest.mark.parametrize("kind", ["preference", "decision", "intention"])
async def test_assistant_claim_is_not_evidence_of_the_users_choice(tmp_path: Path, kind: str) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    quote = "The user prefers SQLite for every project."
    runtime.observe([Message("user", ["Compare storage options."]), Message("assistant", [quote])])
    result = await runtime.propose_memory(
        title="SQLite",
        content=quote,
        when_to_use="choosing storage",
        source_quote=quote,
        kind=kind,
        project_only=False,
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


@pytest.mark.parametrize(("content", "condition"), [("x" * 601, "stale cache"), ("Check versions first", " ")])
async def test_extraction_requires_a_short_memory_with_a_future_use(
    tmp_path: Path, content: str, condition: str
) -> None:
    runtime, store = _runtime(tmp_path)
    prompt = "Remember: check cache versions first."
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Cache", content=content, when_to_use=condition, source_quote=prompt, save_now=True
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


async def test_correcting_a_memory_keeps_its_identity_and_reports_the_replaced_revision(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    old = store.save(MemoryDraft("Cache", "Delete it first", "stale cache"), MemorySource(quote="Old request"))
    prompt = "Update this memory: check cache versions before deletion."
    runtime.observe([Message("user", [prompt])])
    await runtime.recall_memory(old.id, for_update=True)
    result = json.loads(
        await runtime.propose_memory(
            title="Cache",
            content="Check cache versions before deletion",
            when_to_use="stale cache",
            source_quote=prompt,
            save_now=True,
            replaces_id=old.id,
            replaces_revision=old.revision,
        )
    )
    assert result["id"] == old.id and result["revision"] == 2
    assert result["supersedes_revision"] == 1
    assert result["memory"]["memory"] == "Check cache versions before deletion"
    assert len(store.load().entries) == 1
    assert store.load().entries[0].draft.workspace == ""
    assert store.load().entries[0].previous[0].draft.content == "Delete it first"


async def test_chat_cannot_correct_another_projects_memory_by_guessing_its_id(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    old = store.save(
        MemoryDraft("Cache", "Project-specific advice", "stale cache", workspace=str(tmp_path / "other")),
        MemorySource(),
    )
    prompt = "Update this memory: delete cache first."
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Cache",
        content="Delete cache first",
        when_to_use="stale cache",
        source_quote=prompt,
        save_now=True,
        replaces_id=old.id,
        replaces_revision=old.revision,
    )
    assert result.startswith("Error:")
    assert store.load().entries == (old,)


@pytest.mark.parametrize("mode", ["manual", "off"])
async def test_next_turn_without_automatic_recall_clears_previous_turn_reference(tmp_path: Path, mode: str) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Cache", "Inspect artifact versions first", "stale cache"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=bus, session_id="one", workspace=str(tmp_path), store=store)
    changes: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        changes.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    await runtime.prepare([Message("user", ["Inspect the stale cache"])])
    assert changes[-1].snapshot is not None
    assert changes[-1].snapshot.recalls[-1].matches
    store.configure(mode, False)
    changes.clear()
    prepared = await runtime.prepare([Message("user", ["Plan the next task"])])
    assert changes and changes[-1].snapshot is not None
    assert not changes[-1].snapshot.recalls[-1].matches
    assert "Inspect artifact versions first" not in (prepared or "")
    if mode == "off":
        assert prepared is None


async def test_off_lookup_reports_disabled_instead_of_claiming_the_library_has_no_match(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.save(MemoryDraft("Cache", "Inspect artifact versions first", "stale cache"), MemorySource())
    store.configure("off", False)
    result = await runtime.recall_memory("stale cache")
    assert "disabled" in result.lower() and "no search" in result.lower()
    assert "No applicable active memories found" not in result
    assert "Inspect artifact versions" not in result


async def test_short_followups_recall_the_users_task_but_a_new_task_clears_it(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    entry = store.save(MemoryDraft("PPT", "Use editable diagrams", "Technical slides"), MemorySource())
    messages = [Message("user", ["帮我准备技术幻灯片"]), Message("assistant", ["Cache testing unrelated text"])]
    for prompt in ("继续", "继续吧"):
        messages.append(Message("user", [prompt]))
        prepared = await runtime.prepare(messages)
        assert entry.id in (prepared or "")
        assert "context" in store.load().recalls[-1].matches[0].routes
    messages.append(Message("user", ["设计一个数据库连接池"]))
    prepared = await runtime.prepare(messages)
    assert entry.id not in (prepared or "")
    assert not store.load().recalls[-1].matches


async def test_a_followup_search_does_not_hide_memories_already_provided_this_turn(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    first = store.save(MemoryDraft("Cache", "Inspect artifact versions first", "stale cache"), MemorySource())
    second = store.save(MemoryDraft("Deploy", "Check the rollback plan", "deploy release"), MemorySource())
    await runtime.prepare([Message("user", ["Inspect the stale cache"])])
    await runtime.recall_memory("deploy release")
    await runtime.recall_memory("unrelated sailing weather")
    recall = store.load().recalls[-1]
    assert {match.memory_id for match in recall.matches} == {first.id, second.id}
    assert "stale cache" in recall.query and "deploy release" in recall.query
    await runtime.prepare([Message("user", ["unrelated sailing weather"])])
    assert not store.load().recalls[-1].matches


async def test_manual_lookup_keeps_the_users_task_when_model_keywords_lose_the_decision(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    entry = store.save(
        MemoryDraft("橙桥检查", "先做可逆小实验\uff0c再寻找反证\uff0c最后扩大投入。", "跨项目评审决策"),
        MemorySource(),
    )
    store.configure("manual", False)
    runtime.observe(
        [Message("user", ["请查一下个人记忆\uff0c再回答\uff1a我准备把评审流程改成自动发布\uff0c请给一个决策建议。"])]
    )
    result = await runtime.recall_memory("评审流程 自动发布 发布流程 审核")
    assert entry.id in result
    assert store.load().recalls[-1].matches[0].memory_id == entry.id


@pytest.mark.parametrize(
    "prompt",
    [
        "润色后帮我记住这条偏好",
        "帮我润色并记住这条偏好",
        "请先整理，然后记住这条偏好",  # noqa: RUF001 -- Natural Chinese user input.
        "Polish this and please remember this preference.",
    ],
)
async def test_save_request_can_follow_another_requested_action(tmp_path: Path, prompt: str) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Use diagrams and dense visual layouts for technical slides.",
        when_to_use="Preparing technical slides",
        source_quote=prompt,
        kind="preference",
        save_now=True,
    )
    assert not result.startswith("Error:"), result
    assert store.load().entries[0].state == "active"


@pytest.mark.parametrize("tool_messages", [0, 32])
async def test_save_authorization_and_preference_evidence_can_be_in_different_turns(
    tmp_path: Path, tool_messages: int
) -> None:
    runtime, store = _runtime(tmp_path)
    preference = "我更喜欢图文结合、信息密度较高的技术 PPT 版面。"
    original = Message("user", [preference], additional_properties={"_chrys_analytics_item_id": "a" * 32})
    runtime.observe(
        [
            original,
            *[Message("tool", ["Rendered slide"]) for _ in range(tool_messages)],
            Message("user", ["请记住这条偏好"]),
        ]
    )
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Use diagrams and dense visual layouts for technical slides.",
        when_to_use="Preparing technical slides",
        source_quote=preference,
        kind="preference",
        project_only=False,
        save_now=True,
    )
    assert not result.startswith("Error:"), result
    entry = store.load().entries[0]
    assert entry.state == "active" and entry.draft.workspace == ""
    assert entry.source == MemorySource("one", "a" * 32, "user", preference)
    assert store.load().capture is False


@pytest.mark.parametrize(
    "prompt",
    [
        "润色后不要帮我记住这条偏好",
        "帮我润色，但不要记住这条偏好",  # noqa: RUF001 -- Natural Chinese user input.
        "如果以后我说帮我记住，这是什么意思？",  # noqa: RUF001 -- Natural Chinese user input.
        "她让我润色后帮我记住这条偏好",
        "请解释“润色后帮我记住这条偏好”这句话",
        "Polish this, but do not remember this preference.",
    ],
)
async def test_compound_request_does_not_authorize_negation_or_reported_speech(tmp_path: Path, prompt: str) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Use diagrams",
        when_to_use="Technical slides",
        source_quote=prompt,
        save_now=True,
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


async def test_authorized_save_still_rejects_an_invented_source_quote(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", ["请记住这条偏好"])])
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Use diagrams",
        when_to_use="Technical slides",
        source_quote="请记住这条偏好（指已经验证过的高密度版式）",  # noqa: RUF001 -- Invented source wording.
        save_now=True,
    )
    assert result.startswith("Error:")
    assert "verbatim" in result
    assert store.load().entries == ()
