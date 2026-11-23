# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Chat writes require the user's own request and keep corrections attributable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.tool_kinds import KIND_CONTEXT, KIND_FILESYSTEM_READ, TOOL_CALL_KIND_METADATA_KEY
from chrys.foundation.tool_result_metadata import TOOL_FAILED_METADATA_KEY, TOOL_RESULT_METADATA_KEY
from chrys.kernel import Content, Message
from chrys.kernel.compaction import EXCLUDED_KEY
from chrys.service.personal_memory.consent import shared_queue
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


def _runtime(tmp_path: Path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


def _refused_or_waiting(result: str, store: PersonalMemoryStore) -> bool:
    """A write without the user's own request never lands: it either refuses or waits for confirmation."""

    assert store.load().entries == ()
    if result.startswith("Error:"):
        return False
    payload = json.loads(result)
    assert payload["state"] == "awaiting-confirmation"
    shared_queue().clear()
    return True


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
        "请把报告写成文档\uff0c这次不要写入个性化记忆。",
        "请把报告写成文档\uff0c这次不写入个人记忆。",
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
    ("prompt", "intent"),
    [
        ("以默认 Agent 的配置为范例\uff0c总结设计方法\uff0c并将其记住。", "并将其记住"),
        (
            "请学习这些资料\uff0c整理成文档\uff0c再把总结出的做法写入个人记忆。",
            "把总结出的做法写入个人记忆",
        ),
    ],
)
async def test_request_to_distill_profiles_is_not_evidence_for_the_resulting_lesson(
    tmp_path: Path, prompt: str, intent: str
) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Agent Profile 设计骨架",
        content="身份句 → 约束前置 → 原则带反例 → 工具矩阵 → 按读者定输出 → 权限落配置",
        when_to_use="构建专业 Agent",
        source_quote=prompt,
        intent_quote=intent,
        save_now=True,
    )
    assert result.startswith("Error:") and "evidence" in result
    assert store.load().entries == ()


@pytest.mark.parametrize(
    ("prompt", "save_now", "with_application", "expected"),
    [
        ("Please remember that lesson.", True, False, None),
        ("Please remember that lesson.", True, True, "active"),
        ("先学习资料\uff0c整理成文档后\uff0c把可复用的结论写入我的个性化记忆。", True, True, "active"),
        ("不要逐字照抄\uff0c提炼并存入个人记忆备用。", True, True, "active"),
        ("把提炼出的知识写入 `memory` 里。", True, True, "active"),
        ("Summarize the sources, then add the method to my personal memory.", True, True, "active"),
        ("下次做同类任务时\uff0c请继续按这个方法来。", True, True, "active"),
        ("Compare the profiles.", True, True, None),
        ("Compare the profiles.", False, True, "candidate"),
    ],
)
async def test_analysis_lesson_needs_an_application_and_explicit_adoption_to_activate(
    tmp_path: Path, prompt: str, save_now: bool, with_application: bool, expected: str | None
) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", not save_now)
    quote = "The QA profile omits filesystem.write."
    application = "Verify that read-only roles lack file writing tools." if with_application else ""
    runtime.observe(
        [Message("user", ["Read the QA profile."]), Message("assistant", [quote]), Message("user", [prompt])]
    )
    result = await runtime.propose_memory(
        title="Read-only tools",
        content="Omit filesystem.write for read-only roles.",
        when_to_use="Configuring read-only agents",
        source_quote=quote,
        intent_quote=prompt,
        save_now=save_now,
        application=application,
    )
    if expected is None:
        _refused_or_waiting(result, store)
    else:
        assert not result.startswith("Error:"), result
        assert json.loads(result)["state"] == expected
        (entry,) = store.load().entries
        assert entry.source.role == "assistant" and entry.source.quote == quote
        assert application in entry.draft.content


