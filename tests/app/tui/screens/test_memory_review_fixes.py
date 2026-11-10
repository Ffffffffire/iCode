# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Review fixes through the real footer, slash entry, list and event controller."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, OptionList, Static, Tabs, TextArea

from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.app.tui.widgets.chrome.input_bar import InputBar
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import MAX_BYTES, PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for


@pytest.mark.parametrize("width", [60, 100])
async def test_search_batch_review_and_cross_session_feedback(tmp_path: Path, width: int) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    entries = [
        await asyncio.to_thread(
            store.save,
            MemoryDraft(f"Slides {i}", f"Use diagrams {i}", "Technical slides"),
            MemorySource(),
            candidate=True,
        )
        for i in range(2)
    ]
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        bar = main.query_one(InputBar)
        bar.focus_input()
        bar.query_one("#chat-input", TextArea).load_text("/memory")
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        screen.query_one("#memory-search", EnhancedInput).value = "幻灯片"
        await wait_for(lambda: screen.query_one("#memory-list", OptionList).option_count == 2, pilot=pilot)
        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("space", "down", "space")
        await wait_for(lambda: len(screen._marked) == 2, pilot=pilot)
        await click_when_settled(pilot, screen.query_one("#memory-accept", Button))
        await wait_for(lambda: all(e.state == "active" for e in screen.snapshot.entries), pilot=pilot)
        screen.query_one("#memory-view", Tabs).active = "memory-view-active"
        await wait_for(lambda: screen._selected() is not None, pilot=pilot)
        assert screen.query_one("#memory-feedback-actions").display
        assert screen.query_one("#memory-not-applicable", Button).disabled
        helpful = screen.query_one("#memory-helpful", Button)
        helpful.scroll_visible(animate=False)
        await click_when_settled(pilot, helpful)
        await wait_for(lambda: any(e.action == "helpful" for e in screen.snapshot.activity), pilot=pilot)
        usage = rich_plain(screen.query_one("#memory-usage", Static).content)
        assert "1 helpful" in usage and "0 agent uses" in usage
        assert "2 memories" in rich_plain(screen.query_one("#memory-capacity", Static).content)
        assert "/500" not in rich_plain(screen.query_one("#memory-capacity", Static).content)
        assert screen.query_one("#memory-actions").region.right <= app.size.width
        assert not screen.last_error
    assert {e.id for e in store.load().entries} == {e.id for e in entries}


async def test_footer_exposes_rejection_and_clears_it_only_after_a_successful_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 35)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "s1"
        runtime = PersonalMemoryRuntime(bus=bus, session_id="s1", workspace="", store=store)
        runtime.observe([Message("user", ["Remember my preference for slide diagrams."])])
        await runtime.propose_memory("Slides [red]", "Diagrams", "Slides", "Invented", save_now=True)
        indicator = main.query_one(PersonalMemoryIndicator)
        notices = []
        monkeypatch.setattr(indicator, "notify", lambda *args, **kwargs: notices.append(args))
        await wait_for(lambda: "Not saved" in rich_plain(indicator.content), pilot=pilot)
        assert "Slides [red]" in str(indicator.tooltip)
        result = await runtime.propose_memory(
            "Slides [red]", "Diagrams", "Slides", "preference for slide diagrams", save_now=True
        )
        assert not result.startswith("Error:")
        await wait_for(lambda: "Not saved" not in rich_plain(indicator.content), pilot=pilot)
        assert len(notices) == 1
        await runtime.propose_memory("Slides [red]", "Diagrams", "Slides", "Invented", save_now=True)
        await wait_for(lambda: "Not saved" in rich_plain(indicator.content), pilot=pilot)
        await runtime.recall_memory("Slides", for_update=True)
        result = await runtime.propose_memory(
            "Slides [red]", "Diagrams", "Slides", "preference for slide diagrams", save_now=True
        )
        assert not result.startswith("Error:"), result
        await wait_for(lambda: "Not saved" not in rich_plain(indicator.content), pilot=pilot)
        assert len(notices) == 1
        await bus.publish(PersonalMemoryChanged(session_id="s1", snapshot=store.load(), used_bytes=MAX_BYTES))
        await pilot.pause()
        assert not indicator.has_class("-capacity")
        off = await asyncio.to_thread(store.configure, "off", False)
        await bus.publish(PersonalMemoryChanged(session_id="s1", snapshot=off))
        await runtime.propose_memory("Slides [red]", "Diagrams", "Slides", "Invented", save_now=True)
        await wait_for(lambda: "Not saved" in rich_plain(indicator.content), pilot=pilot)


async def test_activity_ui_can_read_records_older_than_the_snapshot_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from chrys.service.personal_memory import activity

    monkeypatch.setattr(activity, "RECENT_ACTIVITY", 4)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(store.save, MemoryDraft("Cache", "Original claim", "cache"), MemorySource())
    for i in range(6):
        entry = await asyncio.to_thread(
            store.save,
            replace(entry.draft, content=f"Claim {i}"),
            MemorySource(),
            memory_id=entry.id,
            revision=entry.revision,
        )
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(80, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory("activity")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await click_when_settled(pilot, screen.query_one("#memory-older", Button))
        await wait_for(lambda: screen._history_page is not None, pilot=pilot)
        assert "Original claim" in rich_plain(screen.query_one("#memory-activity-text", Static).content)
        assert screen.query_one("#memory-older", Button).disabled
        assert not screen.last_error
        page = screen._history_page
        old_snapshot = screen.snapshot
        changed = await asyncio.to_thread(store.configure, "manual", False)
        await bus.publish(PersonalMemoryChanged(snapshot=changed))
        await wait_for(lambda: screen.snapshot.mode == "manual", pilot=pilot)
        assert screen._history_page == page
        assert "Original claim" in rich_plain(screen.query_one("#memory-activity-text", Static).content)
        forgotten = await asyncio.to_thread(store.forget, entry.id, entry.revision)
        await bus.publish(PersonalMemoryChanged(snapshot=forgotten))
        await wait_for(lambda: not screen.snapshot.entries, pilot=pilot)
        await bus.publish(PersonalMemoryChanged(snapshot=old_snapshot, history=page))
        delivered = asyncio.Event()
        screen.call_later(delivered.set)
        await wait_for(delivered.is_set, pilot=pilot)
        assert screen._history_page is None
        assert "Original claim" not in rich_plain(screen.query_one("#memory-activity-text", Static).content)
