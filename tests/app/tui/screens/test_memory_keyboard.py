# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Keyboard navigation and responsive activity paging through the real memory panel."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, OptionList, Select, Static, Tabs

from chrys.app.tui.screens.dialogs.confirm import ConfirmDialog
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryActivity, MemoryDraft, MemorySnapshot, MemorySource
from chrys.service.personal_memory import activity
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for


@pytest.mark.parametrize("width", [60, 100])
async def test_memory_search_escape_and_detail_follow_session_navigation(tmp_path: Path, width: int) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.save, MemoryDraft("Slides", "Use diagrams", "Slides"), MemorySource())
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        options = screen.query_one("#memory-list", OptionList)
        search = screen.query_one("#memory-search", EnhancedInput)
        assert screen.focused is options
        await pilot.press("ctrl+f")
        assert screen.focused is search
        search.value = "No matching memory"
        await wait_for(lambda: options.option_count == 0, pilot=pilot)
        await pilot.press("escape")
        assert app.screen is screen and search.value == ""
        await wait_for(lambda: options.option_count == 1, pilot=pilot)
        assert screen.focused is search
        await pilot.press("escape")
        assert screen.focused is options
        await pilot.press("enter")
        assert screen.query_one("#memory-detail", VerticalScroll).has_focus_within
        await pilot.press("escape")
        assert app.screen is screen and screen.focused is options
        await pilot.press("tab", "shift+tab")
        assert screen.focused is options
        await pilot.press("delete")
        await wait_for(lambda: isinstance(app.screen, ConfirmDialog) and app.screen.is_mounted, pilot=pilot)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen, pilot=pilot)
        assert len(screen.snapshot.entries) == 1
        options.focus()
        await pilot.press("escape")
        await wait_for(lambda: app.screen is main, pilot=pilot)


@pytest.mark.parametrize("width", [60, 100])
async def test_memory_multiselect_has_keyboard_and_visible_exit(
    tmp_path: Path, width: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chrys.app.tui.i18n.persist_locale", lambda _: None)
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for i in range(2):
        await asyncio.to_thread(
            store.save, MemoryDraft(f"Slides {i}", f"Diagrams {i}", "Slides", "Distant projection"), MemorySource()
        )
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory("all")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("end")
        assert options.highlighted == 1
        await pilot.press("home")
        assert options.highlighted == 0
        await pilot.press("space", "down", "space")
        assert len(screen._marked) == 2
        selected_id = screen._selected_id
        await pilot.press("escape")
        assert app.screen is screen and not screen._marked
        assert screen._selected_id == selected_id
        assert screen.query_one("#memory-edit").display
        await pilot.press("space")
        button = screen.query_one("#memory-mark", Button)
        assert "Deselect" in str(button.label)
        app.locale_controller.switch_locale("zh-Hans")
        await wait_for(lambda: str(button.label) == "退出多选", pilot=pilot)
        assert "退出多选" in "".join(strip.text for strip in button.render_lines(button.outer_size.region))
        assert screen.query_one("#memory-reconsider").border_title == "何时不再适用"
        assert "不会自动删除" in str(screen.query_one("#memory-reconsider").tooltip)
        app.save_screenshot(f"memory-selection-{width}.svg", path=str(tmp_path))
        await click_when_settled(pilot, button)
        assert not screen._marked and screen.focused is options
        await pilot.press("space")
        screen.query_one("#memory-view", Tabs).active = "memory-view-activity"
        await wait_for(lambda: screen.query_one("#memory-activity").display, pilot=pilot)
        screen.query_one("#memory-view", Tabs).active = "memory-view-all"
        await wait_for(lambda: screen.query_one("#memory-body").display, pilot=pilot)
        assert not screen._marked


@pytest.mark.parametrize("button_id", ["memory-older", "memory-latest"])
async def test_slow_activity_read_does_not_block_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, button_id: str
) -> None:
    monkeypatch.setattr(activity, "RECENT_ACTIVITY", 2)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for i in range(3):
        await asyncio.to_thread(store.save, MemoryDraft(f"Memory {i}", f"Fact {i}", "work"), MemorySource())
    bus = EventBus()
    controller = PersonalMemoryController(bus, store)
    entered, release = asyncio.Event(), asyncio.Event()
    history_reads = 0

    async def handle(command: PersonalMemoryCommand) -> None:
        nonlocal history_reads
        if command.action == "history":
            history_reads += 1
            entered.set()
            await release.wait()
        await controller.handle(command)

    await bus.subscribe(PersonalMemoryCommand, handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(80, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory("activity")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        button = screen.query_one(f"#{button_id}", Button)
        button.focus()
        button.press()
        await wait_for(entered.is_set)
        assert screen.query_one("#memory-older", Button).disabled
        assert screen.query_one("#memory-latest", Button).disabled
        assert screen.query_one("#memory-activity").loading
        button.press()
        escape = asyncio.create_task(pilot.press("escape"))
        try:
            await wait_for(lambda: app.screen is main, description="Escape closes memory while the read is held")
            assert history_reads == 1
        finally:
            release.set()
            await escape
        await wait_for(lambda: not screen._pending)


async def test_activity_read_failure_preserves_page_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activity, "RECENT_ACTIVITY", 2)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for i in range(3):
        await asyncio.to_thread(store.save, MemoryDraft(f"Memory {i}", f"Fact {i}", "work"), MemorySource())
    history_page = store.history_page
    fail_once = True

    def read_page(*, before: int = 0) -> tuple[MemorySnapshot, tuple[MemoryActivity, ...]]:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise MemoryStoreError("Activity read failed.")
        return history_page(before=before)

    monkeypatch.setattr(store, "history_page", read_page)
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(80, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory("activity")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        current = rich_plain(screen.query_one("#memory-activity-text", Static).content)
        await click_when_settled(pilot, screen.query_one("#memory-older", Button))
        await wait_for(lambda: bool(screen.last_error) and not screen._reading, pilot=pilot)
        assert screen.query_one("#memory-error").display
        assert rich_plain(screen.query_one("#memory-activity-text", Static).content) == current
        assert not screen.query_one("#memory-older", Button).disabled
        await click_when_settled(pilot, screen.query_one("#memory-latest", Button))
        await wait_for(lambda: screen._history_page is not None and not screen._reading, pilot=pilot)
        assert not screen.last_error and not screen.query_one("#memory-error").display
        assert "Fact 0" in rich_plain(screen.query_one("#memory-activity-text", Static).content)
        assert screen.query_one("#memory-activity", VerticalScroll).scroll_y == 0


async def test_memory_escape_closes_filter_before_panel(tmp_path: Path) -> None:
    bus = EventBus()
    await bus.subscribe(
        PersonalMemoryCommand, PersonalMemoryController(bus, PersonalMemoryStore(tmp_path / "m.json")).handle
    )
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(80, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        selector = screen.query_one("#memory-kind-filter", Select)
        selector.focus()
        await pilot.press("enter")
        assert selector.expanded
        await pilot.press("escape")
        assert not selector.expanded and app.screen is screen