@pytest.mark.parametrize(
    "prompt",
    [
        "请学习资料\uff0c总结成文档后写入 README.md。",
        "总结成文档\uff0c然后写入 memory 配置文件。",
        "请总结成文档\uff0c然后写入。",
        "Save the memory settings file after reviewing the profiles.",
        "请评审这个例子\uff1a“先学习资料\uff0c再写入个人记忆。”",
        "例如\uff0c整理好可以写入个人记忆。",
        "整理成文档\uff0c但不要写入个性化记忆。",
    ],
)
async def test_verbatim_task_quote_alone_does_not_authorize_a_memory_write(tmp_path: Path, prompt: str) -> None:
    runtime, store = _runtime(tmp_path)
    evidence = "Review agents should have filesystem.read and never filesystem.write."
    runtime.observe([Message("user", [evidence]), Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Read-only tools",
        content="Omit filesystem.write for read-only roles.",
        when_to_use="Configuring read-only agents",
        source_quote=evidence,
        intent_quote=prompt,
        save_now=True,
        application="Check that the tool list contains filesystem.read and omits filesystem.write.",
    )
    assert _refused_or_waiting(result, store) in (False, True)


async def test_lesson_that_exceeds_the_rendered_recall_budget_is_not_saved(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    escaped = '"\\'
    quote = escaped * 600
    runtime.observe([Message("assistant", [quote]), Message("user", ["Please remember that lesson."])])
    result = await runtime.propose_memory(
        title="Quoted configuration paths",
        content="Preserve the original escaping in configuration paths.\n" + escaped * 650,
        when_to_use="When comparing configuration paths.\n" + escaped * 280,
        source_quote=quote,
        save_now=True,
        application="Check that the parser returns the same path.",
    )
    assert result.startswith("Error:") and "cannot fit in a recall" in result
    assert store.load().entries == ()


@pytest.mark.parametrize("case", ["memory_receipt", "failed_read", "hidden_read", "skipped_line"])
async def test_only_currently_visible_successful_read_results_ground_a_lesson(tmp_path: Path, case: str) -> None:
    runtime, store = _runtime(tmp_path)
    quote = "sub_agent_only: true"
    kind = KIND_CONTEXT if case == "memory_receipt" else KIND_FILESYSTEM_READ
    result_text = quote
    if case == "skipped_line":
        result_text = "File: Profile.yaml (3 lines, 84 chars)\n1|sub_agent_only: true\n2|tools:\n3|  builtins: [filesystem.read]\n"
        quote += " builtins: [filesystem.read]"
    result = Content.from_function_result(
        "reused-id",
        result=result_text,
        additional_properties={TOOL_RESULT_METADATA_KEY: {TOOL_FAILED_METADATA_KEY: case == "failed_read"}},
    )
    runtime.observe(
        [
            Message("user", ["Look at an earlier profile."]),
            Message(
                "assistant",
                [
                    Content.from_function_call(
                        "reused-id",
                        "read_file",
                        additional_properties={TOOL_CALL_KIND_METADATA_KEY: KIND_FILESYSTEM_READ},
                    )
                ],
            ),
            Message("tool", [Content.from_function_result("reused-id", result="name: Earlier")]),
            Message("user", ["Compare the profiles and remember it."]),
            Message(
                "assistant",
                [
                    Content.from_function_call(
                        "reused-id",
                        "read_file" if kind == KIND_FILESYSTEM_READ else "recall_memory",
                        additional_properties={TOOL_CALL_KIND_METADATA_KEY: kind},
                    )
                ],
            ),
            Message("tool", [result], additional_properties={EXCLUDED_KEY: case == "hidden_read"}),
        ]
    )
    response = await runtime.propose_memory(
        title="Sub-agent role",
        content="Declare the investigation profile as a sub-agent.",
        when_to_use="Configuring a delegated role",
        source_quote=quote,
        save_now=True,
        application="Check that the loaded profile is limited to delegated invocations.",
    )
    assert response.startswith("Error:") and "quote" in response.lower()
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
        "这条偏好请帮我记住",
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
