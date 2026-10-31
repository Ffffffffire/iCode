# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Owner-only memory storage with locked revisions and bounded local retrieval.

Only curated memories are read, never session archives. Model suggestions stay
candidates until accepted. Recall references revisions, so correction cannot
silently make an old recall look as though it used the new conclusion.
"""

from __future__ import annotations

import errno
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from chrys.foundation.models.personal_memory import (
    MemoryDraft,
    MemoryMatch,
    MemoryMode,
    MemoryRecall,
    MemoryRevision,
    MemorySnapshot,
    MemorySource,
    MemoryState,
    PersonalMemory,
)
from chrys.foundation.platform import get_platform
from chrys.foundation.platform.files import atomic_write_owner_only_text, secure_open_owner_only_binary
from chrys.foundation.util.lock import FileLock

MAX_BYTES = 8 * 1024 * 1024
MAX_MEMORIES = 500
MAX_REVISIONS = 5
MAX_RECALLS = 40
MAX_RECALLED = 5
MAX_CONTEXT_CHARS = 6000
_STOP_WORDS = frozenset(
    [
        "the",
        "this",
        "that",
        "with",
        "from",
        "have",
        "what",
        "when",
        "where",
        "how",
        "please",
        "help",
        "want",
        "need",
        "memory",
        "using",
        "use",
        "into",
        "and",
        "for",
        "you",
        "your",
        "are",
        "can",
        "should",
        "about",
        "would",
        "could",
    ]
)


class MemoryStoreError(ValueError):
    """A rejected operation whose message is safe to display."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def workspace_key(workspace: str) -> str:
    return os.path.normcase(str(Path(workspace).resolve())) if workspace else ""


def _terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9][a-z0-9_.-]{1,}", text.casefold())) - _STOP_WORDS
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[index : index + 2] for index in range(len(run) - 1))
    return words


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
    if not draft.title.strip() or not draft.content.strip() or not draft.when_to_use.strip():
        raise MemoryStoreError("Title, memory and when to use are required.")
    if draft.kind not in ("decision", "preference", "lesson", "intention"):
        raise MemoryStoreError("Unknown memory kind.")


def _source(raw: dict[str, Any]) -> MemorySource:
    source = MemorySource(**raw)
    if any(not isinstance(value, str) for value in asdict(source).values()) or len(source.quote) > 1200:
        raise MemoryStoreError("Invalid memory source.")
    return source


def _draft(raw: dict[str, Any]) -> MemoryDraft:
    draft = MemoryDraft(**raw)
    _validate_draft(draft)
    return draft


def _entry(raw: dict[str, Any]) -> PersonalMemory:
    values = dict(raw)
    values["draft"] = _draft(values["draft"])
    values["source"] = _source(values["source"])
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
    if entry.state not in ("candidate", "active", "archived") or entry.revision < 1:
        raise MemoryStoreError("Invalid memory revision or state.")
    if len(entry.previous) > MAX_REVISIONS:
        raise MemoryStoreError("Too many memory revisions.")
    return entry


def render_memory(memory: PersonalMemory, terms: tuple[str, ...] = ()) -> str:
    draft = memory.draft
    return json.dumps(
        {
            "id": memory.id,
            "revision": memory.revision,
            "kind": draft.kind,
            "title": draft.title,
            "memory": draft.content,
            "when_to_use": draft.when_to_use,
            "reconsider_when": draft.reconsider_when,
            "scope": "project" if draft.workspace else "personal",
            "source": asdict(memory.source),
            "matched_terms": terms,
        },
        ensure_ascii=False,
    )


class PersonalMemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else get_platform().config_dir / "personal-memory.json"

    def load(self) -> MemorySnapshot:
        try:
            with secure_open_owner_only_binary(self.path) as stream:
                raw = stream.read(MAX_BYTES + 1)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ENOTDIR):
                return MemorySnapshot()
            raise MemoryStoreError("The personal memory file could not be read safely.") from error
        if len(raw) > MAX_BYTES:
            raise MemoryStoreError("The personal memory store exceeds its size limit.")
        try:
            data = json.loads(raw)
            if data["version"] != 1 or data["mode"] not in ("auto", "manual", "off"):
                raise MemoryStoreError("Unknown personal memory format.")
            entries = tuple(_entry(item) for item in data["entries"])
            recalls = tuple(
                MemoryRecall(
                    session_id=item["session_id"],
                    query=item["query"],
                    recalled_at=item["recalled_at"],
                    matches=tuple(
                        MemoryMatch(match["memory_id"], match["revision"], tuple(match["terms"]))
                        for match in item["matches"]
                    ),
                )
                for item in data.get("recalls", [])
            )
            if len(entries) > MAX_MEMORIES or len(recalls) > MAX_RECALLS or type(data["capture"]) is not bool:
                raise MemoryStoreError("Invalid personal memory store limits.")
            if len({entry.id for entry in entries}) != len(entries):
                raise MemoryStoreError("Duplicate memory identities.")
            generation = data.get("generation", 0)
            if type(generation) is not int or generation < 0:
                raise MemoryStoreError("Invalid personal memory generation.")
            return MemorySnapshot(data["mode"], data["capture"], entries, recalls, generation)
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise MemoryStoreError("The personal memory file is invalid; it has not been overwritten.") from error

    def _update(self, edit: Callable[[MemorySnapshot], MemorySnapshot]) -> MemorySnapshot:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.path.with_suffix(".lock"), timeout=2):
            before = self.load()
            after = edit(before)
            if after == before:
                return after
            after = replace(after, generation=before.generation + 1)
            payload = json.dumps({"version": 1, **asdict(after)}, ensure_ascii=True, indent=2) + "\n"
            if len(after.entries) > MAX_MEMORIES or len(payload.encode("utf-8")) > MAX_BYTES:
                raise MemoryStoreError("Memory storage is full. Remove unneeded memories before saving more.")
            atomic_write_owner_only_text(self.path, payload)
            return after

    def configure(self, mode: MemoryMode, capture: bool) -> MemorySnapshot:
        if mode not in ("auto", "manual", "off") or type(capture) is not bool:
            raise MemoryStoreError("Invalid memory settings.")
        return self._update(lambda state: replace(state, mode=mode, capture=capture))

    @staticmethod
    def _find(state: MemorySnapshot, memory_id: str, revision: int) -> PersonalMemory:
        entry = next((item for item in state.entries if item.id == memory_id), None)
        if entry is None:
            raise MemoryStoreError("This memory no longer exists. Refresh the list.")
        if entry.revision != revision:
            raise MemoryStoreError("This memory changed elsewhere. Refresh before editing it.")
        return entry

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
    ) -> PersonalMemory:
        _validate_draft(draft)
        _source(asdict(source))
        draft = replace(draft, title=draft.title.strip(), workspace=workspace_key(draft.workspace))
        saved: PersonalMemory | None = None

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            nonlocal saved
            if candidate and (state.mode == "off" or not state.capture):
                raise MemoryStoreError("Memory suggestions are disabled.")
            if candidate and memory_id:
                raise MemoryStoreError("Suggestions cannot overwrite a memory.")
            if replaces_id:
                target = self._find(state, replaces_id, replaces_revision)
                if target.state == "candidate":
                    raise MemoryStoreError("Review a suggestion before proposing a correction to it.")
            if not memory_id:
                existing = next(
                    (
                        item
                        for item in state.entries
                        if item.draft == draft and item.state != "archived" and item.replaces_id == replaces_id
                    ),
                    None,
                )
                if existing is not None:
                    if not candidate and existing.state == "candidate":
                        saved = replace(
                            existing, source=source, state="active", revision=existing.revision + 1, updated_at=_now()
                        )
                        return replace(
                            state, entries=tuple(saved if item.id == existing.id else item for item in state.entries)
                        )
                    saved = existing
                    return state
            now = _now()
            old = self._find(state, memory_id, revision) if memory_id else None
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
                state=old.state if old else ("candidate" if candidate else "active"),
                created_at=old.created_at if old else now,
                updated_at=now,
                previous=previous,
                replaces_id=old.replaces_id if old else replaces_id,
                replaces_revision=old.replaces_revision if old else replaces_revision,
            )
            return replace(state, entries=(*(item for item in state.entries if item.id != saved.id), saved))

        self._update(edit)
        if saved is None:
            raise MemoryStoreError("The memory was not saved.")
        return saved

    def set_state(self, memory_id: str, revision: int, status: MemoryState) -> MemorySnapshot:
        if status not in ("active", "archived"):
            raise MemoryStoreError("Choose active or archived.")

        def edit(state: MemorySnapshot) -> MemorySnapshot:
            old = self._find(state, memory_id, revision)
            if old.state == status:
                return state
            if status == "active" and old.replaces_id:
                target = self._find(state, old.replaces_id, old.replaces_revision)
                accepted = replace(
                    target,
                    revision=target.revision + 1,
                    draft=old.draft,
                    source=old.source,
                    updated_at=_now(),
                    state="active",
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
            return replace(
                state,
                entries=tuple(
                    replace(item, state=status, revision=item.revision + 1, updated_at=_now())
                    if item.id == old.id
                    else item
                    for item in state.entries
                ),
            )

        return self._update(edit)

    def forget(self, memory_id: str, revision: int) -> MemorySnapshot:
        def edit(state: MemorySnapshot) -> MemorySnapshot:
            self._find(state, memory_id, revision)
            removed = {item.id for item in state.entries if item.id == memory_id or item.replaces_id == memory_id}
            return replace(
                state,
                entries=tuple(item for item in state.entries if item.id not in removed),
                recalls=tuple(
                    replace(recall, matches=tuple(match for match in recall.matches if match.memory_id not in removed))
                    for recall in state.recalls
                ),
            )

        return self._update(edit)

    def recall(
        self,
        query: str,
        workspace: str,
        *,
        session_id: str = "",
        automatic: bool = True,
        record: bool = True,
    ) -> tuple[tuple[PersonalMemory, MemoryMatch], ...]:
        state = self.load()
        if state.mode == "off" or (automatic and state.mode != "auto"):
            return ()
        terms = _terms(query[:4000])
        workspace = workspace_key(workspace)
        ranked: list[tuple[int, PersonalMemory, MemoryMatch]] = []
        for entry in state.entries:
            if entry.state != "active" or (entry.draft.workspace and entry.draft.workspace != workspace):
                continue
            title = terms & _terms(entry.draft.title)
            condition = terms & _terms(entry.draft.when_to_use)
            body = terms & _terms(entry.draft.content)
            matched = title | condition | body
            if len(matched) < 2 and not any(term.isascii() and len(term) >= 3 for term in matched):
                continue
            rank = len(title) * 4 + len(condition) * 3 + len(body)
            ranked.append((rank, entry, MemoryMatch(entry.id, entry.revision, tuple(sorted(matched))[:8])))
        ranked.sort(key=lambda item: (-item[0], item[1].id))
        selected: list[tuple[PersonalMemory, MemoryMatch]] = []
        size = 0
        for _, entry, match in ranked:
            text_size = len(render_memory(entry, match.terms))
            if size + text_size > MAX_CONTEXT_CHARS:
                continue
            selected.append((entry, match))
            size += text_size
            if len(selected) == MAX_RECALLED:
                break
        if record and session_id and (selected or any(item.session_id == session_id for item in state.recalls)):
            recall = MemoryRecall(session_id, query[:320], tuple(match for _, match in selected), _now())
            self._update(
                lambda current: replace(
                    current,
                    recalls=(
                        *[item for item in current.recalls if item.session_id != session_id],
                        recall,
                    )[-MAX_RECALLS:],
                )
            )
        return tuple(selected)
