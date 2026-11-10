# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Real event-bus, sidebar and memory dialog interactions without using a model."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, OptionList, Static

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


@pytest.mark.parametrize("width", [60, 80, 120])
async def test_buddy_shows_recall_and_review_and_opens_the_selected_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    buddy = a_buddy()
    monkeypatch.setattr(buddy_module, "current_buddy", lambda: buddy)
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    selected = store.save(MemoryDraft("[red] PPT", "Use diagrams", "PPT"), MemorySource())
    other = store.save(
        MemoryDraft("Other slides", "用图形讲清技术机制并保持连线关系准确和信息层次清晰。" * 8, "PPT"), MemorySource()
    )
    pending = store.save(MemoryDraft("Cache", "Inspect versions", "Cache"), MemorySource(), candidate=True)
    store.recall(f"memory {selected.id} slides", "", session_id="one")
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "one"
        sidebar = main.query_one(SidebarPanel)
        if not sidebar.is_visible:
            sidebar.toggle()
        sidebar.focus_tab("tab-buddy")
        card = sidebar.query_one(BuddyMemoryCard)
        await wait_for(
            lambda: rich_plain(card.query_one("#buddy-memory-counts", Button).label) == "1 / 2",
            pilot=pilot,
            description="current recall reaches Buddy",
        )
        assert rich_plain(card.query_one("#buddy-memory-review", Button).tooltip) == "Review 1"
        assert card.query_one("#buddy-memory-review", Button).region.right <= app.size.width
        assert not sidebar.buddy_panel.is_petting
        item = card.query_one("#buddy-memory-item", Button)
        assert rich_plain(item.label) == f"{selected.draft.title}\n{selected.draft.content}"
        assert rich_plain(item.render()) == "[red] PPT\nUse diagrams"
        assert item.region.height == 6
        assert item.styles.border_top[0] == "round"
        assert not item.allow_select
        assert not item.FOCUS_ON_CLICK
        await click_when_settled(pilot, card.query_one("#buddy-memory-next", Button))
        await wait_for(lambda: rich_plain(item.label).startswith(other.draft.title), pilot=pilot)
        painted = [strip.text for strip in item.render_lines(item.outer_size.region)]
        assert "用图形讲清" in painted[2]
        assert "…" in painted[4]  # Three CJK lines remain readable; no second wrapping pass hides the ending.
        assert rich_plain(card.query_one("#buddy-memory-prev", Button).label) == "\u2039"
        assert rich_plain(card.query_one("#buddy-memory-next", Button).label) == "\u203a"
        assert rich_plain(card.query_one("#buddy-memory-library", Button).label).startswith("▤ ")
        assert rich_plain(card.query_one("#buddy-memory-review", Button).label).startswith("◇ ")
        assert rich_plain(card.query_one("#buddy-memory-notices", Button).label).startswith("○")
        app.save_screenshot(f"buddy-memory-{width}.svg", path=str(tmp_path))
        await bus.publish(PersonalMemoryChanged(session_id="one", snapshot=store.load()))
        await pilot.pause()
        assert rich_plain(item.label).startswith(other.draft.title)  # Refresh does not reset the page.
        await click_when_settled(pilot, card.query_one("#buddy-memory-prev", Button))
        await wait_for(lambda: rich_plain(item.label).startswith(selected.draft.title), pilot=pilot)
        await click_when_settled(pilot, item)
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and bool(app.screen.snapshot.entries),
            pilot=pilot,
            description="memory title opens its detail",
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        assert screen.current_view == "recalled"
        options = screen.query_one("#memory-list", OptionList)
        assert options.option_count == 2
        assert options.highlighted is not None
        assert options.get_option_at_index(options.highlighted).id == selected.id
        assert "Memory ID" in rich_plain(screen.query_one("#memory-match", Static).render())
        assert not sidebar.buddy_panel.is_petting
        await pilot.press("escape")
        store.set_buddy_notifications(True)
        await asyncio.to_thread(store.maintain)
        await bus.publish(PersonalMemoryChanged(session_id="one", snapshot=store.load()))
        await wait_for(lambda: card.query_one("#buddy-memory-review", Button).visible, pilot=pilot)
        await click_when_settled(pilot, card.query_one("#buddy-memory-review", Button))
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and bool(app.screen.snapshot.entries), pilot=pilot
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        assert screen.current_view == "candidate"
        assert screen.query_one("#memory-list", OptionList).get_option_at_index(0).id == pending.id
        await pilot.press("escape")
        await pilot.pause()
        assert not card.query_one("#buddy-memory-review", Button).has_focus
        item.focus()
        await wait_for(lambda: item.has_focus, pilot=pilot)
        await pilot.press("tab")
        previous = card.query_one("#buddy-memory-prev", Button)
        assert previous.has_focus, repr(app.focused)
        await pilot.press("enter")
        await wait_for(lambda: rich_plain(item.label).startswith(other.draft.title), pilot=pilot)
        await pilot.press("tab")
        counts = card.query_one("#buddy-memory-counts", Button)
        assert counts.has_focus, repr(app.focused)
        assert counts.styles.text_style.underline
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen), pilot=pilot)
        assert app.screen.current_view == "recalled"


