# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""User feedback refines retrieval conditions; silence never establishes an error."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from chrys.foundation.models.personal_memory import (
    MemoryContextSkip,
    MemoryReviewNotice,
    MemoryRevision,
    MemorySnapshot,
    MemoryUse,
)

from . import activity


def condition_review_ids(state: MemorySnapshot) -> frozenset[str]:
    """Active versions with repeated, explicit user reports about applicability."""
    uses = {use.memory_id: use for use in state.uses}
    return frozenset(
        e.id
        for e in state.entries
        if e.state == "active"
        and e.id in uses
        and uses[e.id].revision == e.revision
        and (len(uses[e.id].skips) >= 3 or uses[e.id].excluded_contexts)
    )


def _has_feedback(use: MemoryUse) -> bool:
    return bool(use.skips or use.correction_sessions or use.excluded_contexts)


def record_feedback(
    state: MemorySnapshot,
    memory_id: str,
    revision: int,
    action: Literal["not_applicable", "helpful", "corrected"],
    session_id: str,
    turn_id: str,
    *,
    context_key: str = "",
) -> MemorySnapshot:
    """Record explicit user evidence that changes how a memory can be used or reviewed."""
    if not session_id or not turn_id or (action != "corrected" and not context_key):
        return state
    old = next((u for u in state.uses if u.memory_id == memory_id), None)
    use = (
        old
        if old and old.revision == revision
        else MemoryUse(memory_id, revision, correction_sessions=old.correction_sessions if old else ())
    )
    if action == "not_applicable":
        if any((e.session_id, e.turn_id) == (session_id, turn_id) for e in use.skips):
            return state
        item = MemoryContextSkip(session_id, turn_id, datetime.now(UTC).isoformat(timespec="seconds"), context_key)
        use = replace(use, skips=(*use.skips, item)[-3:])
        if sum(e.context_key == context_key for e in use.skips) >= 3:
            use = replace(use, excluded_contexts=tuple(dict.fromkeys((*use.excluded_contexts, context_key)))[-8:])
    elif action == "helpful":
        use = replace(
            use,
            skips=tuple(e for e in use.skips if e.context_key != context_key),
            excluded_contexts=tuple(key for key in use.excluded_contexts if key != context_key),
        )
    else:
        use = replace(use, correction_sessions=tuple(dict.fromkeys((*use.correction_sessions, session_id)))[-3:])
    if use == old:
        return state
    others = tuple(u for u in state.uses if u.memory_id != memory_id)
    return replace(state, uses=(*others, use) if _has_feedback(use) else others)


def restore(state: MemorySnapshot, data: dict) -> MemorySnapshot:
    uses = tuple(
        MemoryUse(
            memory_id=u["memory_id"],
            revision=u["revision"],
            skips=tuple(MemoryContextSkip(**e) for e in u.get("skips", ())),
            correction_sessions=tuple(u.get("correction_sessions", ())),
            excluded_contexts=tuple(u.get("excluded_contexts", ())),
        )
        for u in data.get("uses", ())
    )
    notice_data = data.get("review_notice")
    notice = (
        MemoryReviewNotice(
            notice_data["created_at"],
            tuple(notice_data["memory_ids"]),
            notice_data["topic"],
            notice_data["archived_candidates"],
        )
        if notice_data
        else None
    )
    timestamps = [e.occurred_at for u in uses for e in u.skips]
    timestamps += [data.get("last_review_at", "")] + ([notice.created_at] if notice else [])
    if (
        any(datetime.fromisoformat(t).tzinfo is None for t in timestamps if t)
        or any(len(set(u.excluded_contexts)) != len(u.excluded_contexts) or "" in u.excluded_contexts for u in uses)
        or any(
            len(u.skips) > 3 or len(u.correction_sessions) > 3 or len(u.excluded_contexts) > 8 or u.revision < 1
            for u in uses
        )
        or len({u.memory_id for u in uses}) != len(uses)
        or any(
            not isinstance(key, str) or (key and not re.fullmatch(r"[a-f0-9]{24}", key))
            for u in uses
            for key in (*u.excluded_contexts, *(e.context_key for e in u.skips))
        )
    ):
        raise ValueError("Invalid memory review evidence.")
    # Old skips did not identify the feedback actor. Retain their audit
    # events, but do not treat unscoped legacy observations as user evidence.
    uses = tuple(replace(use, skips=tuple(e for e in use.skips if e.context_key)) for use in uses)
    return replace(
        state,
        uses=tuple(use for use in uses if _has_feedback(use)),
        review_notice=notice,
        last_review_at=data.get("last_review_at", ""),
    )


def maintain(
    state: MemorySnapshot, *, now: datetime, workspace: str | None = None, notify: bool = True
) -> MemorySnapshot:
    uses = {u.memory_id: u for u in state.uses}
    entries = []
    expired = 0
    changed = 0
    for entry in state.entries:
        # Old policy quarantined facts on silence or contextual mismatches.
        # Restore only those automatic quarantines; explicit pauses remain paused.
        restore_legacy = (
            entry.state == "stale"
            and entry.retired_by is None
            and entry.review_reason
            in {
                "no_helpful_feedback",
                "repeated_mismatch",
            }
        )
        expire = entry.state == "candidate" and datetime.fromisoformat(entry.created_at) <= now - timedelta(days=30)
        if (restore_legacy or expire) and changed < activity.RECENT_ACTIVITY - 1:
            # Leave one outbox slot for a digest; the store drains further batches.
            changed += 1
            expired += int(expire)
            entry = replace(
                entry,
                state="archived" if expire else "active",
                review_reason="candidate_expired" if expire else "",
                revision=entry.revision + 1,
                updated_at=now.isoformat(timespec="seconds"),
                previous=(MemoryRevision(entry.revision, entry.draft, entry.source, entry.updated_at),),
            )
        entries.append(entry)
    result = replace(state, entries=tuple(entries))
    if expired and result.review_notice is not None:
        result = replace(
            result,
            review_notice=replace(
                result.review_notice, archived_candidates=result.review_notice.archived_candidates + expired
            ),
        )
    if (
        not notify
        or not state.buddy_notifications
        or (state.last_review_at and now - datetime.fromisoformat(state.last_review_at) < timedelta(days=7))
    ):
        return result
    eligible = [e for e in entries if e.draft.workspace in ("", workspace) or workspace is None]
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    corrections: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in eligible:
        if e.state == "archived":
            continue
        for topic in e.draft.topics:
            key = e.draft.workspace, topic
            groups[key].append(e.id)
            if e.id in uses:
                corrections[key].update(uses[e.id].correction_sessions)
    group = next((key for key, ids in groups.items() if len(ids) >= 3 or len(corrections[key]) >= 3), None)
    condition_ids = condition_review_ids(result)
    ids = (
        tuple(groups[group][:6])
        if group
        else tuple(e.id for e in eligible if e.state in ("candidate", "stale") or e.id in condition_ids)[:6]
    )
    if not ids and not expired:
        return result
    stamp = now.isoformat(timespec="seconds")
    result = replace(
        result, last_review_at=stamp, review_notice=MemoryReviewNotice(stamp, ids, group[1] if group else "", expired)
    )
    return activity.record(result, "review_digest", actor="system", detail=group[1] if group else "")
