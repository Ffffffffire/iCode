# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""TUI memory library, source review and current-task recall through the event bus."""

from __future__ import annotations

import os
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from rich.style import Style
from rich.text import Text
from textual import on, work
from textual.containers import Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Collapsible, OptionList, Select, Static, Tab, Tabs
from textual.widgets.option_list import Option

from chrys.app.tui.binding_display import CLOSE_BINDING, DELETE_BINDING, localized_binding
from chrys.app.tui.i18n import render_str
from chrys.app.tui.personal_memory_messages import RECALL_TIP
from chrys.app.tui.screens.dialogs.base import BaseDialog
from chrys.app.tui.screens.dialogs.confirm import ConfirmDialog
from chrys.app.tui.widgets import EnhancedInput, HatchedEmptyState
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.i18n import MessageDef, MessageRef
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_block, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import (
    MemoryActivity,
    MemoryDraft,
    MemoryMode,
    MemorySnapshot,
    PersonalMemory,
)
from chrys.service.personal_memory.activity import recent_usage
from chrys.service.personal_memory.organize import OrganizeItem, OrganizeQueue, OrganizeReason
from chrys.service.personal_memory.retrieval import MemoryRetriever
from chrys.service.personal_memory.store import MAX_BATCH, PersonalMemoryStore

from . import messages as m
from .editor import PersonalMemoryEditor
from .presentation import format_memory_time

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult
    from textual.timer import Timer

    from chrys.app.tui.i18n import LocaleController


class _MemoryUpdate(Message):
    def __init__(self, event: PersonalMemoryChanged) -> None:
        super().__init__()
        self.event = event


# The former review-required view is the same queue under its new name.
_VIEW_ALIASES = {"stale": "organize"}

_REASON_LABELS = {
    OrganizeReason.DUPLICATE: m.ORGANIZE_REASON_DUPLICATE,
    OrganizeReason.SOURCE_CHANGED: m.ORGANIZE_REASON_SOURCE,
    OrganizeReason.REPEATED_SKIPS: m.ORGANIZE_REASON_SKIPS,
    OrganizeReason.NEEDS_REVIEW: m.ORGANIZE_REASON_REVIEW,
}


def _normalize_view(view: str) -> str:
    return _VIEW_ALIASES.get(view, view)


class _MemorySearchInput(EnhancedInput):
    """Let the panel clear search and return focus before dismissing, as Sessions does."""

    class Escaped(Message):
        pass

    def _on_key(self, event: Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Escaped())


