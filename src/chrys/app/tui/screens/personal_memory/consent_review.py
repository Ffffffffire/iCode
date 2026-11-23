# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Review proposals that wait for consent, without leaving the conversation.

The footer badge and ``/memory pending`` open this modal. Each row shows what
would be written and which words it came from, so confirming is an informed
click rather than a blind yes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from chrys.app.tui.behaviors.insert_clipboard import INSERT_CLIPBOARD_BINDINGS, InsertClipboardScreenMixin
from chrys.app.tui.binding_display import CLOSE_BINDING, localized_binding
from chrys.app.tui.i18n import render_str, widget_localizer
from chrys.app.tui.util.source_text import sanitize_source_text
from chrys.foundation.events.personal_memory import PersonalMemoryCommand

from . import messages as m

if TYPE_CHECKING:
    from chrys.foundation.events.bus import EventBus
    from chrys.foundation.i18n import MessageRef
    from chrys.service.personal_memory.consent import PendingConsent


class ConsentReviewScreen(InsertClipboardScreenMixin, ModalScreen[None]):
    """List waiting proposals; confirm or drop them in one action."""

    DEFAULT_CSS = """
    ConsentReviewScreen { align: center middle; }
    ConsentReviewScreen > Vertical {
        width: 90; max-width: 90%; height: auto; max-height: 80%;
        border: round $tui-border-accent; background: $surface; padding: 1 2;
    }
    ConsentReviewScreen #consent-title { text-style: bold; }
    ConsentReviewScreen #consent-list { height: auto; max-height: 18; }
    ConsentReviewScreen .consent-row { padding: 0 0 1 0; }
    ConsentReviewScreen #consent-actions { height: auto; padding-top: 1; }
    ConsentReviewScreen #consent-empty { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        localized_binding("escape", "close", CLOSE_BINDING),
        localized_binding("y", "confirm_all", m.CONSENT_CONFIRM_BINDING),
        localized_binding("n", "decline_all", m.CONSENT_DROP_BINDING),
        *INSERT_CLIPBOARD_BINDINGS,
    ]

    def __init__(self, *, bus: EventBus, session_id: str) -> None:
        super().__init__()
        self._bus = bus
        self._session_id = session_id

    def _text(self, message: MessageRef) -> str:
        return render_str(widget_localizer(self), message)

    def _waiting(self) -> tuple[PendingConsent, ...]:
        from chrys.service.personal_memory.consent import shared_queue

        return shared_queue().pending(self._session_id)

    def compose(self) -> ComposeResult:
        waiting = self._waiting()
        with Vertical(id="consent-frame") as frame:
            frame.border_title = Text(self._text(m.CONSENT_REVIEW_TITLE.bind()))
            yield Static(self._text(m.CONSENT_REVIEW_COUNT.bind(count=len(waiting))), id="consent-title")
            with VerticalScroll(id="consent-list"):
                empty = Static(self._text(m.CONSENT_EMPTY.bind()), id="consent-empty")
                empty.display = not waiting
                yield empty
                for index, item in enumerate(waiting, start=1):
                    yield self._row(item, index)
            with HorizontalGroup(id="consent-actions"):
                yield Button(Text(self._text(m.CONSENT_SAVE_ALL.bind())), id="consent-confirm", variant="primary")
                yield Button(Text(self._text(m.CONSENT_DROP_ALL.bind())), id="consent-decline")

    def _row(self, item: PendingConsent, index: int) -> Static:
        draft = item.draft
        body = Text()
        body.append(f"{index}. ", style="bold")
        body.append(sanitize_source_text(draft.title), style="bold")
        body.append("\n")
        body.append(sanitize_source_text(draft.content))
        if item.span:
            body.append("\n")
            body.append(self._text(m.CONSENT_SPAN.bind(span=sanitize_source_text(item.span))), style="dim")
        row = Static(body, classes="consent-row")
        row.tooltip = Text(sanitize_source_text(draft.when_to_use or draft.title))
        return row

    async def action_close(self) -> None:
        self.dismiss(None)

    async def action_confirm_all(self) -> None:
        await self._answer(accept=True)

    async def action_decline_all(self) -> None:
        await self._answer(accept=False)

    async def _answer(self, *, accept: bool) -> None:
        awaiting = self._waiting()
        if not awaiting:
            self.dismiss(None)
            return
        for item in awaiting:
            await self._bus.publish(
                PersonalMemoryCommand(
                    session_id=self._session_id,
                    action="consent_confirm" if accept else "consent_decline",
                    consent_id=item.id,
                )
            )
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "consent-confirm":
            await self.action_confirm_all()
        elif event.button.id == "consent-decline":
            await self.action_decline_all()
