# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
# ruff: noqa: RUF001 -- Titles and spans are user-visible Chinese, punctuation included.

"""Waiting proposals are reviewable in one modal, and confirming writes them."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from chrys.app.tui.screens.personal_memory.consent_review import ConsentReviewScreen
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.consent import shared_queue
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.waiting import wait_for

_DRAFT = MemoryDraft("提交前先跑测试", "提交前先跑测试。", "准备提交改动时")


@pytest.fixture(autouse=True)
def _empty_queue():
    shared_queue().clear()
    yield
    shared_queue().clear()


def _queue(title: str, span: str = "记住这条") -> str:
    draft = MemoryDraft(title, f"{title}：{_DRAFT.content}", _DRAFT.when_to_use)
    return shared_queue().offer(title=title, draft=draft, source=MemorySource(), span=span, session_id="session").id


async def _open(tmp_path: Path, bus: EventBus, pilot) -> ConsentReviewScreen:
    app = pilot.app
    screen = ConsentReviewScreen(bus=bus, session_id="session")
    app.push_screen(screen)
    await wait_for(lambda: screen.is_mounted and bool(screen.query("#consent-empty")), pilot=pilot)
    return screen


async def test_the_modal_lists_each_waiting_proposal(tmp_path: Path) -> None:
    bus = EventBus()
    _queue("提交前先跑测试")
    _queue("评审分两条线")
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await _open(tmp_path, bus, pilot)
        rows = screen.query(".consent-row")
        assert len(rows) == 2
        text = "\n".join(rich_text for rich_text in (str(row.render()) for row in rows))
        assert "提交前先跑测试" in text and "评审分两条线" in text


async def test_confirming_saves_every_waiting_proposal(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    _queue("提交前先跑测试")
    _queue("评审分两条线")
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await _open(tmp_path, bus, pilot)
        await screen.action_confirm_all()
        await wait_for(lambda: shared_queue().pending() == (), pilot=pilot)
        assert [entry.draft.title for entry in store.load().entries] == ["提交前先跑测试", "评审分两条线"]


async def test_dropping_leaves_the_library_untouched(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    _queue("提交前先跑测试")
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await _open(tmp_path, bus, pilot)
        await screen.action_decline_all()
        await wait_for(lambda: shared_queue().pending() == (), pilot=pilot)
        assert store.load().entries == ()


async def test_the_modal_shows_an_empty_notice_when_nothing_waits(tmp_path: Path) -> None:
    bus = EventBus()
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await _open(tmp_path, bus, pilot)
        empty = screen.query_one("#consent-empty", Static)
        assert empty.display is True
        assert not screen.query(".consent-row")