class PersonalMemoryScreen(BaseDialog[None]):
    CSS_PATH = "screen.tcss"
    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "memory--candidate",
        "memory--stale",
        "memory--archived",
        "memory--marked",
        "memory--muted",
        "memory--warning",
    }
    BINDINGS: ClassVar[list] = [
        localized_binding("escape", "escape", CLOSE_BINDING),
        localized_binding("delete", "forget_selected", DELETE_BINDING),
        localized_binding("ctrl+n", "new", m.NEW, show=False),
        localized_binding("ctrl+r", "reload", m.REFRESH, show=False),
        localized_binding("ctrl+f", "search", m.SEARCH, show=False),
    ]

    def __init__(
        self,
        *,
        bus: EventBus,
        workspace: str,
        session_id: str,
        locale_controller: LocaleController | None = None,
        initial_view: str = "",
        memory_id: str = "",
        continue_follow_up: Callable[[str], bool] | None = None,
    ):
        super().__init__()
        self._bus = bus
        self._workspace = workspace
        self._session_id = session_id
        self._locale_controller = locale_controller
        self._initial_view = _normalize_view(initial_view)
        self._continue_follow_up = continue_follow_up
        self.snapshot = MemorySnapshot()
        self._selected_id = memory_id
        self._organize_queue = OrganizeQueue(self.snapshot)
        self._organize: dict[str, OrganizeItem] = {}
        self._organize_in_scope = False
        self._visible_count = 0
        self._updating = False
        self._loaded = False
        self._shown_id = ""
        self._pending: set[str] = set()
        self._replies: dict[str, PersonalMemoryChanged] = {}
        self.last_error = ""
        self._used_bytes = 0
        self._marked: dict[str, int] = {}
        self._history_page: tuple[MemoryActivity, ...] | None = None
        self._browser = MemoryRetriever()
        self._search_timer: Timer | None = None
        self._list_rows: tuple[tuple[str, Text], ...] | None = None
        self._painted_selection = ""
        self._mutating = False
        self._reading = False
        self._last_mutation_reply_at = 0.0
        self._revision_for: tuple[str, int] | None = None
        self._revision_rows = ()
        self._revision_more = True

    def _text(self, message: MessageDef | MessageRef) -> str:
        ref = message.bind() if isinstance(message, MessageDef) else message
        return render_str(self._locale_controller.localizer, ref) if self._locale_controller else format_message(ref)

    def compose(self) -> ComposeResult:
        with Vertical(id="personal-memory") as frame:
            frame.border_title = Text(self._text(m.TITLE))
            with HorizontalGroup(id="memory-toolbar"):
                yield _MemorySearchInput(placeholder=self._text(m.SEARCH), id="memory-search")
                yield Button(Text(self._text(m.NEW)), id="memory-new", variant="primary", disabled=True)
                yield Button(Text(self._text(m.ORGANIZE)), id="memory-organize")
            yield Static("", id="memory-capacity", markup=False)
            yield Tabs(
                *(Tab(label, id=f"memory-view-{value}") for label, value in self._view_options()),
                active=f"memory-view-{self._initial_view or 'active'}",
                id="memory-view",
            )
            with HorizontalGroup(id="memory-filters"):
                yield Select(self._kind_options(), value="all", allow_blank=False, id="memory-kind-filter")
                yield Select(self._scope_options(), value="current", allow_blank=False, id="memory-scope-filter")
                yield Select([(self._text(m.ALL_TOPICS), "")], value="", allow_blank=False, id="memory-topic-filter")
            with Horizontal(id="memory-body"):
                with Vertical(id="memory-index"):
                    with HorizontalGroup(id="memory-selection"):
                        yield Button(Text(self._text(m.MARK)), id="memory-mark")
                        yield Static("", id="memory-selected", markup=False)
                    memory_list = OptionList(id="memory-list")
                    memory_list.tooltip = self._text(m.KEYBOARD_HINT)
                    yield memory_list
                with VerticalScroll(id="memory-detail"):
                    yield Static("", id="memory-title", markup=False)
                    yield Static("", id="memory-meta", markup=False)
                    yield Static("", id="memory-usage", markup=False)
                    yield HatchedEmptyState(self._text(m.EMPTY), id="memory-empty")
                    yield Static("", id="memory-content", classes="memory-card", markup=False)
                    yield Static("", id="memory-replacement", markup=False)
                    yield Static("", id="memory-organize-reasons", classes="memory-card", markup=False)
                    for section in ("when", "reconsider"):
                        card = Static("", id=f"memory-{section}", classes="memory-card", markup=False)
                        if section == "reconsider":
                            card.tooltip = self._text(m.RECONSIDER_TIP)
                        yield card
                    yield Static("", id="memory-follow-up", classes="memory-card", markup=False)
                    with HorizontalGroup(id="memory-follow-actions"):
                        yield Button(Text(self._text(m.CONTINUE)), id="memory-continue", variant="primary")
                        yield Button(Text(self._text(m.COMPLETE)), id="memory-complete")
                    with HorizontalGroup(id="memory-feedback-actions"):
                        yield Button(Text(self._text(m.NOT_APPLICABLE)), id="memory-not-applicable")
                        yield Button(Text(self._text(m.HELPFUL)), id="memory-helpful")
                        yield Button(
                            Text(self._text(m.INCORRECT)), id="memory-incorrect", tooltip=self._text(m.INCORRECT_TIP)
                        )
                    with Collapsible(title=self._text(m.RELATED), collapsed=True, id="memory-relations"):
                        yield OptionList(id="memory-relations-list")
                        yield Static("", id="memory-relations-text", markup=False)
                    with Collapsible(title=self._text(m.SOURCE), collapsed=True, id="memory-evidence"):
                        yield Static("", id="memory-source", markup=False)
                    with Collapsible(title=self._text(m.RECALL_DETAILS), collapsed=True, id="memory-recall-details"):
                        yield Static(Text(self._text(RECALL_TIP)), id="memory-recall-tip", markup=False)
                        yield Static("", id="memory-recall-query", markup=False)
                        yield Static("", id="memory-match", markup=False)
                    with Collapsible(title=self._text(m.HISTORY), collapsed=True, id="memory-history"):
                        yield Static("", id="memory-history-text", markup=False)
                        yield Button(Text(self._text(m.OLDER_REVISIONS)), id="memory-history-more")
                    with Collapsible(title=self._text(m.ACTIVITY), collapsed=True, id="memory-entry-activity"):
                        yield Static("", id="memory-entry-activity-text", markup=False)
            with VerticalScroll(id="memory-activity"):
                yield Static("", id="memory-activity-text", markup=False)
            with HorizontalGroup(id="memory-history-actions"):
                yield Button(Text(self._text(m.OLDER_ACTIVITY)), id="memory-older")
                yield Button(Text(self._text(m.LATEST_ACTIVITY)), id="memory-latest")
            with HorizontalGroup(id="memory-settings"):
                yield Select(
                    self._mode_options(),
                    value="auto",
                    allow_blank=False,
                    id="memory-mode",
                    tooltip=self._text(m.MODE_TIP),
                    disabled=True,
                )
                yield Select(
                    self._capture_options(),
                    value="explicit",
                    allow_blank=False,
                    id="memory-capture",
                    tooltip=self._text(m.CAPTURE_TIP),
                    disabled=True,
                )
            yield Static("", id="memory-error", markup=False)
            with HorizontalGroup(id="memory-actions"):
                for action, label in (
                    ("accept", m.ACCEPT),
                    ("edit", m.EDIT),
                    ("archive", m.ARCHIVE),
                    ("forget", m.FORGET),
                ):
                    yield Button(
                        Text(self._text(label)),
                        id=f"memory-{action}",
                        variant="primary" if action == "accept" else "default",
                    )
                yield Static("", id="memory-action-spacer")
                yield Button(Text(self._text(m.CLOSE)), id="memory-close")

    def _mode_options(self) -> list[tuple[str, str]]:
        return [(self._text(label), value) for value, label in (("auto", m.AUTO), ("manual", m.MANUAL), ("off", m.OFF))]

    def _kind_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (
                ("all", m.TYPES),
                ("preference", m.PREFERENCE),
                ("decision", m.DECISION),
                ("lesson", m.LESSON),
                ("intention", m.INTENTION),
            )
        ]

    def _scope_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (
                ("current", m.SCOPES),
                ("personal", m.PERSONAL),
                ("project", m.PROJECT),
                ("all", m.ALL_SCOPES),
            )
        ]

    def _capture_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (("explicit", m.CAPTURE_EXPLICIT), ("review", m.CAPTURE), ("auto", m.CAPTURE_AUTO))
        ]

    def _capture_value(self) -> str:
        return "explicit" if not self.snapshot.capture else ("auto" if self.snapshot.auto_save else "review")

    def _view_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (
                ("active", m.ACTIVE),
                ("candidate", m.CANDIDATE),
                ("organize", m.ORGANIZE_VIEW),
                ("recalled", m.RECALLED),
                ("followups", m.FOLLOW_UPS),
                ("activity", m.ACTIVITY),
                ("archived", m.ARCHIVED),
                ("all", m.ALL),
            )
        ]

    async def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._theme_changed)
        if self._locale_controller:
            self._locale_controller.register_surface(self)
        await self._bus.subscribe(PersonalMemoryChanged, self._receive)
        self._request_read(PersonalMemoryCommand())

    @property
    def current_view(self) -> str:
        return self.query_one("#memory-view", Tabs).active.removeprefix("memory-view-")

    async def on_unmount(self) -> None:
        self.app.theme_changed_signal.unsubscribe(self)
        if self._search_timer is not None:
            self._search_timer.stop()
        await self._bus.unsubscribe(PersonalMemoryChanged, self._receive)
        if self._locale_controller:
            self._locale_controller.unregister_surface(self)

    async def _receive(self, event: PersonalMemoryChanged) -> None:
        if not event.session_id or event.session_id == self._session_id:
            if event.request_id in self._pending:
                self._replies[event.request_id] = event
            else:
                self.post_message(_MemoryUpdate(event))

    def _request_read(self, command: PersonalMemoryCommand) -> None:
        # Keep one read in flight: repeating a click must not queue filesystem work.
        if self._reading or self._mutating:
            return
        self._reading = True
        self._sync_read_controls()
        self._read_memory(command)

    @work(exclusive=True, group="memory-read")
    async def _read_memory(self, command: PersonalMemoryCommand) -> None:
        try:
            reply = await self._send(command)
            if command.action == "history" and not reply.error and self._composed_live:
                self.query_one("#memory-activity", VerticalScroll).scroll_home(animate=False)
            if command.action == "revisions" and reply.revisions is not None and self._composed_live:
                entry = self._selected()
                if entry and (entry.id, entry.revision) == (command.memory_id, command.revision):
                    rows = {r.revision: r for r in (*self._revision_rows, *reply.revisions)}
                    self._revision_rows = tuple(rows[v] for v in sorted(rows, reverse=True))
                    self._revision_more = len(reply.revisions) == 20
                    self._show_detail()
        finally:
            self._reading = False
            if self._composed_live:
                self._sync_read_controls()

    def _sync_read_controls(self) -> None:
        page = self._history_page if self._history_page is not None else self.snapshot.activity
        self.query_one("#memory-older", Button).disabled = self._reading or not page or page[0].sequence <= 1
        self.query_one("#memory-latest", Button).disabled = self._reading or not self._loaded
        self.query_one("#memory-activity").loading = self._reading
        self.query_one("#memory-history-more", Button).disabled = self._reading or not self._revision_more

    async def _send(self, command: PersonalMemoryCommand) -> PersonalMemoryChanged:
        mutation = command.action not in ("load", "history", "revisions")
        if mutation and self._mutating:
            return PersonalMemoryChanged(error="A memory operation is already in progress.")
        if mutation:
            self._set_mutating(True)
        command.session_id = self._session_id
        self._pending.add(command.event_id)
        try:
            await self._bus.publish(command)
            reply = self._replies.pop(command.event_id, None)
            if reply is None:
                reply = PersonalMemoryChanged(error="The memory service did not respond.")
            # Apply the reply before accepting another queued click with old revisions.
            update = _MemoryUpdate(reply)
            if mutation:
                self._last_mutation_reply_at = update.time
            self.on__memory_update(update)
            return reply
        finally:
            self._pending.discard(command.event_id)
            if mutation:
                self._set_mutating(False)

    def _set_mutating(self, busy: bool) -> None:
        self._mutating = busy
        if self._composed_live:
            for name in ("actions", "selection", "settings", "follow-actions", "feedback-actions"):
                self.query_one(f"#memory-{name}").disabled = busy
            for name in ("accept", "archive", "forget", "edit"):
                self.query_one(f"#memory-{name}", Button).disabled = busy
            self.query_one("#memory-new", Button).disabled = busy or not self._loaded

    def on__memory_update(self, message: _MemoryUpdate) -> None:
        if not self._composed_live:
            return
        event = message.event
        self.last_error = event.error
        error_widget = self.query_one("#memory-error", Static)
        error_widget.update(Text("⚠ " + self._text(m.failure_message(event.error_code)) if event.error else ""))
        error_widget.display = bool(event.error)
        error_widget.tooltip = Text(sanitize_legacy_scalar(event.error)) if event.error else None
        if event.snapshot is not None and event.snapshot.generation >= self.snapshot.generation:
            first_load = not self._loaded
            if {e.id for e in self.snapshot.entries} - {e.id for e in event.snapshot.entries}:
                # Never retain a page which may contain forgotten content or links.
                self._history_page = None
            self.snapshot = event.snapshot
            self._used_bytes = event.used_bytes
            if event.history is not None:
                self._history_page = event.history
            self._updating = True
            with self.prevent(Select.Changed):
                self.query_one("#memory-mode", Select).value = self.snapshot.mode
                self.query_one("#memory-capture", Select).value = self._capture_value()
            self._updating = False
            if (
                not self._loaded
                and not self._initial_view
                and any(entry.state == "candidate" and self._in_workspace(entry) for entry in self.snapshot.entries)
            ):
                self.query_one("#memory-view", Tabs).active = "memory-view-candidate"
            self._loaded = True
            self._refresh_topics()
            self.query_one("#memory-new", Button).disabled = False
            self.query_one("#memory-mode", Select).disabled = False
            self.query_one("#memory-capture", Select).disabled = False
            self._refresh_list()
            if first_load:
                self._focus_results()

    def _refresh_topics(self) -> None:
        topics = sorted({topic for entry in self.snapshot.entries for topic in entry.draft.topics})
        selector = self.query_one("#memory-topic-filter", Select)
        selected = selector.value
        with self.prevent(Select.Changed):
            selector.set_options(
                [(self._text(m.ALL_TOPICS), ""), *((Text(sanitize_legacy_scalar(t)), t) for t in topics)]
            )
            selector.value = selected if selected in topics else ""
            selector.mutate_reactive(Select.value)

    def _selected(self) -> PersonalMemory | None:
        return next((entry for entry in self.snapshot.entries if entry.id == self._selected_id), None)

    def _in_workspace(self, entry: PersonalMemory) -> bool:
        return not entry.draft.workspace or entry.draft.workspace == os.path.normcase(os.path.abspath(self._workspace))

    def _matches_scope(self, entry: PersonalMemory, scope: str) -> bool:
        if scope == "all":
            return True
        if scope == "personal":
            return not entry.draft.workspace
        if scope == "project":
            return bool(entry.draft.workspace) and self._in_workspace(entry)
        return self._in_workspace(entry)

    def _theme_changed(self, _theme: object) -> None:
        if self._loaded:
            self.call_after_refresh(self._refresh_list)

    def _button_label(self, name: str, definition: MessageDef) -> None:
        button = self.query_one(f"#memory-{name}", Button)
        text = self._text(definition)
        if str(button.label) != text:
            button.label = Text(text)
            button.refresh(layout=True)

    def _foreground_style(self, component: str) -> Style:
        # Resolve theme alpha, but leave each row/tab's own selection background intact.
        resolved = self.get_component_rich_style(component)
        return Style(color=resolved.color, bold=resolved.bold, italic=resolved.italic)

    def _row_label(self, entry: PersonalMemory, organize: bool = False) -> Text:
        label = Text()
        prefix = "☑ " if entry.id in self._marked else "☐ " if self._marked else "  "
        label.append(prefix, self._foreground_style("memory--marked"))
        label.append(sanitize_legacy_scalar(entry.draft.title), "bold italic" if entry.state == "archived" else "bold")
        state = {"active": m.ACTIVE, "candidate": m.CANDIDATE, "archived": m.ARCHIVED, "stale": m.REVIEW_REQUIRED}[
            entry.state
        ]
        scope = (
            Path(entry.draft.workspace).name or self._text(m.SCOPE_PROJECT)
            if entry.draft.workspace
            else self._text(m.SCOPE_PERSONAL)
        )
        style = self._foreground_style(f"memory--{entry.state}" if entry.state != "active" else "memory--muted")
        label.append("\n  " + self._text(state), style)
        label.append(
            f" · {sanitize_legacy_scalar(scope)} · v{entry.revision} · {format_memory_time(entry.updated_at, self._text)}",
            self._foreground_style("memory--muted"),
        )
        item = self._organize.get(entry.id) if organize else None
        if item is not None:
            reasons = " · ".join(self._text(_REASON_LABELS[reason]) for reason in item.reasons)
            label.append("\n  " + reasons, self._foreground_style("memory--warning"))
        return label

    def _refresh_list(self) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        view = self.current_view
        query = self.query_one("#memory-search", EnhancedInput).value.casefold().strip()
        recall = next((item for item in reversed(self.snapshot.recalls) if item.session_id == self._session_id), None)
        recalled_ids = {match.memory_id for match in recall.matches} if recall else set()
        kind = self.query_one("#memory-kind-filter", Select).value
        scope = str(self.query_one("#memory-scope-filter", Select).value)
        topic = self.query_one("#memory-topic-filter", Select).value
        self._organize_queue = OrganizeQueue(self.snapshot)
        self._organize = {item.memory_id: item for item in self._organize_queue.items()}
        self._organize_in_scope = any(
            entry.id in self._organize for entry in self.snapshot.entries if self._matches_scope(entry, scope)
        )
        matches = self._browser.browse(self.snapshot.entries, query) if query else ()
        ranks = {match.memory_id: index for index, match in enumerate(matches)}
        filtered = [
            entry
            for entry in reversed(self.snapshot.entries)
            if (
                self._matches_scope(entry, scope)
                and (kind == "all" or entry.draft.kind == kind)
                and (not topic or topic in entry.draft.topics)
                and (
                    not query
                    or entry.id in ranks
                    or query
                    in f"{entry.draft.title} {entry.draft.content} {entry.draft.when_to_use} {' '.join((*entry.draft.topics, *entry.draft.aliases))}".casefold()
                )
            )
        ]
        entries = [
            entry
            for entry in filtered
            if (
                entry.id in recalled_ids
                if view == "recalled"
                else entry.draft.follow_up is not None and entry.state == "active"
                if view == "followups"
                else entry.id in self._organize
                if view == "organize"
                else view in ("all", "activity") or entry.state == view
            )
        ]
        self._visible_count = len(entries) if view == "organize" else 0
        if query:
            entries.sort(key=lambda entry: ranks.get(entry.id, len(ranks)))
        elif view == "candidate":
            entries.sort(key=lambda entry: entry.source.role != "user")
        visible_revisions = {entry.id: entry.revision for entry in entries}
        self._marked = {
            mid: revision for mid, revision in self._marked.items() if visible_revisions.get(mid) == revision
        }
        self.query_one("#memory-selected", Static).update(
            Text(self._text(m.SELECTED.bind(count=len(self._marked))) if self._marked else self._text(m.MARK_HINT))
        )
        self._button_label("mark", m.DESELECT if self._marked else m.MARK)
        capacity = self._text(
            m.CAPACITY.bind(
                count=len(self.snapshot.entries),
                used=f"{self._used_bytes / 1024**2:.1f}",
            )
        )
        queue = self._organize_queue
        warning = queue.needs_review
        capacity_widget = self.query_one("#memory-capacity", Static)
        capacity_text = Text(capacity)
        if warning:
            capacity_text.append(
                " · " + self._text(m.HEALTH_REVIEW.bind(stale=queue.review_count, duplicates=queue.duplicate_count)),
                self._foreground_style("memory--warning"),
            )
        capacity_widget.update(capacity_text)
        capacity_widget.tooltip = Text(self._text(m.CAPACITY_WARNING)) if warning else None
        options = self.query_one("#memory-list", OptionList)
        rows = tuple((entry.id, self._row_label(entry, view == "organize")) for entry in entries)
        if rows != self._list_rows:
            self._list_rows = rows
            with options.prevent(OptionList.OptionHighlighted):
                options.clear_options()
                options.add_options([Option(label, id=memory_id) for memory_id, label in rows])
        if self._selected_id not in {entry.id for entry in entries}:
            self._selected_id = entries[0].id if entries else ""
        options.highlighted = next(
            (index for index, entry in enumerate(entries) if entry.id == self._selected_id), None
        )
        self._paint_selection()
        counts = {
            "candidate": sum(entry.state == "candidate" for entry in filtered),
            "recalled": sum(entry.id in recalled_ids for entry in filtered),
            "followups": sum(entry.state == "active" and entry.draft.follow_up is not None for entry in filtered),
        }
        for name, definition in (("candidate", m.CANDIDATE), ("recalled", m.RECALLED), ("followups", m.FOLLOW_UPS)):
            label = Text(self._text(definition))
            label.append(f" {counts[name]}", self._foreground_style("memory--muted"))
            self.query_one(f"#memory-view-{name}", Tab).label = label
        self._show_detail()
        self.query_one("#memory-index").display = bool(entries)
        self.query_one("#memory-body").display = view != "activity"
        self.query_one("#memory-activity").display = view == "activity"
        self.query_one("#memory-history-actions").display = view == "activity"
        self.query_one("#memory-mark", Button).disabled = not entries
        if view == "activity":
            self.query_one("#memory-activity-text", Static).update(
                self._activity_text(
                    {e.id for e in entries},
                    include_global=kind == "all" and not topic and not query,
                    events=self._history_page,
                )
            )
            for name in ("edit", "accept", "archive", "forget"):
                self.query_one(f"#memory-{name}").display = False
        self._sync_read_controls()
        query_view = self.query_one("#memory-recall-query", Static)
        query_view.update(Text(sanitize_legacy_scalar(recall.query if recall else "")))

    def _show_detail(self) -> None:
        entry = self._selected()
        empty = self.query_one("#memory-empty", HatchedEmptyState)
        empty.display = entry is None
        if self.current_view == "organize":
            empty.update_label(self._text(m.ORGANIZE_EMPTY_FILTERED if self._organize_in_scope else m.ORGANIZE_EMPTY))
        else:
            empty.update_label(self._text(m.NO_RECALL if self.current_view == "recalled" else m.EMPTY))
        for name in (
            "title",
            "meta",
            "content",
            "replacement",
            "organize-reasons",
            "usage",
            "when",
            "reconsider",
            "evidence",
            "history",
            "recall-details",
            "relations",
            "entry-activity",
            "follow-up",
            "follow-actions",
            "feedback-actions",
        ):
            self.query_one(f"#memory-{name}").display = entry is not None
        for name in ("edit", "accept", "archive", "forget"):
            self.query_one(f"#memory-{name}", Button).display = entry is not None
        if entry is None:
            self.query_one("#memory-title", Static).update("")
            for name in ("meta", "match", "content", "replacement", "organize-reasons", "usage"):
                self.query_one(f"#memory-{name}", Static).update("")
            self._shown_id = ""
            return
        condition_review = entry.id in self._organize_queue.condition_ids
        self.query_one("#memory-accept", Button).display = entry.state != "active" or condition_review
        self._button_label(
            "accept", m.CONFIRM_CONDITIONS if condition_review else m.RESTORE if entry.state == "archived" else m.ACCEPT
        )
        self.query_one("#memory-archive", Button).display = entry.state != "archived"
        self._button_label("archive", m.IGNORE if entry.state == "candidate" else m.ARCHIVE)
        self.query_one("#memory-forget", Button).display = entry.state != "candidate"
        if self._marked:
            self.query_one("#memory-edit").display = False
            for name in ("accept", "archive", "forget"):
                self.query_one(f"#memory-{name}").display = True
        if self._shown_id != entry.id:
            self.query_one("#memory-evidence", Collapsible).collapsed = entry.state != "candidate"
            self.query_one("#memory-recall-details", Collapsible).collapsed = True
            self.query_one("#memory-history", Collapsible).collapsed = True
            self.query_one("#memory-detail", VerticalScroll).scroll_home(animate=False)
            self._shown_id = entry.id
        draft = entry.draft
        follow = draft.follow_up
        self.query_one("#memory-follow-up").display = follow is not None
        self.query_one("#memory-follow-actions").display = (
            follow is not None and entry.state == "active" and follow.status not in ("completed", "cancelled")
        )
        if follow:
            status = {
                "pending": m.PENDING,
                "in_progress": m.IN_PROGRESS,
                "waiting": m.WAITING,
                "snoozed": m.SNOOZED,
                "completed": m.COMPLETED,
                "cancelled": m.CANCELLED,
            }[follow.status]
            self.query_one("#memory-follow-up", Static).update(
                Text(
                    sanitize_legacy_block(
                        "\n".join(
                            filter(
                                None,
                                (
                                    self._text(status),
                                    follow.next_step,
                                    format_memory_time(follow.remind_at, self._text),
                                ),
                            )
                        )
                    )
                )
            )
        self.query_one("#memory-relations").display = bool(draft.relations)
        relations = []
        relation_options = []
        for relation in draft.relations:
            target = next((e for e in self.snapshot.entries if e.id == relation.memory_id), None)
            label = {
                "supports": m.LINK_SUPPORT,
                "exception": m.LINK_EXCEPTION,
                "derived_from": m.LINK_DERIVED,
                "merged_from": m.LINK_MERGED,
            }[relation.kind]
            relations.append(
                f"{self._text(label)} · {target.draft.title if target else relation.memory_id} · v{relation.revision}\n{relation.reason}"
            )
            if target is not None:
                relation_options.append(Option(Text(sanitize_legacy_scalar(target.draft.title)), id=target.id))
        relation_list = self.query_one("#memory-relations-list", OptionList)
        relation_list.clear_options()
        relation_list.add_options(relation_options)
        self.query_one("#memory-relations-text", Static).update(Text(sanitize_legacy_block("\n\n".join(relations))))
        self.query_one("#memory-entry-activity-text", Static).update(self._activity_text({entry.id}))
        usage = recent_usage(self.snapshot, entry.id, entry.revision)
        usage_text = (
            self._text(
                m.USAGE.bind(
                    revision=entry.revision,
                    provided=usage.provided,
                    applied=usage.applied,
                    helpful=usage.helpful,
                    user_skipped=usage.user_skipped,
                    agent_skipped=usage.agent_skipped,
                )
            )
            if usage.provided or usage.helpful
            else ""
        )
        if usage.last_provided:
            effect = {"helpful": m.HELPFUL, "not_applicable": m.NOT_APPLICABLE, "incorrect": m.INCORRECT}.get(
                usage.effect, m.EFFECT_UNKNOWN
            )
            usage_text += "\n" + self._text(effect)
            usage_text += "\n" + self._text(
                m.LAST_PROVIDED.bind(date=format_memory_time(usage.last_provided, self._text))
            )
        if usage.skipped_turns >= 3:
            usage_text += "\n" + self._text(m.REVIEW_CONTEXT)
        self.query_one("#memory-usage", Static).update(Text(usage_text))
        self.query_one("#memory-usage").display = bool(usage_text)
        kind = {"decision": m.DECISION, "preference": m.PREFERENCE, "lesson": m.LESSON, "intention": m.INTENTION}[
            draft.kind
        ]
        self.query_one("#memory-title", Static).update(Text(sanitize_legacy_scalar(draft.title)))
        self.query_one("#memory-meta", Static).update(
            Text(
                sanitize_legacy_scalar(
                    f"{self._text(kind)} · {self._text(m.PROJECT if draft.workspace else m.PERSONAL)} · v{entry.revision}"
                    + (" · " + " · ".join(draft.topics) if draft.topics else "")
                    + (" · " + self._text(m.ALWAYS) if draft.use == "always" else "")
                )
            )
        )
        self.query_one("#memory-meta", Static).tooltip = (
            sanitize_legacy_scalar(draft.workspace) if draft.workspace else None
        )
        self.query_one("#memory-content", Static).update(Text(sanitize_legacy_block(draft.content)))
        self.query_one("#memory-content").border_title = Text(self._text(m.CONTENT))
        self.query_one("#memory-follow-up").border_title = Text(self._text(m.FOLLOW_UPS))
        for name, label, value in (
            ("when", m.WHEN, draft.when_to_use),
            ("reconsider", m.RECONSIDER, draft.reconsider_when),
        ):
            section = self.query_one(f"#memory-{name}", Static)
            section.border_title = Text(self._text(label))
            section.update(Text(sanitize_legacy_block(value)))
            section.display = bool(value)
        source = self.query_one("#memory-source", Static)
        label = {"assistant": m.ASSISTANT_SOURCE, "tool": m.TOOL_SOURCE}.get(
            entry.source.role, m.USER_SOURCE if entry.source.quote else m.SAVED_BY_USER
        )
        source.update(
            Text(
                sanitize_legacy_block(
                    "\n".join(
                        filter(
                            None,
                            (
                                self._text(label),
                                entry.source.quote,
                                format_memory_time(entry.updated_at, self._text),
                            ),
                        )
                    )
                )
            )
        )
        source.tooltip = Text(
            sanitize_legacy_block("\n".join(filter(None, (entry.source.session_id, entry.source.item_id))))
        )
        if entry.retired_by is not None:
            source.update(
                Text(sanitize_legacy_block(entry.source.quote))
                + Text("\n\n" + self._text(m.ARCHIVED) + "\n", style="dim")
                + Text(sanitize_legacy_block(entry.retired_by.quote))
            )
        recall = next((item for item in reversed(self.snapshot.recalls) if item.session_id == self._session_id), None)
        match = next((item for item in recall.matches if item.memory_id == entry.id), None) if recall else None
        self.query_one("#memory-feedback-actions").display = entry.state == "active"
        self.query_one("#memory-not-applicable", Button).disabled = (
            not match or match.revision != entry.revision or bool(recall and entry.id in recall.excluded_ids)
        )
        reason = ""
        if match:
            layer_labels = {
                "L0": m.LAYER_STANDING,
                "L1": m.LAYER_OPENING,
                "L2": m.LAYER_ACTION,
                "L3": m.LAYER_REQUESTED,
            }
            reason = (
                self._text(m.RECALL_LAYER.bind(layer=match.layer + " · " + self._text(layer_labels[match.layer])))
                + "\n"
            )
            reason += self._text(m.MATCHED.bind(terms=", ".join(match.terms)))
            routes = {
                "identity": m.ROUTE_ID,
                "title": m.ROUTE_TITLE,
                "keywords": m.ROUTE_KEYWORDS,
                "topic": m.ROUTE_TOPIC,
                "spelling": m.ROUTE_SPELLING,
                "context": m.ROUTE_CONTEXT,
                "standing": m.ALWAYS,
                "association": m.ROUTE_ASSOCIATION,
                "follow_up": m.ROUTE_FOLLOW_UP,
                "alias": m.ROUTE_ALIAS,
            }
            labels = [self._text(routes[route]) for route in match.routes if route in routes]
            if labels:
                reason += "\n" + " · ".join(labels)
            if match.revision != entry.revision:
                reason += "\n" + self._text(m.STALE.bind(revision=match.revision))
        replacement = ""
        review_message = m.review_message(
            "repeated_mismatch" if entry.id in self._organize_queue.condition_ids else entry.review_reason
        )
        if review_message is not None:
            replacement = self._text(review_message)
        if entry.replaces_id:
            target = next((item for item in self.snapshot.entries if item.id == entry.replaces_id), None)
            replacement = self._text(m.REPLACEMENT.bind(title=target.draft.title if target else entry.replaces_id))
        if not PersonalMemoryStore.evidence_current(entry, self.snapshot.entries):
            replacement = "\n".join(filter(None, (replacement, self._text(m.EVIDENCE_STALE))))
        self.query_one("#memory-replacement", Static).update(Text(sanitize_legacy_block(replacement)))
        self.query_one("#memory-replacement").display = bool(replacement)
        reasons = self._organize_reasons(entry)
        reasons_widget = self.query_one("#memory-organize-reasons", Static)
        if reasons:
            reasons_widget.border_title = Text(self._text(m.ORGANIZE_WHY))
            reasons_widget.update(Text(sanitize_legacy_block(reasons)))
        else:
            reasons_widget.update("")
        reasons_widget.display = bool(reasons)
        self.query_one("#memory-recall-details").display = match is not None
        self.query_one("#memory-match", Static).update(Text(sanitize_legacy_block(reason)))
        self.query_one("#memory-history").display = entry.revision > 1
        if self._revision_for != (entry.id, entry.revision):
            self._revision_for = (entry.id, entry.revision)
            self._revision_rows = tuple(reversed(entry.previous))
            self._revision_more = entry.revision > 2
        self.query_one("#memory-history-text", Static).update(
            Text(
                sanitize_legacy_block(
                    "\n\n".join(
                        f"v{old.revision} · {format_memory_time(old.updated_at, self._text)}\n{old.draft.content}\n{self._text(m.WHEN)}: {old.draft.when_to_use}\n{self._text(m.RECONSIDER)}: {old.draft.reconsider_when}"
                        for old in self._revision_rows
                    )
                )
            )
        )

    def _organize_reasons(self, entry: PersonalMemory) -> str:
        item = self._organize.get(entry.id) if self.current_view == "organize" else None
        if item is None:
            return ""
        lines = [self._text(_REASON_LABELS[reason]) for reason in item.reasons]
        if OrganizeReason.DUPLICATE in item.reasons:
            partners = [
                f"{sanitize_legacy_scalar(partner.draft.title)} ({partner.id})" if partner.draft.title else partner.id
                for partner in self._organize_queue.duplicate_partners(entry.id)
            ]
            if partners:
                lines.append(self._text(m.ORGANIZE_PARTNERS.bind(partners=", ".join(partners))))
        if OrganizeReason.NEEDS_REVIEW in item.reasons and m.review_message(entry.review_reason) is None:
            lines.append(self._text(m.ORGANIZE_REVIEW_GENERIC))
        return "\n".join(lines)

    def _activity_text(
        self, ids: set[str], *, include_global: bool = False, events: tuple[MemoryActivity, ...] | None = None
    ) -> Text:
        labels = {
            "created": m.SAVE,
            "updated": m.EDIT,
            "proposed": m.CANDIDATE,
            "activated": m.ACCEPT,
            "paused": m.ARCHIVE,
            "forgotten": m.FORGET,
            "follow_up": m.FOLLOW_UPS,
            "provided": m.PROVIDED,
            "applied": m.APPLIED,
            "not_applicable": m.NOT_APPLICABLE,
            "helpful": m.HELPFUL,
            "incorrect": m.INCORRECT,
            "no_match": m.NO_MATCH,
            "review_required": m.REVIEW_REQUIRED,
            "candidate_expired": m.REVIEW_EXPIRED,
            "revision_imported": m.REVISION_IMPORTED,
            "review_digest": m.WEEKLY_REVIEW,
            "conditions_confirmed": m.CONFIRM_CONDITIONS,
        }
        actors = {"user": m.USER_ACTOR, "agent": m.AGENT_ACTOR, "system": m.SYSTEM_ACTOR}
        entries = {e.id: e for e in self.snapshot.entries}
        rows = []
        for event in reversed(self.snapshot.activity if events is None else events):
            if event.memory_id not in ids and not (include_global and not event.memory_id):
                continue
            entry = entries.get(event.memory_id)
            title = event.draft.title if event.draft else entry.draft.title if entry else ""
            label = labels.get(event.action)
            actor = actors.get(event.actor, m.SYSTEM_ACTOR)
            action = self._text(label) if label else event.action
            review_detail = m.review_message(event.detail)
            detail = self._text(review_detail) if review_detail else event.detail
            rows.append(
                f"{format_memory_time(event.occurred_at, self._text)} · {self._text(actor)} · {action}\n{title}"
                + (f" · v{event.revision}" if event.revision else "")
                + (f"\n{detail}" if detail else "")
                + (f"\n{event.draft.content}" if events is not None and event.draft else "")
            )
        return Text(sanitize_legacy_block("\n\n".join(rows) or self._text(m.EMPTY)))

    @on(Collapsible.Toggled)
    def _detail_toggled(self) -> None:
        detail = self.query_one("#memory-detail", VerticalScroll)
        if not detail.has_focus_within:
            # A programmatic collapse queues a native scroll after selection. Restore
            # the entry's top after it; direct mouse/keyboard expansion keeps its scroll.
            self.call_after_refresh(detail.scroll_home, animate=False)

    def _paint_selection(self) -> None:
        options = self.query_one("#memory-list", OptionList)
        for memory_id, label in self._list_rows or ():
            if memory_id in (self._selected_id, self._painted_selection):
                # Native highlight foreground stays legible in both light and dark themes.
                prompt = Text(label.plain) if memory_id == self._selected_id else label
                if options.get_option(memory_id).prompt != prompt:
                    options.replace_option_prompt(memory_id, prompt)
        self._painted_selection = self._selected_id

    @on(OptionList.OptionHighlighted, "#memory-list")
    def _highlight(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id not in {entry.id for entry in self.snapshot.entries}:
            return
        self._selected_id = event.option.id or ""
        self._paint_selection()
        self._show_detail()

    @on(OptionList.OptionSelected, "#memory-relations-list")
    def _open_related(self, event: OptionList.OptionSelected) -> None:
        self._selected_id = event.option.id or ""
        with self.prevent(Select.Changed):
            self.query_one("#memory-kind-filter", Select).value = "all"
            self.query_one("#memory-topic-filter", Select).value = ""
            self.query_one("#memory-scope-filter", Select).value = "all"
        self.query_one("#memory-search", EnhancedInput).value = ""
        self.query_one("#memory-view", Tabs).active = "memory-view-all"
        self._refresh_list()
        self._focus_results()

    @on(OptionList.OptionSelected, "#memory-list")
    def _open_detail(self) -> None:
        if self._selected() is not None:
            self.query_one("#memory-detail", VerticalScroll).focus()

    def _focus_results(self) -> None:
        if self.current_view == "activity":
            self.query_one("#memory-activity", VerticalScroll).focus()
        elif self.query_one("#memory-index").display:
            self.query_one("#memory-list", OptionList).focus()
        else:
            self.query_one("#memory-search", EnhancedInput).focus()

    @on(_MemorySearchInput.Escaped)
    def _search_escaped(self, event: _MemorySearchInput.Escaped) -> None:
        event.stop()
        self.action_escape()

    @on(EnhancedInput.Changed, "#memory-search")
    def _search_changed(self) -> None:
        if self.is_mounted and self._loaded:
            if self._search_timer is not None:
                self._search_timer.stop()
            self._search_timer = self.set_timer(0.18, self._refresh_list)

    @on(EnhancedInput.Submitted, "#memory-search")
    def _search_submitted(self) -> None:
        self._refresh_list()
        self._focus_results()

    @on(Select.Changed, "#memory-kind-filter")
    @on(Select.Changed, "#memory-scope-filter")
    @on(Select.Changed, "#memory-topic-filter")
    def _filter(self) -> None:
        # Initial tab/input events arrive before the first snapshot. Filtering
        # that empty placeholder would discard a memory opened from Buddy.
        if self.is_mounted and self._loaded and not self._updating:
            self._refresh_list()

    @on(Tabs.TabActivated, "#memory-view")
    def _view_changed(self) -> None:
        if not self.is_mounted or not self._loaded:
            return
        self._marked.clear()
        if self.current_view == "all":
            self.query_one("#memory-scope-filter", Select).value = "all"
        self._filter()

    @on(Select.Changed, "#memory-mode")
    @on(Select.Changed, "#memory-capture")
    async def _settings(self) -> None:
        if self.is_mounted and self._loaded and not self._updating:
            mode = cast(MemoryMode, self.query_one("#memory-mode", Select).value)
            capture = self.query_one("#memory-capture", Select).value
            # Mount-time messages can arrive after a fast background load. Only
            # a user-visible change may turn a read/refresh into a settings write.
            if mode == self.snapshot.mode and capture == self._capture_value():
                return
            await self._send(
                PersonalMemoryCommand(
                    action="settings",
                    mode=mode,
                    capture=capture != "explicit",
                    auto_save=capture == "auto",
                )
            )

    @on(Button.Pressed)
    async def _button(self, event: Button.Pressed) -> None:
        if self._mutating or event.button.disabled or not event.button.display:
            return
        action = event.button.id
        if action == "memory-organize":
            self._review_together()
            return
        if action == "memory-history-more":
            entry = self._selected()
            if entry:
                self._request_read(
                    PersonalMemoryCommand(
                        action="revisions",
                        memory_id=entry.id,
                        revision=entry.revision,
                        before_revision=min((r.revision for r in self._revision_rows), default=entry.revision),
                    )
                )
            return
        if (
            action not in ("memory-close", "memory-older", "memory-latest", "memory-mark")
            and event.time <= self._last_mutation_reply_at
        ):
            return
        entry = self._selected()
        if action == "memory-close":
            self.action_close()
        elif action == "memory-mark":
            if self._marked:
                self._clear_selection()
            else:
                self._mark_selected()
        elif action in ("memory-older", "memory-latest"):
            page = self._history_page if self._history_page is not None else self.snapshot.activity
            self._focus_results()
            self._request_read(
                PersonalMemoryCommand(
                    action="history", before_sequence=page[0].sequence if page and action == "memory-older" else 0
                )
            )
        elif self._marked and action in ("memory-accept", "memory-archive", "memory-forget"):
            references = tuple(self._marked.items())
            if action == "memory-forget":
                removed = set().union(
                    *(PersonalMemoryStore.forgetting_ids(self.snapshot, mid) for mid, _ in references)
                )
                self.app.push_screen(
                    ConfirmDialog(
                        title=m.FORGET.bind(),
                        message=m.BATCH_FORGET.bind(count=len(removed)),
                        confirm_label=m.FORGET.bind(),
                        confirm_variant="error",
                        locale_controller=self._locale_controller,
                    ),
                    partial(self._forget_batch, references=references),
                )
            else:
                await self._batch(
                    PersonalMemoryCommand(
                        action="batch_state",
                        references=references,
                        state="active" if action == "memory-accept" else "archived",
                    )
                )
        elif action in ("memory-new", "memory-edit"):
            selected = entry if action == "memory-edit" else None
            self.app.push_screen(
                PersonalMemoryEditor(
                    workspace=selected.draft.workspace if selected and selected.draft.workspace else self._workspace,
                    draft=selected.draft if selected else None,
                    save=partial(self._save_draft, entry=selected),
                    locale_controller=self._locale_controller,
                ),
            )
        elif entry is not None and action in ("memory-accept", "memory-archive"):
            await self._send(
                PersonalMemoryCommand(
                    action="state",
                    memory_id=entry.id,
                    revision=entry.revision,
                    state="active" if action == "memory-accept" else "archived",
                )
            )
        elif entry is not None and action == "memory-forget":
            self.app.push_screen(
                ConfirmDialog(
                    title=m.FORGET.bind(),
                    message=m.FORGET_CONFIRM.bind(
                        title=entry.draft.title,
                        count=len(PersonalMemoryStore.forgetting_ids(self.snapshot, entry.id)) - 1,
                    ),
                    confirm_label=m.FORGET.bind(),
                    confirm_variant="error",
                    locale_controller=self._locale_controller,
                ),
                lambda confirmed: self._forget(confirmed, entry),
            )
        elif entry is not None and action in ("memory-not-applicable", "memory-helpful", "memory-incorrect"):
            recall = next((r for r in self.snapshot.recalls if r.session_id == self._session_id), None)
            await self._send(
                PersonalMemoryCommand(
                    action="feedback",
                    memory_id=entry.id,
                    revision=entry.revision,
                    outcome={
                        "memory-not-applicable": "not_applicable",
                        "memory-helpful": "helpful",
                        "memory-incorrect": "incorrect",
                    }[action],
                    turn_id=recall.turn_id if recall else "",
                )
            )
        elif entry is not None and entry.draft.follow_up is not None:
            if action == "memory-complete":
                await self._send(
                    PersonalMemoryCommand(
                        action="follow_up",
                        memory_id=entry.id,
                        revision=entry.revision,
                        follow_up=replace(entry.draft.follow_up, status="completed"),
                    )
                )
            elif action == "memory-continue":
                prompt = self._text(
                    m.CONTINUE_PROMPT.bind(
                        title=entry.draft.title,
                        memory_id=entry.id,
                        revision=entry.revision,
                        next_step=entry.draft.follow_up.next_step or entry.draft.content,
                    )
                )
                if self._continue_follow_up is not None:
                    if self._continue_follow_up(prompt):
                        self.dismiss_when_topmost()
                    else:
                        self._show_hint(m.DRAFT_BUSY)

    def _show_hint(self, reference: MessageDef | MessageRef) -> None:
        error = self.query_one("#memory-error", Static)
        error.update(Text("⚠ " + self._text(reference)))
        error.display = True

    def _review_together(self) -> None:
        # Search repaints on a debounce, so a pending refresh leaves _marked and
        # _visible_count describing the previous query. Flushing it here keeps the
        # handoff to what the current filters show.
        if self._search_timer is not None:
            self._refresh_list()
        topic = (
            str(self.query_one("#memory-topic-filter", Select).value)
            or self.query_one("#memory-search", EnhancedInput).value
        ).strip()
        references = ", ".join(f"{mid} v{revision}" for mid, revision in self._marked.items())
        if self.current_view == "organize":
            if not self._visible_count:
                return
            if self._marked:
                prompt = self._text(m.ORGANIZE_PROMPT.bind(topic=topic or self._workspace, references=references))
            elif topic:
                prompt = self._text(m.ORGANIZE_PROMPT_TOPIC.bind(topic=topic))
            else:
                self._show_hint(m.ORGANIZE_SELECT_HINT)
                return
        else:
            prompt = self._text(m.ORGANIZE_PROMPT.bind(topic=topic or self._workspace, references=references))
        if self._continue_follow_up is None:
            return
        if self._continue_follow_up(prompt):
            self.dismiss_when_topmost()
        else:
            self._show_hint(m.DRAFT_BUSY)

    async def _save_draft(self, draft: MemoryDraft, entry: PersonalMemory | None) -> str:
        reply = await self._send(
            PersonalMemoryCommand(
                action="save",
                draft=draft,
                memory_id=entry.id if entry else "",
                revision=entry.revision if entry else 0,
            )
        )
        if not reply.error and entry is None and reply.snapshot is not None:
            saved = next(
                (item for item in reply.snapshot.entries if item.id == reply.saved_memory_id),
                None,
            )
            if saved is not None:
                self._selected_id = saved.id
                self.query_one("#memory-search", EnhancedInput).value = ""
                self.query_one("#memory-view", Tabs).active = "memory-view-active"
        return self._text(m.failure_message(reply.error_code)) if reply.error else ""

    def action_new(self) -> None:
        if self._loaded and not self._mutating:
            self.app.push_screen(
                PersonalMemoryEditor(
                    workspace=self._workspace,
                    save=partial(self._save_draft, entry=None),
                    locale_controller=self._locale_controller,
                )
            )

    def action_reload(self) -> None:
        self._request_read(PersonalMemoryCommand())

    def action_search(self) -> None:
        self.query_one("#memory-search", EnhancedInput).focus()

    def action_escape(self) -> None:
        if self._marked:
            self._clear_selection()
        elif self.focused is self.query_one("#memory-search"):
            search = self.query_one("#memory-search", EnhancedInput)
            if search.value:
                search.value = ""
                self._refresh_list()
            elif self.current_view != "activity" and not self.query_one("#memory-index").display:
                self.action_close()
            else:
                self._focus_results()
        elif self.query_one("#memory-detail").has_focus_within:
            self._focus_results()
        else:
            self.action_close()

    def action_forget_selected(self) -> None:
        button = self.query_one("#memory-forget", Button)
        if self.focused is self.query_one("#memory-list") and button.display and not button.disabled:
            button.press()

    def _clear_selection(self) -> None:
        self._marked.clear()
        self._refresh_list()
        self._focus_results()

    def on_key(self, event: Key) -> None:
        if event.key == "space" and self.focused is self.query_one("#memory-list"):
            self._mark_selected()
            event.stop()
            event.prevent_default()
        if event.key == "down" and self.focused is self.query_one("#memory-search"):
            self._refresh_list()
            self._focus_results()
            event.stop()
            event.prevent_default()

    def _mark_selected(self) -> None:
        if self._mutating:
            return
        entry = self._selected()
        if entry is not None:
            if entry.id in self._marked:
                del self._marked[entry.id]
            else:
                if len(self._marked) >= MAX_BATCH:
                    error = self.query_one("#memory-error", Static)
                    error.update(Text("⚠ " + self._text(m.BATCH_LIMIT)))
                    error.display = True
                    return
                self._marked[entry.id] = entry.revision
            self._refresh_list()

    async def _batch(self, command: PersonalMemoryCommand) -> None:
        reply = await self._send(command)
        if not reply.error:
            self._marked.clear()
            self._refresh_list()

    def _forget_batch(self, confirmed: bool | None, *, references: tuple[tuple[str, int], ...]) -> None:
        if confirmed:
            self.run_worker(self._batch(PersonalMemoryCommand(action="batch_forget", references=references)))

    def _forget(self, confirmed: bool | None, entry: PersonalMemory) -> None:
        if confirmed:
            self.run_worker(
                self._send(PersonalMemoryCommand(action="forget", memory_id=entry.id, revision=entry.revision))
            )

    def on_resize(self) -> None:
        self.set_class(self.size.width < 72, "-compact")

    def refresh_localization(self) -> None:
        self.query_one("#personal-memory").border_title = Text(self._text(m.TITLE))
        self.query_one("#memory-search", EnhancedInput).placeholder = self._text(m.SEARCH)
        self.query_one("#memory-list").tooltip = self._text(m.KEYBOARD_HINT)
        self.query_one("#memory-reconsider").tooltip = self._text(m.RECONSIDER_TIP)
        self.query_one("#memory-capture", Select).tooltip = self._text(m.CAPTURE_TIP)
        self.query_one("#memory-mode", Select).tooltip = self._text(m.MODE_TIP)
        with self.prevent(Select.Changed):
            mode = self.query_one("#memory-mode", Select)
            mode.set_options(self._mode_options())
            mode.value = self.snapshot.mode
            mode.mutate_reactive(Select.value)
            capture = self.query_one("#memory-capture", Select)
            capture.set_options(self._capture_options())
            capture.value = self._capture_value()
            capture.mutate_reactive(Select.value)
        for label, value in self._view_options():
            self.query_one(f"#memory-view-{value}", Tab).label = Text(label)
        for action, label in (
            ("mark", m.MARK),
            ("older", m.OLDER_ACTIVITY),
            ("latest", m.LATEST_ACTIVITY),
            ("new", m.NEW),
            ("edit", m.EDIT),
            ("accept", m.ACCEPT),
            ("archive", m.ARCHIVE),
            ("forget", m.FORGET),
            ("close", m.CLOSE),
        ):
            self._button_label(action, label)
        self.query_one("#memory-history", Collapsible).title = self._text(m.HISTORY)
        self.query_one("#memory-evidence", Collapsible).title = self._text(m.SOURCE)
        self.query_one("#memory-recall-details", Collapsible).title = self._text(m.RECALL_DETAILS)
        self.query_one("#memory-recall-tip", Static).update(Text(self._text(RECALL_TIP)))
        self.query_one("#memory-incorrect").tooltip = self._text(m.INCORRECT_TIP)
        for name, options in (("kind", self._kind_options()), ("scope", self._scope_options())):
            selector = self.query_one(f"#memory-{name}-filter", Select)
            value = selector.value
            with self.prevent(Select.Changed):
                selector.set_options(options)
                selector.value = value
                selector.mutate_reactive(Select.value)
        self._refresh_topics()
        for name, label in (
            ("organize", m.ORGANIZE),
            ("history-more", m.OLDER_REVISIONS),
            ("continue", m.CONTINUE),
            ("complete", m.COMPLETE),
            ("not-applicable", m.NOT_APPLICABLE),
            ("helpful", m.HELPFUL),
            ("incorrect", m.INCORRECT),
        ):
            self._button_label(name, label)
        for name, label in (("relations", m.RELATED), ("entry-activity", m.ACTIVITY)):
            self.query_one(f"#memory-{name}", Collapsible).title = self._text(label)
        self._refresh_list()

    def action_close(self) -> None:
        self.dismiss_when_topmost()
