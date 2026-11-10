# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Real slash entry, typed browsing, feedback and personal follow-up actions."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.widgets import Button, Select, Static, Tabs, TextArea
from textual.widgets._select import SelectCurrent

from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets.chrome.input_bar import InputBar
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryFollowUp, MemorySource
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for


@pytest.mark.parametrize("width", [60, 80, 120])
async def test_slash_filters_feedback_activity_and_follow_up_completion(tmp_path: Path, width: int) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    preference = await asyncio.to_thread(
        store.save,
        MemoryDraft(
            "Diagram preference", "Use diagrams for technical talks", "PPT", kind="preference", topics=("PPT [red]",)
        ),
        MemorySource(),
    )
    follow = await asyncio.to_thread(
        store.save,
        MemoryDraft(
            "Rollback drill",
            "Verify rollback before release",
            "release",
            kind="intention",
            topics=("release",),
            follow_up=MemoryFollowUp(next_step="Run staging rollback", remind_at="2020-01-01T09:00:00+08:00"),
        ),
        MemorySource(),
    )
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        main.chat_session_id = "one"
        await asyncio.to_thread(store.recall, "PPT", "", session_id=main.chat_session_id, turn_id="turn-1")
        bar = main.query_one(InputBar)
        bar.focus_input()
        bar.query_one("#chat-input", TextArea).load_text("/memory")
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        screen.query_one("#memory-view", Tabs).active = "memory-view-recalled"
        screen.query_one("#memory-kind-filter", Select).value = "preference"
        topics = screen.query_one("#memory-topic-filter", Select)
        topics.value = "PPT [red]"
        await wait_for(lambda: screen._selected_id == preference.id, pilot=pilot)
        assert "PPT [red]" in str(topics.query_one(SelectCurrent).query_one("#label", Static).render())
        skip = screen.query_one("#memory-not-applicable", Button)
        skip.scroll_visible(animate=False)
        await click_when_settled(pilot, skip)
        await wait_for(lambda: preference.id in screen.snapshot.recalls[-1].excluded_ids, pilot=pilot)
        assert next(e for e in screen.snapshot.entries if e.id == preference.id).state == "active"
        assert screen.query_one("#memory-filters").region.right <= app.size.width
        screen.query_one("#memory-kind-filter", Select).value = "all"
        screen.query_one("#memory-topic-filter", Select).value = ""
        screen.query_one("#memory-view", Tabs).active = "memory-view-followups"
        await wait_for(lambda: screen._selected_id == follow.id, pilot=pilot)
        complete = screen.query_one("#memory-complete", Button)
        complete.scroll_visible(animate=False)
        await click_when_settled(pilot, complete)
        await wait_for(
            lambda: next(e for e in screen.snapshot.entries if e.id == follow.id).draft.follow_up.status == "completed",
            pilot=pilot,
        )
        assert not screen.query_one("#memory-follow-actions").display
        screen.query_one("#memory-view", Tabs).active = "memory-view-activity"
        await wait_for(lambda: screen.query_one("#memory-activity").display, pilot=pilot)
        text = rich_plain(screen.query_one("#memory-activity-text", Static).content)
        assert "Rollback drill" in text and "Skip this turn" in text
        assert not screen.last_error


async def test_continue_follow_up_uses_normal_composer_and_preserves_existing_draft(tmp_path: Path) -> None:
    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = await asyncio.to_thread(
        store.save,
        MemoryDraft(
            "Release drill",
            "Test rollback",
            "release",
            kind="intention",
            follow_up=MemoryFollowUp(next_step="Deploy staging"),
        ),
        MemorySource(),
    )
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 42)) as pilot:
        main = app._main_screen
        assert main is not None
        bar = main.query_one(InputBar)
        bar.replace_draft("Unfinished draft")
        main.action_personal_memory("followups", entry.id)
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await click_when_settled(pilot, screen.query_one("#memory-continue", Button))
        assert bar.value == "Unfinished draft" and app.screen is screen
        bar.replace_draft("")
        assert bar.can_commit_editor_draft(), (bar.locked, bar.shell_mode)
        button = screen.query_one("#memory-continue", Button)
        await wait_for(
            lambda: not button.has_class("-active"), pilot=pilot, description="native button press feedback finished"
        )
        button.focus()
        await pilot.press("enter")
        await wait_for(lambda: app.screen is main, pilot=pilot)
        assert entry.id in bar.value and "Deploy staging" in bar.value
        assert (await asyncio.to_thread(store.load)).entries[0].draft.follow_up.status == "pending"
