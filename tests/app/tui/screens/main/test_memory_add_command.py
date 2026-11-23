# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""``/memory add`` is a consent-free write path: the user typed the text."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from chrys.app.tui.screens.main.commands import MainSlashCommandRegistry
from chrys.service.personal_memory.quick_add import CONTENT_CHARS, TITLE_CHARS, QuickAddError, draft_from_text


def test_first_sentence_becomes_the_title() -> None:
    draft = draft_from_text("提交前先跑测试。顺手把文档也更新一下。")
    assert draft.title == "提交前先跑测试"
    assert draft.content == "提交前先跑测试。顺手把文档也更新一下。"
    assert draft.when_to_use == ""


def test_long_text_without_a_stop_keeps_a_bounded_title() -> None:
    draft = draft_from_text("很长的说明" * 20)
    assert len(draft.title) <= TITLE_CHARS
    assert draft.content


def test_whitespace_is_collapsed_and_blank_text_is_refused() -> None:
    assert draft_from_text("  先跑\n测试  ").content == "先跑 测试"
    with pytest.raises(QuickAddError) as missing:
        draft_from_text("   ")
    assert missing.value.code == "memory_text_missing"


def test_oversized_text_is_refused_rather_than_truncated() -> None:
    with pytest.raises(QuickAddError) as too_long:
        draft_from_text("字" * (CONTENT_CHARS + 1))
    assert too_long.value.code == "memory_text_too_long"


def _memory_command(actions) -> object:
    registry = MainSlashCommandRegistry(actions=actions, buddy=MagicMock(), render_message=lambda _message: "described")
    return next(command for command in registry.build() if command.name == "memory")


def test_memory_add_routes_the_text_to_the_screen() -> None:
    actions = MagicMock()
    _memory_command(actions).action("add 提交前先跑测试")
    actions.add_memory.assert_called_once_with("提交前先跑测试")
    actions.personal_memory.assert_not_called()


def test_memory_without_add_still_opens_the_library() -> None:
    actions = MagicMock()
    _memory_command(actions).action("")
    actions.personal_memory.assert_called_once_with()
    actions.add_memory.assert_not_called()


def test_memory_add_without_text_explains_the_usage() -> None:
    actions = MagicMock()
    _memory_command(actions).action("add   ")
    actions.notify_warning.assert_called_once()
    actions.add_memory.assert_not_called()


def test_memory_confirm_answers_the_queue_without_an_id() -> None:
    actions = MagicMock()
    _memory_command(actions).action("confirm")
    actions.confirm_memory.assert_called_once_with("", accept=True)


def test_memory_decline_accepts_one_id() -> None:
    actions = MagicMock()
    _memory_command(actions).action("decline 4f2a")
    actions.confirm_memory.assert_called_once_with("4f2a", accept=False)
