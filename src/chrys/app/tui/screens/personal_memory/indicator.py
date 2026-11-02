# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""A quiet memory entry in the existing footer, without changing transcript geometry."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from rich.text import Text
from textual.markup import escape
from textual.message import Message
from textual.reactive import reactive

from chrys.app.tui.i18n import render_str
from chrys.app.tui.widgets.selection import NonSelectableStatic
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import MemorySnapshot

from . import messages as m

if TYPE_CHECKING:
    from textual.events import Click

    from chrys.app.tui.i18n import LocaleController
    from chrys.foundation.events.bus import EventBus


class _MemoryStatus(Message):
    def __init__(self, event: PersonalMemoryChanged) -> None:
        super().__init__()
        self.event = event


class PersonalMemoryIndicator(NonSelectableStatic):
    DEFAULT_CSS = """
    PersonalMemoryIndicator {
        width: auto; max-width: 20; height: 1; padding: 0 1;
        background: $footer-item-background; color: $text-muted;
        text-wrap: nowrap; text-overflow: ellipsis;
    }
    PersonalMemoryIndicator:hover { background: $control-background; color: $text; }
    """

    session_id: reactive[str] = reactive("", repaint=False)
    workspace_cwd: reactive[str] = reactive("", repaint=False)

    class OpenRequested(Message):
        def __init__(self, view: str) -> None:
            super().__init__()
            self.view = view

    def __init__(self, *, bus: EventBus, workspace: str, locale_controller: LocaleController | None = None) -> None:
        super().__init__("", markup=False)
        self._bus = bus
        self._workspace = workspace
        self._locale_controller = locale_controller
        self._snapshot = MemorySnapshot()
        self._view = ""
        self._compact = False
        self._processing = False

    async def on_mount(self) -> None:
        if self._locale_controller:
            self._locale_controller.register_surface(self)
        await self._bus.subscribe(PersonalMemoryChanged, self._receive)
        self._compact = self.app.size.width < 123
        self.refresh_localization()
        await self._load()

    async def on_unmount(self) -> None:
        await self._bus.unsubscribe(PersonalMemoryChanged, self._receive)
        if self._locale_controller:
            self._locale_controller.unregister_surface(self)

    async def _load(self) -> None:
        await self._bus.publish(PersonalMemoryCommand(session_id=self.session_id))

    async def _receive(self, event: PersonalMemoryChanged) -> None:
        self.post_message(_MemoryStatus(event))

    def on__memory_status(self, message: _MemoryStatus) -> None:
        event = message.event
        if event.session_id and event.session_id != self.session_id:
            return
        self._processing = event.processing
        if event.snapshot is not None and event.snapshot.generation >= self._snapshot.generation:
            self._snapshot = event.snapshot
            saved = next((item for item in event.snapshot.entries if item.id == event.saved_memory_id), None)
            if saved is not None:
                notice = (m.PROPOSED if saved.state == "candidate" else m.REMEMBERED).bind(
                    title=sanitize_legacy_scalar(saved.draft.title)
                )
                localizer = self._locale_controller.localizer if self._locale_controller else None
                self.notify(escape(render_str(localizer, notice) if localizer else format_message(notice)))
        if event.error:
            notice = m.ERROR.bind(error=sanitize_legacy_scalar(event.error))
            localizer = self._locale_controller.localizer if self._locale_controller else None
            self.notify(
                escape(render_str(localizer, notice) if localizer else format_message(notice)), severity="warning"
            )
        self.refresh_localization()

    def watch_session_id(self) -> None:
        if self.is_mounted:
            self._processing = False
            self.refresh_localization()
            self.run_worker(self._load, group="personal-memory-status", exclusive=True)

    def watch_workspace_cwd(self) -> None:
        if self.is_mounted:
            self.refresh_localization()

    def set_compact(self, compact: bool) -> None:
        if self._compact != compact:
            self._compact = compact
            self.refresh_localization()

    def refresh_localization(self) -> None:
        workspace = os.path.normcase(os.path.abspath(self.workspace_cwd or self._workspace))
        entries = [
            entry for entry in self._snapshot.entries if not entry.draft.workspace or entry.draft.workspace == workspace
        ]
        pending = sum(entry.state == "candidate" for entry in entries)
        recall = next((item for item in reversed(self._snapshot.recalls) if item.session_id == self.session_id), None)
        recalled = len(recall.matches) if recall else 0
        self._view = "candidate" if pending else ("recalled" if recalled else "active")
        if self._snapshot.mode == "off":
            label = m.OFF_BADGE.bind()
        elif self._processing:
            label = m.PROCESSING.bind()
        elif pending:
            label = m.PENDING_BADGE.bind(pending=pending)
        elif recalled:
            label = m.RECALL_BADGE.bind(recalled=recalled)
        else:
            label = (m.INDICATOR_COMPACT if self._compact else m.INDICATOR).bind()
        summary = m.COUNTS.bind(
            active=sum(entry.state == "active" for entry in entries),
            candidates=pending,
            archived=sum(entry.state == "archived" for entry in entries),
        )
        localizer = self._locale_controller.localizer if self._locale_controller else None
        text = render_str(localizer, label) if localizer else format_message(label)
        tooltip = render_str(localizer, summary) if localizer else format_message(summary)
        if recalled:
            tooltip += "\n" + (
                render_str(localizer, m.RECALL_TIP.bind()) if localizer else format_message(m.RECALL_TIP.bind())
            )
        self.update(Text(text, style="bold" if pending and self._snapshot.mode != "off" else ""), layout=False)
        self.tooltip = Text(tooltip)

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.post_message(self.OpenRequested(self._view))
