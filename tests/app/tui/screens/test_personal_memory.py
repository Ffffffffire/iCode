# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Exercise the real slash entry, memory editor and lifecycle controls."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Collapsible, OptionList, Select, Static, Tabs, TextArea

from chrys.app.tui.screens.dialogs.confirm import ConfirmDialog
from chrys.app.tui.screens.personal_memory.editor import PersonalMemoryEditor
from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.app.tui.widgets.chrome.footer import ChrysFooter
from chrys.app.tui.widgets.chrome.hook_indicator import HookIndicator
from chrys.app.tui.widgets.chrome.input_bar import InputBar
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
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
        capture = screen.query_one("#memory-capture", Select)
        capture.value = "auto"
        await wait_for(
            lambda: screen.snapshot.capture and screen.snapshot.auto_save,
            pilot=pilot,
            description="clear preferences automatically saved",
        )
        capture.value = "review"
        await wait_for(
            lambda: screen.snapshot.capture and not screen.snapshot.auto_save,
            pilot=pilot,
            description="review all extracted memories",
        )
        capture.value = "explicit"
        await wait_for(lambda: not screen.snapshot.capture, pilot=pilot, description="explicit writes only")
        await click_when_settled(pilot, screen.query_one("#memory-new", Button))
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryEditor) and app.screen.is_mounted,
            pilot=pilot,
            description="memory editor",
        )
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-content", TextArea).load_text("Inspect persisted artifact versions.")
        assert editor.focused is editor.query_one("#memory-edit-content", TextArea)
        await pilot.press("ctrl+enter")
        await wait_for(
            lambda: app.screen is screen and len(screen.snapshot.entries) == 1,
            pilot=pilot,
            description="memory saved through event bus",
        )
        assert not screen.last_error
        assert screen.snapshot.entries[0].state == "active"
        assert screen.snapshot.entries[0].draft.title == "Inspect persisted artifact versions."
        assert screen.snapshot.entries[0].draft.when_to_use == ""
        await click_when_settled(pilot, screen.query_one("#memory-edit", Button))
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryEditor) and app.screen.is_mounted, pilot=pilot, description="edit existing memory"
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
        screen.query_one("#memory-view", Tabs).active = "memory-view-archived"
        await wait_for(
            lambda: screen.query_one("#memory-forget", Button).display,
            pilot=pilot,
            description="archived memory visible",
        )
        await click_when_settled(pilot, screen.query_one("#memory-accept", Button))
        await wait_for(lambda: screen.snapshot.entries[0].state == "active", pilot=pilot, description="memory restored")
        screen.query_one("#memory-view", Tabs).active = "memory-view-active"
        await wait_for(
            lambda: screen.query_one("#memory-forget", Button).display,
            pilot=pilot,
            description="active memory can be forgotten directly",
        )
        await click_when_settled(pilot, screen.query_one("#memory-forget", Button))
        await wait_for(lambda: isinstance(app.screen, ConfirmDialog) and app.screen.is_mounted, pilot=pilot, description="forget confirmation")
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


async def test_memory_footer_entry_preserves_shortcuts_at_narrow_width(tmp_path: Path) -> None:
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine())
    async with app.run_test(size=(60, 28)) as pilot:
        await pilot.pause()
        main = app._main_screen
        assert main is not None
        footer = main.query_one(ChrysFooter)
        indicator = main.query_one(PersonalMemoryIndicator)
        hooks = main.query_one(HookIndicator)
        assert footer.region.width >= 30
        assert footer.region.right == indicator.region.x
        assert indicator.region.right == hooks.region.x
        assert hooks.region.right == 60


