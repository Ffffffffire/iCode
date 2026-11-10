# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory navigation, editing and concurrent actions through the real TUI."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Button, Collapsible, OptionList, Select, Static

from chrys.app.tui.screens.personal_memory.editor import PersonalMemoryEditor
from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import (
    MemoryDraft,
    MemoryRelation,
    MemorySnapshot,
    MemorySource,
    PersonalMemory,
)
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import MAX_BYTES, PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for


async def test_search_coalesces_changes_and_enter_flushes_the_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for word in ("Tea", "Slides", "Testing"):
        store.save(MemoryDraft(word, f"Preference for {word}", word), MemorySource())
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        searches = []
        browse = screen._browser.browse

        def search(entries, query):
            searches.append(query)
            return browse(entries, query)

        monkeypatch.setattr(screen._browser, "browse", search)
        field = screen.query_one("#memory-search", EnhancedInput)
        options = screen.query_one("#memory-list", OptionList)
        for value in ("T", "Te", "Tea"):
            field.value = value
        await wait_for(lambda: options.option_count == 1, pilot=pilot)
        assert searches == ["tea"]
        row = options.get_option_at_index(0)
        await bus.publish(PersonalMemoryChanged(snapshot=store.load()))
        await wait_for(lambda: len(searches) == 2, pilot=pilot)
        assert options.get_option_at_index(0) is row
        field.value = "Slides"
        field.focus()
        await pilot.press("enter")
        await wait_for(lambda: screen.focused is options, pilot=pilot)
        assert screen._selected().draft.title == "Slides"


async def test_related_entry_opens_across_scope_with_all_tab_already_selected(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    target = store.save(MemoryDraft("General practice", "Check consumers", "Design"), MemorySource())
    project = store.save(
        MemoryDraft(
            "Project plan",
            "Test the consumer",
            "Project",
            workspace=str(tmp_path),
            relations=(MemoryRelation(target.id, target.revision, "supports", "Practice"),),
        ),
        MemorySource(),
    )
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = PersonalMemoryScreen(bus=bus, workspace=str(tmp_path), session_id="s", initial_view="all")
        app.push_screen(screen)
        await wait_for(lambda: screen._loaded, pilot=pilot)
        screen.query_one("#memory-scope-filter", Select).value = "project"
        await wait_for(
            lambda: (
                screen._selected_id == project.id and screen.query_one("#memory-list", OptionList).option_count == 1
            ),
            pilot=pilot,
        )
        screen.query_one("#memory-relations", Collapsible).collapsed = False
        relations = screen.query_one("#memory-relations-list", OptionList)
        await wait_for(lambda: relations.region.height > 0, pilot=pilot)
        relations.focus()
        relations.highlighted = 0
        await pilot.press("enter")
        await wait_for(lambda: screen._selected_id == target.id, pilot=pilot)
        assert screen.current_view == "all"
        assert screen.query_one("#memory-scope-filter", Select).value == "all"


async def test_editor_validates_metadata_then_updates_the_same_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "Slides"), MemorySource())
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 45)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        await click_when_settled(pilot, screen.query_one("#memory-edit", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryEditor), pilot=pilot)
        editor = app.screen
        assert isinstance(editor, PersonalMemoryEditor)
        editor.query_one("#memory-edit-options", Collapsible).collapsed = False
        topics = editor.query_one("#memory-edit-topics", EnhancedInput)
        aliases = editor.query_one("#memory-edit-aliases", EnhancedInput)
        for field, value, expected in (
            (topics, "a,b,c,d,e,f,g", "6 topics"),
            (topics, "x" * 41, "1-40"),
            (aliases, "x", "2-80"),
            (aliases, "x" * 81, "2-80"),
        ):
            topics.value = "PPT"
            aliases.value = "架构配图"
            field.value = value
            await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
            await wait_for(
                lambda expected=expected: (
                    expected in rich_plain(editor.query_one("#memory-edit-error", Static).content)
                ),
                pilot=pilot,
            )
            assert store.load().entries[0].revision == entry.revision
            assert editor.focused is field
        topics.value = "PPT\uff0c技术汇报"
        aliases.value = "架构配图\uff0c演讲配图"
        await click_when_settled(pilot, editor.query_one("#memory-edit-save", Button))
        await wait_for(lambda: app.screen is screen, pilot=pilot)
        updated = store.load().entries[0]
        assert updated.id == entry.id and updated.revision == entry.revision + 1
        assert updated.draft.topics == ("PPT", "技术汇报")
        assert store.recall("架构配图", "", record=False)[0][0].id == entry.id


