# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Edit a memory without overwriting a live draft during asynchronous refreshes."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.widgets import Button, Checkbox, Collapsible, Label, Select, Static, TextArea

from chrys.app.tui.binding_display import CANCEL_BINDING, localized_binding
from chrys.app.tui.i18n import render_str
from chrys.app.tui.screens.dialogs.base import BaseDialog
from chrys.app.tui.widgets import EnhancedInput
from chrys.foundation.i18n import MessageDef, MessageRef
from chrys.foundation.i18n.formatting import format_message, sanitize_legacy_scalar
from chrys.foundation.models.personal_memory import FollowUpStatus, MemoryDraft, MemoryFollowUp, MemoryKind

from . import messages as m

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from textual.app import ComposeResult

    from chrys.app.tui.i18n import LocaleController


class PersonalMemoryEditor(BaseDialog[None]):
    CSS_PATH = "editor.tcss"
    BINDINGS: ClassVar[list] = [
        localized_binding("escape", "cancel", CANCEL_BINDING, show=False),
        localized_binding("ctrl+enter", "save", m.SAVE, show=False, priority=True),
    ]

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
        self._saving = False

    def _text(self, message: MessageDef | MessageRef) -> str:
        ref = message.bind() if isinstance(message, MessageDef) else message
        return render_str(self._locale_controller.localizer, ref) if self._locale_controller else format_message(ref)

    def compose(self) -> ComposeResult:
        draft = self._draft or MemoryDraft("", "", "", workspace=self._workspace)
        with VerticalGroup(id="memory-editor") as frame:
            frame.border_title = Text(self._text(m.EDIT if self._draft else m.NEW))
            with VerticalScroll(id="memory-editor-fields"):
                yield TextArea(draft.content, id="memory-edit-content", show_line_numbers=False)
                with HorizontalGroup(id="memory-edit-meta"):
                    yield Checkbox(Text(self._text(m.PROJECT)), value=bool(draft.workspace), id="memory-edit-project")
                with Collapsible(title=self._text(m.OPTIONS), collapsed=True, id="memory-edit-options"):
                    yield Label(Text(self._text(m.NAME)), id="memory-label-title", classes="memory-field-label")
                    yield EnhancedInput(draft.title, id="memory-edit-title", max_length=120)
                    yield Label(Text(self._text(m.KIND)), id="memory-label-kind", classes="memory-field-label")
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
                    yield Label(Text(self._text(m.WHEN)), id="memory-label-when", classes="memory-field-label")
                    yield EnhancedInput(draft.when_to_use, id="memory-edit-when", max_length=600)
                    yield Label(
                        Text(self._text(m.RECONSIDER)), id="memory-label-reconsider", classes="memory-field-label"
                    )
                    yield EnhancedInput(
                        draft.reconsider_when,
                        tooltip=self._text(m.RECONSIDER_TIP),
                        id="memory-edit-reconsider",
                        max_length=600,
                    )
                    yield Label(Text(self._text(m.TOPICS)), id="memory-label-topics", classes="memory-field-label")
                    yield EnhancedInput(
                        ", ".join(draft.topics),
                        tooltip=self._text(m.TERMS_TIP),
                        id="memory-edit-topics",
                        max_length=250,
                    )
                    yield Label(Text(self._text(m.ALIASES)), id="memory-label-aliases", classes="memory-field-label")
                    yield EnhancedInput(
                        ", ".join(draft.aliases),
                        tooltip=self._text(m.TERMS_TIP),
                        id="memory-edit-aliases",
                        max_length=490,
                    )
                    yield Checkbox(Text(self._text(m.ALWAYS)), value=draft.use == "always", id="memory-edit-always")
                    yield Checkbox(Text(self._text(m.TRACK)), value=draft.follow_up is not None, id="memory-edit-track")
                    with VerticalGroup(id="memory-edit-follow-up"):
                        follow = draft.follow_up or MemoryFollowUp()
                        yield Label(
                            Text(self._text(m.FOLLOW_UP_STATUS)), id="memory-label-status", classes="memory-field-label"
                        )
                        yield Select(
                            self._status_options(), value=follow.status, allow_blank=False, id="memory-edit-status"
                        )
                        yield Label(Text(self._text(m.NEXT_STEP)), id="memory-label-next", classes="memory-field-label")
                        yield EnhancedInput(follow.next_step, id="memory-edit-next", max_length=600)
                        yield Label(
                            Text(self._text(m.REMIND_AT)), id="memory-label-remind", classes="memory-field-label"
                        )
                        yield EnhancedInput(
                            follow.remind_at,
                            placeholder=self._text(m.DATE_FORMAT),
                            tooltip=self._text(m.REMIND_TIP),
                            id="memory-edit-remind",
                        )
            yield Static("", id="memory-edit-error", markup=False)
            with HorizontalGroup(id="memory-edit-buttons"):
                yield Button(Text(self._text(m.SAVE)), id="memory-edit-save", variant="primary")
                yield Button(Text(self._text(m.CANCEL)), id="memory-edit-cancel")

    def on_mount(self) -> None:
        if self._locale_controller:
            self._locale_controller.register_surface(self)
        self.query_one("#memory-edit-content", TextArea).border_title = Text(self._text(m.CONTENT))
        self.query_one("#memory-edit-content", TextArea).focus()
        self._fields_changed()

    def _status_options(self) -> list[tuple[str, str]]:
        return [
            (self._text(label), value)
            for value, label in (
                ("pending", m.PENDING),
                ("in_progress", m.IN_PROGRESS),
                ("waiting", m.WAITING),
                ("snoozed", m.SNOOZED),
                ("completed", m.COMPLETED),
                ("cancelled", m.CANCELLED),
            )
        ]

    @on(Select.Changed, "#memory-edit-kind")
    @on(Checkbox.Changed, "#memory-edit-track")
    def _fields_changed(self) -> None:
        if not self.is_mounted:
            return
        kind = self.query_one("#memory-edit-kind", Select).value
        self.query_one("#memory-edit-always").display = kind == "preference"
        self.query_one("#memory-edit-track").display = kind == "intention"
        self.query_one("#memory-edit-follow-up").display = (
            kind == "intention" and self.query_one("#memory-edit-track", Checkbox).value
        )

    def on_unmount(self) -> None:
        if self._locale_controller:
            self._locale_controller.unregister_surface(self)

    def refresh_localization(self) -> None:
        self.query_one("#memory-edit-reconsider").tooltip = self._text(m.RECONSIDER_TIP)
        for name, label in (
            ("title", m.NAME),
            ("kind", m.KIND),
            ("when", m.WHEN),
            ("reconsider", m.RECONSIDER),
            ("topics", m.TOPICS),
            ("aliases", m.ALIASES),
            ("status", m.FOLLOW_UP_STATUS),
            ("next", m.NEXT_STEP),
            ("remind", m.REMIND_AT),
        ):
            self.query_one(f"#memory-label-{name}", Label).update(Text(self._text(label)))
        self.query_one("#memory-editor").border_title = Text(self._text(m.EDIT if self._draft else m.NEW))
        self.query_one("#memory-edit-content", TextArea).border_title = Text(self._text(m.CONTENT))
        self.query_one("#memory-edit-options", Collapsible).title = self._text(m.OPTIONS)
        self.query_one("#memory-edit-project", Checkbox).label = Text(self._text(m.PROJECT))
        self.query_one("#memory-edit-save", Button).label = Text(self._text(m.SAVE))
        self.query_one("#memory-edit-cancel", Button).label = Text(self._text(m.CANCEL))
        self.query_one("#memory-edit-save").refresh(layout=True)
        self.query_one("#memory-edit-cancel").refresh(layout=True)
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
        kind_select.mutate_reactive(Select.value)
        for name in ("topics", "aliases"):
            self.query_one(f"#memory-edit-{name}").tooltip = self._text(m.TERMS_TIP)
        self.query_one("#memory-edit-remind", EnhancedInput).placeholder = self._text(m.DATE_FORMAT)
        self.query_one("#memory-edit-remind").tooltip = self._text(m.REMIND_TIP)
        for name, label in (("always", m.ALWAYS), ("track", m.TRACK)):
            self.query_one(f"#memory-edit-{name}", Checkbox).label = Text(self._text(label))
        status = self.query_one("#memory-edit-status", Select)
        value = status.value
        status.set_options(self._status_options())
        status.value = value
        status.mutate_reactive(Select.value)

    @on(Button.Pressed, "#memory-edit-save")
    async def action_save(self) -> None:
        if self._saving:
            return
        title = self.query_one("#memory-edit-title", EnhancedInput).value.strip()
        content = self.query_one("#memory-edit-content", TextArea).text.strip()
        if not content:
            self._field_error("content", m.REQUIRED)
            return
        when = self.query_one("#memory-edit-when", EnhancedInput).value.strip()
        kind = cast(MemoryKind, self.query_one("#memory-edit-kind", Select).value)
        terms: dict[str, tuple[str, ...]] = {}
        for name, minimum, maximum, error in (
            ("topics", 1, 40, m.BAD_TOPICS),
            ("aliases", 2, 80, m.BAD_ALIASES),
        ):
            field = self.query_one(f"#memory-edit-{name}", EnhancedInput)
            values = tuple(t.strip() for t in re.split(r"[,\uFF0C]", field.value) if t.strip())
            if len(values) > 6 or any(not minimum <= len(t) <= maximum for t in values):
                self._field_error(name, error)
                return
            terms[name] = values
        follow = None
        if kind == "intention" and self.query_one("#memory-edit-track", Checkbox).value:
            date = self.query_one("#memory-edit-remind", EnhancedInput).value.strip()
            if date:
                try:
                    date = datetime.fromisoformat(date).astimezone().isoformat()
                except ValueError:
                    self._field_error("remind", m.BAD_DATE)
                    return
            follow = MemoryFollowUp(
                cast(FollowUpStatus, self.query_one("#memory-edit-status", Select).value),
                self.query_one("#memory-edit-next", EnhancedInput).value.strip(),
                date,
            )
        self.query_one("#memory-edit-error").display = False
        self._saving = True
        self.query_one("#memory-editor-fields").disabled = True
        self.query_one("#memory-edit-save", Button).disabled = True
        try:
            error = await self._save_memory(
                MemoryDraft(
                    title or content.splitlines()[0][:120],
                    content,
                    when,
                    self.query_one("#memory-edit-reconsider", EnhancedInput).value.strip(),
                    kind,
                    self._workspace if self.query_one("#memory-edit-project", Checkbox).value else "",
                    topics=terms["topics"],
                    use="always"
                    if kind == "preference" and self.query_one("#memory-edit-always", Checkbox).value
                    else "contextual",
                    follow_up=follow,
                    relations=self._draft.relations if self._draft else (),
                    aliases=terms["aliases"],
                )
            )
        finally:
            self._saving = False
            self.query_one("#memory-editor-fields").disabled = False
            self.query_one("#memory-edit-save", Button).disabled = False
        if error:
            error_widget = self.query_one("#memory-edit-error", Static)
            error_widget.update(Text("⚠ " + self._text(m.ERROR.bind(error=sanitize_legacy_scalar(error)))))
            error_widget.display = True
        else:
            self.dismiss_when_topmost()

    def _field_error(self, name: str, message: MessageDef) -> None:
        if name != "content":
            self.query_one("#memory-edit-options", Collapsible).collapsed = False
        error = self.query_one("#memory-edit-error", Static)
        error.update(Text("⚠ " + self._text(message)))
        error.display = True
        field = self.query_one(f"#memory-edit-{name}")
        field.focus()
        field.scroll_visible(animate=False)

    @on(Collapsible.Expanded, "#memory-edit-options")
    @on(Collapsible.Collapsed, "#memory-edit-options")
    def _options_changed(self) -> None:
        self.set_class(not self.query_one("#memory-edit-options", Collapsible).collapsed, "-expanded")

    @on(Button.Pressed, "#memory-edit-cancel")
    def action_cancel(self) -> None:
        if not self._saving:
            self.dismiss_when_topmost(None)
