# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Owner-only memory storage with locked revisions and bounded local retrieval.

Only curated memories are read, never session archives. Model suggestions stay
candidates until accepted. Recall references revisions, so correction cannot
silently make an old recall look as though it used the new conclusion.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from itertools import islice, pairwise
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from chrys.foundation.models.personal_memory import (
    MemoryActivity,
    MemoryDraft,
    MemoryFeedback,
    MemoryFollowUp,
    MemoryMatch,
    MemoryMode,
    MemoryRecall,
    MemoryRelation,
    MemoryRevision,
    MemorySnapshot,
    MemorySource,
    MemoryState,
    PersonalMemory,
)
from chrys.foundation.platform import get_platform
from chrys.foundation.platform.files import atomic_write_owner_only_text, secure_open_owner_only_binary
from chrys.foundation.util.lock import FileLock

from . import activity, lifecycle
from .retrieval import MemoryRetriever, continues_previous_task, decision_key, decision_terms, linked_to_decision

_log = logging.getLogger(__name__)

MAX_BYTES = 64 * 1024 * 1024
STORE_VERSION = 4
MAX_REVISIONS = 1
MAX_RECALLS = 40
MAX_RECALLED = 5
MAX_CONTEXT_CHARS = 6000
MAX_INSPECTED = 8
MAX_INSPECTION_CHARS = 12000
MAX_TURN_SEARCHES = 3
MAX_TURN_RECALLED = 15
MAX_TURN_CONTEXT_CHARS = 18000
MAX_BATCH = 25


class MemoryStoreError(ValueError):
    """A rejected operation whose message is safe to display."""

    def __init__(self, message: str, *, code: str = "memory_rejected") -> None:
        super().__init__(message)
        self.code = code