@pytest.mark.parametrize("reject", [False, True])
async def test_batch_action_locks_controls_and_recovers_after_reply(tmp_path: Path, reject: bool) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    entry = store.save(MemoryDraft("Slides", "Diagrams", "Slides"), MemorySource(), candidate=True)
    bus = EventBus()
    controller = PersonalMemoryController(bus, store)
    entered = asyncio.Event()
    release = asyncio.Event()
    batches = []

    async def handle(command: PersonalMemoryCommand) -> None:
        if command.action == "batch_state":
            batches.append(command)
            entered.set()
            await release.wait()
            if reject:
                await bus.publish(PersonalMemoryChanged(request_id=command.event_id, error="Changed elsewhere"))
                return
        await controller.handle(command)

    await bus.subscribe(PersonalMemoryCommand, handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        screen.query_one("#memory-list", OptionList).focus()
        await pilot.press("space")
        button = screen.query_one("#memory-accept", Button)
        button.press()
        try:
            await wait_for(entered.is_set)
            assert button.is_disabled
            button.press()
            # A click queued before the first reply must also be ignored after an error.
            screen.post_message(Button.Pressed(button))
            assert len(batches) == 1
        finally:
            release.set()
        await wait_for(lambda: not screen._mutating, pilot=pilot)
        assert not screen.query_one("#memory-actions").disabled
        assert len(batches) == 1
        assert bool(screen.last_error) == reject
        assert store.load().entries[0].state == ("candidate" if reject else "active")
        assert (entry.id in screen._marked) == reject
        if reject:
            button.press()
            await wait_for(lambda: len(batches) == 2 and not screen._mutating, pilot=pilot)
            revised = await asyncio.to_thread(
                store.save,
                replace(entry.draft, content="Revised elsewhere"),
                MemorySource(),
                memory_id=entry.id,
                revision=entry.revision,
            )
            await pilot.press("ctrl+r")
            await wait_for(lambda: screen.snapshot.entries[0].revision == revised.revision, pilot=pilot)
            assert entry.id not in screen._marked


async def test_model_error_uses_readable_ui_message_and_keeps_detail_in_tooltip(tmp_path: Path) -> None:
    bus = EventBus()
    await bus.subscribe(
        PersonalMemoryCommand, PersonalMemoryController(bus, PersonalMemoryStore(tmp_path / "memory.json")).handle
    )
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        app._main_screen.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        await bus.publish(
            PersonalMemoryChanged(
                error="Quote the latest user request in intent_quote.",
                error_code="memory_request_missing",
                attempted_title="Slides",
            )
        )
        await wait_for(lambda: bool(screen.last_error), pilot=pilot)
        error = screen.query_one("#memory-error", Static)
        assert "intent_quote" not in rich_plain(error.content)
        assert "save request" in rich_plain(error.content)
        assert "intent_quote" in str(error.tooltip)


@pytest.mark.parametrize(
    ("count", "used", "state", "warns"),
    [
        (449, 0, "active", False),
        (450, 0, "active", False),
        (1, int(MAX_BYTES * 0.85), "active", False),
        (1, MAX_BYTES, "active", False),
        (1, 0, "stale", True),
    ],
)
async def test_library_and_footer_agree_on_capacity_warning(
    tmp_path: Path, count: int, used: int, state: str, warns: bool
) -> None:
    bus = EventBus()
    await bus.subscribe(
        PersonalMemoryCommand, PersonalMemoryController(bus, PersonalMemoryStore(tmp_path / "memory.json")).handle
    )
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 40)) as pilot:
        main = app._main_screen
        assert main is not None
        main.action_personal_memory()
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen._loaded, pilot=pilot)
        screen = app.screen
        snapshot = MemorySnapshot(
            generation=1,
            entries=tuple(
                PersonalMemory(
                    f"{i:016x}", 1, MemoryDraft(f"Item {i}", f"Fact {i}", "Example"), MemorySource(), state, "", ""
                )
                for i in range(count)
            ),
        )
        await bus.publish(PersonalMemoryChanged(snapshot=snapshot, used_bytes=used))
        await wait_for(lambda: len(screen.snapshot.entries) == count, pilot=pilot)
        footer = main.query_one(PersonalMemoryIndicator)
        assert ("Review" in rich_plain(footer.content)) == warns
        assert "/500" not in rich_plain(screen.query_one("#memory-capacity", Static).content)
        assert bool(screen.query_one("#memory-capacity", Static).tooltip) == warns
