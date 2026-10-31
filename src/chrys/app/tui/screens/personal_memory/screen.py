# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""TUI memory library, source review and current-task recall through the event bus."""

from __future__ import annotations

import os
from functools import partial
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on
from textual.containers import Grid, Horizontal, HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, Collapsible, OptionList, Select, Static
from textual.widgets.option_list import Option

from chrys.app.tui.binding_display import CLOSE_BINDING, localized_binding
from chrys.app.tui.i18n import render_str
from chrys.app.tui.screens.dialogs.base import BaseDialog
from chrys.app.tui.screens.dialogs.confirm import ConfirmDialog
from chrys.app.tui.widgets import EnhancedInput
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.i18n import MessageDef, MessageRef
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_block, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryMode, MemorySnapshot, PersonalMemory

from . import messages as m
from .editor import PersonalMemoryEditor

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from chrys.app.tui.i18n import LocaleController


class _MemoryUpdate(Message):
    def __init__(self, event: PersonalMemoryChanged) -> None:
        super().__init__()
        self.event = event


class PersonalMemoryScreen(BaseDialog[None]):
    CSS_PATH = "screen.tcss"
    BINDINGS: ClassVar[list] = [localized_binding("escape", "close", CLOSE_BINDING, show=False)]

    def __init__(
        self, *, bus: EventBus, workspace: str, session_id: str, locale_controller: LocaleController | None = None
    ):
        super().__init__()
        self._bus = bus
        self._workspace = workspace
        self._session_id = session_id
        self._locale_controller = locale_controller
        self.snapshot = MemorySnapshot()
        self._selected_id = ""
        self._updating = False
        self._loaded = False
        self._pending: set[str] = set()
        self._replies: dict[str, PersonalMemoryChanged] = {}
        self.last_error = ""

    def _text(self, message: MessageDef | MessageRef) -> str:
        ref = message.bind() if isinstance(message, MessageDef) else message
        return render_str(self._locale_controller.localizer, ref) if self._locale_controller else format_message(ref)

    def compose(self) -> ComposeResult:
        with Vertical(id="personal-memory") as frame:
            frame.border_title = Text(self._text(m.TITLE))
            with HorizontalGroup(id="memory-toolbar"):
                yield Select(
                    self._mode_options(),
                    value="auto",
                    allow_blank=False,
                    id="memory-mode",
                    tooltip=self._text(m.MODE_TIP),
                    disabled=True,
                )
                yield Checkbox(
                    Text(self._text(m.CAPTURE)),
                    value=True,
                    id="memory-capture",
                    tooltip=self._text(m.CAPTURE_TIP),
                    disabled=True,
                )
                yield Button(Text(self._text(m.NEW)), id="memory-new", variant="primary")
            yield Static("", id="memory-counts", markup=False)
            yield Static("", id="memory-recall-query", markup=False)
            with Horizontal(id="memory-body"):
                with Vertical(id="memory-index"):
                    with Vertical(id="memory-filters"):
                        yield EnhancedInput(placeholder=self._text(m.SEARCH), id="memory-search")
                        yield Select(self._view_options(), value="active", allow_blank=False, id="memory-view")
                    yield OptionList(id="memory-list")
                with VerticalScroll(id="memory-detail"):
                    yield Static("", id="memory-title", markup=False)
                    yield Static("", id="memory-meta", markup=False)
                    yield Static("", id="memory-match", markup=False)
                    yield Static("", id="memory-content", markup=False)
                    for section in ("when", "reconsider", "source"):
                        yield Static("", id=f"memory-{section}", classes="memory-section", markup=False)
                    with Collapsible(title=self._text(m.HISTORY), collapsed=True, id="memory-history"):
                        yield Static("", id="memory-history-text", markup=False)
            yield Static("", id="memory-error", markup=False)
            with Grid(id="memory-actions"):
                for action, label in (
                    ("edit", m.EDIT),
                    ("accept", m.ACCEPT),
                    ("archive", m.ARCHIVE),
                    ("forget", m.FORGET),
                    ("refresh", m.REFRESH),
                    ("close", m.CLOSE),
                ):
                    yield Button(
                        Text(self._text(label)),
                        id=f"memory-{action}",
                        variant="primary" if action == "accept" else "default",
                    )

    def _mode_options(self) -> list[tuple[str, str]]:
        return [(self._text(label), value) for value, label in (("auto", m.AUTO), ("manual", m.MANUAL), ("off", m.OFF))]

    def _view_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (
                ("active", m.ACTIVE),
                ("candidate", m.CANDIDATE),
                ("recalled", m.RECALLED),
                ("archived", m.ARCHIVED),
                ("all", m.ALL),
            )
        ]

    async def on_mount(self) -> None:
        if self._locale_controller:
            self._locale_controller.register_surface(self)
        await self._bus.subscribe(PersonalMemoryChanged, self._receive)
        await self._send(PersonalMemoryCommand())

    async def on_unmount(self) -> None:
        await self._bus.unsubscribe(PersonalMemoryChanged, self._receive)
        if self._locale_controller:
            self._locale_controller.unregister_surface(self)

    async def _receive(self, event: PersonalMemoryChanged) -> None:
        if not event.session_id or event.session_id == self._session_id:
            if event.request_id in self._pending:
                self._replies[event.request_id] = event
            self.post_message(_MemoryUpdate(event))

    async def _send(self, command: PersonalMemoryCommand) -> PersonalMemoryChanged:
        command.session_id = self._session_id
        self._pending.add(command.event_id)
        try:
            await self._bus.publish(command)
            return self._replies.pop(
                command.event_id, PersonalMemoryChanged(error="The memory service did not respond.")
            )
        finally:
            self._pending.discard(command.event_id)

    def on__memory_update(self, message: _MemoryUpdate) -> None:
        if not self._composed_live:
            return
        event = message.event
        self.last_error = event.error
        self.query_one("#memory-error", Static).update(
            Text(self._text(m.ERROR.bind(error=sanitize_legacy_scalar(event.error))) if event.error else "")
        )
        if event.snapshot is not None and event.snapshot.generation >= self.snapshot.generation:
            self.snapshot = event.snapshot
            self._updating = True
            with self.prevent(Select.Changed, Checkbox.Changed):
                self.query_one("#memory-mode", Select).value = self.snapshot.mode
                self.query_one("#memory-capture", Checkbox).value = self.snapshot.capture
            self._updating = False
            self._loaded = True
            self.query_one("#memory-mode", Select).disabled = False
            self.query_one("#memory-capture", Checkbox).disabled = False
            self._refresh_list()

    def _selected(self) -> PersonalMemory | None:
        return next((entry for entry in self.snapshot.entries if entry.id == self._selected_id), None)

    def _refresh_list(self) -> None:
        view = self.query_one("#memory-view", Select).value
        query = self.query_one("#memory-search", EnhancedInput).value.casefold().strip()
        recall = next((item for item in reversed(self.snapshot.recalls) if item.session_id == self._session_id), None)
        recalled_ids = {match.memory_id for match in recall.matches} if recall else set()
        entries = [
            entry
            for entry in reversed(self.snapshot.entries)
            if (
                (entry.id in recalled_ids if view == "recalled" else view == "all" or entry.state == view)
                and (
                    view == "all"
                    or not entry.draft.workspace
                    or entry.draft.workspace == os.path.normcase(self._workspace)
                )
                and (
                    not query
                    or query in f"{entry.draft.title} {entry.draft.content} {entry.draft.when_to_use}".casefold()
                )
            )
        ]
        options = self.query_one("#memory-list", OptionList)
        options.clear_options()
        options.add_options([Option(Text(sanitize_legacy_scalar(entry.draft.title)), id=entry.id) for entry in entries])
        if self._selected_id not in {entry.id for entry in entries}:
            self._selected_id = entries[0].id if entries else ""
        options.highlighted = next(
            (index for index, entry in enumerate(entries) if entry.id == self._selected_id), None
        )
        self.query_one("#memory-counts", Static).update(
            Text(
                self._text(
                    m.COUNTS.bind(
                        active=sum(entry.state == "active" for entry in self.snapshot.entries),
                        candidates=sum(entry.state == "candidate" for entry in self.snapshot.entries),
                        archived=sum(entry.state == "archived" for entry in self.snapshot.entries),
                    )
                )
            )
        )
        self._show_detail()
        query_view = self.query_one("#memory-recall-query", Static)
        query_view.display = view == "recalled" and recall is not None
        query_view.update(Text(sanitize_legacy_scalar(recall.query if recall else "")))

    def _show_detail(self) -> None:
        entry = self._selected()
        for name in ("when", "reconsider", "source", "history"):
            self.query_one(f"#memory-{name}").display = entry is not None
        for name in ("edit", "accept", "archive", "forget"):
            self.query_one(f"#memory-{name}", Button).disabled = entry is None
        if entry is None:
            self.query_one("#memory-title", Static).update(
                Text(self._text(m.NO_RECALL if self.query_one("#memory-view", Select).value == "recalled" else m.EMPTY))
            )
            for name in ("meta", "match", "content"):
                self.query_one(f"#memory-{name}", Static).update("")
            return
        self.query_one("#memory-accept", Button).disabled = entry.state == "active"
        self.query_one("#memory-archive", Button).disabled = entry.state == "archived"
        draft = entry.draft
        kind = {"decision": m.DECISION, "preference": m.PREFERENCE, "lesson": m.LESSON, "intention": m.INTENTION}[
            draft.kind
        ]
        self.query_one("#memory-title", Static).update(Text(sanitize_legacy_scalar(draft.title)))
        self.query_one("#memory-meta", Static).update(
            Text(f"{self._text(kind)} · {self._text(m.PROJECT if draft.workspace else m.PERSONAL)} · v{entry.revision}")
        )
        self.query_one("#memory-meta", Static).tooltip = (
            sanitize_legacy_scalar(draft.workspace) if draft.workspace else None
        )
        self.query_one("#memory-content", Static).update(Text(sanitize_legacy_block(draft.content)))
        for name, label, value in (
            ("when", m.WHEN, draft.when_to_use),
            ("reconsider", m.RECONSIDER, draft.reconsider_when),
        ):
            section = self.query_one(f"#memory-{name}", Static)
            section.border_title = Text(self._text(label))
            section.update(Text(sanitize_legacy_block(value)))
            section.display = bool(value)
        source = self.query_one("#memory-source", Static)
        source.border_title = Text(self._text(m.SOURCE))
        label = (
            m.ASSISTANT_SOURCE
            if entry.source.role == "assistant"
            else (m.USER_SOURCE if entry.source.quote else m.SAVED_BY_USER)
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
                                entry.source.session_id,
                                entry.source.item_id,
                                entry.updated_at,
                            ),
                        )
                    )
                )
            )
        )
        recall = next((item for item in reversed(self.snapshot.recalls) if item.session_id == self._session_id), None)
        match = next((item for item in recall.matches if item.memory_id == entry.id), None) if recall else None
        reason = ""
        if match:
            reason = self._text(m.MATCHED.bind(terms=", ".join(match.terms)))
            if match.revision != entry.revision:
                reason += "\n" + self._text(m.STALE.bind(revision=match.revision))
        if entry.replaces_id:
            target = next((item for item in self.snapshot.entries if item.id == entry.replaces_id), None)
            reason = self._text(m.REPLACEMENT.bind(title=target.draft.title if target else entry.replaces_id))
        self.query_one("#memory-match", Static).update(Text(sanitize_legacy_block(reason)))
        self.query_one("#memory-history").display = bool(entry.previous)
        self.query_one("#memory-history-text", Static).update(
            Text(
                sanitize_legacy_block(
                    "\n\n".join(
                        f"v{old.revision} · {old.updated_at}\n{old.draft.content}\n{self._text(m.WHEN)}: {old.draft.when_to_use}\n{self._text(m.RECONSIDER)}: {old.draft.reconsider_when}"
                        for old in reversed(entry.previous)
                    )
                )
            )
        )

    @on(OptionList.OptionHighlighted, "#memory-list")
    def _highlight(self, event: OptionList.OptionHighlighted) -> None:
        self._selected_id = event.option.id or ""
        self._show_detail()

    @on(EnhancedInput.Changed, "#memory-search")
    @on(Select.Changed, "#memory-view")
    def _filter(self) -> None:
        if self.is_mounted and not self._updating:
            self._refresh_list()

    @on(Select.Changed, "#memory-mode")
    @on(Checkbox.Changed, "#memory-capture")
    async def _settings(self) -> None:
        if self.is_mounted and self._loaded and not self._updating:
            await self._send(
                PersonalMemoryCommand(
                    action="settings",
                    mode=cast(MemoryMode, self.query_one("#memory-mode", Select).value),
                    capture=self.query_one("#memory-capture", Checkbox).value,
                )
            )

    @on(Button.Pressed)
    async def _button(self, event: Button.Pressed) -> None:
        action = event.button.id
        entry = self._selected()
        if action == "memory-close":
            self.action_close()
        elif action == "memory-refresh":
            await self._send(PersonalMemoryCommand())
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
                    message=m.FORGET_CONFIRM.bind(title=entry.draft.title),
                    confirm_label=m.FORGET.bind(),
                    confirm_variant="error",
                    locale_controller=self._locale_controller,
                ),
                lambda confirmed: self._forget(confirmed, entry),
            )

    async def _save_draft(self, draft: MemoryDraft, entry: PersonalMemory | None) -> str:
        reply = await self._send(
            PersonalMemoryCommand(
                action="save",
                draft=draft,
                memory_id=entry.id if entry else "",
                revision=entry.revision if entry else 0,
            )
        )
        return reply.error

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
        self.query_one("#memory-capture", Checkbox).label = Text(self._text(m.CAPTURE))
        self.query_one("#memory-capture", Checkbox).tooltip = self._text(m.CAPTURE_TIP)
        self.query_one("#memory-mode", Select).tooltip = self._text(m.MODE_TIP)
        with self.prevent(Select.Changed):
            mode = self.query_one("#memory-mode", Select)
            view = self.query_one("#memory-view", Select)
            selected_view = view.value
            mode.set_options(self._mode_options())
            mode.value = self.snapshot.mode
            view.set_options(self._view_options())
            view.value = selected_view
        for action, label in (
            ("new", m.NEW),
            ("edit", m.EDIT),
            ("accept", m.ACCEPT),
            ("archive", m.ARCHIVE),
            ("forget", m.FORGET),
            ("refresh", m.REFRESH),
            ("close", m.CLOSE),
        ):
            self.query_one(f"#memory-{action}", Button).label = Text(self._text(label))
        self.query_one("#memory-history", Collapsible).title = self._text(m.HISTORY)
        self._refresh_list()

    def action_close(self) -> None:
        self.dismiss_when_topmost()
