# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Edit a memory without overwriting a live draft during asynchronous refreshes."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.widgets import Button, Checkbox, Select, Static, TextArea

from chrys.app.tui.binding_display import CANCEL_BINDING, localized_binding
from chrys.app.tui.i18n import render_str
from chrys.app.tui.screens.dialogs.base import BaseDialog
from chrys.app.tui.widgets import EnhancedInput
from chrys.foundation.i18n import MessageDef, MessageRef
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryKind

from . import messages as m

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from textual.app import ComposeResult

    from chrys.app.tui.i18n import LocaleController


class PersonalMemoryEditor(BaseDialog[None]):
    CSS_PATH = "editor.tcss"
    BINDINGS: ClassVar[list] = [localized_binding("escape", "cancel", CANCEL_BINDING, show=False)]

    def __init__(
        self,
        *,
        workspace: str,
        save: Callable[[MemoryDraft], Awaitable[str]],
        draft: MemoryDraft | None = None,
        locale_controller: LocaleController | None = None,
    ):
        super().__init__(dismiss_on_backdrop=False)
        self._workspace = workspace
        self._draft = draft
        self._save_memory = save
        self._locale_controller = locale_controller

    def _text(self, message: MessageDef | MessageRef) -> str:
        ref = message.bind() if isinstance(message, MessageDef) else message
        return render_str(self._locale_controller.localizer, ref) if self._locale_controller else format_message(ref)

    def compose(self) -> ComposeResult:
        draft = self._draft or MemoryDraft("", "", "", workspace=self._workspace)
        with VerticalGroup(id="memory-editor") as frame:
            frame.border_title = Text(self._text(m.EDIT if self._draft else m.NEW))
            with VerticalScroll(id="memory-editor-fields"):
                yield EnhancedInput(draft.title, placeholder=self._text(m.NAME), id="memory-edit-title", max_length=120)
                with HorizontalGroup(id="memory-edit-meta"):
                    yield Select(
                        [
                            (self._text(label), kind)
                            for kind, label in (
                                ("decision", m.DECISION),
                                ("preference", m.PREFERENCE),
                                ("lesson", m.LESSON),
                                ("intention", m.INTENTION),
                            )
                        ],
                        value=draft.kind,
                        allow_blank=False,
                        id="memory-edit-kind",
                    )
                    yield Checkbox(Text(self._text(m.PROJECT)), value=bool(draft.workspace), id="memory-edit-project")
                yield Static(Text(self._text(m.CONTENT)), classes="memory-edit-label")
                yield TextArea(draft.content, id="memory-edit-content", show_line_numbers=False)
                yield Static(Text(self._text(m.WHEN)), classes="memory-edit-label")
                yield EnhancedInput(draft.when_to_use, id="memory-edit-when", max_length=600)
                yield Static(Text(self._text(m.RECONSIDER)), classes="memory-edit-label")
                yield EnhancedInput(draft.reconsider_when, id="memory-edit-reconsider", max_length=600)
                yield Static("", id="memory-edit-error", markup=False)
            with HorizontalGroup(id="memory-edit-buttons"):
                yield Button(Text(self._text(m.SAVE)), id="memory-edit-save", variant="primary")
                yield Button(Text(self._text(m.CANCEL)), id="memory-edit-cancel")

    def on_mount(self) -> None:
        if self._locale_controller:
            self._locale_controller.register_surface(self)
        self.query_one("#memory-edit-title", EnhancedInput).focus()

    def on_unmount(self) -> None:
        if self._locale_controller:
            self._locale_controller.unregister_surface(self)

    def refresh_localization(self) -> None:
        self.query_one("#memory-editor").border_title = Text(self._text(m.EDIT if self._draft else m.NEW))
        self.query_one("#memory-edit-title", EnhancedInput).placeholder = self._text(m.NAME)
        self.query_one("#memory-edit-project", Checkbox).label = Text(self._text(m.PROJECT))
        self.query_one("#memory-edit-save", Button).label = Text(self._text(m.SAVE))
        self.query_one("#memory-edit-cancel", Button).label = Text(self._text(m.CANCEL))
        for widget, label in zip(self.query(".memory-edit-label"), (m.CONTENT, m.WHEN, m.RECONSIDER), strict=True):
            cast(Static, widget).update(Text(self._text(label)))
        kind_select = self.query_one("#memory-edit-kind", Select)
        selected_kind = kind_select.value
        kind_select.set_options(
            [
                (self._text(label), kind)
                for kind, label in (
                    ("decision", m.DECISION),
                    ("preference", m.PREFERENCE),
                    ("lesson", m.LESSON),
                    ("intention", m.INTENTION),
                )
            ]
        )
        kind_select.value = selected_kind

    @on(Button.Pressed, "#memory-edit-save")
    async def _save(self) -> None:
        title = self.query_one("#memory-edit-title", EnhancedInput).value.strip()
        content = self.query_one("#memory-edit-content", TextArea).text.strip()
        when = self.query_one("#memory-edit-when", EnhancedInput).value.strip()
        if not title or not content or not when:
            self.query_one("#memory-edit-error", Static).update(Text(self._text(m.REQUIRED)))
            return
        error = await self._save_memory(
            MemoryDraft(
                title,
                content,
                when,
                self.query_one("#memory-edit-reconsider", EnhancedInput).value.strip(),
                cast(MemoryKind, self.query_one("#memory-edit-kind", Select).value),
                self._workspace if self.query_one("#memory-edit-project", Checkbox).value else "",
            )
        )
        if error:
            self.query_one("#memory-edit-error", Static).update(
                Text(self._text(m.ERROR.bind(error=sanitize_legacy_scalar(error))))
            )
        else:
            self.dismiss_when_topmost()

    @on(Button.Pressed, "#memory-edit-cancel")
    def action_cancel(self) -> None:
        self.dismiss_when_topmost(None)
