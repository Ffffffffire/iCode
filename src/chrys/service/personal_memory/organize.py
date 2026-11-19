# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Derive review counts, queue rows and duplicate partners from a memory snapshot."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from chrys.foundation.models.personal_memory import MemorySnapshot, PersonalMemory

from .lifecycle import condition_review_ids
from .store import PersonalMemoryStore


class OrganizeReason(StrEnum):
    DUPLICATE = "duplicate"
    SOURCE_CHANGED = "source_changed"
    REPEATED_SKIPS = "repeated_skips"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True, slots=True)
class OrganizeItem:
    memory_id: str
    revision: int
    reasons: tuple[OrganizeReason, ...]


def normalize_content(content: str) -> str:
    """Group equivalent content across case, character width and whitespace."""
    return "".join(unicodedata.normalize("NFKC", content).casefold().split())


def _group_key(entry: PersonalMemory) -> tuple[str, str, str]:
    return entry.draft.workspace, entry.draft.kind, normalize_content(entry.draft.content)


class OrganizeQueue:
    """One grouping for the library, its warning badge and duplicate details."""

    def __init__(self, state: MemorySnapshot) -> None:
        self._entries = state.entries
        groups: dict[tuple[str, str, str], list[PersonalMemory]] = defaultdict(list)
        for entry in self._entries:
            if entry.state != "archived":
                groups[_group_key(entry)].append(entry)
        duplicates = [tuple(group) for group in groups.values() if len(group) > 1]
        self._duplicates = {entry.id: group for group in duplicates for entry in group}
        self.duplicate_count = sum(len(group) - 1 for group in duplicates)
        self.condition_ids = condition_review_ids(state)
        self.review_count = len(self.condition_ids) + sum(entry.state == "stale" for entry in self._entries)

    @property
    def needs_review(self) -> bool:
        """The badge calls attention to duplicates and memories needing review."""
        return bool(self.duplicate_count or self.review_count)

    def duplicate_partners(self, memory_id: str) -> tuple[PersonalMemory, ...]:
        """Other members of this duplicate group in catalog order."""
        return tuple(entry for entry in self._duplicates.get(memory_id, ()) if entry.id != memory_id)

    def items(self) -> tuple[OrganizeItem, ...]:
        """One row per non-archived memory that needs organizing, in catalog order."""
        by_id = {entry.id: entry for entry in self._entries}
        items = []
        for entry in self._entries:
            if entry.state == "archived":
                continue
            reasons = []
            if entry.id in self._duplicates:
                reasons.append(OrganizeReason.DUPLICATE)
            if entry.draft.relations and not PersonalMemoryStore.evidence_current(entry, by_id):
                reasons.append(OrganizeReason.SOURCE_CHANGED)
            if entry.id in self.condition_ids:
                reasons.append(OrganizeReason.REPEATED_SKIPS)
            if entry.state == "stale":
                reasons.append(OrganizeReason.NEEDS_REVIEW)
            if reasons:
                items.append(OrganizeItem(entry.id, entry.revision, tuple(reasons)))
        return tuple(items)


def organize_items(state: MemorySnapshot) -> tuple[OrganizeItem, ...]:
    return OrganizeQueue(state).items()


def organize_ids(state: MemorySnapshot) -> frozenset[str]:
    """The ids entry points need; equal to ``{item.memory_id for item in organize_items(state)}``."""
    return frozenset(item.memory_id for item in organize_items(state))
