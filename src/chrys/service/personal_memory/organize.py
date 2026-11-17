# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Derive the actionable review queue from one loaded memory snapshot.

The queue reuses the existing thresholds instead of defining a second policy:
duplicates follow health()'s grouping, source changes follow
``PersonalMemoryStore.evidence_current`` and repeated skips follow
``condition_review_ids``. Nothing here writes to the library or keeps state.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from chrys.foundation.models.personal_memory import MemorySnapshot, PersonalMemory

from .lifecycle import condition_review_ids
from .store import PersonalMemoryStore

_GROUPED_STATES = ("active", "candidate", "stale")


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
    """The normalization health() groups duplicates with: NFKC, casefold, no whitespace."""
    return "".join(unicodedata.normalize("NFKC", content).casefold().split())


def _group_key(entry: PersonalMemory) -> tuple[str, str, str]:
    return entry.draft.workspace, entry.draft.kind, normalize_content(entry.draft.content)


def duplicate_partners(state: MemorySnapshot, entry: PersonalMemory) -> tuple[PersonalMemory, ...]:
    """Other members of the entry's duplicate group, in snapshot order; empty for archived entries."""
    if entry.state not in _GROUPED_STATES:
        return ()
    key = _group_key(entry)
    return tuple(
        item
        for item in state.entries
        if item.id != entry.id and item.state in _GROUPED_STATES and _group_key(item) == key
    )


def organize_items(state: MemorySnapshot) -> tuple[OrganizeItem, ...]:
    """One row per non-archived memory that needs organizing, in snapshot order."""
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for entry in state.entries:
        if entry.state in _GROUPED_STATES:
            counts[_group_key(entry)] += 1
    conditions = condition_review_ids(state)
    items = []
    for entry in state.entries:
        if entry.state == "archived":
            continue
        reasons = []
        if counts[_group_key(entry)] > 1:
            reasons.append(OrganizeReason.DUPLICATE)
        if entry.draft.relations and not PersonalMemoryStore.evidence_current(entry, state.entries):
            reasons.append(OrganizeReason.SOURCE_CHANGED)
        if entry.id in conditions:
            reasons.append(OrganizeReason.REPEATED_SKIPS)
        if entry.state == "stale":
            reasons.append(OrganizeReason.NEEDS_REVIEW)
        if reasons:
            items.append(OrganizeItem(entry.id, entry.revision, tuple(reasons)))
    return tuple(items)


def organize_ids(state: MemorySnapshot) -> frozenset[str]:
    """The ids entry points need; equal to ``{item.memory_id for item in organize_items(state)}``."""
    return frozenset(item.memory_id for item in organize_items(state))
