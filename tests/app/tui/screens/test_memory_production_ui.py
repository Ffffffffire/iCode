# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Review and historical revisions use the real panel command path."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Button, Collapsible, Static

from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets.sidebar import buddy as buddy_module
from chrys.app.tui.widgets.sidebar.buddy_memory import BuddyMemoryCard
from chrys.app.tui.widgets.sidebar.panel import SidebarPanel
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.buddies import a_buddy
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for


async def test_recall_unavailability_is_visible_and_a_successful_read_clears_it(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        indicator = app._main_screen.query_one(PersonalMemoryIndicator)
        await bus.publish(PersonalMemoryChanged(error_code="memory_unavailable", error="Read failed"))
        await wait_for(lambda: "Unavailable" in rich_plain(indicator.content), pilot=pilot)
        await bus.publish(PersonalMemoryChanged(snapshot=await asyncio.to_thread(store.load)))
        await wait_for(lambda: "Unavailable" not in rich_plain(indicator.content), pilot=pilot)


async def test_older_revisions_are_loaded_when_requested(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(store.save, MemoryDraft("Slides", "Original", "technical slides"), MemorySource())
    for i in range(4):
        entry = await asyncio.to_thread(
            store.save,
            replace(entry.draft, content=f"Version {i}"),
            MemorySource(),
            memory_id=entry.id,
            revision=entry.revision,
        )
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        panel = app.screen
        panel.query_one("#memory-history", Collapsible).scroll_visible(animate=False)
        await click_when_settled(pilot, "#memory-history CollapsibleTitle")
        await pilot.wait_for_scheduled_animations()
        more = panel.query_one("#memory-history-more", Button)
        more.scroll_visible(animate=False)
        await click_when_settled(pilot, more)
        await wait_for(
            lambda: "Original" in rich_plain(panel.query_one("#memory-history-text", Static).content), pilot=pilot
        )


async def test_review_queue_checks_conditions_without_globally_pausing_the_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save, MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource()
    )
    for i in range(3):
        await asyncio.to_thread(store.recall, "technical slides", "", session_id="one", turn_id=str(i))
        await asyncio.to_thread(
            store.feedback,
            entry.id,
            1,
            "not_applicable",
            session_id="one",
            turn_id=str(i),
            source=MemorySource(role="user"),
        )
    await asyncio.to_thread(store.maintain)
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory("stale")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        panel = app.screen
        assert "three" in rich_plain(panel.query_one("#memory-replacement", Static).content).lower()
        assert panel.snapshot.entries[0].state == "active"
        await click_when_settled(pilot, "#memory-accept")
        await wait_for(lambda: not panel.snapshot.uses, pilot=pilot)


async def test_panel_distinguishes_unknown_effect_from_confirmed_helpfulness(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save, MemoryDraft("Slides", "Use diagrams", "technical slides"), MemorySource()
    )
    await asyncio.to_thread(store.recall, "technical slides", "", session_id="one", turn_id="1")
    await asyncio.to_thread(store.feedback, entry.id, 1, "applied", session_id="one", turn_id="1")
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        panel = app.screen
        assert "Effect unknown" in rich_plain(panel.query_one("#memory-usage", Static).content)
        assert not panel.query_one("#memory-replacement", Static).display
        state = await asyncio.to_thread(
            store.feedback, entry.id, 1, "helpful", session_id="one", turn_id="1", source=MemorySource(role="user")
        )
        await bus.publish(PersonalMemoryChanged(snapshot=state))
        await wait_for(
            lambda: "Effect unknown" not in rich_plain(panel.query_one("#memory-usage", Static).content), pilot=pilot
        )
        assert "Helpful" in rich_plain(panel.query_one("#memory-usage", Static).content)


async def test_pending_memory_is_quiet_until_weekly_review_and_opening_dismisses_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buddy = a_buddy()
    monkeypatch.setattr(buddy_module, "current_buddy", lambda: buddy)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    await asyncio.to_thread(
        store.save,
        MemoryDraft("Slides", "Inferred preference", "technical slides"),
        MemorySource(role="assistant"),
        candidate=True,
    )
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(120, 42)) as pilot:
        main = app._main_screen
        sidebar = main.query_one(SidebarPanel)
        if not sidebar.is_visible:
            sidebar.toggle()
        sidebar.focus_tab("tab-buddy")
        card = sidebar.query_one(BuddyMemoryCard)
        await bus.publish(PersonalMemoryChanged(snapshot=await asyncio.to_thread(store.load)))
        await wait_for(lambda: card._pending == 1, pilot=pilot)
        assert not card.query_one("#buddy-memory-review", Button).visible
        await asyncio.to_thread(store.set_buddy_notifications, True)
        state = await asyncio.to_thread(store.maintain)
        await bus.publish(PersonalMemoryChanged(snapshot=state))
        await wait_for(lambda: card.query_one("#buddy-memory-review", Button).visible, pilot=pilot)
        await click_when_settled(pilot, "#buddy-memory-review")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen), pilot=pilot)
        assert (await asyncio.to_thread(store.load)).review_notice is None
