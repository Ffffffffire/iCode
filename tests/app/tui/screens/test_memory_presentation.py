# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory's native controls, visual states and compact layout through the real app."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rich.cells import cell_len
from textual.widgets import Button, Collapsible, Label, OptionList, Select, Static, Tab, Tabs, TextArea

from chrys.app.tui.screens.personal_memory.editor import PersonalMemoryEditor
from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.presentation import format_memory_time
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput, HatchedEmptyState
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.i18n import MessageDef
from chrys.foundation.i18n.formatting import format_message
from chrys.foundation.models.personal_memory import (
    MemoryDraft,
    MemoryFollowUp,
    MemorySnapshot,
    MemorySource,
    PersonalMemory,
)
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import rich_plain
from tests.support.waiting import wait_for


@pytest.mark.parametrize(
    ("seconds", "expected"), [(0, "Just now"), (59, "Just now"), (60, "1m ago"), (3600, "1h ago"), (86400, "1d ago")]
)
def test_recent_memory_time_is_readable(seconds: int, expected: str) -> None:
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    value = (now - timedelta(seconds=seconds)).isoformat()
    assert (
        format_memory_time(
            value, lambda ref: format_message(ref.bind() if isinstance(ref, MessageDef) else ref), now=now
        )
        == expected
    )


@pytest.mark.parametrize("offset", [-7, 1])
def test_old_records_and_future_reminders_keep_a_local_calendar_time(offset: int) -> None:
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    value = now + timedelta(days=offset)
    assert format_memory_time(value.isoformat(), lambda _: "relative", now=now) == value.astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )


@pytest.mark.parametrize(
    ("width", "height", "theme"), [(60, 24, "chrys"), (60, 40, "chrys"), (80, 40, "textual-light"), (120, 40, "chrys")]
)
async def test_memory_rows_keep_selection_alignment_and_hide_empty_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int, height: int, theme: str
) -> None:
    monkeypatch.setattr("chrys.app.tui.i18n.persist_locale", lambda _: None)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    saved = store.save(
        MemoryDraft(
            "技术汇报版式",
            "优先用结构图和流程图解释技术机制。保持信息层次清晰。",
            "制作技术汇报 PPT",
            kind="preference",
        ),
        MemorySource(),
    )
    paused = store.save(MemoryDraft("旧版排版偏好", "曾使用纯文字卡片说明技术机制。", "制作 PPT"), MemorySource())
    store.set_state(paused.id, paused.revision, "archived")
    store.save(
        MemoryDraft("先验证实际消费方", "扩展字段前先验证它如何改变下游产出。", "设计数据结构"),
        MemorySource(),
        candidate=True,
    )
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(width, height)) as pilot:
        app.theme = theme
        app._main_screen.action_personal_memory("all")
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded,
            pilot=pilot,
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        options = screen.query_one("#memory-list", OptionList)
        rows = [rich_plain(options.get_option_at_index(i).prompt) for i in range(3)]
        assert all(len(row.splitlines()) == 2 and row.startswith("  ") for row in rows)
        assert any("Paused" in row for row in rows) and any("Review" in row for row in rows)
        assert rich_plain(screen.query_one("#memory-selected", Static).content) == "Space to select"
        options.focus()
        await pilot.press("space")
        marked = rich_plain(options.get_option_at_index(0).prompt)
        assert marked.splitlines()[0][2:] == rows[0].splitlines()[0][2:]
        assert marked.startswith("☑ ")
        await pilot.press("space")
        options.highlighted = next(i for i in range(3) if options.get_option_at_index(i).id == saved.id)
        await wait_for(lambda: screen._selected_id == saved.id, pilot=pilot)
        assert screen.query_one("#memory-content").styles.border_left[0] == "solid"
        assert not screen.query_one("#memory-usage").display
        assert not screen.query_one("#memory-reconsider").display
        assert screen.query_one("#memory-actions").region.bottom <= screen.query_one("#personal-memory").region.bottom
        assert screen.query_one("#memory-detail").content_size.height >= 4
        await pilot.pause()
        assert options.virtual_size.height == 6  # Three two-line rows, including at 80 columns.
        foreground = options.get_component_rich_style("option-list--option-highlighted").color
        metadata = [
            segment
            for strip in options.render_lines(options.outer_size.region)
            for segment in strip
            if "Saved" in segment.text
        ]
        assert metadata and all(segment.style is not None and segment.style.color == foreground for segment in metadata)
        archive = screen.query_one("#memory-archive", Button)
        assert "Pause" in "".join(strip.text for strip in archive.render_lines(archive.outer_size.region))
        app.save_screenshot(f"library-{width}-{theme}.svg", path=str(tmp_path))
        app.locale_controller.switch_locale("zh-Hans")
        await pilot.pause()
        assert screen.query_one("#personal-memory").border_title == "个性化记忆"
        assert screen.query_one("#memory-detail").scroll_y == 0
        for name in ("kind-filter", "topic-filter", "mode"):
            displayed = rich_plain(screen.query_one(f"#memory-{name} SelectCurrent #label", Static).content)
            assert any("\u4e00" <= char <= "\u9fff" for char in displayed), displayed
        app.save_screenshot(f"library-zh-{width}-{theme}.svg", path=str(tmp_path))
        app.locale_controller.switch_locale("en-US")
        await pilot.pause()
        if height == 24:
            evidence = screen.query_one("#memory-evidence", Collapsible)
            evidence.query_one("CollapsibleTitle").focus()
            await pilot.press("enter")
            await wait_for(lambda: not evidence.collapsed, pilot=pilot)
            assert screen.query_one("#memory-detail").scroll_y > 0  # Deliberately opening a section still reveals it.
        screen.query_one("#memory-kind-filter", Select).value = "preference"
        await wait_for(lambda: options.option_count == 1, pilot=pilot)
        assert rich_plain(screen.query_one("#memory-view-candidate", Tab).label) == "Review 0"
        screen.query_one("#memory-kind-filter", Select).value = "all"
        screen.query_one("#memory-search", EnhancedInput).value = "zz-unmatched-query-zz"
        await wait_for(lambda: options.option_count == 0, pilot=pilot)
        empty = screen.query_one("#memory-empty", HatchedEmptyState)
        assert empty.display and empty.label == "No memories in this view."
        assert not screen.query_one("#memory-content").display
        assert not screen.query_one("#memory-meta").display
        screen.query_one("#memory-search", EnhancedInput).value = ""
        screen.query_one("#memory-view", Tabs).active = "memory-view-recalled"
        await wait_for(lambda: empty.label == "No memories recalled for this task.", pilot=pilot)
        app.save_screenshot(f"empty-{width}-{theme}.svg", path=str(tmp_path))


async def test_full_library_can_be_filtered_and_opened_without_losing_the_selection(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    original = store.save(MemoryDraft("Notes", "Review the component interface", "Code reviews"), MemorySource())
    entries = tuple(
        replace(
            original,
            id=f"{index:012x}",
            draft=replace(original.draft, title="quartzneedle" if index == 250 else f"Component {index}"),
        )
        for index in range(500)
    )
    snapshot = replace(store.load(), entries=entries)
    bus = EventBus()
    requests: list[str] = []

    async def load(command: PersonalMemoryCommand) -> None:
        requests.append(command.action)
        assert command.action == "load"
        await bus.publish(
            PersonalMemoryChanged(session_id=command.session_id, request_id=command.event_id, snapshot=snapshot)
        )

    await bus.subscribe(PersonalMemoryCommand, load)
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(120, 40)) as pilot:
        app._main_screen.action_personal_memory("all")
        await wait_for(
            lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded,
            pilot=pilot,
        )
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        options = screen.query_one("#memory-list", OptionList)
        assert options.option_count == 500
        search = screen.query_one("#memory-search", EnhancedInput)
        await pilot.press("ctrl+f")
        search.value = "quartzneedle"
        await wait_for(lambda: options.option_count == 1, pilot=pilot)
        assert options.get_option_at_index(0).id == entries[250].id
        await pilot.press("enter")
        await wait_for(lambda: options.has_focus, pilot=pilot)
        assert screen._selected_id == entries[250].id
        assert rich_plain(screen.query_one("#memory-title", Static).content) == "quartzneedle"
        search.value = ""
        await wait_for(lambda: options.option_count == 500, pilot=pilot)
        assert options.highlighted is not None
        assert options.get_option_at_index(options.highlighted).id == entries[250].id
        assert set(requests) == {"load"}
        assert not screen.last_error


