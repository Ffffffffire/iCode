# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""An event-fed note beside the buddy; private storage stays outside the UI."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual import on
from textual.containers import HorizontalGroup, VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button

from chrys.app.tui.i18n import render_str
from chrys.app.tui.personal_memory_messages import RECALL_TIP
from chrys.app.tui.util.visibility import set_rules_without_layout
from chrys.app.tui.widgets.selection import NonSelectableTextMixin
from chrys.foundation.i18n import MessageRef, msg
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import MemoryReviewNotice, MemorySnapshot, PersonalMemory
from chrys.service.personal_memory.organize import organize_ids

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.events import Click, DescendantFocus, Resize

    from chrys.app.tui.i18n import LocaleController

_TITLE = msg("tui.buddy.memory.title", fallback="This came to mind")
_RECALLED = msg("tui.buddy.memory.recalled", fallback="{recalled} notes for this turn")
_PENDING = msg("tui.buddy.memory.pending", fallback="Review {pending}")
_LIBRARY = msg("tui.buddy.memory.library", fallback="▤ Saved {total}")
_NOTICES_ON = msg("tui.buddy.memory.notices_on", fallback="Recall alerts on")
_NOTICES_OFF = msg("tui.buddy.memory.notices_off", fallback="Recall alerts off")
_PREVIOUS = msg("tui.buddy.memory.previous", fallback="Previous note")
_NEXT = msg("tui.buddy.memory.next", fallback="Next note")
_FOLLOW_UP = msg("tui.buddy.memory.follow_up", fallback="Still on your list")
_NOTICE_TIP = msg(
    "tui.buddy.memory.notice_tip", fallback="Notify on recall and weekly memory reviews. Buddy mute takes priority."
)
_ALERTS = msg("tui.buddy.memory.alerts", fallback="Alerts")
_WEEKLY = msg("tui.buddy.memory.weekly", fallback="Weekly memory review")
_WEEKLY_BODY = msg(
    "tui.buddy.memory.weekly_body",
    fallback="{count} memory to review together",
    plural_fallback="{count} memories to review together",
)
_WEEKLY_ARCHIVED = msg("tui.buddy.memory.weekly_archived", fallback="{archived} unreviewed suggestions archived")
_WEEKLY_ITEMS = msg("tui.buddy.memory.weekly_items", fallback="Related memories")
MEMORY_NOTICE = msg("tui.buddy.memory.notice", fallback="{name} found a note: {title}")


class _BuddyButton(NonSelectableTextMixin, Button):
    """Mouse actions leave typing focus alone; Tab still exposes a visible focus."""

    FOCUS_ON_CLICK = False