async def test_footer_only_announces_confirmed_saves_for_the_current_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = EventBus()
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("[red] slides", "Prefer diagrams", "Technical slides"), MemorySource(role="user"))
    notices: list[str] = []

    def notify(message: str, **kwargs):
        notices.append(message)

    async with app.run_test(size=(80, 32)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "capture-session"
        indicator = main.query_one(PersonalMemoryIndicator)
        monkeypatch.setattr(indicator, "notify", notify)
        assert not notices
        await bus.publish(
            PersonalMemoryChanged(session_id=main.chat_session_id, snapshot=store.load(), saved_memory_id=entry.id)
        )
        await wait_for(lambda: bool(notices), pilot=pilot, description="confirmed save announced")
        assert "Remembered:" in notices[0] and "\\[red] slides" in notices[0]
        await bus.publish(
            PersonalMemoryChanged(session_id="another-session", snapshot=store.load(), saved_memory_id=entry.id)
        )
        await pilot.pause()
        assert len(notices) == 1


async def test_paused_memory_shows_original_evidence_and_reason_in_the_library(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Graph research", "Investigate graph learning", "Research planning"),
        MemorySource(quote="Original intention"),
    )
    reason = "This research is complete; stop reminding me."
    store.pause(entry.id, entry.revision, MemorySource(quote=reason), str(tmp_path))
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 38)) as pilot:
        screen = PersonalMemoryScreen(
            bus=bus, workspace=str(tmp_path), session_id="review", initial_view="archived", memory_id=entry.id
        )
        await app.push_screen(screen)
        await wait_for(
            lambda: reason in rich_plain(screen.query_one("#memory-source", Static).render()),
            pilot=pilot,
            description="paused source and reason loaded",
        )
        text = rich_plain(screen.query_one("#memory-source", Static).render())
        assert "Original intention" in text and "Paused" in text


async def test_duplicate_save_returns_to_the_actual_saved_memory(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    existing = await asyncio.to_thread(
        store.save,
        MemoryDraft("Original cache advice", "Inspect artifact versions first.", "", workspace=str(tmp_path)),
        MemorySource(),
    )
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 36)) as pilot:
        screen = PersonalMemoryScreen(bus=bus, workspace=str(tmp_path), session_id="deduplicate")
        app.push_screen(screen)
        await wait_for(lambda: len(screen.snapshot.entries) == 1, pilot=pilot, description="memory loaded")
        screen.query_one("#memory-view", Tabs).active = "memory-view-archived"
        await wait_for(
            lambda: screen.query_one("#memory-list", OptionList).option_count == 0,
            pilot=pilot,
            description="empty paused view",
        )
        await click_when_settled(pilot, screen.query_one("#memory-new", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryEditor) and app.screen.is_mounted, pilot=pilot, description="memory editor")
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-content", TextArea).load_text(existing.draft.content)
        await pilot.press("ctrl+enter")
        await wait_for(lambda: app.screen is screen, pilot=pilot, description="duplicate saved")
        assert screen.current_view == "active"
        assert len(screen.snapshot.entries) == 1 and screen.snapshot.entries[0] == existing
        options = screen.query_one("#memory-list", OptionList)
        await wait_for(lambda: options.highlighted is not None, pilot=pilot, description="existing memory selected")
        assert options.highlighted is not None
        assert options.get_option_at_index(options.highlighted).id == existing.id


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
        screen.query_one("#memory-view", Tabs).active = "memory-view-all"
        await wait_for(
            lambda: screen.query_one("#memory-edit", Button).display,
            pilot=pilot,
            description="other project memory selected",
        )
        await click_when_settled(pilot, screen.query_one("#memory-edit", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryEditor) and app.screen.is_mounted, pilot=pilot, description="editor open")
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
        screen.query_one("#memory-view", Tabs).active = "memory-view-recalled"
        await wait_for(
            lambda: "Matched:" in rich_plain(screen.query_one("#memory-match", Static).render()),
            pilot=pilot,
            description="recall reason visible",
        )
        assert source.quote in rich_plain(screen.query_one("#memory-source", Static).render())
        assert entry.draft.when_to_use in rich_plain(screen.query_one("#memory-when", Static).render())
        for selector in (
            "#memory-mode",
            "#memory-capture",
            "#memory-new",
            "#memory-close",
            "#memory-list",
            "#memory-detail",
        ):
            region = screen.query_one(selector).region
            assert region.width > 0 and region.height > 0
            assert region.x >= 0 and region.right <= size[0]
            assert region.y >= 0 and region.bottom <= size[1]
        await resize_when_settled(pilot, 110, 38)
        assert screen.query_one("#memory-detail").region.width > 0
    await bus.unsubscribe(PersonalMemoryCommand, controller.handle)


