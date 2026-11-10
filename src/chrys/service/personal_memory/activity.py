# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Committed memory activity, with a bounded UI tail and recoverable full journal.

The memory snapshot is the commit record. Its recent events are also an outbox:
writers drain it before another mutation, then append the newly committed events.
A failed append never rolls back a successful memory edit. Sequence numbers make
recovery idempotent; the same memory file lock protects the snapshot and journal.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from chrys.foundation.models.personal_memory import MemoryActivity, MemoryDraft, MemorySnapshot, MemorySource
from chrys.foundation.platform.files import (
    fsync_directory,
    replace_with_retry,
    secure_open_owner_only,
    secure_open_owner_only_append,
    secure_open_owner_only_binary,
    secure_unlink_owner_verified,
)

RECENT_ACTIVITY = 128
_TAIL_BYTES = 65536


@dataclass(frozen=True, slots=True)
class MemoryUsage:
    provided: int = 0
    user_skipped: int = 0
    agent_skipped: int = 0
    helpful: int = 0
    applied: int = 0
    last_provided: str = ""
    skipped_turns: int = 0


def recent_usage(state: MemorySnapshot, memory_id: str, revision: int) -> MemoryUsage:
    """Five recall turns plus explicit feedback; no claims about missing history or truth."""
    events = [e for e in state.activity if e.memory_id == memory_id and e.revision == revision]
    provided = {(e.session_id, e.turn_id): e for e in events if e.action == "provided"}
    turns = set(list(provided)[-5:])

    def count(action: str, actor: str) -> int:
        return len(
            {
                (e.session_id, e.turn_id)
                for e in events
                if e.action == action and e.actor == actor and (e.session_id, e.turn_id) in turns
            }
        )

    return MemoryUsage(
        len(turns),
        count("not_applicable", "user"),
        count("not_applicable", "agent"),
        len({(e.session_id, e.turn_id) for e in events if e.action == "helpful" and e.actor == "user"}),
        count("applied", "agent"),
        next(reversed(provided.values())).occurred_at if provided else "",
        len(
            {
                (e.session_id, e.turn_id)
                for e in events
                if e.action == "not_applicable" and (e.session_id, e.turn_id) in turns
            }
        ),
    )


def read_page(path: Path, *, before: int, limit: int = 100) -> tuple[dict, ...]:
    """Read older journal records backwards in bounded blocks, newest page first."""
    rows = []
    with secure_open_owner_only_binary(path) as stream:
        position = stream.seek(0, os.SEEK_END)
        remainder = b""
        while position:
            start = max(0, position - _TAIL_BYTES)
            stream.seek(start)
            chunk = stream.read(position - start) + remainder
            lines = chunk.split(b"\n")
            remainder = lines.pop(0) if start else b""
            if len(remainder) > _TAIL_BYTES:
                raise ValueError("Memory activity record exceeds its limit.")
            for line in reversed(lines):
                if not line:
                    continue
                row = json.loads(line)
                if row["sequence"] < before:
                    rows.append(row)
                    if len(rows) == limit:
                        return tuple(reversed(rows))
            position = start
    return tuple(reversed(rows))


def record(
    state: MemorySnapshot,
    action: str,
    *,
    memory_id: str = "",
    revision: int = 0,
    session_id: str = "",
    turn_id: str = "",
    actor: str = "user",
    detail: str = "",
    draft: MemoryDraft | None = None,
    source: MemorySource | None = None,
    removed_ids: tuple[str, ...] = (),
    occurred_at: str = "",
    memory_source: MemorySource | None = None,
) -> MemorySnapshot:
    event = MemoryActivity(
        state.activity_sequence + 1,
        action,
        occurred_at or datetime.now(UTC).isoformat(timespec="seconds"),
        memory_id,
        revision,
        session_id,
        turn_id,
        actor,
        detail[:600],
        draft,
        source,
        removed_ids,
        memory_source,
    )
    return replace(state, activity=(*state.activity, event)[-RECENT_ACTIVITY:], activity_sequence=event.sequence)


