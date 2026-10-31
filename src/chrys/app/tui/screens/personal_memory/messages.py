# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""User-facing personal memory labels."""

from __future__ import annotations

from chrys.foundation.i18n import msg

TITLE = msg("tui.personal_memory.title", fallback="Personal Memory")
SEARCH = msg("tui.personal_memory.search", fallback="Search memories")
ACTIVE = msg("tui.personal_memory.active", fallback="Active")
CANDIDATE = msg("tui.personal_memory.candidate", fallback="Suggestions")
ARCHIVED = msg("tui.personal_memory.archived", fallback="Archived")
RECALLED = msg("tui.personal_memory.recalled", fallback="Latest recall")
ALL = msg("tui.personal_memory.all", fallback="All memories")
AUTO = msg("tui.personal_memory.auto", fallback="Automatic recall")
MANUAL = msg("tui.personal_memory.manual", fallback="Recall on request")
OFF = msg("tui.personal_memory.off", fallback="Memory off")
CAPTURE = msg("tui.personal_memory.capture", fallback="Allow suggestions")
NEW = msg("tui.personal_memory.new", fallback="+ New")
EDIT = msg("tui.personal_memory.edit", fallback="Edit")
ACCEPT = msg("tui.personal_memory.accept", fallback="Activate")
ARCHIVE = msg("tui.personal_memory.archive", fallback="Archive")
FORGET = msg("tui.personal_memory.forget", fallback="Forget")
REFRESH = msg("tui.personal_memory.refresh", fallback="Refresh")
CLOSE = msg("tui.personal_memory.close", fallback="Close")
SAVE = msg("tui.personal_memory.save", fallback="Save")
CANCEL = msg("tui.personal_memory.cancel", fallback="Cancel")
WHEN = msg("tui.personal_memory.when", fallback="When to use")
RECONSIDER = msg("tui.personal_memory.reconsider", fallback="Reconsider when")
SOURCE = msg("tui.personal_memory.source", fallback="Source")
HISTORY = msg("tui.personal_memory.history", fallback="Earlier revisions")
PERSONAL = msg("tui.personal_memory.personal", fallback="Across projects")
PROJECT = msg("tui.personal_memory.project", fallback="This project only")
DECISION = msg("tui.personal_memory.decision", fallback="Decision")
PREFERENCE = msg("tui.personal_memory.preference", fallback="Preference")
LESSON = msg("tui.personal_memory.lesson", fallback="Lesson")
INTENTION = msg("tui.personal_memory.intention", fallback="Intention")
NAME = msg("tui.personal_memory.name", fallback="Title")
CONTENT = msg("tui.personal_memory.content", fallback="Memory and rationale")
EMPTY = msg(
    "tui.personal_memory.empty", fallback="No memories here. Add one or review a suggestion from a conversation."
)
NO_RECALL = msg("tui.personal_memory.no_recall", fallback="No memories recalled for this task.")
MATCHED = msg("tui.personal_memory.matched", fallback="Matched: {terms}")
STALE = msg(
    "tui.personal_memory.stale", fallback="This task recalled revision {revision}; the memory has since changed."
)
REPLACEMENT = msg("tui.personal_memory.replacement", fallback="Proposed correction to {title}")
COUNTS = msg("tui.personal_memory.counts", fallback="{active} active · {candidates} suggestions · {archived} archived")
FORGET_CONFIRM = msg(
    "tui.personal_memory.forget_confirm", fallback="Forget “{title}”, its revisions and pending corrections?"
)
ERROR = msg("tui.personal_memory.error", fallback="Memory action failed: {error}")
REQUIRED = msg("tui.personal_memory.required", fallback="Enter a title, memory and when to use it.")
SAVED_BY_USER = msg("tui.personal_memory.saved_by_user", fallback="Saved by you")
USER_SOURCE = msg("tui.personal_memory.user_source", fallback="User message")
ASSISTANT_SOURCE = msg("tui.personal_memory.assistant_source", fallback="Assistant message · review the claim")
CAPTURE_TIP = msg(
    "tui.personal_memory.capture_tip",
    fallback="The agent can suggest memories with source quotes. Only activated memories are recalled automatically.",
)
MODE_TIP = msg(
    "tui.personal_memory.mode_tip",
    fallback="Changes apply to the next turn. Recall on request lets the agent search when asked; off disables recall and suggestions.",
)
