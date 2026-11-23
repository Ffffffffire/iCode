# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""User-facing personal memory labels."""

from __future__ import annotations

from chrys.foundation.i18n import MessageDef, msg

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
RECONSIDER = msg("tui.personal_memory.reconsider", fallback="When this no longer applies")
RECONSIDER_TIP = msg(
    "tui.personal_memory.reconsider_tip",
    fallback="For example: use sparse slides for distant projection. Recheck or update the memory in these situations; it is not deleted automatically.",
)
SOURCE = msg("tui.personal_memory.source", fallback="Source")
HISTORY = msg("tui.personal_memory.history", fallback="Earlier revisions")
PERSONAL = msg("tui.personal_memory.personal", fallback="Across projects")
PROJECT = msg("tui.personal_memory.project", fallback="This project only")
DECISION = msg("tui.personal_memory.decision", fallback="Decision")
PREFERENCE = msg("tui.personal_memory.preference", fallback="Preference")
LESSON = msg("tui.personal_memory.lesson", fallback="Lesson")
INTENTION = msg("tui.personal_memory.intention", fallback="Intention")
NAME = msg("tui.personal_memory.name", fallback="Title")
KIND = msg("tui.personal_memory.kind", fallback="Type")
FOLLOW_UP_STATUS = msg("tui.personal_memory.follow_up_status", fallback="Status")
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
    "tui.personal_memory.forget_confirm",
    fallback="Forget “{title}”, its revisions, activity and {count} dependent memory?",
    plural_fallback="Forget “{title}”, its revisions, activity and {count} dependent memories?",
)
ERROR = msg("tui.personal_memory.error", fallback="Memory action failed: {error}")
REQUIRED = msg("tui.personal_memory.required", fallback="Write something to remember.")
SAVED_BY_USER = msg("tui.personal_memory.saved_by_user", fallback="Saved by you")
USER_SOURCE = msg("tui.personal_memory.user_source", fallback="User message")
ASSISTANT_SOURCE = msg("tui.personal_memory.assistant_source", fallback="Assistant message · review the claim")
TOOL_SOURCE = msg("tui.personal_memory.tool_source", fallback="Tool result")
CAPTURE_TIP = msg(
    "tui.personal_memory.capture_tip",
    fallback="The agent writes through tools when a lasting preference or useful experience is expressed. Ordinary tasks make no extra extraction request. Inferred knowledge needs review.",
)
MODE_TIP = msg(
    "tui.personal_memory.mode_tip",
    fallback="Changes apply to the next turn. Recall on request lets the agent search when asked; off disables recall and suggestions.",
)
OPTIONS = msg("tui.personal_memory.options", fallback="More options")
IGNORE = msg("tui.personal_memory.ignore", fallback="Skip")
RESTORE = msg("tui.personal_memory.restore", fallback="Restore")
RECALL_DETAILS = msg("tui.personal_memory.recall_details", fallback="Why it was selected")
INDICATOR = msg("tui.personal_memory.indicator", fallback="Memory")
INDICATOR_COMPACT = msg("tui.personal_memory.indicator_compact", fallback="Mem")
PENDING_BADGE = msg("tui.personal_memory.pending_badge", fallback="Mem · Review {pending}")
CONSENT_BADGE = msg("tui.personal_memory.consent_badge", fallback="Mem · Save? {pending}")
CONSENT_CONFIRM_BINDING = msg("tui.personal_memory.consent_confirm_binding", fallback="Save all")
CONSENT_DROP_BINDING = msg("tui.personal_memory.consent_drop_binding", fallback="Drop all")
CONSENT_EMPTY = msg("tui.personal_memory.consent_empty", fallback="Nothing is waiting for you.")
CONSENT_REVIEW_TITLE = msg("tui.personal_memory.consent_review_title", fallback="Proposed memories")
CONSENT_REVIEW_COUNT = msg(
    "tui.personal_memory.consent_review_count",
    fallback="{count} waiting for your answer",
    plural_fallback="{count} waiting for your answer",
)
CONSENT_SPAN = msg("tui.personal_memory.consent_span", fallback="From: “{span}”")
CONSENT_SAVE_ALL = msg("tui.personal_memory.consent_save_all", fallback="Save all (y)")
CONSENT_DROP_ALL = msg("tui.personal_memory.consent_drop_all", fallback="Drop all (n)")
CONSENT_WARNING = msg(
    "tui.personal_memory.consent_warning",
    fallback="Waiting for your confirmation: {titles} — /memory confirm saves, /memory decline drops.",
)
RECALL_BADGE = msg("tui.personal_memory.recall_badge", fallback="Mem · {recalled} sent")
OFF_BADGE = msg("tui.personal_memory.off_badge", fallback="Mem · Off")
REMEMBERED = msg("tui.personal_memory.remembered", fallback="Remembered: {title}")
PROPOSED = msg("tui.personal_memory.proposed", fallback="Memory ready for review: {title}")
ROUTE_ID = msg("tui.personal_memory.route_id", fallback="Memory ID")
ROUTE_TITLE = msg("tui.personal_memory.route_title", fallback="Title match")
ROUTE_KEYWORDS = msg("tui.personal_memory.route_keywords", fallback="Keywords")
ROUTE_TOPIC = msg("tui.personal_memory.route_topic", fallback="Related terminology")
ROUTE_SPELLING = msg("tui.personal_memory.route_spelling", fallback="Similar spelling")
ROUTE_CONTEXT = msg("tui.personal_memory.route_context", fallback="Continuing the previous task")
FOLLOW_UPS = msg("tui.personal_memory.follow_ups", fallback="Follow-ups")
ACTIVITY = msg("tui.personal_memory.activity", fallback="Activity")
TYPES = msg("tui.personal_memory.types", fallback="All types")
SCOPES = msg("tui.personal_memory.scopes", fallback="Current workspace")
ALL_SCOPES = msg("tui.personal_memory.all_scopes", fallback="All workspaces")
TOPICS = msg("tui.personal_memory.topics", fallback="Topics")
ALL_TOPICS = msg("tui.personal_memory.all_topics", fallback="All topics")
ALWAYS = msg("tui.personal_memory.always", fallback="Always available")
TRACK = msg("tui.personal_memory.track", fallback="Keep as a follow-up")
NEXT_STEP = msg("tui.personal_memory.next_step", fallback="Next step")
REMIND_AT = msg("tui.personal_memory.remind_at", fallback="Remind at")
DATE_FORMAT = msg("tui.personal_memory.date_format", fallback="YYYY-MM-DD HH:MM")
TERMS_TIP = msg("tui.personal_memory.terms_tip", fallback="Separate entries with commas.")
REMIND_TIP = msg(
    "tui.personal_memory.remind_tip",
    fallback="Local time unless an offset is given. Appears during app use; no notification while closed.",
)
BAD_DATE = msg("tui.personal_memory.bad_date", fallback="Enter a date and time, for example 2026-11-20 09:00.")
PENDING = msg("tui.personal_memory.pending", fallback="To do")
IN_PROGRESS = msg("tui.personal_memory.in_progress", fallback="In progress")
WAITING = msg("tui.personal_memory.waiting", fallback="Waiting")
SNOOZED = msg("tui.personal_memory.snoozed", fallback="Later")
COMPLETED = msg("tui.personal_memory.completed", fallback="Completed")
CANCELLED = msg("tui.personal_memory.cancelled", fallback="Cancelled")
CONTINUE = msg("tui.personal_memory.continue", fallback="Continue")
COMPLETE = msg("tui.personal_memory.complete", fallback="Mark done")
CONTINUE_PROMPT = msg(
    "tui.personal_memory.continue_prompt",
    fallback="Continue this follow-up: {title}\nMemory: {memory_id} v{revision}\nNext step: {next_step}",
    multiline=True,
)
RELATED = msg("tui.personal_memory.related", fallback="Related evidence")
EVIDENCE_STALE = msg("tui.personal_memory.evidence_stale", fallback="Source changed · review before using")
LINK_SUPPORT = msg("tui.personal_memory.link_support", fallback="Supports")
LINK_EXCEPTION = msg("tui.personal_memory.link_exception", fallback="Exception")
LINK_DERIVED = msg("tui.personal_memory.link_derived", fallback="Derived from")
LINK_MERGED = msg("tui.personal_memory.link_merged", fallback="Merged from")
APPLIED = msg("tui.personal_memory.applied", fallback="Agent reported use")
HELPFUL = msg("tui.personal_memory.helpful", fallback="Helpful")
INCORRECT = msg("tui.personal_memory.incorrect", fallback="Incorrect")
NOT_APPLICABLE = msg("tui.personal_memory.not_applicable", fallback="Skip this turn")
EFFECT_UNKNOWN = msg("tui.personal_memory.effect_unknown", fallback="Effect unknown")
CONFIRM_CONDITIONS = msg("tui.personal_memory.confirm_conditions", fallback="Keep conditions")
PROVIDED = msg("tui.personal_memory.provided", fallback="Provided")
NO_MATCH = msg("tui.personal_memory.no_match", fallback="No match")
USER_ACTOR = msg("tui.personal_memory.user_actor", fallback="You")
AGENT_ACTOR = msg("tui.personal_memory.agent_actor", fallback="Agent")
SYSTEM_ACTOR = msg("tui.personal_memory.system_actor", fallback="System")
ROUTE_ASSOCIATION = msg("tui.personal_memory.route_association", fallback="Linked evidence")
ROUTE_FOLLOW_UP = msg("tui.personal_memory.route_follow_up", fallback="Due follow-up")
DRAFT_BUSY = msg(
    "tui.personal_memory.draft_busy", fallback="Finish the current draft before continuing this follow-up."
)
INCORRECT_TIP = msg(
    "tui.personal_memory.incorrect_tip",
    fallback="Record your correction and pause this memory. You can edit or restore it.",
)
ALIASES = msg("tui.personal_memory.aliases", fallback="Retrieval phrases")
ROUTE_ALIAS = msg("tui.personal_memory.route_alias", fallback="Your retrieval phrases")
SAVE_FAILED = msg("tui.personal_memory.save_failed", fallback="Not saved: {title}")
FAIL_BADGE = msg("tui.personal_memory.fail_badge", fallback="Mem · Not saved")
UNAVAILABLE_BADGE = msg("tui.personal_memory.unavailable_badge", fallback="Mem · Unavailable")
FAIL_SOURCE = msg(
    "tui.personal_memory.fail_source",
    fallback="The original evidence could not be verified. Quote it again or add the memory in /memory.",
)
FAIL_REQUEST = msg(
    "tui.personal_memory.fail_request",
    fallback="No supported save request was found. You can add this memory in /memory.",
)
FAIL_DISTILLED = msg(
    "tui.personal_memory.fail_distilled",
    fallback="Check the rule, its future use and length. A lesson from research also needs an application.",
)
FAIL_REVIEW = msg(
    "tui.personal_memory.fail_review",
    fallback="Related memories must be checked first. The agent can inspect them and retry.",
)
FAIL_DISABLED = msg(
    "tui.personal_memory.fail_disabled", fallback="The current saving policy does not permit this write."
)
CAPACITY = msg(
    "tui.personal_memory.capacity",
    fallback="{count} memory · {used} MiB",
    plural_fallback="{count} memories · {used} MiB",
)
CAPACITY_WARNING = msg(
    "tui.personal_memory.capacity_warning", fallback="Review memories with outdated conditions or repeated mismatches"
)
CAPACITY_BADGE = msg("tui.personal_memory.capacity_badge", fallback="Mem · Review")
NEARLY_FULL = msg("tui.personal_memory.nearly_full", fallback="Needs review")
REVIEW_REQUIRED = msg("tui.personal_memory.review_required", fallback="Needs review")
REVIEW_SKIPPED = msg(
    "tui.personal_memory.review_skipped",
    fallback="Applicability was questioned in three turns. Review the conditions.",
)
REVIEW_NO_FEEDBACK = msg(
    "tui.personal_memory.review_no_feedback",
    fallback="No helpful feedback was recorded. Its effect is unknown.",
)
REVIEW_EXPIRED = msg(
    "tui.personal_memory.review_expired", fallback="Unreviewed for 30 days; archived for later inspection."
)
HEALTH_REVIEW = msg("tui.personal_memory.health_review", fallback="{stale} to review · {duplicates} similar")
ORGANIZE = msg("tui.personal_memory.organize", fallback="Review together")
ORGANIZE_PROMPT = msg(
    "tui.personal_memory.organize_prompt",
    fallback="Review my habits and conditional experience about {topic}. Inspect these memories: {references}. Propose a concise synthesis or merge, explain what each source contributes and which exceptions remain. Wait for my confirmation before retiring sources.",
)
ORGANIZE_PROMPT_TOPIC = msg(
    "tui.personal_memory.organize_prompt_topic",
    fallback="Review my habits and conditional experience about {topic}. Propose a concise synthesis or merge and explain which exceptions remain. Wait for my confirmation before retiring sources.",
)
ORGANIZE_VIEW = msg("tui.personal_memory.organize_view", fallback="To organize")
ORGANIZE_WHY = msg("tui.personal_memory.organize_why", fallback="Why it needs organizing")
ORGANIZE_REASON_DUPLICATE = msg("tui.personal_memory.organize_reason_duplicate", fallback="Similar content")
ORGANIZE_REASON_SOURCE = msg("tui.personal_memory.organize_reason_source", fallback="Source changed")
ORGANIZE_REASON_SKIPS = msg("tui.personal_memory.organize_reason_skips", fallback="Repeatedly not applicable")
ORGANIZE_REASON_REVIEW = msg("tui.personal_memory.organize_reason_review", fallback="Marked for review")
ORGANIZE_PARTNERS = msg(
    "tui.personal_memory.organize_partners",
    fallback="Same content (same type and scope): {partners}",
)
ORGANIZE_REVIEW_GENERIC = msg(
    "tui.personal_memory.organize_review_generic",
    fallback="Marked for review. Check whether it still applies.",
)
ORGANIZE_EMPTY = msg("tui.personal_memory.organize_empty", fallback="No memories need organizing.")
ORGANIZE_EMPTY_FILTERED = msg(
    "tui.personal_memory.organize_empty_filtered",
    fallback="No memories need organizing with the current filters.",
)
ORGANIZE_SELECT_HINT = msg(
    "tui.personal_memory.organize_select_hint",
    fallback="Select a memory, or choose a topic or search first.",
)
OLDER_REVISIONS = msg("tui.personal_memory.older_revisions", fallback="Earlier revisions")
RECALL_LAYER = msg("tui.personal_memory.recall_layer", fallback="Recall stage: {layer}")
LAYER_STANDING = msg("tui.personal_memory.layer_standing", fallback="Always available")
LAYER_OPENING = msg("tui.personal_memory.layer_opening", fallback="Task start")
LAYER_ACTION = msg("tui.personal_memory.layer_action", fallback="Before an action")
LAYER_REQUESTED = msg("tui.personal_memory.layer_requested", fallback="On request")
REVISION_IMPORTED = msg("tui.personal_memory.revision_imported", fallback="Earlier revision imported")
WEEKLY_REVIEW = msg("tui.personal_memory.weekly_review", fallback="Weekly review")