class _MemoryNote(_BuddyButton):
    """Fixed-size preview: resize the excerpt, never the surrounding conversation."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {"memory-note--title", "memory-note--body"}

    def __init__(self) -> None:
        super().__init__("", id="buddy-memory-item")
        self._title = ""
        self._body = ""

    def show_note(self, note: PersonalMemory | None) -> None:
        title = sanitize_legacy_scalar(note.draft.title) if note else ""
        body = (
            sanitize_legacy_scalar(
                note.draft.follow_up.next_step or note.draft.content if note.draft.follow_up else note.draft.content
            )
            if note
            else ""
        )
        self.show_text(title, body)

    def show_text(self, title: str, body: str) -> None:
        if (title, body) == (self._title, self._body):
            return
        self._title, self._body = title, body
        self.label = Text(f"{title}\n{body}")
        self.tooltip = Text(f"{title}\n\n{body}")

    def render(self) -> Text:
        # Button's native per-line padding is separate from the widget gutter.
        width = max(1, self.outer_size.width - self.styles.gutter.width - 2 * self.styles.line_pad)
        title = Text(" ".join(self._title.split()), style=self.get_component_rich_style("memory-note--title"))
        title.truncate(width, overflow="ellipsis")
        body = Text(" ".join(self._body.split()), style=self.get_component_rich_style("memory-note--body"))
        lines = body.wrap(self.app.console, width, overflow="fold")
        if len(lines) > 3:
            lines[2].truncate(max(0, width - 1))
            lines[2].append("…")
        return Text.assemble(title, "\n", Text("\n").join(lines[:3]))


class BuddyMemoryCard(Widget):
    ALLOW_SELECT = False

    DEFAULT_CSS = """
    BuddyMemoryCard { height: 9; width: 100%; margin: 1 0 0 0; }
    BuddyMemoryCard Button.-style-default {
        width: 100%; min-width: 0; height: 1; min-height: 1;
        border: none; padding: 0; text-style: none; text-align: center; content-align: center middle;
        background: transparent; color: $text-muted; text-wrap: nowrap; text-overflow: ellipsis;
    }
    BuddyMemoryCard Button.-style-default:hover {
        background: $block-hover-background; color: $text;
    }
    BuddyMemoryCard Button.-style-default:focus {
        background: $block-cursor-background; color: $block-cursor-foreground; text-style: bold underline;
    }
    BuddyMemoryCard Button.-style-default:disabled {
        background: transparent; color: $text-disabled; opacity: 100%;
    }
    BuddyMemoryCard #buddy-memory-note { height: 8; overflow: hidden; }
    BuddyMemoryCard #buddy-memory-item {
        height: 6; border: round $tui-border-accent $border-opacity; background: $surface;
        border-title-align: left; border-title-color: $accent;
        text-align: left; content-align: left top;
    }
    BuddyMemoryCard #buddy-memory-item:hover, BuddyMemoryCard #buddy-memory-item:focus {
        border: round $tui-border-accent; background: $surface;
    }
    BuddyMemoryCard #buddy-memory-item:focus { text-style: underline; }
    BuddyMemoryCard _MemoryNote > .memory-note--title { color: $text; text-style: bold; }
    BuddyMemoryCard _MemoryNote > .memory-note--body { color: $text-muted; }
    BuddyMemoryCard HorizontalGroup { height: 1; }
    BuddyMemoryCard #buddy-memory-pager { margin-bottom: 1; }
    BuddyMemoryCard #buddy-memory-prev, BuddyMemoryCard #buddy-memory-next { width: 4; color: $accent; }
    BuddyMemoryCard #buddy-memory-counts { width: 1fr; }
    BuddyMemoryCard #buddy-memory-library, BuddyMemoryCard #buddy-memory-review { width: 1fr; }
    BuddyMemoryCard #buddy-memory-review { color: $primary; }
    BuddyMemoryCard #buddy-memory-notices { width: auto; min-width: 3; padding: 0 1; }
    BuddyMemoryCard #buddy-memory-notices.-enabled { color: $primary; }
    """

    class OpenRequested(Message):
        def __init__(self, view: str, memory_id: str = "", *, dismiss_review: bool = False) -> None:
            super().__init__()
            self.view = view
            self.memory_id = memory_id
            self.dismiss_review = dismiss_review

    class NotificationsRequested(Message):
        def __init__(self, enabled: bool) -> None:
            super().__init__()
            self.enabled = enabled

    def __init__(self, *, locale_controller: LocaleController | None = None) -> None:
        super().__init__(id="buddy-memory")
        self._locale_controller = locale_controller
        self._snapshot = MemorySnapshot()
        self._workspace = ""
        self._view = "active"
        self._notes: tuple[PersonalMemory, ...] = ()
        self._position = 0
        self._compact = False
        self._recalled = self._pending = self._active = 0
        self._selection_key: tuple[str, ...] = ()
        self._notice_key: tuple[object, ...] = ()
        self._shown: dict[str, str] = {}
        self._weekly: MemoryReviewNotice | None = None

    def _text(self, reference: MessageRef) -> str:
        return (
            render_str(self._locale_controller.localizer, reference)
            if self._locale_controller
            else format_message(reference)
        )

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="buddy-memory-note"):
            yield _MemoryNote()
            with HorizontalGroup(id="buddy-memory-pager"):
                yield _BuddyButton("\u2039", id="buddy-memory-prev", compact=True)
                yield _BuddyButton("", id="buddy-memory-counts", compact=True)
                yield _BuddyButton("\u203a", id="buddy-memory-next", compact=True)
        with HorizontalGroup(id="buddy-memory-actions"):
            yield _BuddyButton("", id="buddy-memory-library", compact=True)
            yield _BuddyButton("", id="buddy-memory-review", compact=True)
            yield _BuddyButton("", id="buddy-memory-notices", compact=True)

    def on_mount(self) -> None:
        self.refresh_localization()

    def on_resize(self, event: Resize) -> None:
        compact = event.size.width < 32
        if compact != self._compact:
            self._compact = compact
            self.refresh_localization()

    def update_memory(self, snapshot: MemorySnapshot, session_id: str, workspace: str, *, announce: bool) -> str:
        self._snapshot = snapshot
        self._workspace = os.path.normcase(os.path.abspath(workspace)) if workspace else ""
        entries = {e.id: e for e in snapshot.entries if not e.draft.workspace or e.draft.workspace == self._workspace}
        recall = next((r for r in reversed(snapshot.recalls) if r.session_id == session_id), None)
        matches = (
            tuple(
                m
                for m in recall.matches
                if m.memory_id in entries
                and entries[m.memory_id].state == "active"
                and entries[m.memory_id].revision == m.revision
                and m.memory_id not in recall.excluded_ids
            )
            if recall and snapshot.mode != "off"
            else ()
        )
        pending = tuple(e for e in entries.values() if e.state == "candidate")
        self._recalled, self._pending = len(matches), len(pending)
        self._active = sum(e.state == "active" for e in entries.values())
        old_id = self._notes[self._position].id if self._notes else ""
        now = datetime.now(UTC)
        due = (
            tuple(
                e
                for e in entries.values()
                if e.state == "active"
                and (not recall or e.id not in recall.excluded_ids)
                and e.draft.follow_up
                and e.draft.follow_up.status not in ("completed", "cancelled")
                and e.draft.follow_up.remind_at
                and datetime.fromisoformat(e.draft.follow_up.remind_at) <= now
            )
            if snapshot.mode == "auto"
            else ()
        )
        self._weekly = snapshot.review_notice if snapshot.buddy_notifications else None
        if (
            self._weekly
            and not (set(self._weekly.memory_ids) & entries.keys())
            and not self._weekly.archived_candidates
        ):
            self._weekly = None
        self._notes = tuple(entries[m.memory_id] for m in matches) or due[:1]
        self._view = (
            "recalled"
            if matches
            else ("followups" if due else "candidate" if pending else "all" if self._weekly else "active")
        )
        selection_key = (session_id, self._workspace, self._view, recall.query if matches and recall else "")
        self._position = (
            next((i for i, e in enumerate(self._notes) if e.id == old_id), 0)
            if selection_key == self._selection_key
            else 0
        )
        self._selection_key = selection_key
        key = (
            session_id,
            recall.query if recall else "",
            tuple((m.memory_id, m.revision) for m in matches),
            self._weekly.created_at if self._weekly else "",
        )
        notice = (
            sanitize_legacy_scalar(self._notes[0].draft.title)
            if announce and matches and key != self._notice_key and snapshot.buddy_notifications
            else ""
        )
        if announce and not matches and self._weekly and key != self._notice_key:
            notice = self._text(_WEEKLY.bind())
        self._notice_key = key
        if self.is_mounted:
            self.refresh_localization()
        return notice

    def _label(self, selector: str, label: str) -> None:
        if self._shown.get(selector) != label:
            self._shown[selector] = label
            button = self.query_one(selector, Button)
            button.label = Text(label, no_wrap=True, overflow="ellipsis")
            if button.styles.width is not None and button.styles.width.is_auto:
                button.refresh(layout=True)

    def refresh_localization(self) -> None:
        item = self.query_one(_MemoryNote)
        note = self._notes[self._position] if self._notes else None
        weekly = self._weekly if note is None else None
        title = self._text((_WEEKLY if weekly else _FOLLOW_UP if note and note.draft.follow_up else _TITLE).bind())
        if self._shown.get("heading") != title:
            self._shown["heading"] = title
            item.border_title = title
        item.show_note(note)
        if weekly:
            body = self._text(_WEEKLY_BODY.bind(count=len(weekly.memory_ids))) if weekly.memory_ids else ""
            if weekly.archived_candidates:
                body = "\n".join(
                    filter(None, (body, self._text(_WEEKLY_ARCHIVED.bind(archived=weekly.archived_candidates))))
                )
            item.show_text(weekly.topic or self._text(_WEEKLY_ITEMS.bind()), body)
        item.disabled = note is None and weekly is None
        self._label("#buddy-memory-counts", f"{self._position + 1} / {len(self._notes)}" if note else "")
        self.query_one("#buddy-memory-counts", Button).tooltip = Text(
            self._text(_PENDING.bind(pending=self._pending))
            if self._view == "candidate"
            else self._text(_FOLLOW_UP.bind())
            if self._view == "followups"
            else f"{self._text(_RECALLED.bind(recalled=self._recalled))}\n{self._text(RECALL_TIP.bind())}"
        )
        for selector, definition in (("#buddy-memory-prev", _PREVIOUS), ("#buddy-memory-next", _NEXT)):
            button = self.query_one(selector, Button)
            button.tooltip = Text(self._text(definition.bind()))
            button.disabled = len(self._notes) < 2
        review_count = len(self._weekly.memory_ids) if self._weekly else self._pending
        pending = self._text(_PENDING.bind(pending=review_count)) if review_count else self._text(_WEEKLY.bind())
        library = self._text(_LIBRARY.bind(total=self._active))
        self._label(
            "#buddy-memory-review",
            f"◇ {review_count}" if self._compact and review_count else "◇" if self._compact else f"◇ {pending}",
        )
        self._label("#buddy-memory-library", f"▤ {self._active}" if self._compact else library)
        self.query_one("#buddy-memory-review", Button).tooltip = Text(pending)
        self.query_one("#buddy-memory-library", Button).tooltip = Text(library)
        notices = self.query_one("#buddy-memory-notices", Button)
        symbol = "●" if self._snapshot.buddy_notifications else "○"
        self._label("#buddy-memory-notices", symbol if self._compact else f"{symbol} {self._text(_ALERTS.bind())}")
        notices.set_class(self._snapshot.buddy_notifications, "-enabled")
        notices.tooltip = Text(
            f"{self._text((_NOTICES_ON if self._snapshot.buddy_notifications else _NOTICES_OFF).bind())}\n"
            f"{self._text(_NOTICE_TIP.bind())}"
        )
        notices.disabled = False
        # Fixed chrome can collapse without recomputing the whole transcript.
        container = self.query_one("#buddy-memory-note")
        set_rules_without_layout(
            heights=[(container, 8 if note or weekly else 0), (self, 9 if note or weekly else 1)],
            visibility=[
                (container, note is not None or weekly is not None),
                (self.query_one("#buddy-memory-review"), self._weekly is not None),
            ],
        )

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if button_id in ("buddy-memory-prev", "buddy-memory-next"):
            if self._notes:
                self._position = (self._position + (-1 if button_id == "buddy-memory-prev" else 1)) % len(self._notes)
                self.refresh_localization()
        elif button_id == "buddy-memory-notices":
            event.button.disabled = True
            self.post_message(self.NotificationsRequested(not self._snapshot.buddy_notifications))
        elif button_id == "buddy-memory-library":
            self.post_message(self.OpenRequested("active"))
        elif button_id == "buddy-memory-review" and self._weekly is not None:
            visible = {
                e.id for e in self._snapshot.entries if not e.draft.workspace or e.draft.workspace == self._workspace
            }
            members = visible.intersection(self._weekly.memory_ids)
            self.post_message(
                self.OpenRequested(
                    "organize"
                    if members.intersection(organize_ids(self._snapshot))
                    else "candidate"
                    if self._pending
                    else "all",
                    dismiss_review=True,
                )
            )
        elif button_id == "buddy-memory-counts":
            self.post_message(self.OpenRequested(self._view))
        elif self._notes:
            self.post_message(self.OpenRequested(self._view, self._notes[self._position].id))
        elif self._weekly:
            self.post_message(self.OpenRequested(self._view, dismiss_review=True))

    def on_click(self, event: Click) -> None:
        # Memory controls must not bubble into BuddyPanel's click-to-pet action.
        event.stop()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        # The main screen redirects display-only sidebar focus to the composer.
        # These controls must remain reachable with Tab.
        event.stop()