async def test_footer_reviews_candidates_then_inspects_recall_without_interrupting_chat(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    source = MemorySource(session_id="origin", quote="先确认下游消费方。再增加 IR 字段。")
    first = await asyncio.to_thread(
        store.save, MemoryDraft("轨迹 IR", "新增字段前确认消费方。", "扩展轨迹 IR"), source, candidate=True
    )
    second = await asyncio.to_thread(
        store.save, MemoryDraft("报告缓存", "先检查产物版本。", "报告内容仍旧"), source, candidate=True
    )
    await asyncio.to_thread(store.set_buddy_notifications, True)
    await asyncio.to_thread(store.maintain)
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 36)) as pilot:
        main = app._main_screen
        assert main is not None
        indicator = main.query_one(PersonalMemoryIndicator)
        main.chat_session_id = "memory-session"
        await wait_for(
            lambda: "Review 2" in rich_plain(indicator.render()), pilot=pilot, description="quiet review entry"
        )
        bar = main.query_one(InputBar)
        before = bar.region
        assert app.screen is main
        await click_when_settled(pilot, indicator)
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted,
            pilot=pilot,
            description="footer opens review",
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await wait_for(
            lambda: screen.current_view == "candidate" and screen.query_one("#memory-accept", Button).display,
            pilot=pilot,
            description="review actions",
        )
        assert not screen.query_one("#memory-evidence", Collapsible).collapsed
        assert source.quote in rich_plain(screen.query_one("#memory-source", Static).render())
        assert not screen.query_one("#memory-forget", Button).display
        assert not screen.query_one("#memory-recall-details").display
        await click_when_settled(pilot, screen.query_one("#memory-accept", Button))
        await wait_for(
            lambda: len([entry for entry in screen.snapshot.entries if entry.state == "candidate"]) == 1,
            pilot=pilot,
            description="accept advances to next suggestion",
        )
        await wait_for(
            lambda: rich_plain(screen.query_one("#memory-title", Static).render()) == "轨迹 IR",
            pilot=pilot,
            description="next suggestion selected",
        )
        await click_when_settled(pilot, screen.query_one("#memory-archive", Button))
        await wait_for(
            lambda: not screen.query_one("#memory-accept", Button).display,
            pilot=pilot,
            description="review queue empty",
        )
        await pilot.press("escape")
        assert app.screen is main
        await wait_for(lambda: rich_plain(indicator.render()) == "Mem", pilot=pilot, description="review badge cleared")
        assert bar.region == before
        state = await asyncio.to_thread(store.load)
        assert next(entry for entry in state.entries if entry.id == second.id).state == "active"
        assert next(entry for entry in state.entries if entry.id == first.id).state == "archived"
        await asyncio.to_thread(store.recall, "报告缓存内容仍旧", "", session_id=main.chat_session_id)
        await bus.publish(
            PersonalMemoryChanged(snapshot=await asyncio.to_thread(store.load), session_id=main.chat_session_id)
        )
        await wait_for(
            lambda: "1 sent" in rich_plain(indicator.render()), pilot=pilot, description="reference shown in footer"
        )
        assert app.screen is main and bar.region == before
        await click_when_settled(pilot, indicator)
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted,
            pilot=pilot,
            description="inspect this turn",
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await wait_for(lambda: screen.current_view == "recalled", pilot=pilot, description="direct recall view")
        assert "does not confirm" in rich_plain(screen.query_one("#memory-recall-tip", Static).render())
        await pilot.press("ctrl+f")
        screen.query_one("#memory-search", EnhancedInput).value = "报告"
        await pilot.press("down")
        assert screen.focused is screen.query_one("#memory-list", OptionList)
        await pilot.press("escape")
        await asyncio.to_thread(store.configure, "manual", False)
        runtime = PersonalMemoryRuntime(bus=bus, session_id=main.chat_session_id, workspace="", store=store)
        await runtime.prepare([Message("user", ["Plan the next task."])])
        await wait_for(
            lambda: rich_plain(indicator.render()) == "Mem",
            pilot=pilot,
            description="manual turn clears the previous turn's reference badge",
        )
        main.chat_session_id = "different-session"
        await wait_for(
            lambda: rich_plain(indicator.render()) == "Mem",
            pilot=pilot,
            description="new chat clears old recall badge",
        )
    await bus.unsubscribe(PersonalMemoryCommand, controller.handle)