async def test_editor_keeps_labels_and_error_actions_visible_when_scrolled(tmp_path: Path) -> None:
    saved = []

    async def save(draft: MemoryDraft) -> str:
        saved.append(draft)
        return ""

    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine())
    async with app.run_test(size=(60, 28)) as pilot:
        draft = MemoryDraft(
            "Follow up", "Check the next release", "Release", kind="intention", follow_up=MemoryFollowUp()
        )
        editor = PersonalMemoryEditor(
            workspace=str(tmp_path), save=save, draft=draft, locale_controller=app.locale_controller
        )
        app.push_screen(editor)
        await wait_for(lambda: editor.is_mounted, pilot=pilot)
        editor.query_one("#memory-edit-options", Collapsible).collapsed = False
        field = editor.query_one("#memory-edit-remind", EnhancedInput)
        field.value = "invalid-date"
        field.focus()
        field.scroll_visible(animate=False)
        await pilot.press("ctrl+enter")
        await wait_for(lambda: editor.query_one("#memory-edit-error").display, pilot=pilot)
        assert editor.focused is field
        assert not saved
        error = editor.query_one("#memory-edit-error", Static)
        assert error.parent is editor.query_one("#memory-editor")
        assert error.region.bottom <= editor.query_one("#memory-edit-buttons").region.y
        assert rich_plain(editor.query_one("#memory-label-title", Label).content) == "Title"
        assert editor.query_one("#memory-edit-title").styles.height.value == 1
        app.save_screenshot("editor-error-60.svg", path=str(tmp_path))
        field.value = ""
        editor.query_one("#memory-edit-content", TextArea).load_text("")
        await pilot.press("ctrl+enter")
        await wait_for(lambda: editor.focused is editor.query_one("#memory-edit-content"), pilot=pilot)
        assert "Write something" in rich_plain(error.content)
        assert not saved


async def test_footer_colors_and_badge_width_follow_the_visible_state(tmp_path: Path) -> None:
    bus = EventBus()
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    async with app.run_test(size=(100, 35)) as pilot:
        indicator = app._main_screen.query_one(PersonalMemoryIndicator)
        stale = PersonalMemory(
            "a" * 16,
            1,
            MemoryDraft("Slides", "Use diagrams", "slides"),
            MemorySource(),
            "stale",
            "",
            "",
            review_reason="repeated_mismatch",
        )
        await bus.publish(PersonalMemoryChanged(snapshot=MemorySnapshot(entries=(stale,))))
        await wait_for(lambda: indicator.has_class("-capacity"), pilot=pilot)
        assert rich_plain(indicator.content) == "Mem · Review"
        assert cell_len(rich_plain(indicator.content)) + indicator.styles.padding.width <= 20
        capacity_color = indicator.styles.color
        await bus.publish(
            PersonalMemoryChanged(error="Rejected", attempted_title="Slides", error_code="memory_source_missing")
        )
        await wait_for(lambda: indicator.has_class("-failed"), pilot=pilot)
        assert not indicator.has_class("-capacity")
        assert indicator.styles.color != capacity_color
        await pilot.pause()
        assert indicator.region.width >= cell_len(rich_plain(indicator.content)) + indicator.styles.padding.width
        app.save_screenshot("footer-failed.svg", path=str(tmp_path))
