# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Explicit review signals; absence of feedback requests review, never proves error."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from chrys.foundation.models.personal_memory import (
    MemoryExposure,
    MemoryReviewNotice,
    MemoryRevision,
    MemorySnapshot,
    MemoryUse,
)

from . import activity


@dataclass(frozen=True, slots=True)
class MemoryHealth:
    pending: int
    stale: int
    duplicates: int

    @property
    def needs_review(self) -> bool:
        return bool(self.stale or self.duplicates)


def health(state: MemorySnapshot) -> MemoryHealth:
    groups: dict[tuple[str, str, str], int] = defaultdict(int)
    for entry in state.entries:
        if entry.state not in ("active", "candidate", "stale"):
            continue
        content = "".join(unicodedata.normalize("NFKC", entry.draft.content).casefold().split())
        groups[(entry.draft.workspace, entry.draft.kind, content)] += 1
    return MemoryHealth(
        sum(e.state == "candidate" for e in state.entries),
        sum(e.state == "stale" for e in state.entries),
        sum(count - 1 for count in groups.values() if count > 1),
    )


def record_use(
    state: MemorySnapshot,
    memory_id: str,
    revision: int,
    action: str,
    session_id: str,
    turn_id: str,
    *,
    user: bool = False,
) -> MemorySnapshot:
    if not session_id or not turn_id:
        return state
    now = datetime.now(UTC).isoformat(timespec="seconds")
    old = next((u for u in state.uses if u.memory_id == memory_id), None)
    use = (
        old
        if old and old.revision == revision
        else MemoryUse(memory_id, revision, correction_sessions=old.correction_sessions if old else ())
    )
    item = MemoryExposure(session_id, turn_id, now)
    if action == "provided" and not any((e.session_id, e.turn_id) == (session_id, turn_id) for e in use.exposures):
        use = replace(use, exposures=(*use.exposures, item)[-5:])
    elif action == "not_applicable" and not any((e.session_id, e.turn_id) == (session_id, turn_id) for e in use.skips):
        use = replace(use, skips=(*use.skips, item)[-3:])
    elif action == "helpful" and user:
        use = replace(use, helpful_at=now, skips=())
    elif action == "corrected" and user:
        use = replace(use, correction_sessions=tuple(dict.fromkeys((*use.correction_sessions, session_id)))[-3:])
    return replace(state, uses=(*[u for u in state.uses if u.memory_id != memory_id], use))


def review_reason(use: MemoryUse, *, now: datetime) -> str:
    if len(use.skips) >= 3:
        return "repeated_mismatch"
    # Calendar six months, not a fixed number of seconds or a confidence score.
    month = (now.year * 12 + now.month - 1) - 6
    import calendar

    cutoff = now.replace(
        year=month // 12, month=month % 12 + 1, day=min(now.day, calendar.monthrange(month // 12, month % 12 + 1)[1])
    )
    exposures = [e for e in use.exposures if datetime.fromisoformat(e.occurred_at) >= cutoff]
    if len(exposures) >= 5 and (not use.helpful_at or datetime.fromisoformat(use.helpful_at) < cutoff):
        return "no_helpful_feedback"
    return ""


def restore(state: MemorySnapshot, data: dict) -> MemorySnapshot:
    uses = tuple(
        MemoryUse(
            u["memory_id"],
            u["revision"],
            tuple(MemoryExposure(**e) for e in u.get("exposures", ())),
            tuple(MemoryExposure(**e) for e in u.get("skips", ())),
            u.get("helpful_at", ""),
            tuple(u.get("correction_sessions", ())),
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
    timestamps = [e.occurred_at for u in uses for e in (*u.exposures, *u.skips)]
    timestamps += (
        [u.helpful_at for u in uses] + [data.get("last_review_at", "")] + ([notice.created_at] if notice else [])
    )
    if (
        any(datetime.fromisoformat(t).tzinfo is None for t in timestamps if t)
        or any(
            len(u.exposures) > 5 or len(u.skips) > 3 or len(u.correction_sessions) > 3 or u.revision < 1 for u in uses
        )
        or len({u.memory_id for u in uses}) != len(uses)
    ):
        raise ValueError("Invalid memory review evidence.")
    return replace(state, uses=uses, review_notice=notice, last_review_at=data.get("last_review_at", ""))


def maintain(
    state: MemorySnapshot, *, now: datetime, workspace: str | None = None, notify: bool = True
) -> MemorySnapshot:
    uses = {u.memory_id: u for u in state.uses}
    entries = []
    expired = 0
    changed = 0
    for entry in state.entries:
        reason = (
            review_reason(uses[entry.id], now=now)
            if entry.state == "active" and entry.id in uses and uses[entry.id].revision == entry.revision
            else ""
        )
        expire = entry.state == "candidate" and datetime.fromisoformat(entry.created_at) <= now - timedelta(days=30)
        if (reason or expire) and changed < activity.RECENT_ACTIVITY - 1:
            # Leave one outbox slot for a digest; the store drains further batches.
            changed += 1
            expired += int(expire)
            entry = replace(
                entry,
                state="archived" if expire else "stale",
                review_reason="candidate_expired" if expire else reason,
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
    ids = tuple(groups[group][:6]) if group else tuple(e.id for e in eligible if e.state in ("candidate", "stale"))[:6]
    if not ids and not expired:
        return result
    stamp = now.isoformat(timespec="seconds")
    result = replace(
        result, last_review_at=stamp, review_notice=MemoryReviewNotice(stamp, ids, group[1] if group else "", expired)
    )
    return activity.record(result, "review_digest", actor="system", detail=group[1] if group else "")