def record_changes(
    before: MemorySnapshot, after: MemorySnapshot, *, actor: str = "user", session_id: str = "", turn_id: str = ""
) -> MemorySnapshot:
    previous = {entry.id: entry for entry in before.entries}
    for entry in after.entries:
        old = previous.get(entry.id)
        if old == entry:
            continue
        action = "created" if old is None else "updated"
        if entry.state == "candidate":
            action = "proposed"
        elif old and old.state != entry.state:
            action = (
                "review_required"
                if entry.state == "stale"
                else "candidate_expired"
                if entry.review_reason == "candidate_expired"
                else "activated"
                if entry.state == "active"
                else "paused"
            )
        elif old and old.draft.follow_up != entry.draft.follow_up:
            action = "follow_up"
        after = record(
            after,
            action,
            memory_id=entry.id,
            revision=entry.revision,
            session_id=session_id,
            turn_id=turn_id,
            actor=actor,
            draft=entry.draft,
            source=entry.retired_by if action == "paused" and entry.retired_by is not None else entry.source,
            detail=entry.review_reason,
            memory_source=entry.source if action == "paused" and entry.retired_by is not None else None,
        )
    return after


def _mentions(row: dict, removed: set[str]) -> bool:
    draft = row.get("draft") or {}
    return row.get("memory_id") in removed or any(
        relation["memory_id"] in removed for relation in draft.get("relations", ())
    )


def _purge(path: Path, removed: set[str]) -> None:
    """Physically remove forgotten content, including historical derived drafts."""
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        fd = secure_open_owner_only(temporary, write=True, create=True)
        with os.fdopen(fd, "wb") as target, secure_open_owner_only_binary(path) as source:
            for line in source:
                if line.strip() and not _mentions(json.loads(line), removed):
                    target.write(line)
            target.flush()
            os.fsync(target.fileno())
        replace_with_retry(temporary, path)
        fsync_directory(path.parent)
    finally:
        secure_unlink_owner_verified(temporary)


def _encode(event: MemoryActivity) -> bytes:
    payload = (json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(payload) > _TAIL_BYTES // 2:
        raise ValueError("Memory activity record exceeds its limit.")
    return payload


def validate_pending(state: MemorySnapshot, after_sequence: int) -> None:
    """Reject an unflushable event before its outbox becomes the committed snapshot."""
    for event in state.activity:
        if event.sequence > after_sequence:
            _encode(event)


def synchronize(path: Path, state: MemorySnapshot) -> None:
    """Drain a committed outbox. Caller holds the memory store's cross-process lock."""
    if not state.activity:
        return
    handle = secure_open_owner_only_append(path)
    with os.fdopen(handle.fd, "r+b") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        start = max(0, size - _TAIL_BYTES)
        stream.seek(start)
        tail = stream.read()
        # An interrupted append may leave one unterminated final record.
        end = tail.rfind(b"\n") + 1
        if size and not end:
            if start:
                raise ValueError("Memory activity journal has an invalid tail.")
            stream.truncate(0)
        elif end < len(tail):
            stream.truncate(start + end)
        lines = tail[:end].splitlines()
        last = int(json.loads(lines[-1])["sequence"]) if lines else 0
        if last > state.activity_sequence:
            raise ValueError("Memory activity journal is newer than the memory store.")
        pending = tuple(event for event in state.activity if event.sequence > last)
        if pending and pending[0].sequence != last + 1 and not any(e.removed_ids for e in pending):
            raise ValueError("Memory activity journal has a gap; restore it before writing.")
    removed = {mid for event in pending for mid in event.removed_ids}
    if removed:
        _purge(path, removed)
    if not pending:
        return
    with os.fdopen(secure_open_owner_only_append(path).fd, "wb") as stream:
        for event in pending:
            stream.write(_encode(event))
        stream.flush()
        os.fsync(stream.fileno())
    if handle.created:
        fsync_directory(path.parent)
