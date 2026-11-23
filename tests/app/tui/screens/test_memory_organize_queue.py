# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
"""The /memory organize view lists, filters, selects and hands off review work.

Every case mounts the real main screen, the real ``PersonalMemoryController``
and an isolated ``PersonalMemoryStore``; nothing here reads the user's library.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from textual.widgets import Button, OptionList, Select, Static, Tab, Tabs

from chrys.app.tui.screens.personal_memory.indicator import PersonalMemoryIndicator
from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
from chrys.app.tui.widgets import EnhancedInput
from chrys.app.tui.widgets.chrome.input_bar import InputBar
from chrys.app.tui.widgets.sidebar import buddy as buddy_module
from chrys.app.tui.widgets.sidebar.buddy_memory import BuddyMemoryCard
from chrys.app.tui.widgets.sidebar.panel import SidebarPanel
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryRelation, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.buddies import a_buddy
from tests.support.tui_app_harness import SessionGenerationEngine, make_chrys_app
from tests.support.tui_helpers import click_when_settled, rich_plain
from tests.support.waiting import wait_for

_REVIEW_PROMPT_TAIL = "Wait for my confirmation before retiring sources."


async def _save(store: PersonalMemoryStore, draft: MemoryDraft, **kwargs: object):
    return await asyncio.to_thread(store.save, draft, MemorySource(), **kwargs)


def _labels(screen: PersonalMemoryScreen) -> list[str]:
    options = screen.query_one("#memory-list", OptionList)
    return [rich_plain(options.get_option_at_index(index).prompt) for index in range(options.option_count)]


def _ids(screen: PersonalMemoryScreen) -> list[str]:
    options = screen.query_one("#memory-list", OptionList)
    return [str(options.get_option_at_index(index).id) for index in range(options.option_count)]


def _detail(screen: PersonalMemoryScreen, widget_id: str) -> str:
    return rich_plain(screen.query_one(widget_id, Static).content)


def _patch_entries(store: PersonalMemoryStore, changes: dict[str, dict[str, object]]) -> None:
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    for entry in payload["entries"]:
        fields = changes.get(entry["id"])
        if fields:
            entry.update(fields)
    atomic_write_owner_only_text(store.path, json.dumps(payload))


async def _skip_turns(store: PersonalMemoryStore, entry, query: str, count: int = 3, *, user: bool = True) -> None:
    for turn in range(count):
        await asyncio.to_thread(store.recall, query, "", session_id="one", turn_id=f"{entry.id[:4]}-{turn}")
        await asyncio.to_thread(
            store.feedback,
            entry.id,
            entry.revision,
            "not_applicable",
            session_id="one",
            turn_id=f"{entry.id[:4]}-{turn}",
            source=MemorySource(role="user") if user else None,
        )


async def _stale(store: PersonalMemoryStore, entry, tmp_path: Path, *, reason: str = "repeated_mismatch"):
    """A stale record that the load-time maintenance keeps stale, as AC-004 requires."""
    paused = await asyncio.to_thread(
        store.pause, entry.id, entry.revision, MemorySource(role="user", quote="This no longer applies"), str(tmp_path)
    )
    _patch_entries(store, {paused.id: {"state": "stale", "review_reason": reason}})
    return paused


async def _duplicate_pair(
    store: PersonalMemoryStore,
    *,
    topics: tuple[tuple[str, ...], tuple[str, ...]] = ((), ()),
    candidate_second: bool = False,
):
    first = await _save(store, MemoryDraft("Density", "Use  dense diagrams", "technical slides", topics=topics[0]))
    second = await _save(
        store,
        MemoryDraft("Density revised", "use dense diagrams", "technical slides", topics=topics[1]),
        candidate=candidate_second,
    )
    return first, second


def _open_app(tmp_path: Path, store: PersonalMemoryStore, bus: EventBus):
    app = make_chrys_app(tmp_path / "sessions", engine=SessionGenerationEngine(), event_bus=bus)
    return app


async def _mount_memory_app(tmp_path: Path, store: PersonalMemoryStore):
    bus = EventBus()
    await bus.subscribe(PersonalMemoryCommand, PersonalMemoryController(bus, store).handle)
    app = _open_app(tmp_path, store, bus)
    return bus, app


async def _open_panel(pilot, app, *, view: str = "organize", memory_id: str = "") -> PersonalMemoryScreen:
    app._main_screen.action_personal_memory(view, memory_id)
    await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
    screen = app.screen
    assert isinstance(screen, PersonalMemoryScreen)
    return screen


async def test_organize_view_lists_each_reason_and_its_detail(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    duplicate_a, duplicate_b = await _duplicate_pair(store)
    source = await _save(store, MemoryDraft("Checksum", "Write the checksum report", "release checks"))
    derived = await _save(
        store,
        MemoryDraft(
            "Checksum follow-up",
            "Compare both checksum reports",
            "release checks",
            relations=(MemoryRelation(source.id, 1, "derived_from", "Comes from the checksum rule"),),
        ),
    )
    skipped = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
    await _skip_turns(store, skipped, "margins")
    stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
    stale = await _stale(store, stale, tmp_path)
    healthy = await _save(store, MemoryDraft("Unrelated", "Run the tests twice", "testing"))
    archived = await _save(store, MemoryDraft("Withdrawn", "Use the old publisher", "releases"))
    await asyncio.to_thread(store.set_state, archived.id, archived.revision, "archived")
    await _save(
        store,
        MemoryDraft("Checksum, corrected", "Write the checksum report twice", "release checks"),
        memory_id=source.id,
        revision=1,
    )

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)

        assert screen.current_view == "organize"
        listed = _ids(screen)
        assert set(listed) == {duplicate_a.id, duplicate_b.id, derived.id, skipped.id, stale.id}
        assert healthy.id not in listed and archived.id not in listed

        rows = _labels(screen)
        by_id = dict(zip(listed, rows, strict=True))
        assert "Similar content" in by_id[duplicate_a.id]
        assert "Source changed" in by_id[derived.id]
        assert "Repeatedly not applicable" in by_id[skipped.id]
        assert "Marked for review" in by_id[stale.id]
        assert "Similar content" not in by_id[derived.id]

        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("home")
        index = listed.index(derived.id)
        await pilot.press(*(["down"] * index))
        await wait_for(lambda: screen._selected_id == derived.id, pilot=pilot)
        assert "Source changed · review before using" in _detail(screen, "#memory-replacement")
        assert "Source changed" in _detail(screen, "#memory-organize-reasons")

        skipped_index = listed.index(skipped.id)
        await pilot.press("home")
        await pilot.press(*(["down"] * skipped_index))
        await wait_for(lambda: screen._selected_id == skipped.id, pilot=pilot)
        assert "Repeatedly not applicable" in _detail(screen, "#memory-organize-reasons")
        usage = _detail(screen, "#memory-usage")
        assert "3 user skips" in usage
        assert "Repeated skips: check whether the usage conditions need narrowing." in usage

        stale_index = listed.index(stale.id)
        await pilot.press("home")
        await pilot.press(*(["down"] * stale_index))
        await wait_for(lambda: screen._selected_id == stale.id, pilot=pilot)
        assert "Applicability was questioned in three turns" in _detail(screen, "#memory-replacement")
        assert "Marked for review" in _detail(screen, "#memory-organize-reasons")


async def test_stale_memory_without_a_specific_reason_shows_the_generic_review_hint(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
    stale = await _stale(store, stale, tmp_path, reason="")
    await _save(store, MemoryDraft("Unrelated", "Run the tests twice", "testing"))

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert _ids(screen) == [stale.id]
        assert "Marked for review" in _labels(screen)[0]

        screen.query_one("#memory-list", OptionList).focus()
        await pilot.press("home")
        await wait_for(lambda: screen._selected_id == stale.id, pilot=pilot)
        reasons = _detail(screen, "#memory-organize-reasons")
        assert "Marked for review" in reasons
        assert "Marked for review. Check whether it still applies." in reasons
        assert "Applicability was questioned in three turns" not in reasons
        assert "Applicability was questioned in three turns" not in _detail(screen, "#memory-replacement")

        app.locale_controller.switch_locale("zh-Hans")
        await wait_for(
            lambda: (
                "已标记需复核" in _detail(screen, "#memory-organize-reasons")
                and "请确认是否仍然适用。" in _detail(screen, "#memory-organize-reasons")
            ),
            pilot=pilot,
            description="the generic review hint is localized",
        )
        assert "Marked for review. Check whether it still applies." not in _detail(screen, "#memory-organize-reasons")


async def test_multi_reason_memory_stays_one_row_whose_detail_names_every_reason(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = await _save(store, MemoryDraft("Density source", "Measure the density baseline", "technical slides"))
    many = await _save(
        store,
        MemoryDraft(
            "Density",
            "Use  density charts",
            "technical slides",
            relations=(MemoryRelation(source.id, 1, "derived_from", "Comes from the density rule"),),
        ),
    )
    partner = await _save(store, MemoryDraft("Density second copy", "use density charts", "technical slides"))
    await _skip_turns(store, many, "density")
    await _save(
        store,
        MemoryDraft("Density source, revised", "Measure the density baseline twice", "technical slides"),
        memory_id=source.id,
        revision=1,
    )

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)

        listed = _ids(screen)
        assert listed.count(many.id) == 1
        assert set(listed) == {many.id, partner.id}
        row = dict(zip(listed, _labels(screen), strict=True))[many.id]
        for label in ("Similar content", "Source changed", "Repeatedly not applicable"):
            assert row.count(label) == 1

        screen.query_one("#memory-list", OptionList).focus()
        await pilot.press("home")
        await pilot.press(*(["down"] * listed.index(many.id)))
        await wait_for(lambda: screen._selected_id == many.id, pilot=pilot)
        reasons = _detail(screen, "#memory-organize-reasons")
        assert "Similar content" in reasons and "Source changed" in reasons
        assert "Repeatedly not applicable" in reasons
        assert reasons.count("Similar content") == 1 and reasons.count("Source changed") == 1
        assert partner.draft.title in reasons
        assert _detail(screen, "#memory-replacement").count("Source changed") == 1


async def test_candidate_joins_the_queue_and_stays_in_the_review_view(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    active, candidate = await _duplicate_pair(store, candidate_second=True)
    other_kind = await _save(
        store,
        MemoryDraft("Density preference", "Use dense diagrams", "technical slides", kind="preference"),
        candidate=True,
    )
    alone = await _save(store, MemoryDraft("Group logs", "Group logs by request id", "logs"), candidate=True)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        assert set(listed) == {active.id, candidate.id}
        assert other_kind.id not in listed and alone.id not in listed

        screen.query_one("#memory-view", Tabs).active = "memory-view-candidate"
        await wait_for(lambda: screen.current_view == "candidate", pilot=pilot)
        await wait_for(lambda: set(_ids(screen)) == {candidate.id, other_kind.id, alone.id}, pilot=pilot)

        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("end")
        await wait_for(lambda: screen._selected_id == _ids(screen)[-1], pilot=pilot)
        await click_when_settled(pilot, "#memory-accept")

        def promoted() -> bool:
            return next(entry for entry in screen.snapshot.entries if entry.id == candidate.id).state == "active"

        await wait_for(promoted, pilot=pilot, description="the duplicate candidate was accepted from its own view")
        screen.query_one("#memory-view", Tabs).active = "memory-view-organize"
        await wait_for(lambda: screen.current_view == "organize", pilot=pilot)
        await wait_for(
            lambda: candidate.id in _ids(screen), pilot=pilot, description="the accepted duplicate stays in the queue"
        )


async def test_duplicate_detail_names_every_partner_even_when_the_topic_filter_hides_it(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    visible, hidden = await _duplicate_pair(store, topics=(("slides",), ("release",)))
    third = await _save(
        store, MemoryDraft("Charts", "\uff35\uff33\uff25 dense diagrams", "technical slides", topics=("release",))
    )
    elsewhere = await _save(
        store,
        MemoryDraft(
            "Other project chart", "Use dense diagrams", "technical slides", workspace=str(tmp_path / "other-project")
        ),
    )

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert set(_ids(screen)) == {visible.id, hidden.id, third.id}

        screen.query_one("#memory-topic-filter", Select).value = "slides"
        await wait_for(lambda: _ids(screen) == [visible.id], pilot=pilot, description="topic filter hides partners")

        reasons = _detail(screen, "#memory-organize-reasons")
        assert "Same content (same type and scope):" in reasons
        assert hidden.draft.title in reasons and third.draft.title in reasons
        assert hidden.id in reasons and third.id in reasons
        assert elsewhere.draft.title not in reasons and elsewhere.id not in reasons


async def test_scope_filters_never_leak_another_projects_private_memory(tmp_path: Path) -> None:
    current_project = os.getcwd()
    other_project = str(tmp_path / "another-project")
    store = PersonalMemoryStore(tmp_path / "memory.json")

    async def pair(name: str, workspace: str) -> tuple[str, str]:
        first = await _save(
            store,
            MemoryDraft(f"{name} density", "Use  project dense diagrams", "technical slides", workspace=workspace),
        )
        second = await _save(
            store,
            MemoryDraft(
                f"{name} density, second copy", "use project dense diagrams", "technical slides", workspace=workspace
            ),
        )
        return first.id, second.id

    project_ids = await pair("Project", current_project)
    personal_ids = await pair("Personal", "")
    other_ids = await pair("Other", other_project)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert set(_ids(screen)) == {*project_ids, *personal_ids}

        scope = screen.query_one("#memory-scope-filter", Select)
        scope.value = "personal"
        await wait_for(lambda: set(_ids(screen)) == set(personal_ids), pilot=pilot, description="personal scope")
        scope.value = "project"
        await wait_for(lambda: set(_ids(screen)) == set(project_ids), pilot=pilot, description="project scope")
        scope.value = "all"
        await wait_for(
            lambda: set(_ids(screen)) == {*project_ids, *personal_ids, *other_ids}, pilot=pilot, description="all scope"
        )


async def _mark_rows(pilot, screen: PersonalMemoryScreen, indices: tuple[int, ...]) -> None:
    options = screen.query_one("#memory-list", OptionList)
    options.focus()
    await pilot.press("home")
    position = 0
    for index in sorted(indices):
        if index > position:
            await pilot.press(*(["down"] * (index - position)))
        position = index
        await pilot.press("space")
    await wait_for(lambda: set(screen._marked) == {_ids(screen)[i] for i in indices}, pilot=pilot)


def _files(store: PersonalMemoryStore) -> tuple[bytes, bytes, bytes]:
    return (store.path.read_bytes(), store.receipts_path.read_bytes(), store.activity_path.read_bytes())


async def test_kind_topic_and_search_filters_narrow_the_queue_by_intersection(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    slides_a = await _save(
        store, MemoryDraft("Slides density", "Use  dense diagrams", "technical slides", topics=("slides",))
    )
    slides_b = await _save(
        store,
        MemoryDraft("Slides density, second copy", "use dense diagrams", "technical slides", topics=("slides",)),
    )
    release_a = await _save(
        store,
        MemoryDraft(
            "Release density",
            "Keep release notes dense",
            "release notes",
            kind="preference",
            topics=("release",),
        ),
    )
    release_b = await _save(
        store,
        MemoryDraft(
            "Release density, second copy",
            "keep  release notes dense",
            "release notes",
            kind="preference",
            topics=("release",),
        ),
    )
    skipped = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides", topics=("slides",)))
    await _skip_turns(store, skipped, "margins")

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert set(_ids(screen)) == {slides_a.id, slides_b.id, release_a.id, release_b.id, skipped.id}

        kind = screen.query_one("#memory-kind-filter", Select)
        kind.value = "preference"
        await wait_for(lambda: set(_ids(screen)) == {release_a.id, release_b.id}, pilot=pilot, description="kind")
        kind.value = "all"
        topic = screen.query_one("#memory-topic-filter", Select)
        topic.value = "slides"
        await wait_for(
            lambda: set(_ids(screen)) == {slides_a.id, slides_b.id, skipped.id}, pilot=pilot, description="topic"
        )
        kind.value = "lesson"
        await wait_for(lambda: set(_ids(screen)) == {slides_a.id, slides_b.id, skipped.id}, pilot=pilot)
        kind.value = "preference"
        await wait_for(lambda: _ids(screen) == [], pilot=pilot, description="intersection of kind and topic")
        kind.value = "all"
        topic.value = ""
        search = screen.query_one("#memory-search", EnhancedInput)
        search.value = "release notes"
        await wait_for(lambda: set(_ids(screen)) == {release_a.id, release_b.id}, pilot=pilot, description="search")
        rows = dict(zip(_ids(screen), _labels(screen), strict=True))
        assert "Similar content" in rows[release_a.id]
        search.value = ""
        await wait_for(lambda: len(_ids(screen)) == 5, pilot=pilot, description="filters cleared")


async def test_selection_stops_at_the_batch_limit_and_cancels_cleanly(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for index in range(26):
        await _save(store, MemoryDraft(f"Density {index}", f"Use{' ' * (index + 2)}density charts", "technical slides"))

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 60)) as pilot:
        screen = await _open_panel(pilot, app)
        assert len(_ids(screen)) == 26
        before = _files(store)

        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("home")
        for _ in range(25):
            await pilot.press("space", "down")
        await wait_for(lambda: len(screen._marked) == 25, pilot=pilot)
        await pilot.press("space")
        assert len(screen._marked) == 25
        error = screen.query_one("#memory-error", Static)
        assert error.display
        assert "Select up to 25 memories at a time." in rich_plain(error.content)

        await pilot.press("up", "space")
        await wait_for(lambda: len(screen._marked) == 24, pilot=pilot)
        assert "24 selected" in rich_plain(screen.query_one("#memory-selected", Static).content)
        assert _files(store) == before


async def test_selection_drops_hidden_rows_and_does_not_come_back(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    slides, release = await _duplicate_pair(store, topics=(("slides",), ("release",)))

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        await _mark_rows(pilot, screen, (0, 1))
        assert set(screen._marked) == {slides.id, release.id}

        topic = screen.query_one("#memory-topic-filter", Select)
        topic.value = "slides"
        await wait_for(lambda: _ids(screen) == [slides.id], pilot=pilot, description="release row hidden")
        assert set(screen._marked) == {slides.id}
        topic.value = ""
        await wait_for(lambda: set(_ids(screen)) == {slides.id, release.id}, pilot=pilot, description="filters cleared")
        assert set(screen._marked) == {slides.id}


async def test_a_new_snapshot_drops_stale_versions_and_finished_conditions(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store)
    first = await _save(
        store,
        MemoryDraft("Density", "Use   dense diagrams", "technical slides"),
        memory_id=first.id,
        revision=1,
    )
    condition = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
    await _skip_turns(store, condition, "margins")

    bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert set(_ids(screen)) == {first.id, second.id, condition.id}
        await _mark_rows(pilot, screen, (0, 1, 2))
        assert set(screen._marked) == {first.id, second.id, condition.id}

        await _save(
            store,
            MemoryDraft("Density", "Use    dense diagrams", "technical slides"),
            memory_id=first.id,
            revision=first.revision,
        )
        await asyncio.to_thread(store.set_state, condition.id, condition.revision, "active")
        await bus.publish(PersonalMemoryChanged(snapshot=await asyncio.to_thread(store.load)))
        await wait_for(lambda: set(screen._marked) == {second.id}, pilot=pilot, description="stale selections dropped")

        input_bar = app._main_screen.query_one(InputBar)
        await click_when_settled(pilot, "#memory-organize")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="handoff closes the panel")
        prompt = input_bar.value
        assert f"{second.id} v{second.revision}" in prompt
        assert first.id not in prompt and condition.id not in prompt


async def test_review_together_hands_selected_versions_to_the_composer(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store, topics=(("slides",), ("slides",)))
    first = await _save(
        store,
        MemoryDraft("Density", "Use   dense diagrams", "technical slides", topics=("slides",)),
        memory_id=first.id,
        revision=1,
    )
    unselected = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides", topics=("slides",)))
    await _skip_turns(store, unselected, "margins")

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        await _mark_rows(pilot, screen, (listed.index(first.id), listed.index(second.id)))
        screen.query_one("#memory-topic-filter", Select).value = "slides"
        await wait_for(lambda: len(_ids(screen)) == 3, pilot=pilot, description="topic narrowed")
        before = _files(store)
        input_bar = app._main_screen.query_one(InputBar)
        assert input_bar.value == ""

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="successful handoff closes")

        prompt = input_bar.value
        assert f"{first.id} v{first.revision}" in prompt
        assert f"{second.id} v{second.revision}" in prompt
        assert unselected.id not in prompt
        assert "slides" in prompt
        assert _REVIEW_PROMPT_TAIL in prompt
        assert _files(store) == before


async def test_review_together_without_selection_or_context_asks_first(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await _duplicate_pair(store)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        input_bar = app._main_screen.query_one(InputBar)
        before = _files(store)

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(
            lambda: screen.query_one("#memory-error", Static).display, pilot=pilot, description="selection hint"
        )
        assert "Select a memory, or choose a topic or search first." in _detail(screen, "#memory-error")
        assert app.screen is screen
        assert input_bar.value == ""
        assert not screen._marked
        assert _files(store) == before


async def test_review_together_with_a_topic_only_sends_the_context(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store, topics=(("slides",), ("slides",)))

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        screen.query_one("#memory-topic-filter", Select).value = "slides"
        await wait_for(lambda: len(_ids(screen)) == 2, pilot=pilot)
        input_bar = app._main_screen.query_one(InputBar)

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="topic handoff closes")

        prompt = input_bar.value
        assert "slides" in prompt and _REVIEW_PROMPT_TAIL in prompt
        assert first.id not in prompt and second.id not in prompt
        assert "Inspect these memories" not in prompt


async def test_review_together_with_a_search_only_context_sends_the_context(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store, topics=(("slides",), ("slides",)))

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert not str(screen.query_one("#memory-topic-filter", Select).value), "no topic context"
        screen.query_one("#memory-search", EnhancedInput).value = "density"
        await wait_for(lambda: len(_ids(screen)) == 2, pilot=pilot, description="search keeps the queue")
        input_bar = app._main_screen.query_one(InputBar)
        before = _files(store)

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="search handoff closes")

        prompt = input_bar.value
        assert "density" in prompt and _REVIEW_PROMPT_TAIL in prompt
        assert first.id not in prompt and second.id not in prompt
        assert "Inspect these memories" not in prompt
        assert not screen._marked
        assert _files(store) == before


async def test_a_pending_search_never_hands_off_a_selection_it_hid(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        await _mark_rows(pilot, screen, (listed.index(first.id), listed.index(second.id)))
        input_bar = app._main_screen.query_one(InputBar)
        before = _files(store)

        screen.query_one("#memory-search", EnhancedInput).value = "revised"
        await pilot.pause()
        assert screen._search_timer is not None, "the debounce must still be pending to exercise this window"
        assert set(screen._marked) == {first.id, second.id}, "the hidden row has not been pruned yet"

        screen._review_together()
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="handoff closes")

        prompt = input_bar.value
        assert f"{second.id} v{second.revision}" in prompt
        assert first.id not in prompt
        assert "revised" in prompt
        assert _files(store) == before


async def test_a_pending_search_hiding_the_queue_does_not_hand_off_its_context(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await _duplicate_pair(store)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        input_bar = app._main_screen.query_one(InputBar)
        before = _files(store)

        screen.query_one("#memory-search", EnhancedInput).value = "no such memory"
        await pilot.pause()
        assert screen._search_timer is not None, "the debounce must still be pending to exercise this window"
        assert screen._visible_count == 2, "the pending refresh has not emptied the queue yet"

        screen._review_together()
        await pilot.pause()

        assert app.screen is screen
        assert input_bar.value == ""
        empty = screen.query_one("#memory-empty")
        assert empty.display
        assert empty.label == "No memories need organizing with the current filters."
        assert not screen._marked
        assert _files(store) == before


async def test_empty_queue_keeps_the_panel_and_writes_nothing(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    await _save(store, MemoryDraft("Healthy", "Run the tests twice", "testing"))
    await _save(store, MemoryDraft("Plain suggestion", "Group logs by request id", "logs"), candidate=True)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert _ids(screen) == []
        empty = screen.query_one("#memory-empty")
        assert empty.display
        assert empty.label == "No memories need organizing."
        assert empty.label != "No memories in this view."
        input_bar = app._main_screen.query_one(InputBar)
        before = _files(store)

        await click_when_settled(pilot, "#memory-organize")
        await pilot.pause()
        assert app.screen is screen
        assert input_bar.value == ""
        assert _files(store) == before


async def test_filtered_empty_queue_uses_its_own_message(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await _duplicate_pair(store, topics=(("slides",), ("slides",)))
    await _save(
        store, MemoryDraft("Release checklist", "Follow the release checklist", "releases", topics=("release",))
    )

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        assert len(_ids(screen)) == 2
        empty = screen.query_one("#memory-empty")
        assert not empty.display

        screen.query_one("#memory-topic-filter", Select).value = "release"
        await wait_for(lambda: _ids(screen) == [], pilot=pilot, description="topic hides the queue")
        assert empty.display
        assert empty.label == "No memories need organizing with the current filters."
        assert "deleted" not in empty.label and "empty" not in empty.label.lower()

        screen.query_one("#memory-topic-filter", Select).value = ""
        await wait_for(
            lambda: len(_ids(screen)) == 2, pilot=pilot, description="clearing the filter restores the queue"
        )
        assert screen.query_one("#memory-empty").label == "No memories need organizing with the current filters."


async def test_an_unsendable_draft_keeps_the_panel_selection_and_composer(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, _second = await _duplicate_pair(store)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        await _mark_rows(pilot, screen, (listed.index(first.id),))
        input_bar = app._main_screen.query_one(InputBar)
        input_bar.value = "keep me"
        before = _files(store)

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(
            lambda: "Finish the current draft" in _detail(screen, "#memory-error"),
            pilot=pilot,
            description="draft hint",
        )
        assert app.screen is screen
        assert input_bar.value == "keep me"
        assert set(screen._marked) == {first.id}
        assert _files(store) == before


async def test_legacy_stale_entry_opens_the_same_queue_and_selects_the_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
    stale = await _stale(store, stale, tmp_path)
    condition = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
    await _skip_turns(store, condition, "margins")

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app, view="stale")
        assert screen.current_view == "organize"
        assert set(_ids(screen)) == {stale.id, condition.id}
        assert screen.query_one("#memory-title", Static).display

        await pilot.press("escape")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot)
        screen = await _open_panel(pilot, app, view="stale", memory_id=stale.id)
        assert screen.current_view == "organize"
        await wait_for(lambda: screen._selected_id == stale.id, pilot=pilot, description="requested memory selected")
        assert _detail(screen, "#memory-title") == stale.draft.title


async def test_one_review_queue_tab_and_candidates_keep_their_own_view(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
    stale = await _stale(store, stale, tmp_path)
    condition = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
    await _skip_turns(store, condition, "margins")
    active, candidate = await _duplicate_pair(store, candidate_second=True)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        assert set(listed) == {stale.id, condition.id, active.id, candidate.id}
        assert len(listed) == len(set(listed))

        tabs = screen.query_one("#memory-view", Tabs)
        tab_ids = [str(tab.id) for tab in tabs.query(Tab)]
        assert "memory-view-organize" in tab_ids
        assert "memory-view-stale" not in tab_ids
        assert tab_ids.count("memory-view-organize") == 1

        tabs.active = "memory-view-candidate"
        await wait_for(lambda: screen.current_view == "candidate", pilot=pilot)
        await wait_for(lambda: _ids(screen) == [candidate.id], pilot=pilot, description="candidate keeps its own view")

        for view in ("active", "archived", "recalled", "followups", "all"):
            tabs.active = f"memory-view-{view}"
            await wait_for(lambda expected=view: screen.current_view == expected, pilot=pilot)
            assert not (view != "all" and {stale.id, condition.id} <= set(_ids(screen)))


async def test_footer_review_badge_opens_the_queue_for_duplicates_only(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        main = app._main_screen
        main.chat_session_id = "one"
        indicator = main.query_one(PersonalMemoryIndicator)
        await wait_for(
            lambda: "Mem · Review" in rich_plain(indicator.render()), pilot=pilot, description="review badge"
        )
        before = _files(store)

        await click_when_settled(pilot, indicator)
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        assert screen.current_view == "organize"
        assert set(_ids(screen)) == {first.id, second.id}
        assert _files(store) == before


async def test_queue_labels_follow_the_active_language(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, _second = await _duplicate_pair(store, topics=(("slides",), ("slides",)))
    skipped = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
    await _skip_turns(store, skipped, "margins")
    await _save(
        store, MemoryDraft("Release checklist", "Follow the release checklist", "releases", topics=("release",))
    )

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        listed = _ids(screen)
        english = dict(zip(listed, _labels(screen), strict=True))
        assert "Similar content" in english[first.id]
        assert "Repeatedly not applicable" in english[skipped.id]
        assert str(screen.query_one("#memory-view-organize", Tab).label) == "To organize"

        app.locale_controller.switch_locale("zh-Hans")
        await wait_for(
            lambda: str(screen.query_one("#memory-view-organize", Tab).label) == "待整理",
            pilot=pilot,
            description="localized tab",
        )
        chinese = dict(zip(_ids(screen), _labels(screen), strict=True))
        assert "内容重复" in chinese[first.id]
        assert "多次不适用" in chinese[skipped.id]
        for english_label in ("Similar content", "Repeatedly not applicable", "Marked for review"):
            assert english_label not in chinese[first.id] + chinese[skipped.id]

        screen.query_one("#memory-topic-filter", Select).value = "release"
        await wait_for(lambda: _ids(screen) == [], pilot=pilot, description="topic hides the queue in Chinese")
        assert screen.query_one("#memory-empty").label == "没有符合当前筛选的待整理记忆。"
        screen.query_one("#memory-topic-filter", Select).value = ""
        await wait_for(lambda: len(_ids(screen)) == 3, pilot=pilot)

        await click_when_settled(pilot, "#memory-organize")
        await wait_for(
            lambda: "请先选择记忆" in _detail(screen, "#memory-error"), pilot=pilot, description="localized hint"
        )
        app.locale_controller.switch_locale("en")
        await wait_for(
            lambda: str(screen.query_one("#memory-view-organize", Tab).label) == "To organize",
            pilot=pilot,
            description="English restored",
        )
        assert "Similar content" in dict(zip(_ids(screen), _labels(screen), strict=True))[first.id]


async def test_browsing_filtering_selecting_and_handing_off_never_write_memory_files(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    first, second = await _duplicate_pair(store, topics=(("slides",), ("slides",)))
    skipped = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides", topics=("release",)))
    await _skip_turns(store, skipped, "margins")

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        screen = await _open_panel(pilot, app)
        await pilot.pause()
        before = _files(store)

        screen.query_one("#memory-list", OptionList).focus()
        await pilot.press("end", "home")
        screen.query_one("#memory-kind-filter", Select).value = "lesson"
        await wait_for(lambda: set(_ids(screen)) == {first.id, second.id, skipped.id}, pilot=pilot)
        screen.query_one("#memory-topic-filter", Select).value = "slides"
        await wait_for(lambda: set(_ids(screen)) == {first.id, second.id}, pilot=pilot)
        screen.query_one("#memory-topic-filter", Select).value = ""
        search = screen.query_one("#memory-search", EnhancedInput)
        search.value = "margins"
        await wait_for(lambda: _ids(screen) == [skipped.id], pilot=pilot)
        search.value = ""
        await wait_for(lambda: len(_ids(screen)) == 3, pilot=pilot)
        await _mark_rows(pilot, screen, (0,))
        await pilot.press("space")
        await wait_for(lambda: not screen._marked, pilot=pilot)
        await _mark_rows(pilot, screen, (0,))
        for view in ("active", "candidate", "all", "organize"):
            screen.query_one("#memory-view", Tabs).active = f"memory-view-{view}"
            await wait_for(lambda expected=view: screen.current_view == expected, pilot=pilot)
        await _mark_rows(pilot, screen, (0,))
        await click_when_settled(pilot, "#memory-organize")
        await wait_for(lambda: app.screen is app._main_screen, pilot=pilot, description="handoff closes")

        assert _files(store) == before


async def _source_changed_item(store: PersonalMemoryStore, name: str = "Checksum", *, topics: tuple[str, ...] = ()):
    source = await _save(store, MemoryDraft(f"{name} source", f"Write the {name} report", "release checks"))
    derived = await _save(
        store,
        MemoryDraft(
            f"{name} follow-up",
            f"Compare the {name} reports",
            "release checks",
            topics=topics,
            relations=(MemoryRelation(source.id, 1, "derived_from", "Comes from the report rule"),),
        ),
    )
    await _save(
        store,
        MemoryDraft(f"{name} source", f"Write the {name} report twice", "release checks"),
        memory_id=source.id,
        revision=1,
    )
    return derived, source


async def _weekly_scenario(tmp_path: Path, scenario: str) -> tuple[PersonalMemoryStore, set[str]]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    if scenario == "duplicate":
        first = await _save(
            store, MemoryDraft("Slides density", "Use  dense diagrams", "technical slides", topics=("slides",))
        )
        second = await _save(
            store,
            MemoryDraft("Slides density, second copy", "use dense diagrams", "technical slides", topics=("slides",)),
        )
        await _save(
            store, MemoryDraft("Slides review", "Review slides before sending", "technical slides", topics=("slides",))
        )
        expected = {first.id, second.id}
    elif scenario == "source":
        derived, _source = await _source_changed_item(store, topics=("release",))
        await _save(
            store, MemoryDraft("Release notes", "Write release notes early", "release checks", topics=("release",))
        )
        await _save(
            store, MemoryDraft("Release tags", "Tag releases after review", "release checks", topics=("release",))
        )
        expected = {derived.id}
    elif scenario == "condition":
        condition = await _save(store, MemoryDraft("Margins", "Widen the margins", "technical slides"))
        await _skip_turns(store, condition, "margins")
        expected = {condition.id}
    else:
        stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
        stale = await _stale(store, stale, tmp_path)
        expected = {stale.id}
    await asyncio.to_thread(store.set_buddy_notifications, True)
    state = await asyncio.to_thread(store.maintain, workspace=os.getcwd())
    assert state.review_notice is not None and state.review_notice.memory_ids
    return store, expected


async def _non_organizing_scenario(tmp_path: Path, scenario: str) -> tuple[PersonalMemoryStore, str]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    unrelated, _source = await _source_changed_item(store)
    if scenario == "candidate":
        candidate = await _save(store, MemoryDraft("Group logs", "Group logs by request id", "logs"), candidate=True)
        expected_view, expected_id = "candidate", candidate.id
    elif scenario == "topic":
        for index in range(3):
            await _save(
                store,
                MemoryDraft(
                    f"Release note {index}",
                    f"Write release note {index} before tagging",
                    "release checks",
                    topics=("release",),
                ),
            )
        expected_view, expected_id = "all", ""
    else:
        candidate = await _save(store, MemoryDraft("Group logs", "Group logs by request id", "logs"), candidate=True)
        _patch_entries(store, {candidate.id: {"created_at": "2024-01-01T00:00:00+00:00"}})
        expected_view, expected_id = "all", ""
    await asyncio.to_thread(store.set_buddy_notifications, True)
    state = await asyncio.to_thread(store.maintain, workspace=os.getcwd())
    assert state.review_notice is not None
    if scenario == "archived":
        assert state.review_notice.archived_candidates == 1
    return store, expected_view, expected_id, unrelated.id


async def _open_buddy(app):
    main = app._main_screen
    sidebar = main.query_one(SidebarPanel)
    if not sidebar.is_visible:
        sidebar.toggle()
    sidebar.focus_tab("tab-buddy")
    return sidebar.query_one(BuddyMemoryCard)


@pytest.mark.parametrize("scenario", ["duplicate", "source", "condition", "stale"])
async def test_buddy_weekly_review_opens_the_queue_when_a_member_needs_organizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setattr(buddy_module, "current_buddy", a_buddy)
    store, expected = await _weekly_scenario(tmp_path, scenario)
    before = await asyncio.to_thread(store.load)
    bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        main = app._main_screen
        main.chat_session_id = "one"
        card = await _open_buddy(app)
        await bus.publish(PersonalMemoryChanged(session_id="one", snapshot=before))
        await wait_for(lambda: card.query_one("#buddy-memory-review", Button).visible, pilot=pilot)

        await click_when_settled(pilot, card.query_one("#buddy-memory-review", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        assert screen.current_view == "organize"
        assert expected <= set(_ids(screen))

        await wait_for(
            lambda: screen.snapshot.review_notice is None, pilot=pilot, description="the weekly notice was dismissed"
        )
        state = await asyncio.to_thread(store.load)
        assert state.entries == before.entries
        assert state.activity == before.activity


@pytest.mark.parametrize("scenario", ["candidate", "topic", "archived"])
async def test_buddy_weekly_review_keeps_its_target_when_members_need_no_organizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setattr(buddy_module, "current_buddy", a_buddy)
    store, expected_view, expected_id, unrelated_id = await _non_organizing_scenario(tmp_path, scenario)
    before = await asyncio.to_thread(store.load)
    bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        main = app._main_screen
        main.chat_session_id = "one"
        card = await _open_buddy(app)
        await bus.publish(PersonalMemoryChanged(session_id="one", snapshot=before))
        await wait_for(lambda: card.query_one("#buddy-memory-review", Button).visible, pilot=pilot)

        await click_when_settled(pilot, card.query_one("#buddy-memory-review", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert isinstance(screen, PersonalMemoryScreen)
        assert screen.current_view == expected_view
        if expected_id:
            assert expected_id in _ids(screen)
        assert unrelated_id not in _ids(screen) or screen.current_view == "all"

        await wait_for(
            lambda: screen.snapshot.review_notice is None, pilot=pilot, description="the weekly notice was dismissed"
        )
        state = await asyncio.to_thread(store.load)
        assert state.entries == before.entries


async def test_ordinary_entries_never_reroute_to_the_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buddy_module, "current_buddy", a_buddy)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    await asyncio.to_thread(store.configure, "auto", True)
    for index in range(3):
        await _save(
            store,
            MemoryDraft(
                f"Release note {index}",
                f"Write release note {index} before tagging",
                "release checks",
                topics=("release",),
            ),
        )
    unrelated, _source = await _source_changed_item(store)
    candidate = await _save(store, MemoryDraft("Group logs", "Group logs by request id", "logs"), candidate=True)
    other_candidate = await _save(store, MemoryDraft("Rotate logs", "Rotate the logs daily", "logs"), candidate=True)
    recalled = await _save(store, MemoryDraft("Release recall", "Recall the release checklist", "release checks"))
    await asyncio.to_thread(store.set_buddy_notifications, True)
    await asyncio.to_thread(store.maintain, workspace=os.getcwd())
    await asyncio.to_thread(store.dismiss_review)
    await asyncio.to_thread(store.recall, "release recall", "", session_id="one")
    state = await asyncio.to_thread(store.load)
    assert state.review_notice is None and state.last_review_at

    bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(140, 48)) as pilot:
        main = app._main_screen
        main.chat_session_id = "one"
        card = await _open_buddy(app)
        indicator = main.query_one(PersonalMemoryIndicator)
        await bus.publish(PersonalMemoryChanged(session_id="one", snapshot=state))
        await wait_for(lambda: "1 sent" in rich_plain(indicator.render()), pilot=pilot, description="recall badge")
        assert not card.query_one("#buddy-memory-review", Button).visible
        before = await asyncio.to_thread(store.load)

        await click_when_settled(pilot, card.query_one("#buddy-memory-library", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        assert app.screen.current_view == "active"
        assert recalled.id in _ids(app.screen)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is main, pilot=pilot)

        await click_when_settled(pilot, card.query_one("#buddy-memory-counts", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        assert app.screen.current_view == "recalled"
        assert recalled.id in _ids(app.screen)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is main, pilot=pilot)

        await click_when_settled(pilot, card.query_one("#buddy-memory-item", Button))
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert screen.current_view == "recalled"
        await wait_for(lambda: screen._selected_id == recalled.id, pilot=pilot)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is main, pilot=pilot)

        await click_when_settled(pilot, indicator)
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert screen.current_view == "recalled"
        tabs = screen.query_one("#memory-view", Tabs)
        tabs.active = "memory-view-active"
        await wait_for(lambda: screen.current_view == "active", pilot=pilot)
        await wait_for(lambda: recalled.id in _ids(screen), pilot=pilot, description="saved view lists the memory")
        tabs.active = "memory-view-all"
        await wait_for(
            lambda: {unrelated.id, candidate.id, other_candidate.id, recalled.id} <= set(_ids(screen)),
            pilot=pilot,
            description="all view lists every memory",
        )
        tabs.active = "memory-view-candidate"
        await wait_for(
            lambda: set(_ids(screen)) == {candidate.id, other_candidate.id},
            pilot=pilot,
            description="review keeps its candidates",
        )
        tabs.active = "memory-view-organize"
        await wait_for(lambda: screen.current_view == "organize", pilot=pilot)
        await wait_for(lambda: unrelated.id in _ids(screen), pilot=pilot, description="the whole queue is listed again")
        assert candidate.id not in _ids(screen)
        after_browsing = await asyncio.to_thread(store.load)
        assert after_browsing.entries == before.entries
        assert after_browsing.activity == before.activity

        # Candidates keep their own accept/skip actions; only the browsing above must write nothing.
        tabs.active = "memory-view-candidate"
        await wait_for(lambda: set(_ids(screen)) == {candidate.id, other_candidate.id}, pilot=pilot)
        review_rows = _ids(screen)
        accepted, skipped = review_rows
        options = screen.query_one("#memory-list", OptionList)
        options.focus()
        await pilot.press("home")
        await wait_for(lambda: screen._selected_id == accepted, pilot=pilot)
        await click_when_settled(pilot, "#memory-accept")
        await wait_for(
            lambda: next(entry for entry in screen.snapshot.entries if entry.id == accepted).state == "active",
            pilot=pilot,
            description="a candidate is still accepted from the review view",
        )
        await wait_for(lambda: _ids(screen) == [skipped], pilot=pilot)
        await pilot.press("home")
        await wait_for(lambda: screen._selected_id == skipped, pilot=pilot)
        await click_when_settled(pilot, "#memory-archive")
        await wait_for(
            lambda: next(entry for entry in screen.snapshot.entries if entry.id == skipped).state == "archived",
            pilot=pilot,
            description="a candidate is still skipped from the review view",
        )


async def test_off_or_failed_footer_keeps_its_browsing_target_with_a_stale_memory(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    stale = await _save(store, MemoryDraft("Old renderer", "Prefer the classic renderer", "rendering"))
    await _stale(store, stale, tmp_path)
    await asyncio.to_thread(store.configure, "off", False)
    state = await asyncio.to_thread(store.load)

    _bus, app = await _mount_memory_app(tmp_path, store)
    async with app.run_test(size=(120, 44)) as pilot:
        main = app._main_screen
        main.chat_session_id = "one"
        indicator = main.query_one(PersonalMemoryIndicator)
        await _bus.publish(PersonalMemoryChanged(session_id="one", snapshot=state))
        await wait_for(lambda: "Mem · Off" in rich_plain(indicator.render()), pilot=pilot, description="off badge")

        await click_when_settled(pilot, indicator)
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        assert app.screen.current_view == "active"
        assert _ids(app.screen) == []
        await pilot.press("escape")
        await wait_for(lambda: app.screen is main, pilot=pilot)

        await _bus.publish(
            PersonalMemoryChanged(session_id="one", error_code="memory_unavailable", error="Read failed")
        )
        await wait_for(lambda: "Mem · Unavailable" in rich_plain(indicator.render()), pilot=pilot, description="failed")
        await click_when_settled(pilot, indicator)
        await wait_for(lambda: isinstance(app.screen, PersonalMemoryScreen) and app.screen.is_mounted and app.screen._loaded, pilot=pilot)
        screen = app.screen
        assert screen.current_view == "active"
        screen.query_one("#memory-view", Tabs).active = "memory-view-organize"
        await wait_for(
            lambda: screen.current_view == "organize" and stale.id in _ids(screen),
            pilot=pilot,
            description="the stale memory was queued but the footer did not open it",
        )
        after = await asyncio.to_thread(store.load)
        assert after.entries == state.entries
        assert after.activity == state.activity
