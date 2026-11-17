# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""A quiet memory entry in the existing footer, without changing transcript geometry."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING

from rich.text import Text
from textual.markup import escape
from textual.message import Message
from textual.reactive import reactive

from chrys.app.tui.i18n import render_str
from chrys.app.tui.personal_memory_messages import RECALL_TIP
from chrys.app.tui.util.static_update import update_static_in_place
from chrys.app.tui.widgets.selection import NonSelectableStatic
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import MemorySnapshot
from chrys.service.personal_memory.lifecycle import health

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
    PersonalMemoryIndicator.-failed { background: $error 15%; color: $error; }
    PersonalMemoryIndicator.-capacity { background: $warning 15%; color: $warning; }
    PersonalMemoryIndicator.-review { background: $primary 15%; color: $primary; text-style: bold; }
    """

    session_id: reactive[str] = reactive("", repaint=False)
    workspace_cwd: reactive[str] = reactive("", repaint=False)

    class OpenRequested(Message):
        def __init__(self, view: str) -> None:
            super().__init__()
            self.view = view

    class StateChanged(Message):
        def __init__(self, snapshot: MemorySnapshot, session_id: str, workspace: str, *, announce: bool) -> None:
            super().__init__()
            self.snapshot = snapshot
            self.session_id = session_id
            self.workspace = workspace
            self.announce = announce

    def __init__(self, *, bus: EventBus, workspace: str, locale_controller: LocaleController | None = None) -> None:
        super().__init__("", markup=False)
        self._bus = bus
        self._workspace = workspace
        self._locale_controller = locale_controller
        self._snapshot = MemorySnapshot()
        self._view = ""
        self._compact = False
        self._failed_title = ""
        self._failure_code = ""

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
        if event.snapshot is not None and event.snapshot.generation >= self._snapshot.generation:
            self._snapshot = event.snapshot
            if not self._failed_title and self._failure_code == "memory_unavailable":
                self._failure_code = ""
            saved = next((item for item in event.snapshot.entries if item.id == event.saved_memory_id), None)
            if saved is not None:
                self._failed_title = ""
                self._failure_code = ""
                if event.saved_changed:
                    notice = (m.PROPOSED if saved.state == "candidate" else m.REMEMBERED).bind(
                        title=sanitize_legacy_scalar(saved.draft.title)
                    )
                    localizer = self._locale_controller.localizer if self._locale_controller else None
                    self.notify(escape(render_str(localizer, notice) if localizer else format_message(notice)))
        if event.attempted_title:
            self._failed_title = sanitize_legacy_scalar(event.attempted_title)
            self._failure_code = event.error_code
        elif event.error:
            if event.error_code == "memory_unavailable" and not self._failed_title:
                self._failure_code = event.error_code
            notice = m.failure_message(event.error_code).bind()
            localizer = self._locale_controller.localizer if self._locale_controller else None
            self.notify(
                escape(render_str(localizer, notice) if localizer else format_message(notice)), severity="warning"
            )
        self.refresh_localization(
            announce_recall=bool(
                event.snapshot is not None
                and event.snapshot.generation >= self._snapshot.generation
                and not event.request_id
                and not event.saved_memory_id
                and not event.error
            )
        )

    def watch_session_id(self) -> None:
        self._failed_title = ""
        self._failure_code = ""
        if self.is_mounted:
            self.refresh_localization()
            self.run_worker(self._load, group="personal-memory-status", exclusive=True)

    def watch_workspace_cwd(self) -> None:
        if self.is_mounted:
            self.refresh_localization()

    def set_compact(self, compact: bool) -> None:
        if self._compact != compact:
            self._compact = compact
            self.refresh_localization()

    def refresh_localization(self, *, announce_recall: bool = False) -> None:
        workspace = os.path.normcase(os.path.abspath(self.workspace_cwd or self._workspace))
        entries = [
            entry for entry in self._snapshot.entries if not entry.draft.workspace or entry.draft.workspace == workspace
        ]
        pending = sum(entry.state == "candidate" for entry in entries)
        recall = next((item for item in reversed(self._snapshot.recalls) if item.session_id == self.session_id), None)
        recalled = len(recall.matches) if recall else 0
        status = health(replace(self._snapshot, entries=tuple(entries)))
        weekly = self._snapshot.buddy_notifications and self._snapshot.review_notice is not None
        if self._failed_title:
            label = m.FAIL_BADGE.bind()
            state = "failed"
        elif self._failure_code == "memory_unavailable":
            label = m.UNAVAILABLE_BADGE.bind()
            state = "failed"
        elif self._snapshot.mode == "off":
            label = m.OFF_BADGE.bind()
            state = "quiet"
        elif status.needs_review:
            label = m.CAPACITY_BADGE.bind()
            state = "capacity"
        elif pending and weekly:
            label = m.PENDING_BADGE.bind(pending=pending)
            state = "review"
        elif recalled:
            label = m.RECALL_BADGE.bind(recalled=recalled)
            state = "quiet"
        else:
            label = (m.INDICATOR_COMPACT if self._compact else m.INDICATOR).bind()
            state = "quiet"
        # Only the review badge (health().needs_review) opens the organize queue;
        # pending, off and failure states keep their existing targets.
        self._view = (
            "organize"
            if state == "capacity"
            else "candidate"
            if weekly and pending
            else "recalled"
            if recalled
            else "active"
        )
        for name in ("failed", "capacity", "review"):
            self.set_class(state == name, f"-{name}")
        summary = m.COUNTS.bind(
            active=sum(entry.state == "active" for entry in entries),
            candidates=pending,
            archived=sum(entry.state == "archived" for entry in entries),
        )
        localizer = self._locale_controller.localizer if self._locale_controller else None
        text = render_str(localizer, label) if localizer else format_message(label)
        tooltip = render_str(localizer, summary) if localizer else format_message(summary)
        if self._failed_title:
            reason = m.failure_message(self._failure_code)
            refs = (m.SAVE_FAILED.bind(title=self._failed_title), reason.bind())
            tooltip = "\n".join(render_str(localizer, ref) if localizer else format_message(ref) for ref in refs)
        elif self._failure_code == "memory_unavailable":
            ref = m.FAIL_UNAVAILABLE.bind()
            tooltip = render_str(localizer, ref) if localizer else format_message(ref)
        elif status.needs_review:
            ref = m.CAPACITY_WARNING.bind()
            tooltip += "\n" + (render_str(localizer, ref) if localizer else format_message(ref))
        if recalled:
            tooltip += "\n" + (
                render_str(localizer, RECALL_TIP.bind()) if localizer else format_message(RECALL_TIP.bind())
            )
        update_static_in_place(self, Text(text))
        self.tooltip = Text(tooltip)
        self.post_message(self.StateChanged(self._snapshot, self.session_id, workspace, announce=announce_recall))

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.post_message(self.OpenRequested(self._view))