class MemoryRecallBudgetExceeded(MemoryStoreError):
    """The turn has already received its bounded advice context."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def workspace_key(workspace: str) -> str:
    return os.path.normcase(str(Path(workspace).resolve())) if workspace else ""


def _recall_context_key(query: str, context: str, workspace: str, layer: str | None) -> str:
    if context and layer == "L2":
        return decision_key(query + "\n" + context, workspace)
    return decision_key(context if context and continues_previous_task(query) else query, workspace)


def review_key(state: MemorySnapshot, workspace: str) -> tuple[tuple[str, int], ...]:
    """Content revisions, independent of recall receipts or unrelated projects."""
    workspace = workspace_key(workspace)
    return tuple(
        sorted((entry.id, entry.revision) for entry in state.entries if entry.draft.workspace in ("", workspace))
    )


def _validate_draft(draft: MemoryDraft) -> None:
    for value, limit in (
        (draft.title, 120),
        (draft.content, 2400),
        (draft.when_to_use, 600),
        (draft.reconsider_when, 600),
        (draft.workspace, 4096),
    ):
        if not isinstance(value, str) or len(value) > limit:
            raise MemoryStoreError("Memory text exceeds its field limit.")
    if not draft.title.strip() or not draft.content.strip():
        raise MemoryStoreError("Title and memory are required.")
    if draft.kind not in ("decision", "preference", "lesson", "intention"):
        raise MemoryStoreError("Unknown memory kind.")
    if draft.use not in ("contextual", "always") or (draft.use == "always" and draft.kind != "preference"):
        raise MemoryStoreError("Only explicitly selected collaboration preferences can be always available.")
    if len(draft.topics) > 6 or any(not isinstance(t, str) or not 1 <= len(t.strip()) <= 40 for t in draft.topics):
        raise MemoryStoreError("Use at most six short topics.")
    if len(draft.aliases) > 6 or any(not isinstance(t, str) or not 2 <= len(t.strip()) <= 80 for t in draft.aliases):
        raise MemoryStoreError("Use at most six retrieval phrases, each between 2 and 80 characters.")
    if draft.follow_up is not None:
        follow = draft.follow_up
        if draft.kind != "intention" or follow.status not in (
            "pending",
            "in_progress",
            "waiting",
            "snoozed",
            "completed",
            "cancelled",
        ):
            raise MemoryStoreError("Follow-ups require an intention and a valid status.")
        if not isinstance(follow.next_step, str) or len(follow.next_step) > 600:
            raise MemoryStoreError("The next step exceeds its limit.")
        if not isinstance(follow.remind_at, str):
            raise MemoryStoreError("Reminder time must be text.")
        if follow.remind_at:
            try:
                date = datetime.fromisoformat(follow.remind_at)
                if date.tzinfo is None:
                    raise ValueError
            except ValueError, TypeError:
                raise MemoryStoreError("Reminder time must be an ISO 8601 timestamp with a timezone.") from None
        if follow.status == "snoozed" and not follow.remind_at:
            raise MemoryStoreError("Choose when to show a snoozed follow-up again.")
    if len(draft.relations) > 6 or len({r.memory_id for r in draft.relations}) != len(draft.relations):
        raise MemoryStoreError("Use at most six distinct related memories.")
    for relation in draft.relations:
        if (
            not isinstance(relation.memory_id, str)
            or not relation.memory_id
            or not isinstance(relation.reason, str)
            or relation.kind not in ("supports", "exception", "derived_from", "merged_from")
            or type(relation.revision) is not int
            or relation.revision < 1
            or not 1 <= len(relation.reason.strip()) <= 300
        ):
            raise MemoryStoreError("A relation requires a current revision and a short explanation.")


def _source(raw: dict[str, Any]) -> MemorySource:
    source = MemorySource(**raw)
    if any(not isinstance(value, str) for value in asdict(source).values()) or len(source.quote) > 1200:
        raise MemoryStoreError("Invalid memory source.")
    return source


def _draft(raw: dict[str, Any]) -> MemoryDraft:
    values = dict(raw)
    if not isinstance(values.get("topics", ()), (tuple, list)) or not isinstance(
        values.get("relations", ()), (tuple, list)
    ):
        raise MemoryStoreError("Invalid memory topics or relations.")
    values["topics"] = tuple(values.get("topics", ()))
    if not isinstance(values.get("aliases", ()), (tuple, list)):
        raise MemoryStoreError("Invalid retrieval phrases.")
    values["aliases"] = tuple(values.get("aliases", ()))
    values["relations"] = tuple(MemoryRelation(**item) for item in values.get("relations", ()))
    if values.get("follow_up") is not None:
        values["follow_up"] = MemoryFollowUp(**values["follow_up"])
    draft = MemoryDraft(**values)
    _validate_draft(draft)
    return draft


def _activity(raw: dict[str, Any]) -> MemoryActivity:
    if not isinstance(raw, dict):
        raise MemoryStoreError("Invalid memory activity.")
    event = MemoryActivity(
        sequence=raw["sequence"],
        action=raw["action"],
        occurred_at=raw["occurred_at"],
        memory_id=raw.get("memory_id", ""),
        revision=raw.get("revision", 0),
        session_id=raw.get("session_id", ""),
        turn_id=raw.get("turn_id", ""),
        actor=raw.get("actor", "system"),
        detail=raw.get("detail", ""),
        draft=_draft(raw["draft"]) if raw.get("draft") else None,
        memory_source=_source(raw["memory_source"]) if raw.get("memory_source") else None,
        source=_source(raw["source"]) if raw.get("source") else None,
        removed_ids=tuple(raw.get("removed_ids", ())),
    )
    if (
        type(event.sequence) is not int
        or type(event.revision) is not int
        or event.revision < 0
        or not all(
            isinstance(v, str)
            for v in (
                event.action,
                event.occurred_at,
                event.memory_id,
                event.session_id,
                event.turn_id,
                event.actor,
                event.detail,
                *event.removed_ids,
            )
        )
    ):
        raise MemoryStoreError("Invalid memory activity.")
    return event


def _same_fact(left: MemoryDraft, right: MemoryDraft) -> bool:
    # Titles and curation metadata do not create a new fact. Preserve case and internal whitespace:
    # paths, code and commands may change meaning when normalized more aggressively.
    return all(
        a.strip() == b.strip()
        for a, b in (
            (left.content, right.content),
            (left.when_to_use, right.when_to_use),
            (left.reconsider_when, right.reconsider_when),
            (left.kind, right.kind),
            (left.workspace, right.workspace),
        )
    )


def _check_active_overlap(
    state: MemorySnapshot, draft: MemoryDraft, *exclude_ids: str, include_candidates: bool = False
) -> None:
    for entry in state.entries:
        if (
            entry.state == "archived"
            or entry.id in exclude_ids
            or (entry.state == "candidate" and not include_candidates)
        ):
            continue
        old = entry.draft
        same_context = (
            old.title.strip().casefold() == draft.title.strip().casefold()
            and old.workspace == draft.workspace
            and old.kind == draft.kind
            and old.when_to_use.strip() == draft.when_to_use.strip()
        )
        if same_context or _same_fact(old, draft):
            raise MemoryStoreError(
                f"An existing {entry.state} memory already covers this content or title and situation: {entry.id} "
                f"(revision {entry.revision}). Review it and update that memory, or specify a distinct situation.",
                code="memory_duplicate",
            )


def _entry(raw: dict[str, Any]) -> PersonalMemory:
    values = dict(raw)
    values["draft"] = _draft(values["draft"])
    values["source"] = _source(values["source"])
    if values.get("retired_by") is not None:
        values["retired_by"] = _source(values["retired_by"])
    values["previous"] = tuple(
        MemoryRevision(
            revision=item["revision"],
            draft=_draft(item["draft"]),
            source=_source(item["source"]),
            updated_at=item["updated_at"],
        )
        for item in values.get("previous", [])
    )
    entry = PersonalMemory(**values)
    if entry.state not in ("candidate", "active", "archived", "stale") or entry.revision < 1:
        raise MemoryStoreError("Invalid memory revision or state.")
    if len(entry.previous) > 5:
        raise MemoryStoreError("Too many memory revisions.")
    return entry


def render_memory(memory: PersonalMemory, terms: tuple[str, ...] = ()) -> str:
    draft = memory.draft
    return json.dumps(
        {
            "id": memory.id,
            "revision": memory.revision,
            "state": memory.state,
            "review_reason": memory.review_reason,
            "updated_at": memory.updated_at,
            "kind": draft.kind,
            "title": draft.title,
            "memory": draft.content,
            "when_to_use": draft.when_to_use,
            "reconsider_when": draft.reconsider_when,
            "scope": "project" if draft.workspace else "personal",
            "source": asdict(memory.source),
            "retired_by": asdict(memory.retired_by) if memory.retired_by else None,
            "matched_terms": terms,
            "topics": draft.topics,
            "aliases": draft.aliases,
            "use": draft.use,
            "follow_up": asdict(draft.follow_up) if draft.follow_up else None,
            "relations": [asdict(relation) for relation in draft.relations],
        },
        ensure_ascii=False,
    )


def _recall(item: dict) -> MemoryRecall:
    result = MemoryRecall(
        item["session_id"],
        item["query"],
        tuple(
            MemoryMatch(
                m["memory_id"],
                m["revision"],
                tuple(m["terms"]),
                tuple(m.get("routes", ())),
                m.get("layer", "L1"),
                m.get("context_key", ""),
            )
            for m in item["matches"]
        ),
        item["recalled_at"],
        item.get("turn_id", ""),
        tuple(item.get("excluded_ids", ())),
        item.get("searches", 0),
        item.get("context_chars", 0),
    )
    if any(type(v) is not int or v < 0 for v in (result.searches, result.context_chars)) or any(
        m.layer not in ("L0", "L1", "L2", "L3")
        or type(m.revision) is not int
        or m.revision < 1
        or not isinstance(m.context_key, str)
        or (m.context_key and not re.fullmatch(r"[a-f0-9]{24}", m.context_key))
        for m in result.matches
    ):
        raise MemoryStoreError("Invalid memory recall budget or provenance.")
    return result


class PersonalMemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else get_platform().config_dir / "personal-memory.json"
        self._retriever = MemoryRetriever()
        self._review_retriever = MemoryRetriever()
        self._read_lock = RLock()
        self._signature: tuple[int, int, int, int, int] | None = None
        self._snapshot: MemorySnapshot | None = None
        self._receipt_signature: tuple[int, int, int, int, int] | None = None
        self._receipts: tuple[int, MemorySnapshot] | None = None

    @property
    def receipts_path(self) -> Path:
        return self.path.with_suffix(".recalls.json")

    @property
    def receipts_lock_path(self) -> Path:
        return self.path.with_suffix(".recalls.lock")

    @property
    def activity_path(self) -> Path:
        return self.path.with_suffix(".activity.jsonl")

    @property
    def used_bytes(self) -> int:
        """Size of the last safely loaded snapshot; never stat a different file identity."""
        with self._read_lock:
            return self._signature[2] if self._signature else 0

    def load(self) -> MemorySnapshot:
        with self._read_lock:
            for attempt in range(3):
                catalog = self._load()
                if self._snapshot is None:
                    # An orphan receipt never resurrects a removed catalog.
                    return catalog
                try:
                    return self._load_receipts(catalog)
                except MemoryStoreError as error:
                    if error.code != "memory_generation_race" or attempt == 2:
                        raise
            raise MemoryStoreError("Memory changed repeatedly while reading. Retry the operation.")

    def _load_receipts(self, catalog: MemorySnapshot) -> MemorySnapshot:
        try:
            with secure_open_owner_only_binary(self.receipts_path) as stream:
                signature = self._file_signature(os.fstat(stream.fileno()))
                if signature != self._receipt_signature or self._receipts is None:
                    raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES or signature != self._file_signature(os.fstat(stream.fileno())):
                        raise MemoryStoreError("The memory recall file is too large or changed while reading.")
                    data = json.loads(raw)
                    if (
                        type(data["version"]) is not int
                        or data["version"] != 1
                        or type(data["catalog_generation"]) is not int
                        or data["catalog_generation"] < 0
                    ):
                        raise MemoryStoreError("Unknown memory recall format.")
                    state = MemorySnapshot(
                        recalls=tuple(_recall(r) for r in data["recalls"]),
                        generation=data["generation"],
                        activity=tuple(_activity(a) for a in data["activity"]),
                        activity_sequence=data["activity_sequence"],
                    )
                    state = lifecycle.restore(state, data)
                    if (
                        type(state.generation) is not int
                        or state.generation < data["catalog_generation"]
                        or type(state.activity_sequence) is not int
                        or state.activity_sequence < 0
                        or len(state.recalls) > MAX_RECALLS
                        or len(state.activity) > activity.RECENT_ACTIVITY
                        or any(a.sequence > state.activity_sequence for a in state.activity)
                        or any(a.sequence >= b.sequence for a, b in pairwise(state.activity))
                    ):
                        raise MemoryStoreError("Invalid memory recall state.")
                    self._receipts = (data["catalog_generation"], state)
                    self._receipt_signature = signature
        except OSError as error:
            self._receipts = None
            self._receipt_signature = None
            if error.errno in (errno.ENOENT, errno.ENOTDIR):
                return catalog
            raise MemoryStoreError("Memory recalls could not be read safely.") from error
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise MemoryStoreError("The memory recall file is invalid; it has not been overwritten.") from error
        catalog_generation, state = self._receipts
        if catalog_generation > catalog.generation:
            raise MemoryStoreError(
                "Memory recalls are newer than the catalog; restore the matching files.", code="memory_generation_race"
            )
        if catalog_generation < catalog.generation:
            # Catalog commits carry a recovery outbox. A crash between the two
            # atomic replacements must not roll a correction or deletion back.
            return catalog
        return replace(
            catalog,
            generation=state.generation,
            recalls=state.recalls,
            activity=state.activity,
            activity_sequence=state.activity_sequence,
            uses=state.uses,
            review_notice=state.review_notice,
            last_review_at=state.last_review_at,
        )

    def _write_receipts(self, state: MemorySnapshot, *, catalog_generation: int) -> None:
        payload = (
            json.dumps(
                {
                    "version": 1,
                    "catalog_generation": catalog_generation,
                    "generation": state.generation,
                    "recalls": [asdict(r) for r in state.recalls],
                    "activity": [asdict(a) for a in state.activity],
                    "activity_sequence": state.activity_sequence,
                    "uses": [asdict(u) for u in state.uses],
                    "review_notice": asdict(state.review_notice) if state.review_notice else None,
                    "last_review_at": state.last_review_at,
                },
                ensure_ascii=True,
            )
            + "\n"
        )
        if len(payload.encode("utf-8")) > MAX_BYTES:
            raise MemoryStoreError("Memory recall data exceeds the integrity limit.")
        atomic_write_owner_only_text(self.receipts_path, payload)
        with self._read_lock:
            self._receipt_signature = None
            self._receipts = None

    def _update_receipts(self, edit: Callable[[MemorySnapshot], MemorySnapshot]) -> MemorySnapshot:
        if any(len(e.previous) > MAX_REVISIONS for e in self.load().entries):
            self._update(lambda state: state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Readers hold only the receipt lock. Catalog writers take catalog then
        # receipt; they cannot replace the catalog while a recall is committed.
        with FileLock(self.receipts_lock_path, timeout=2):
            before = self.load()
            try:
                activity.synchronize(self.activity_path, before)
            except ValueError as error:
                raise MemoryStoreError(str(error)) from error
            after = edit(before)
            if after == before:
                return before
            if after.entries != before.entries or self._snapshot is None:
                raise MemoryStoreError("A receipt operation cannot change the memory catalog.")
            after = replace(after, generation=before.generation + 1)
            activity.validate_pending(after, before.activity_sequence)
            self._write_receipts(after, catalog_generation=self._snapshot.generation)
            try:
                activity.synchronize(self.activity_path, after)
            except OSError, ValueError:
                _log.warning("Memory recall committed; activity synchronization is pending", exc_info=True)
            return after

    @staticmethod
    def _file_signature(stat: os.stat_result) -> tuple[int, int, int, int, int]:
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _load(self) -> MemorySnapshot:
        try:
            with secure_open_owner_only_binary(self.path) as stream:
                # Always perform the owner/no-follow checks, even on a cache hit.
                # Fingerprint the open handle, never a separate path stat: another
                # process may atomically replace the path while it is being read.
                signature = self._file_signature(os.fstat(stream.fileno()))
                if signature == self._signature and self._snapshot is not None:
                    return self._snapshot
                self._snapshot = None
                self._signature = None
                raw = stream.read(MAX_BYTES + 1)
                if signature != self._file_signature(os.fstat(stream.fileno())):
                    raise MemoryStoreError("The personal memory file changed while being read. Retry the operation.")
        except OSError as error:
            self._snapshot = None
            self._signature = None
            if error.errno in (errno.ENOENT, errno.ENOTDIR):
                return MemorySnapshot()
            raise MemoryStoreError("The personal memory file could not be read safely.") from error
        if len(raw) > MAX_BYTES:
            raise MemoryStoreError("The personal memory store exceeds its size limit.")
        try:
            data = json.loads(raw)
            if (
                type(data["version"]) is not int
                or data["version"] not in (1, 2, 3, STORE_VERSION)
                or data["mode"] not in ("auto", "manual", "off")
            ):
                raise MemoryStoreError("Unknown personal memory format.")
            entries = tuple(_entry(item) for item in data["entries"])
            recalls = tuple(_recall(item) for item in data.get("recalls", []))
            if len(recalls) > MAX_RECALLS or type(data["capture"]) is not bool:
                raise MemoryStoreError("Invalid personal memory store limits.")
            if len({entry.id for entry in entries}) != len(entries):
                raise MemoryStoreError("Duplicate memory identities.")
            generation = data.get("generation", 0)
            if type(generation) is not int or generation < 0:
                raise MemoryStoreError("Invalid personal memory generation.")
            auto_save = data.get("auto_save", True)
            if type(auto_save) is not bool:
                raise MemoryStoreError("Invalid automatic memory setting.")
            notifications = data.get("buddy_notifications", False)
            if type(notifications) is not bool:
                raise MemoryStoreError("Invalid memory notification setting.")
            recent = tuple(_activity(item) for item in data.get("activity", ()))
            sequence = data.get("activity_sequence", 0)
            if (
                type(sequence) is not int
                or sequence < 0
                or len(recent) > activity.RECENT_ACTIVITY
                or any(a.sequence < 1 or a.sequence > sequence for a in recent)
                or any(a.sequence >= b.sequence for a, b in pairwise(recent))
            ):
                raise MemoryStoreError("Invalid memory activity sequence.")
            self._snapshot = MemorySnapshot(
                data["mode"], data["capture"], entries, recalls, generation, auto_save, notifications, recent, sequence
            )
            self._snapshot = lifecycle.restore(self._snapshot, data)
            self._signature = signature
            return self._snapshot
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise MemoryStoreError("The personal memory file is invalid; it has not been overwritten.") from error

    def _update(
        self,
        edit: Callable[[MemorySnapshot], MemorySnapshot],
        *,
        actor: str = "user",
        session_id: str = "",
        turn_id: str = "",
        require_journal: bool = False,
    ) -> MemorySnapshot:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.path.with_suffix(".lock"), timeout=2), FileLock(self.receipts_lock_path, timeout=2):
            before = self.load()
            try:
                activity.synchronize(self.activity_path, before)
            except ValueError as error:
                raise MemoryStoreError(str(error)) from error
            before = self._compact_history(before)
            after = edit(before)
            if after == before:
                return after
            after = replace(
                activity.record_changes(before, after, actor=actor, session_id=session_id, turn_id=turn_id),
                generation=before.generation + 1,
            )
            surviving = {e.id for e in after.entries}
            original = {e.id: e for e in before.entries}
            for entry in after.entries:
                old = original.get(entry.id)
                if old and old.draft != entry.draft and entry.source.role == "user" and turn_id:
                    after = lifecycle.record_feedback(
                        after, entry.id, entry.revision, "corrected", entry.source.session_id, turn_id
                    )
            after = replace(
                after,
                uses=tuple(u for u in after.uses if u.memory_id in surviving),
                review_notice=after.review_notice
                if after.review_notice is None or set(after.review_notice.memory_ids) <= surviving
                else None,
            )
            if after.review_notice is not None:
                condition_ids = lifecycle.condition_review_ids(after)
                eligible = {
                    e.id
                    for e in after.entries
                    if e.state
                    in (("active", "candidate", "stale") if after.review_notice.topic else ("candidate", "stale"))
                    or e.id in condition_ids
                }
                ids = tuple(mid for mid in after.review_notice.memory_ids if mid in eligible)
                after = replace(
                    after,
                    review_notice=replace(after.review_notice, memory_ids=ids)
                    if ids or after.review_notice.archived_candidates
                    else None,
                )
            return self._commit_catalog(before, after, require_journal=require_journal)

    def _commit_catalog(
        self, before: MemorySnapshot, after: MemorySnapshot, *, require_journal: bool = False
    ) -> MemorySnapshot:
        pending_count = sum(event.sequence > before.activity_sequence for event in after.activity)
        if after.activity_sequence - before.activity_sequence != pending_count:
            raise MemoryStoreError(
                "This operation creates too many activity records; reduce the selection or unlink related memories first."
            )
        try:
            activity.validate_pending(after, before.activity_sequence)
        except ValueError as error:
            raise MemoryStoreError(str(error)) from error
        payload = json.dumps({"version": STORE_VERSION, **asdict(after)}, ensure_ascii=True, indent=2) + "\n"
        if len(payload.encode("utf-8")) > MAX_BYTES:
            raise MemoryStoreError("Memory catalog exceeds the integrity limit; archive it before continuing.")
        atomic_write_owner_only_text(self.path, payload)
        # Do not associate 'after' with a fresh path stat: a different writer
        # might already own that file. The next secure read supplies both.
        with self._read_lock:
            self._snapshot = None
            self._signature = None
        try:
            self._write_receipts(after, catalog_generation=after.generation)
            activity.synchronize(self.activity_path, after)
        except (OSError, ValueError) as error:
            if require_journal:
                raise MemoryStoreError(
                    "Memory removed from recall, but activity cleanup is pending. Retry forgetting to finish local deletion."
                ) from error
            # The committed snapshot retains the outbox. The next writer must
            # drain it before making another change, so no event is skipped.
            _log.warning("Memory saved; activity journal synchronization is pending", exc_info=True)
        return after

    def _compact_history(self, state: MemorySnapshot) -> MemorySnapshot:
        legacy = {(e.id, r.revision): r for e in state.entries if len(e.previous) > MAX_REVISIONS for r in e.previous}
        if not legacy:
            return state
        missing = dict(legacy)
        before = state.activity_sequence + 1
        while missing and before > 1:
            page = activity.read_page(self.activity_path, before=before)
            if not page:
                break
            for row in page:
                if row.get("draft") is not None:
                    key = (row["memory_id"], row["revision"])
                    old = missing.get(key)
                    if (
                        old is not None
                        and row["draft"] == asdict(old.draft)
                        and (row.get("memory_source") or row["source"]) == asdict(old.source)
                    ):
                        missing.pop(key)
            before = page[0]["sequence"]
        items = list(missing.items())
        for start in range(0, len(items), 64):
            staged = state
            for (memory_id, revision), old in items[start : start + 64]:
                staged = activity.record(
                    staged,
                    "revision_imported",
                    memory_id=memory_id,
                    revision=revision,
                    actor="system",
                    draft=old.draft,
                    source=old.source,
                    occurred_at=old.updated_at,
                )
            staged = replace(staged, generation=state.generation + 1)
            if self._snapshot is None:
                raise MemoryStoreError("The memory catalog is unavailable during history import.")
            # Commit only the small outbox per chunk; replace the large legacy catalog once.
            activity.validate_pending(staged, state.activity_sequence)
            self._write_receipts(staged, catalog_generation=self._snapshot.generation)
            try:
                activity.synchronize(self.activity_path, staged)
            except (OSError, ValueError) as error:
                raise MemoryStoreError(
                    "History import is pending; retry to finish before compacting the catalog."
                ) from error
            state = staged
        trimmed = replace(
            state,
            entries=tuple(replace(e, previous=e.previous[-MAX_REVISIONS:]) for e in state.entries),
            generation=state.generation + 1,
        )
        return self._commit_catalog(state, trimmed, require_journal=True)

    def revisions(
        self, memory_id: str, *, before_revision: int = 0, limit: int = 20, expected_revision: int = 0
    ) -> tuple[MemoryRevision, ...]:
        if type(before_revision) is not int or before_revision < 0 or not 1 <= limit <= 100:
            raise MemoryStoreError("Invalid memory revision cursor.")
        with FileLock(self.path.with_suffix(".lock"), timeout=2), FileLock(self.receipts_lock_path, timeout=2):
            state = self.load()
            entry = next((e for e in state.entries if e.id == memory_id), None)
            if entry is None:
                raise MemoryStoreError("This memory no longer exists.")
            if expected_revision and entry.revision != expected_revision:
                raise MemoryStoreError("This memory changed elsewhere. Refresh before loading history.")
            before = min(before_revision or entry.revision, entry.revision)
            versions = {r.revision: r for r in entry.previous if r.revision < before}
            try:
                activity.synchronize(self.activity_path, state)
                cursor = state.activity_sequence + 1
                while cursor > 1:
                    page = activity.read_page(self.activity_path, before=cursor)
                    if not page:
                        break
                    for row in reversed(page):
                        if row["memory_id"] == memory_id and row["revision"] < before and row.get("draft") is not None:
                            versions.setdefault(
                                row["revision"],
                                MemoryRevision(
                                    row["revision"],
                                    _draft(row["draft"]),
                                    _source(row.get("memory_source") or row["source"]),
                                    row["occurred_at"],
                                ),
                            )
                    cursor = page[0]["sequence"]
                return tuple(versions[v] for v in sorted(versions, reverse=True)[:limit])
            except (ValueError, OSError, KeyError, TypeError) as error:
                raise MemoryStoreError("Memory revision history could not be read safely.") from error

    def configure(self, mode: MemoryMode, capture: bool, *, auto_save: bool | None = None) -> MemorySnapshot:
        if mode not in ("auto", "manual", "off") or type(capture) is not bool:
            raise MemoryStoreError("Invalid memory settings.")
        if auto_save is not None and type(auto_save) is not bool:
            raise MemoryStoreError("Invalid automatic memory setting.")
        return self._update(
            lambda state: replace(
                state, mode=mode, capture=capture, auto_save=state.auto_save if auto_save is None else auto_save
            )
        )

    def maintain(self, *, workspace: str | None = None, notify: bool = True) -> MemorySnapshot:
        now = datetime.now(UTC)
        key = workspace_key(workspace) if workspace is not None else None
        state = self.load()
        # Bounded commits retain every event when a large imported queue expires together.
        # Concurrent additions beyond this pass's initial size wait for the next call.
        for _ in range(len(state.entries) // (activity.RECENT_ACTIVITY - 1) + 2):
            if state.mode == "off" or lifecycle.maintain(state, now=now, workspace=key, notify=notify) == state:
                return state
            state = self._update(
                lambda current: lifecycle.maintain(current, now=now, workspace=key, notify=notify), actor="system"
            )
        return state

    def dismiss_review(self) -> MemorySnapshot:
        return self._update_receipts(lambda state: replace(state, review_notice=None))

    @staticmethod
    def _find(state: MemorySnapshot, memory_id: str, revision: int) -> PersonalMemory:
        entry = next((item for item in state.entries if item.id == memory_id), None)
        if entry is None:
            raise MemoryStoreError("This memory no longer exists. Refresh the list.")
        if entry.revision != revision:
            raise MemoryStoreError("This memory changed elsewhere. Refresh before editing it.")
        return entry

    def set_buddy_notifications(self, enabled: bool) -> MemorySnapshot:
        if type(enabled) is not bool:
            raise MemoryStoreError("Invalid memory notification setting.")
        return self._update(lambda state: replace(state, buddy_notifications=enabled))

    @staticmethod
    def _validate_relations(state: MemorySnapshot, draft: MemoryDraft, memory_id: str = "") -> None:
        entries = {entry.id: entry for entry in state.entries}
        for relation in draft.relations:
            target = PersonalMemoryStore._find(state, relation.memory_id, relation.revision)
            if target.id == memory_id or target.state == "candidate":
                raise MemoryStoreError("Relations need a different, reviewed source memory.")
            if target.draft.workspace and target.draft.workspace != draft.workspace:
                raise MemoryStoreError("A relation cannot widen a project's private scope.")
            if relation.kind != "merged_from" and target.state != "active":
                raise MemoryStoreError("Related evidence must refer to active source memories.")
            if relation.kind not in ("derived_from", "merged_from"):
                continue
            pending, seen = [target.id], set()
            while pending:
                current = pending.pop()
                if current == memory_id:
                    raise MemoryStoreError("Derived memories cannot form an evidence cycle.")
                if current in seen:
                    continue
                seen.add(current)
                parent = entries.get(current)
                if parent:
                    pending.extend(
                        r.memory_id for r in parent.draft.relations if r.kind in ("derived_from", "merged_from")
                    )

    @staticmethod
    def evidence_current(
        entry: PersonalMemory, entries: tuple[PersonalMemory, ...] | dict[str, PersonalMemory]
    ) -> bool:
        if not entry.draft.relations:
            return True
        by_id = entries if isinstance(entries, dict) else {item.id: item for item in entries}
        pending, seen = [entry], set()
        while pending:
            current = pending.pop()
            if current.id in seen:
                continue
            seen.add(current.id)
            for relation in current.draft.relations:
                parent = by_id.get(relation.memory_id)
                if (
                    parent is None
                    or parent.revision != relation.revision
                    or parent.state == "candidate"
                    or (relation.kind != "merged_from" and parent.state != "active")
                ):
                    return False
                pending.append(parent)
        return True

    def feedback(
        self,
        memory_id: str,
        revision: int,
        outcome: MemoryFeedback,
        *,
        session_id: str,
        turn_id: str = "",
        reason: str = "",
        source: MemorySource | None = None,
        workspace: str | None = None,
    ) -> MemorySnapshot:
        if outcome not in ("applied", "not_applicable", "helpful", "incorrect") or len(reason) > 600:
            raise MemoryStoreError("Choose a supported memory feedback and a short reason.")

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            entry = self._find(state, memory_id, revision)
            if workspace is not None and (
                state.mode == "off" or entry.draft.workspace not in ("", workspace_key(workspace))
            ):
                raise MemoryStoreError("This memory is unavailable in the current project.")
            receipt = next((r for r in state.recalls if r.session_id == session_id), None)
            actual_turn = turn_id or (receipt.turn_id if receipt else "")
            actor = "user" if outcome != "applied" and source is not None and source.role == "user" else "agent"
            if outcome in ("helpful", "incorrect") and actor != "user":
                raise MemoryStoreError("User feedback needs the user's evidence.")
            if outcome == "applied" and (
                not receipt
                or receipt.turn_id != actual_turn
                or not any(m.memory_id == memory_id and m.revision == revision for m in receipt.matches)
            ):
                raise MemoryStoreError("Only a memory provided in this turn can be reported as applied.")
            if outcome == "not_applicable":
                if (
                    receipt is None
                    or receipt.turn_id != actual_turn
                    or not any(m.memory_id == memory_id and m.revision == revision for m in receipt.matches)
                ):
                    raise MemoryStoreError("There is no current-turn recall to exclude.")
                revised = replace(receipt, excluded_ids=tuple(dict.fromkeys((*receipt.excluded_ids, memory_id))))
                state = replace(state, recalls=tuple(revised if r is receipt else r for r in state.recalls))
            if outcome == "incorrect" and entry.state == "active":
                paused = replace(
                    entry,
                    state="archived",
                    revision=entry.revision + 1,
                    updated_at=_now(),
                    retired_by=source,
                    review_reason="incorrect",
                )
                state = replace(state, entries=tuple(paused if e.id == entry.id else e for e in state.entries))
            if any(
                a.action == outcome
                and a.memory_id == memory_id
                and a.revision == revision
                and a.session_id == session_id
                and a.turn_id == actual_turn
                and a.actor == actor
                and a.detail == reason
                for a in state.activity
            ):
                return state
            if (
                actor == "user"
                and outcome in ("not_applicable", "helpful")
                and receipt
                and receipt.turn_id == actual_turn
            ):
                state = lifecycle.record_feedback(
                    state,
                    memory_id,
                    revision,
                    outcome,
                    session_id,
                    actual_turn,
                    context_key=next(
                        (m.context_key for m in receipt.matches if m.memory_id == memory_id and m.revision == revision),
                        "",
                    ),
                )
            return activity.record(
                state,
                outcome,
                memory_id=memory_id,
                revision=revision,
                session_id=session_id,
                turn_id=actual_turn,
                actor=actor,
                detail=reason,
                source=source,
            )

        return self._update(edit) if outcome == "incorrect" else self._update_receipts(edit)

    def merge(
        self,
        references: tuple[tuple[str, int], ...],
        draft: MemoryDraft,
        source: MemorySource,
        *,
        workspace: str | None = None,
        turn_id: str = "",
    ) -> PersonalMemory:
        """Commit one replacement and retire its duplicate sources in the same lock."""
        _validate_draft(draft)
        _source(asdict(source))
        if not 2 <= len(references) <= 6 or len({mid for mid, _ in references}) != len(references):
            raise MemoryStoreError("Choose two to six distinct memories to merge.")

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            subjects = [self._find(state, mid, rev) for mid, rev in references]
            first = subjects[0]
            if any(
                e.state != "active"
                or e.draft.kind != first.draft.kind
                or e.draft.workspace != first.draft.workspace
                or e.draft.follow_up is not None
                for e in subjects
            ):
                raise MemoryStoreError("Merge only active memories of one kind and scope, without follow-up tasks.")
            if workspace is not None and (
                state.mode == "off" or first.draft.workspace not in ("", workspace_key(workspace))
            ):
                raise MemoryStoreError("This memory is unavailable in the current project.")
            merged = replace(
                draft,
                workspace=first.draft.workspace,
                kind=first.draft.kind,
                relations=tuple(r for r in first.draft.relations if r.memory_id not in {e.id for e in subjects[1:]})
                + tuple(MemoryRelation(e.id, e.revision + 1, "merged_from", "Merged source") for e in subjects[1:]),
            )
            if merged.follow_up is not None:
                raise MemoryStoreError("Follow-up tasks cannot be merged as facts.")
            _validate_draft(merged)
            _check_active_overlap(state, merged, *(e.id for e in subjects))
            now = _now()
            retired = {
                e.id: replace(e, state="archived", revision=e.revision + 1, updated_at=now) for e in subjects[1:]
            }
            self._validate_relations(
                replace(state, entries=tuple(retired.get(e.id, e) for e in state.entries)), merged, first.id
            )
            target = replace(
                first,
                draft=merged,
                source=source,
                revision=first.revision + 1,
                updated_at=now,
                previous=(*first.previous, MemoryRevision(first.revision, first.draft, first.source, first.updated_at))[
                    -MAX_REVISIONS:
                ],
            )
            return replace(
                state, entries=tuple(target if e.id == first.id else retired.get(e.id, e) for e in state.entries)
            )

        result = self._update(
            edit, actor="agent" if workspace is not None else "user", session_id=source.session_id, turn_id=turn_id
        )
        return next(e for e in result.entries if e.id == references[0][0])

    def update_follow_up(
        self,
        memory_id: str,
        revision: int,
        follow_up: MemoryFollowUp,
        source: MemorySource,
        *,
        workspace: str | None = None,
        turn_id: str = "",
        reopen: bool = False,
    ) -> PersonalMemory:
        """A user's transition updates one accepted commitment, never the session's todo list."""
        current = self.load()
        entry = self._find(current, memory_id, revision)
        if entry.state != "active" or entry.draft.kind != "intention" or entry.draft.follow_up is None:
            raise MemoryStoreError("Choose an active, accepted follow-up.")
        return self.save(
            replace(entry.draft, follow_up=follow_up),
            source,
            memory_id=memory_id,
            revision=revision,
            request_workspace=workspace,
            authorization="request" if workspace is not None else "manual",
            turn_id=turn_id,
            reopen=reopen,
        )

    def save(
        self,
        draft: MemoryDraft,
        source: MemorySource,
        *,
        memory_id: str = "",
        revision: int = 0,
        candidate: bool = False,
        replaces_id: str = "",
        replaces_revision: int = 0,
        request_workspace: str | None = None,
        authorization: Literal["manual", "request", "capture", "summary"] = "manual",
        reviewed_catalog: tuple[tuple[str, int], ...] | None = None,
        turn_id: str = "",
        reopen: bool = False,
    ) -> PersonalMemory:
        _validate_draft(draft)
        if candidate and not draft.when_to_use.strip():
            raise MemoryStoreError("Suggestions need a future situation where the memory is useful.")
        _source(asdict(source))
        draft = replace(
            draft,
            title=draft.title.strip(),
            content=draft.content.strip(),
            when_to_use=draft.when_to_use.strip(),
            reconsider_when=draft.reconsider_when.strip(),
            workspace=workspace_key(draft.workspace),
            topics=tuple(dict.fromkeys(topic.strip() for topic in draft.topics)),
            aliases=tuple(dict.fromkeys(alias.strip() for alias in draft.aliases)),
        )
        saved: PersonalMemory | None = None

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            nonlocal saved, draft
            if reviewed_catalog is not None and review_key(state, request_workspace or "") != reviewed_catalog:
                raise MemoryStoreError("Related memories changed. Inspect them again before saving.")
            if authorization != "manual" and state.mode == "off":
                raise MemoryStoreError("Chat memory is disabled.")
            if (
                draft.use == "always"
                and authorization not in ("manual", "request")
                and not any(e.id in (memory_id, replaces_id) and e.draft.use == "always" for e in state.entries)
            ):
                raise MemoryStoreError("Always-available preferences require an explicit user choice.")
            self._validate_relations(state, draft, memory_id)
            if authorization == "summary":
                if not candidate or memory_id or replaces_id or draft.workspace or not source.item_id:
                    raise MemoryStoreError("Summary memories must be sourced personal suggestions, without overwrites.")
                if not state.capture:
                    raise MemoryStoreError("Memory suggestions are disabled.")
                # A repeated compression of the same evidence is not new knowledge.
                # Include archived entries so rejected suggestions cannot reappear.
                existing_source = next(
                    (
                        entry
                        for entry in state.entries
                        if entry.source == source and entry.draft.kind == draft.kind and not entry.draft.workspace
                    ),
                    None,
                )
                if existing_source is not None:
                    saved = existing_source
                    return state
            if authorization == "capture" and not state.capture:
                raise MemoryStoreError("Memory suggestions are disabled.")
            if (
                authorization == "capture"
                and not candidate
                and not (state.auto_save and draft.kind == "preference" and source.role == "user")
            ):
                raise MemoryStoreError("This memory needs review before activation.")
            if candidate and (state.mode == "off" or (not state.capture and authorization != "request")):
                raise MemoryStoreError("Memory suggestions are disabled.")
            if candidate and memory_id:
                raise MemoryStoreError("Suggestions cannot overwrite a memory.")
            old = self._find(state, memory_id, revision) if memory_id else None
            if authorization == "capture" and old is not None and old.state == "archived":
                raise MemoryStoreError("A paused memory cannot be changed automatically.")
            target = self._find(state, replaces_id, replaces_revision) if replaces_id else None
            if authorization == "capture" and target is not None and target.state == "archived":
                raise MemoryStoreError("A paused memory cannot be changed automatically.")
            for subject in (old, target):
                if subject is not None and subject.draft.follow_up is not None:
                    previous = subject.draft.follow_up.status
                    following = draft.follow_up.status if draft.follow_up else None
                    if previous in ("completed", "cancelled") and following not in (None, previous):
                        if following != "pending":
                            raise MemoryStoreError("Reopen a closed follow-up as pending before changing its progress.")
                        if authorization != "manual" and not reopen:
                            raise MemoryStoreError("A closed follow-up requires an explicit reopen request.")
            for subject in (old, target):
                if (
                    subject is not None
                    and request_workspace is not None
                    and subject.draft.workspace
                    and subject.draft.workspace != workspace_key(request_workspace)
                ):
                    raise MemoryStoreError("This memory belongs to another project. Manage it in /memory.")
                if subject is not None and request_workspace is not None:
                    # Chat corrections keep the existing audience. Explicit scope
                    # changes remain available in the library editor.
                    draft = replace(draft, workspace=subject.draft.workspace)
            if target is not None and target.state == "candidate":
                raise MemoryStoreError("Review a suggestion before proposing a correction to it.")
            if old is not None and old.draft == draft and not (old.state == "stale" and authorization == "request"):
                saved = old
                return state
            if authorization != "manual" and any(
                item.state == "archived" and item.id != memory_id and _same_fact(item.draft, draft)
                for item in state.entries
            ):
                raise MemoryStoreError(
                    "This memory was paused. Restore it in /memory instead of creating a duplicate.",
                    code="memory_paused",
                )
            if not memory_id:
                merge_sources = (
                    {r.memory_id for r in draft.relations}
                    if candidate and draft.relations and all(r.kind == "merged_from" for r in draft.relations)
                    else set()
                )
                existing = next(
                    (
                        item
                        for item in state.entries
                        if _same_fact(item.draft, draft)
                        and item.id not in merge_sources
                        and item.state != "archived"
                        and item.replaces_id == replaces_id
                        and item.replaces_revision == replaces_revision
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        existing.draft.use,
                        existing.draft.follow_up,
                        existing.draft.relations,
                        existing.draft.aliases,
                        existing.draft.topics,
                    ) != (draft.use, draft.follow_up, draft.relations, draft.aliases, draft.topics):
                        raise MemoryStoreError(
                            f"This fact already exists: {existing.id} (revision {existing.revision}). "
                            "Update that memory by ID and revision to change its metadata.",
                            code="memory_duplicate",
                        )
                    if not candidate and existing.state == "candidate":
                        if existing.draft.relations and all(r.kind == "merged_from" for r in existing.draft.relations):
                            raise MemoryStoreError(
                                "Confirm the merge proposal in /memory or organize_memory; saving a duplicate cannot retire its sources."
                            )
                        _check_active_overlap(state, draft, existing.id)
                        saved = replace(
                            existing, source=source, state="active", revision=existing.revision + 1, updated_at=_now()
                        )
                        return replace(
                            state, entries=tuple(saved if item.id == existing.id else item for item in state.entries)
                        )
                    saved = existing
                    return state
            _check_active_overlap(
                state,
                draft,
                memory_id,
                replaces_id,
                *(
                    {r.memory_id for r in draft.relations}
                    if candidate and draft.relations and all(r.kind == "merged_from" for r in draft.relations)
                    else ()
                ),
                include_candidates=candidate or bool(old and old.state == "candidate"),
            )
            if authorization != "manual" and not memory_id and not replaces_id:
                similar = self._review_retriever.near_duplicates(state.entries, draft)
                if candidate and draft.relations and all(r.kind == "merged_from" for r in draft.relations):
                    similar = tuple(e for e in similar if e.id not in {r.memory_id for r in draft.relations})
                if similar:
                    entry = similar[0]
                    raise MemoryStoreError(
                        f"Lexically similar memory: {entry.id} (revision {entry.revision}). "
                        "Revise that ID, or describe the different situation in when_to_use before adding a separate memory.",
                        code="memory_duplicate",
                    )
            now = _now()
            previous = (
                (*old.previous, MemoryRevision(old.revision, old.draft, old.source, old.updated_at))[-MAX_REVISIONS:]
                if old
                else ()
            )
            saved = PersonalMemory(
                id=old.id if old else uuid4().hex[:16],
                revision=old.revision + 1 if old else 1,
                draft=draft,
                source=source,
                state="active"
                if old and old.state == "stale" and authorization == "request" and not candidate
                else old.state
                if old
                else ("candidate" if candidate else "active"),
                created_at=old.created_at if old else now,
                updated_at=now,
                previous=previous,
                replaces_id=old.replaces_id if old else replaces_id,
                replaces_revision=old.replaces_revision if old else replaces_revision,
                retired_by=old.retired_by if old else None,
                review_reason=old.review_reason
                if old and not (old.state == "stale" and authorization == "request")
                else "",
            )
            if (
                draft.kind == "lesson"
                and authorization in ("request", "capture")
                and len(render_memory(saved)) > MAX_CONTEXT_CHARS
            ):
                raise MemoryStoreError(
                    "This lesson cannot fit in a recall. Shorten the evidence or separate independent decisions.",
                    code="memory_not_distilled",
                )
            return replace(state, entries=(*(item for item in state.entries if item.id != saved.id), saved))

        self._update(
            edit, actor="user" if authorization == "manual" else "agent", session_id=source.session_id, turn_id=turn_id
        )
        if saved is None:
            raise MemoryStoreError("The memory was not saved.")
        return saved

    def set_state(
        self,
        memory_id: str,
        revision: int,
        status: MemoryState,
        *,
        session_id: str = "",
        confirmation: MemorySource | None = None,
        turn_id: str = "",
    ) -> MemorySnapshot:
        return self.set_states(
            ((memory_id, revision),), status, session_id=session_id, confirmation=confirmation, turn_id=turn_id
        )

    def set_states(
        self,
        references: tuple[tuple[str, int], ...],
        status: MemoryState,
        *,
        session_id: str = "",
        confirmation: MemorySource | None = None,
        turn_id: str = "",
    ) -> MemorySnapshot:
        self._validate_batch(references)
        if status not in ("active", "archived"):
            raise MemoryStoreError("Choose active or archived.")

        def change(state: MemorySnapshot, memory_id: str, revision: int) -> MemorySnapshot:
            old = self._find(state, memory_id, revision)
            if old.state == status:
                if status == "active" and old.id in lifecycle.condition_review_ids(state):
                    state = replace(state, uses=tuple(u for u in state.uses if u.memory_id != old.id))
                    return activity.record(
                        state,
                        "conditions_confirmed",
                        memory_id=old.id,
                        revision=old.revision,
                        session_id=session_id,
                        turn_id=turn_id,
                        actor="user",
                        source=confirmation,
                    )
                return state
            source_ids = {r.memory_id for r in old.draft.relations if r.kind == "merged_from"}
            if (
                status == "active"
                and old.draft.relations
                and all(r.kind == "merged_from" for r in old.draft.relations)
                and (
                    old.state == "candidate"
                    or old.review_reason == "candidate_expired"
                    or any(e.id in source_ids and e.state == "active" for e in state.entries)
                )
            ):
                if confirmation is not None:
                    _source(asdict(confirmation))
                    origin = next(
                        (
                            e
                            for e in reversed(state.activity)
                            if e.memory_id == old.id and e.revision == old.revision and e.action == "proposed"
                        ),
                        None,
                    )
                    cursor = state.activity_sequence + 1
                    while origin is None and cursor > 1:
                        page = activity.read_page(self.activity_path, before=cursor)
                        if not page:
                            break
                        origin = next(
                            (
                                _activity(r)
                                for r in reversed(page)
                                if r["memory_id"] == old.id
                                and r["revision"] == old.revision
                                and r["action"] == "proposed"
                            ),
                            None,
                        )
                        cursor = page[0]["sequence"]
                    if (
                        confirmation.role != "user"
                        or not confirmation.quote
                        or not turn_id
                        or origin is None
                        or not origin.turn_id
                        or (origin.session_id, origin.turn_id) == (session_id, turn_id)
                    ):
                        raise MemoryStoreError(
                            "A merge proposal needs confirmation in a later user turn, or in /memory."
                        )
                sources = [self._find(state, r.memory_id, r.revision) for r in old.draft.relations]
                if (
                    len(sources) < 2
                    or old.draft.follow_up is not None
                    or any(
                        e.state != "active"
                        or e.draft.kind != old.draft.kind
                        or e.draft.workspace != old.draft.workspace
                        or e.draft.follow_up
                        for e in sources
                    )
                ):
                    raise MemoryStoreError("Merge sources changed; review a new proposal before confirming.")
                _check_active_overlap(state, old.draft, old.id, *source_ids)
                now = _now()
                merged = replace(
                    old,
                    state="active",
                    revision=old.revision + 1,
                    updated_at=now,
                    source=confirmation or old.source,
                    retired_by=None,
                    review_reason="",
                    previous=(MemoryRevision(old.revision, old.draft, old.source, old.updated_at),),
                    draft=replace(
                        old.draft, relations=tuple(replace(r, revision=r.revision + 1) for r in old.draft.relations)
                    ),
                )
                entries = tuple(
                    merged
                    if e.id == old.id
                    else replace(e, state="archived", revision=e.revision + 1, updated_at=now)
                    if e.id in source_ids
                    else e
                    for e in state.entries
                )
                return replace(state, entries=entries)
            if status == "active" and old.replaces_id:
                self._validate_relations(state, old.draft, old.replaces_id)
                target = self._find(state, old.replaces_id, old.replaces_revision)
                _check_active_overlap(state, old.draft, old.id, target.id)
                accepted = replace(
                    target,
                    revision=target.revision + 1,
                    draft=old.draft,
                    source=old.source,
                    updated_at=_now(),
                    state="active",
                    retired_by=None,
                    previous=(
                        *target.previous,
                        MemoryRevision(
                            target.revision,
                            target.draft,
                            target.source,
                            target.updated_at,
                        ),
                    )[-MAX_REVISIONS:],
                )
                return replace(
                    state, entries=(*(item for item in state.entries if item.id not in (old.id, target.id)), accepted)
                )
            if status == "active":
                self._validate_relations(state, old.draft, old.id)
                _check_active_overlap(state, old.draft, old.id)
                if old.state == "stale":
                    state = replace(state, uses=tuple(u for u in state.uses if u.memory_id != old.id))
            return replace(
                state,
                entries=tuple(
                    replace(
                        item,
                        state=status,
                        revision=item.revision + 1,
                        updated_at=_now(),
                        retired_by=None,
                        review_reason="" if status == "active" else item.review_reason,
                    )
                    if item.id == old.id
                    else item
                    for item in state.entries
                ),
            )

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            for memory_id, revision in references:
                state = change(state, memory_id, revision)
            return state

        return self._update(edit, session_id=session_id, turn_id=turn_id)

    def pause(
        self, memory_id: str, revision: int, source: MemorySource, workspace: str, *, turn_id: str = ""
    ) -> PersonalMemory:
        """Retain the original evidence and record why this version stopped applying."""
        _source(asdict(source))
        if source.role != "user" or not source.quote.strip():
            raise MemoryStoreError("Pausing through chat needs the user's own evidence.")

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            if state.mode == "off":
                raise MemoryStoreError("Chat memory is disabled.")
            old = self._find(state, memory_id, revision)
            if old.draft.workspace not in ("", workspace_key(workspace)):
                raise MemoryStoreError("This memory belongs to another project.")
            if old.state != "active":
                raise MemoryStoreError("Only an active memory can be paused through chat.")
            paused = replace(old, state="archived", revision=old.revision + 1, updated_at=_now(), retired_by=source)
            return replace(state, entries=tuple(paused if item.id == old.id else item for item in state.entries))

        updated = self._update(edit, actor="agent", session_id=source.session_id, turn_id=turn_id)
        return next(entry for entry in updated.entries if entry.id == memory_id)

    def inspect(
        self, query: str, workspace: str
    ) -> tuple[MemorySnapshot, tuple[tuple[PersonalMemory, MemoryMatch], ...]]:
        """Read related memories in all states without recording them as active advice."""
        state = self.load()
        if state.mode == "off":
            return state, ()
        searchable = tuple(replace(entry, state="active") for entry in state.entries)
        ranked = self._review_retriever.search(searchable, query, workspace_key(workspace), automatic=False)
        entries = {entry.id: entry for entry in state.entries}
        selected: list[tuple[PersonalMemory, MemoryMatch]] = []
        size = 0
        for match in ranked:
            entry = entries[match.memory_id]
            length = len(render_memory(entry, match.terms))
            if size + length > MAX_INSPECTION_CHARS:
                continue
            selected.append((entry, match))
            size += length
            if len(selected) == MAX_INSPECTED:
                break
        return state, tuple(selected)

    def history(self, *, before: int = 0) -> tuple[MemoryActivity, ...]:
        """Page the committed journal."""
        return self.history_page(before=before)[1]

    def history_page(self, *, before: int = 0) -> tuple[MemorySnapshot, tuple[MemoryActivity, ...]]:
        """Read the page and its snapshot atomically with respect to forgetting."""
        if type(before) is not int or before < 0:
            raise MemoryStoreError("Invalid activity cursor.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.path.with_suffix(".lock"), timeout=2), FileLock(self.receipts_lock_path, timeout=2):
            state = self.load()
            if not state.activity_sequence:
                return state, ()
            try:
                activity.synchronize(self.activity_path, state)
                return state, tuple(
                    _activity(row)
                    for row in activity.read_page(
                        self.activity_path,
                        before=min(before or state.activity_sequence + 1, state.activity_sequence + 1),
                    )
                )
            except (OSError, ValueError, TypeError, KeyError) as error:
                raise MemoryStoreError("The memory activity journal could not be read safely.") from error

    @staticmethod
    def forgetting_ids(state: MemorySnapshot, memory_id: str) -> set[str]:
        removed = {memory_id}
        while True:
            dependents = {
                e.id
                for e in state.entries
                if e.replaces_id in removed
                or any(r.memory_id in removed and r.kind in ("derived_from", "merged_from") for r in e.draft.relations)
            }
            if dependents <= removed:
                return removed
            removed.update(dependents)

    @staticmethod
    def _validate_batch(references: tuple[tuple[str, int], ...]) -> None:
        if not 1 <= len(references) <= MAX_BATCH or len({mid for mid, _ in references}) != len(references):
            raise MemoryStoreError(f"Choose between 1 and {MAX_BATCH} distinct memories per operation.")

    def forget(self, memory_id: str, revision: int) -> MemorySnapshot:
        return self.forget_many(((memory_id, revision),))

    def forget_many(self, references: tuple[tuple[str, int], ...]) -> MemorySnapshot:
        self._validate_batch(references)

        def remove(state: MemorySnapshot, memory_id: str, revision: int) -> MemorySnapshot:
            if not any(e.id == memory_id for e in state.entries) and any(
                memory_id in e.removed_ids for e in state.activity
            ):
                return state
            self._find(state, memory_id, revision)
            removed = self.forgetting_ids(state, memory_id)

            def clean(draft: MemoryDraft) -> MemoryDraft:
                return replace(draft, relations=tuple(r for r in draft.relations if r.memory_id not in removed))

            cleaned = replace(
                state,
                entries=tuple(
                    replace(
                        item,
                        draft=clean(item.draft),
                        revision=item.revision + (clean(item.draft) != item.draft),
                        updated_at=_now() if clean(item.draft) != item.draft else item.updated_at,
                        previous=tuple(
                            replace(version, draft=clean(version.draft))
                            for version in item.previous
                            if not any(
                                r.memory_id in removed and r.kind in ("derived_from", "merged_from")
                                for r in version.draft.relations
                            )
                        ),
                    )
                    for item in state.entries
                    if item.id not in removed
                ),
                recalls=tuple(
                    replace(
                        recall,
                        query="" if any(match.memory_id in removed for match in recall.matches) else recall.query,
                        matches=tuple(match for match in recall.matches if match.memory_id not in removed),
                        excluded_ids=tuple(mid for mid in recall.excluded_ids if mid not in removed),
                    )
                    for recall in state.recalls
                ),
                activity=tuple(
                    event
                    for event in state.activity
                    if event.memory_id not in removed
                    and not (event.draft and any(r.memory_id in removed for r in event.draft.relations))
                ),
            )
            return activity.record(cleaned, "forgotten", removed_ids=tuple(sorted(removed)))

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            for memory_id, revision in references:
                if any(e.id == memory_id for e in state.entries):
                    self._find(state, memory_id, revision)
                elif not any(memory_id in e.removed_ids for e in state.activity):
                    raise MemoryStoreError("This memory no longer exists. Refresh the list.")
            for memory_id, _revision in references:
                if any(e.id == memory_id for e in state.entries):
                    # Earlier removals can clean links and bump a later selected
                    # entry. All user-supplied versions were validated above.
                    current = next(e for e in state.entries if e.id == memory_id)
                    state = remove(state, memory_id, current.revision)
            return state

        return self._update(edit, require_journal=True)

    def _select(
        self,
        state: MemorySnapshot,
        query: str,
        workspace: str,
        *,
        automatic: bool,
        context: str,
        session_id: str = "",
        turn_id: str = "",
        exclude_versions: set[tuple[str, int]] | None = None,
        layer: Literal["L1", "L2", "L3"] | None = None,
        alternatives: tuple[str, ...] = (),
        action_targets: tuple[str, ...] | None = None,
    ) -> tuple[tuple[PersonalMemory, MemoryMatch], ...]:
        if state.mode == "off" or (automatic and state.mode != "auto"):
            return ()
        searchable = (
            tuple(replace(e, state="active") if e.state == "stale" else e for e in state.entries)
            if not automatic
            else state.entries
        )
        entries = {entry.id: entry for entry in state.entries}
        receipt = next((r for r in state.recalls if r.session_id == session_id and r.turn_id == turn_id), None)
        excluded = set(receipt.excluded_ids) if receipt else set()
        query_context = _recall_context_key(query, context, workspace, layer)
        uses = {use.memory_id: use for use in state.uses}
        now = datetime.now(UTC)

        def available(entry: PersonalMemory) -> bool:
            follow = entry.draft.follow_up
            return (
                (entry.state == "active" or (not automatic and entry.state == "stale"))
                and entry.draft.workspace in ("", workspace)
                and entry.id not in excluded
                and not (
                    automatic
                    and entry.id in uses
                    and uses[entry.id].revision == entry.revision
                    and query_context in uses[entry.id].excluded_contexts
                )
                and self.evidence_current(entry, entries)
                and (
                    follow is None
                    or (
                        follow.status not in ("completed", "cancelled")
                        and not (follow.status == "snoozed" and datetime.fromisoformat(follow.remind_at) > now)
                    )
                )
            )

        # Hard eligibility precedes statistics, score admission and shortlist truncation.
        # Keep the shared index intact; query-specific views isolate the allowed set.
        eligible_ids = frozenset(entry.id for entry in state.entries if available(entry))
        ranked = tuple(
            match
            for match in self._retriever.search(
                searchable,
                query,
                workspace,
                automatic=automatic,
                context=context,
                eligible_ids=eligible_ids,
                alternatives=alternatives,
                action_targets=action_targets,
            )
            if not exclude_versions or (match.memory_id, match.revision) not in exclude_versions
        )
        # A delivered version may still explain why a weak match was rejected.
        # Suppress delivery after admission, without changing its statistics.
        anchors = tuple(
            match for match in ranked if match.terms or "identity" in match.routes or "title" in match.routes
        )
        if automatic and layer != "L2":
            defaults = tuple(
                islice(
                    (
                        MemoryMatch(e.id, e.revision, (), ("standing",))
                        for e in state.entries
                        if e.draft.use == "always" and e.id in eligible_ids
                    ),
                    2,
                )
            )
            due = tuple(
                MemoryMatch(e.id, e.revision, (), ("follow_up",))
                for e in sorted(state.entries, key=lambda e: e.draft.follow_up.remind_at if e.draft.follow_up else "")
                if e.id in eligible_ids
                and e.draft.follow_up
                and e.draft.follow_up.remind_at
                and datetime.fromisoformat(e.draft.follow_up.remind_at) <= now
            )[:1]
            direct = tuple(m for m in ranked if "identity" in m.routes or "title" in m.routes)
            ranked = (*direct, *defaults, *due, *ranked)
        # Expand from a contextual match only. Supporting material can fill
        # unused room after direct advice and cannot initiate an action hold.
        if anchors and layer != "L2":
            anchor_ids = {match.memory_id for match in anchors[:3]}
            linked = {
                r.memory_id: r.kind == "exception"
                for match in anchors[:3]
                for r in entries[match.memory_id].draft.relations
                if r.memory_id in eligible_ids
                and entries[r.memory_id].revision == r.revision
                and r.kind in ("supports", "exception", "derived_from")
            }
            for entry in state.entries:
                if entry.id not in eligible_ids or entry.id in linked:
                    continue
                links = tuple(
                    r
                    for r in entry.draft.relations
                    if r.memory_id in anchor_ids
                    and r.kind in ("derived_from", "supports", "exception")
                    and entries[r.memory_id].revision == r.revision
                )
                if links:
                    linked[entry.id] = any(r.kind == "exception" for r in links)
            if linked:
                decision = context if context and continues_previous_task(query) else query
                terms = decision_terms("\n".join((decision, *alternatives)), automatic=automatic)
                ranked = (
                    *ranked,
                    *(
                        MemoryMatch(mid, entries[mid].revision, (), ("association",))
                        for mid, exception in linked.items()
                        if linked_to_decision(entries[mid].draft, terms, needs_corroboration=exception)
                    ),
                )
        selected: list[tuple[PersonalMemory, MemoryMatch]] = []
        seen: set[str] = set()
        size = 0
        for match in ranked:
            entry = entries[match.memory_id]
            if entry.id in seen or (exclude_versions and (entry.id, entry.revision) in exclude_versions):
                continue
            text_size = len(render_memory(entry, match.terms))
            if size + text_size > MAX_CONTEXT_CHARS:
                continue
            selected.append(
                (
                    entry,
                    replace(
                        match,
                        context_key=query_context,
                        layer="L0"
                        if any(r in match.routes for r in ("standing", "follow_up"))
                        else (layer or ("L1" if automatic else "L3")),
                    ),
                )
            )
            seen.add(entry.id)
            size += text_size
            if len(selected) == MAX_RECALLED:
                break
        return tuple(selected)

    def recall(
        self,
        query: str,
        workspace: str,
        *,
        session_id: str = "",
        automatic: bool = True,
        record: bool = True,
        extend_record: bool = False,
        context: str = "",
        turn_id: str = "",
        fallback_query: str = "",
        layer: Literal["L1", "L2", "L3"] | None = None,
        novel_only: bool = False,
        receipt_query: str | None = None,
        delivered_versions: set[tuple[str, int]] | None = None,
        alternatives: tuple[str, ...] = (),
        action_targets: tuple[str, ...] | None = None,
    ) -> tuple[tuple[PersonalMemory, MemoryMatch], ...]:
        workspace = workspace_key(workspace)
        state = self.load()

        def known_versions(snapshot: MemorySnapshot) -> set[tuple[str, int]] | None:
            previous = next((r for r in snapshot.recalls if r.session_id == session_id and r.turn_id == turn_id), None)
            return (
                {
                    (m.memory_id, m.revision)
                    for m in previous.matches
                    if m.layer != "L2" or delivered_versions is None or (m.memory_id, m.revision) in delivered_versions
                }
                if novel_only and previous
                else None
            )

        if not record or not session_id:
            return self._select(
                state,
                query,
                workspace,
                automatic=automatic,
                context=context,
                session_id=session_id,
                turn_id=turn_id,
                layer=layer,
                exclude_versions=known_versions(state),
                alternatives=alternatives,
                action_targets=action_targets,
            )
        if not state.entries and not any(item.session_id == session_id for item in state.recalls):
            return ()
        if (
            automatic
            and layer == "L2"
            and novel_only
            and not self._select(
                state,
                query,
                workspace,
                automatic=True,
                context=context,
                session_id=session_id,
                turn_id=turn_id,
                exclude_versions=known_versions(state),
                layer=layer,
                action_targets=action_targets,
            )
        ):
            # Most actions add no decision evidence. The common index answers
            # this read-only admission check; misses never rewrite the receipt
            # or consume the budget needed by a later relevant action.
            return ()
        selected: tuple[tuple[PersonalMemory, MemoryMatch], ...] = ()

        def record_selection(current: MemorySnapshot) -> MemorySnapshot:
            nonlocal selected
            previous = next((item for item in current.recalls if item.session_id == session_id), None)
            same_turn = previous is not None and previous.turn_id == turn_id
            searches = previous.searches if same_turn and previous else 0
            consumed = previous.context_chars if same_turn and previous else 0
            enabled = current.mode != "off" and (not automatic or current.mode == "auto")
            if not enabled:
                if previous is not None and not same_turn:
                    empty = MemoryRecall(session_id, query[:320], (), _now(), turn_id)
                    return replace(
                        current,
                        recalls=(*[r for r in current.recalls if r.session_id != session_id], empty)[-MAX_RECALLS:],
                    )
                return current
            # A cancelled preflight may have recorded evidence without ever
            # delivering a tool result. Replay that decision without charging
            # another search or suppressing its unseen memories on retry.
            replay = (
                layer == "L2"
                and same_turn
                and previous is not None
                and any(
                    m.layer == "L2"
                    and m.context_key == _recall_context_key(query, context, workspace, layer)
                    and delivered_versions is not None
                    and (m.memory_id, m.revision) not in delivered_versions
                    for m in previous.matches
                )
            )
            charged_search = (not automatic or layer == "L2") and not replay
            search_limit = MAX_TURN_SEARCHES - 1 if layer == "L2" else MAX_TURN_SEARCHES
            # Select and record under the same file lock. A concurrent correction,
            # removal or mode switch cannot leave a stale selection in the receipt.
            selected = self._select(
                current,
                query,
                workspace,
                automatic=automatic,
                context=context,
                session_id=session_id,
                turn_id=turn_id,
                exclude_versions=known_versions(current),
                layer=layer,
                alternatives=alternatives,
                action_targets=action_targets,
            )
            if not selected and fallback_query and fallback_query != query:
                selected = self._select(
                    current,
                    fallback_query,
                    workspace,
                    automatic=automatic,
                    context="",
                    session_id=session_id,
                    turn_id=turn_id,
                    layer=layer,
                )
            if automatic and layer == "L2" and novel_only and not selected:
                return current  # A concurrent correction invalidated admission.
            if enabled and charged_search and (searches >= search_limit or consumed >= MAX_TURN_CONTEXT_CHARS):
                raise MemoryRecallBudgetExceeded(
                    "Memory recall budget reached for this turn; use the supplied memories. Inspection for a write remains available."
                )
            supplied_ids = {m.memory_id for m in previous.matches} if same_turn and previous else set()
            supplied_versions = (
                {(m.memory_id, m.revision) for m in previous.matches} if same_turn and previous else set()
            )
            bounded = []
            size = 0
            for entry, match in selected:
                length = len(render_memory(entry, match.terms))
                charge = 0 if automatic and (entry.id, entry.revision) in supplied_versions else length
                if consumed + size + charge > MAX_TURN_CONTEXT_CHARS:
                    continue
                if entry.id not in supplied_ids and len(supplied_ids) >= MAX_TURN_RECALLED:
                    continue
                bounded.append((entry, match))
                supplied_ids.add(entry.id)
                size += charge
            if selected and not bounded and (not automatic or layer == "L2"):
                raise MemoryRecallBudgetExceeded(
                    "Memory recall budget cannot fit these results; use the supplied memories or inspect an ID for a write."
                )
            selected = tuple(bounded)
            matches = tuple(match for _, match in selected)
            queries = (query if receipt_query is None else receipt_query)[:320]
            if (extend_record or automatic) and enabled and previous is not None and same_turn:
                by_id = {match.memory_id: match for match in (*previous.matches, *matches)}
                matches = tuple(by_id.values())
                queries = "\n".join(dict.fromkeys([*previous.query.splitlines(), queries]))[:320]
            excluded = previous.excluded_ids if previous and previous.turn_id == turn_id else ()
            recall = MemoryRecall(
                session_id,
                queries,
                matches,
                _now(),
                turn_id,
                excluded,
                searches + int(enabled and charged_search),
                consumed + size,
            )
            result = replace(
                current,
                recalls=(*[item for item in current.recalls if item.session_id != session_id], recall)[-MAX_RECALLS:],
            )
            for entry, match in selected:
                if not any(
                    a.action == "provided"
                    and a.memory_id == entry.id
                    and a.revision == entry.revision
                    and a.session_id == session_id
                    and a.turn_id == turn_id
                    for a in current.activity
                ):
                    result = activity.record(
                        result,
                        "provided",
                        memory_id=entry.id,
                        revision=entry.revision,
                        session_id=session_id,
                        turn_id=turn_id,
                        actor="system",
                        detail=match.layer + ": " + ", ".join(match.routes),
                    )
            if not selected and enabled:
                result = activity.record(result, "no_match", session_id=session_id, turn_id=turn_id, actor="system")
            return result

        self._update_receipts(record_selection)
        return selected