async def test_buddy_alerts_are_opt_in_deduplicated_mutable_and_session_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buddy = a_buddy()
    monkeypatch.setattr(buddy_module, "current_buddy", lambda: buddy)
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Technical slides", "Use diagrams", "PPT"), MemorySource())
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(120, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "one"
        sidebar = main.query_one(SidebarPanel)
        if not sidebar.is_visible:
            sidebar.toggle()
        sidebar.focus_tab("tab-buddy")
        panel = sidebar.buddy_panel
        card = panel.query_one(BuddyMemoryCard)
        notices: list[object] = []
        monkeypatch.setattr(panel, "_toast", lambda message, timeout: notices.append(message))

        async def recall(query: str, *, session: str = "one", request_id: str = "") -> None:
            store.recall(query, "", session_id=session)
            await bus.publish(PersonalMemoryChanged(session_id=session, request_id=request_id, snapshot=store.load()))
            await pilot.pause()

        await recall("PPT")
        assert not notices
        assert not store.load().buddy_notifications
        button = card.query_one("#buddy-memory-notices", Button)
        assert button.region.height == 1 and card.region.contains_region(button.region)
        await click_when_settled(pilot, card.query_one("#buddy-memory-notices", Button))
        await wait_for(lambda: store.load().buddy_notifications, pilot=pilot, description="alert preference persisted")
        assert not notices  # Enabling alerts does not re-announce an old selection.
        assert store.load().mode == "auto" and not store.load().capture
        await recall("PowerPoint", request_id="restore")
        assert not notices  # Loading a historical snapshot is not a new recall.
        await recall("make slides")
        assert len(notices) == 1
        await recall("make slides")
        assert len(notices) == 1
        await recall("PPT for another task", session="two")
        assert len(notices) == 1
        buddy = a_buddy(muted=True)
        await recall("PPT presentation")
        assert len(notices) == 1
        store.configure("off", False)
        await recall("PPT again")
        assert len(notices) == 1
        assert card.region.height == 1
        main.chat_session_id = "new-session"
        await wait_for(lambda: card.query_one("#buddy-memory-item", Button).disabled, pilot=pilot)


async def test_buddy_drops_obsolete_recall_and_keeps_project_and_candidate_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(buddy_module, "current_buddy", a_buddy)
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    current = store.save(MemoryDraft("PPT", "Use diagrams", "PPT"), MemorySource())
    store.save(
        MemoryDraft("Private project", "Keep out", "PPT", workspace=str(tmp_path / "another-project")), MemorySource()
    )
    store.recall("PPT", "", session_id="one")
    controller = PersonalMemoryController(bus, store)
    await bus.subscribe(PersonalMemoryCommand, controller.handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(80, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "one"
        sidebar = main.query_one(SidebarPanel)
        if not sidebar.is_visible:
            sidebar.toggle()
        sidebar.focus_tab("tab-buddy")
        card = sidebar.query_one(BuddyMemoryCard)
        item = card.query_one("#buddy-memory-item", Button)
        await wait_for(lambda: rich_plain(item.label) == "PPT\nUse diagrams", pilot=pilot)
        assert rich_plain(item.label) == "PPT\nUse diagrams"
        assert rich_plain(card.query_one("#buddy-memory-library", Button).tooltip) == "▤ Saved 1"
        assert not card.query_one("#buddy-memory-review").visible

        store.save(MemoryDraft("PPT", "Use a single diagram", "PPT"), MemorySource(), memory_id=current.id, revision=1)
        card.update_memory(store.load(), "one", "", announce=False)
        await pilot.pause()
        assert item.disabled and card.region.height == 1  # The old receipt did not provide the new version.

        proposal = store.save(MemoryDraft("Draft", "[bold] needs review", "Review"), MemorySource(), candidate=True)
        card.update_memory(store.load(), "one", "", announce=False)
        await pilot.pause()
        assert item.disabled and card.region.height == 1
        assert not card.query_one("#buddy-memory-review").visible
        store.set_buddy_notifications(True)
        store.maintain()
        card.update_memory(store.load(), "one", "", announce=False)
        await pilot.pause()
        assert "needs review" not in rich_plain(item.render())
        assert item.border_title == "Weekly memory review"
        assert card.region.height == 9
        store.set_state(proposal.id, proposal.revision, "archived")
        card.update_memory(store.load(), "two", "", announce=False)
        await pilot.pause()
        assert item.disabled and card.region.height == 1
        assert not sidebar.buddy_panel.is_petting