def review_message(reason: str) -> MessageDef | None:
    return {
        "repeated_mismatch": REVIEW_SKIPPED,
        "no_helpful_feedback": REVIEW_NO_FEEDBACK,
        "candidate_expired": REVIEW_EXPIRED,
        "incorrect": INCORRECT,
    }.get(reason)


MARK_HINT = msg("tui.personal_memory.mark_hint", fallback="Space to select")
SCOPE_PERSONAL = msg("tui.personal_memory.scope_personal", fallback="Personal")
SCOPE_PROJECT = msg("tui.personal_memory.scope_project", fallback="Project")
JUST_NOW = msg("tui.personal_memory.just_now", fallback="Just now")
MINUTES_AGO = msg("tui.personal_memory.minutes_ago", fallback="{minutes}m ago")
HOURS_AGO = msg("tui.personal_memory.hours_ago", fallback="{hours}h ago")
DAYS_AGO = msg("tui.personal_memory.days_ago", fallback="{days}d ago")
SELECTED = msg(
    "tui.personal_memory.selected",
    fallback="{count} selected · Esc",
    plural_fallback="{count} selected · Esc",
)
MARK = msg("tui.personal_memory.mark", fallback="Select")
DESELECT = msg("tui.personal_memory.deselect", fallback="Deselect")
KEYBOARD_HINT = msg(
    "tui.personal_memory.keyboard_hint",
    fallback="↑/↓ Navigate · Enter Details · Space Select · Esc Back · Delete Forget · Ctrl+F Search",
)
BATCH_FORGET = msg(
    "tui.personal_memory.batch_forget",
    fallback="Forget this memory, including its revisions and activity?",
    plural_fallback="Forget all {count} selected or dependent memories, including their revisions and activity?",
)
USAGE = msg(
    "tui.personal_memory.usage",
    fallback="Recent activity (v{revision}): {provided} recall turns · {applied} agent uses · {helpful} helpful · {user_skipped} user skips · {agent_skipped} agent skips",
)
LAST_PROVIDED = msg("tui.personal_memory.last_provided", fallback="Last recorded recall: {date}")
REVIEW_CONTEXT = msg(
    "tui.personal_memory.review_context", fallback="Repeated skips: check whether the usage conditions need narrowing."
)
OLDER_ACTIVITY = msg("tui.personal_memory.older_activity", fallback="Earlier activity")
LATEST_ACTIVITY = msg("tui.personal_memory.latest_activity", fallback="Latest")
BAD_TOPICS = msg("tui.personal_memory.bad_topics", fallback="Use up to 6 topics, each 1-40 characters.")
BAD_ALIASES = msg("tui.personal_memory.bad_aliases", fallback="Use up to 6 retrieval phrases, each 2-80 characters.")
BATCH_LIMIT = msg("tui.personal_memory.batch_limit", fallback="Select up to 25 memories at a time.")
FAIL_UNAVAILABLE = msg(
    "tui.personal_memory.fail_unavailable", fallback="Memory is unavailable. Check local file access, then retry."
)
FAIL_PAUSED = msg(
    "tui.personal_memory.fail_paused", fallback="This memory was paused. Restore the existing entry to use it again."
)
FAIL_DUPLICATE = msg(
    "tui.personal_memory.fail_duplicate", fallback="A related memory already exists. Edit that entry instead."
)
FAIL_ACTION = msg(
    "tui.personal_memory.fail_action",
    fallback="The operation could not be completed. Refresh and retry; hover for details.",
)


def failure_message(code: str) -> MessageDef:
    """Keep model-facing retry instructions out of visible UI error prose."""
    return {
        "memory_source_missing": FAIL_SOURCE,
        "memory_not_distilled": FAIL_DISTILLED,
        "memory_request_missing": FAIL_REQUEST,
        "memory_consent_invalid": FAIL_REQUEST,
        "memory_review_required": FAIL_REVIEW,
        "memory_disabled": FAIL_DISABLED,
        "memory_declined": FAIL_DISABLED,
        "memory_unavailable": FAIL_UNAVAILABLE,
        "memory_paused": FAIL_PAUSED,
        "memory_duplicate": FAIL_DUPLICATE,
    }.get(code, FAIL_ACTION)
