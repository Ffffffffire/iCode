# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Exercise the real slash entry, memory editor and lifecycle controls."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Select, Static, TextArea

from chrys.app.tui.screens.dialogs.confirm import ConfirmDialog
from chrys.app.tui.screens.personal_memory.editor import PersonalMemoryEditor
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.app.tui.widgets.chrome.input_bar import InputBar
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, resize_when_settled, rich_plain
from tests.support.waiting import wait_for


async def test_slash_memory_creates_edits_archives_and_forgets_through_ui(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "off", False)
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(120, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        bar = main.query_one(InputBar)
        bar.focus_input()
        bar.query_one("#chat-input", TextArea).load_text("/memory")
        await pilot.press("enter")
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted,
            pilot=pilot,
            description="/memory opens personal memory",
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await wait_for(
            lambda: screen.snapshot.mode == "off", pilot=pilot, description="opening the library preserves memory off"
        )
        screen.query_one("#memory-mode", Select).value = "manual"
        await wait_for(
            lambda: screen.snapshot.mode == "manual", pilot=pilot, description="recall mode changed through the UI"
        )
        await click_when_settled(pilot, screen.query_one("#memory-new", Button))
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryEditor) and app.screen.is_mounted,
            pilot=pilot,
            description="memory editor",
        )
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-title", EnhancedInput).value = "Report cache"
        editor.query_one("#memory-edit-content", TextArea).load_text("Inspect persisted artifact versions.")
        editor.query_one("#memory-edit-when", EnhancedInput).value = "Report stays stale after recognition changes"
        await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
        await wait_for(
            lambda: app.screen is screen and len(screen.snapshot.entries) == 1,
            pilot=pilot,
            description="memory saved through event bus",
        )
        assert not screen.last_error
        assert screen.snapshot.entries[0].state == "active"
        await click_when_settled(pilot, screen.query_one("#memory-edit", Button))
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryEditor), pilot=pilot, description="edit existing memory"
        )
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-content", TextArea).load_text("Check artifact versions before deleting a cache.")
        await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
        await wait_for(
            lambda: app.screen is screen and screen.snapshot.entries[0].revision == 2,
            pilot=pilot,
            description="memory correction persisted",
        )
        assert screen.snapshot.entries[0].previous[0].draft.content == "Inspect persisted artifact versions."
        await click_when_settled(pilot, screen.query_one("#memory-archive", Button))
        await wait_for(
            lambda: screen.snapshot.entries[0].state == "archived", pilot=pilot, description="memory archived"
        )
        screen.query_one("#memory-view", Select).value = "archived"
        await wait_for(
            lambda: not screen.query_one("#memory-forget", Button).disabled,
            pilot=pilot,
            description="archived memory visible",
        )
        await click_when_settled(pilot, screen.query_one("#memory-forget", Button))
        await wait_for(lambda: isinstance(app.screen, ConfirmDialog), pilot=pilot, description="forget confirmation")
        await click_when_settled(pilot, app.screen.query_one("#confirm-yes", Button))
        await wait_for(
            lambda: app.screen is screen and not screen.snapshot.entries,
            pilot=pilot,
            description="memory and history forgotten",
        )
        persisted = await asyncio.to_thread(store.load)
        assert persisted.entries == ()
        assert persisted.mode == "manual" and persisted.capture is False
        await pilot.press("escape")
        assert app.screen is main
    await bus.unsubscribe(PersonalMemoryCommand, controller.handle)


async def test_failed_save_preserves_draft_kind_and_other_project_scope(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft("Decision", "Check the consumer first.", "Changing the IR", workspace=str(tmp_path / "other")),
        MemorySource(role="user"),
    )
    bus = EventBus()
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(120, 42)) as pilot:
        screen = PersonalMemoryScreen(bus=bus, workspace=str(tmp_path / "current"), session_id="edit-session")
        app.push_screen(screen)
        await wait_for(lambda: len(screen.snapshot.entries) == 1, pilot=pilot, description="memory loaded")
        screen.query_one("#memory-view", Select).value = "all"
        await wait_for(
            lambda: not screen.query_one("#memory-edit", Button).disabled,
            pilot=pilot,
            description="other project memory selected",
        )
        await click_when_settled(pilot, screen.query_one("#memory-edit", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryEditor), pilot=pilot, description="editor open")
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-kind", Select).value = "intention"
        editor.refresh_localization()
        assert editor.query_one("#memory-edit-kind", Select).value == "intention"
        editor.query_one("#memory-edit-content", TextArea).load_text("x" * 2401)
        await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
        await wait_for(
            lambda: bool(rich_plain(editor.query_one("#memory-edit-error", Static).render())),
            pilot=pilot,
            description="failed save shown without dismissing draft",
        )
        assert app.screen is editor
        assert editor.query_one("#memory-edit-content", TextArea).text == "x" * 2401
        assert (await asyncio.to_thread(store.load)).entries[0].revision == entry.revision
        editor.query_one("#memory-edit-content", TextArea).load_text("Validate the downstream consumer.")
        await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
        await wait_for(lambda: app.screen is screen, pilot=pilot, description="corrected draft saved")
        saved = (await asyncio.to_thread(store.load)).entries[0]
        assert saved.draft.workspace == entry.draft.workspace
        assert saved.draft.kind == "intention"
    await bus.unsubscribe(PersonalMemoryCommand, controller.handle)


@pytest.mark.parametrize("size", [(120, 42), (80, 32), (60, 28)])
async def test_source_conditions_recall_and_controls_are_visible_at_terminal_sizes(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = MemorySource(session_id="original-session", role="user", quote="先证明下游能消费。再扩展结构。")
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft(
            "轨迹知识需要下游消费",
            "结构化投入应当改善下一次分析或决策。",
            "设计轨迹知识结构或新增 IR 字段",
            "已有真实消费方时重新评估",
            kind="decision",
        ),
        source,
    )
    await asyncio.to_thread(store.recall, "轨迹知识结构", "", session_id="current-session")
    bus = EventBus()
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=size) as pilot:
        screen = PersonalMemoryScreen(
            bus=bus, workspace=str(tmp_path), session_id="current-session", locale_controller=app.locale_controller
        )
        app.push_screen(screen)
        await wait_for(
            lambda: screen.is_mounted and len(screen.snapshot.entries) == 1,
            pilot=pilot,
            description="populated memory screen",
        )
        screen.query_one("#memory-view", Select).value = "recalled"
        await wait_for(
            lambda: "Matched:" in rich_plain(screen.query_one("#memory-match", Static).render()),
            pilot=pilot,
            description="recall reason visible",
        )
        assert source.quote in rich_plain(screen.query_one("#memory-source", Static).render())
        assert entry.draft.when_to_use in rich_plain(screen.query_one("#memory-when", Static).render())
        for selector in ("#memory-mode", "#memory-new", "#memory-close", "#memory-list", "#memory-detail"):
            region = screen.query_one(selector).region
            assert region.width > 0 and region.height > 0
            assert region.x >= 0 and region.right <= size[0]
            assert region.y >= 0 and region.bottom <= size[1]
        await resize_when_settled(pilot, 110, 38)
        assert screen.query_one("#memory-detail").region.width > 0
    await bus.unsubscribe(PersonalMemoryCommand, controller.handle)
