# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""User-facing personal memory labels."""

from __future__ import annotations

from chrys.foundation.i18n import msg

TITLE = msg("tui.personal_memory.title", fallback="Personal Memory")
SEARCH = msg("tui.personal_memory.search", fallback="Search memories")
ACTIVE = msg("tui.personal_memory.active", fallback="Saved")
CANDIDATE = msg("tui.personal_memory.candidate", fallback="Review")
ARCHIVED = msg("tui.personal_memory.archived", fallback="Paused")
RECALLED = msg("tui.personal_memory.recalled", fallback="This turn")
ALL = msg("tui.personal_memory.all", fallback="All")
AUTO = msg("tui.personal_memory.auto", fallback="Automatic recall")
MANUAL = msg("tui.personal_memory.manual", fallback="Recall on request")
OFF = msg("tui.personal_memory.off", fallback="Memory off")
CAPTURE = msg("tui.personal_memory.capture", fallback="Review before saving")
CAPTURE_EXPLICIT = msg("tui.personal_memory.capture_explicit", fallback="Only when asked")
CAPTURE_AUTO = msg("tui.personal_memory.capture_auto", fallback="Remember clear preferences")
NEW = msg("tui.personal_memory.new", fallback="+ New")
EDIT = msg("tui.personal_memory.edit", fallback="Edit")
ACCEPT = msg("tui.personal_memory.accept", fallback="Remember")
ARCHIVE = msg("tui.personal_memory.archive", fallback="Pause")
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
CONTENT = msg("tui.personal_memory.content", fallback="What should be remembered?")
EMPTY = msg("tui.personal_memory.empty", fallback="No memories in this view.")
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
REQUIRED = msg("tui.personal_memory.required", fallback="Write something to remember.")
SAVED_BY_USER = msg("tui.personal_memory.saved_by_user", fallback="Saved by you")
USER_SOURCE = msg("tui.personal_memory.user_source", fallback="User message")
ASSISTANT_SOURCE = msg("tui.personal_memory.assistant_source", fallback="Assistant message · review the claim")
CAPTURE_TIP = msg(
    "tui.personal_memory.capture_tip",
    fallback="Only when asked adds no automatic model call. Other modes check each new message using the current model. Inferred lessons always need review.",
)
MODE_TIP = msg(
    "tui.personal_memory.mode_tip",
    fallback="Changes apply to the next turn. Recall on request lets the agent search when asked; off disables recall and suggestions.",
)
OPTIONS = msg("tui.personal_memory.options", fallback="More options")
IGNORE = msg("tui.personal_memory.ignore", fallback="Skip")
RESTORE = msg("tui.personal_memory.restore", fallback="Restore")
RECALL_DETAILS = msg("tui.personal_memory.recall_details", fallback="Why it was selected")
RECALL_TIP = msg(
    "tui.personal_memory.recall_tip",
    fallback="Provided to the agent for reference. This does not confirm it was applied in the answer.",
)
INDICATOR = msg("tui.personal_memory.indicator", fallback="Memory")
INDICATOR_COMPACT = msg("tui.personal_memory.indicator_compact", fallback="Mem")
PENDING_BADGE = msg("tui.personal_memory.pending_badge", fallback="Memory · Review {pending}")
RECALL_BADGE = msg("tui.personal_memory.recall_badge", fallback="Memory · {recalled} sent")
OFF_BADGE = msg("tui.personal_memory.off_badge", fallback="Memory · Off")
PROCESSING = msg("tui.personal_memory.processing", fallback="Memory · Checking")
REMEMBERED = msg("tui.personal_memory.remembered", fallback="Remembered: {title}")
PROPOSED = msg("tui.personal_memory.proposed", fallback="Memory ready for review: {title}")
