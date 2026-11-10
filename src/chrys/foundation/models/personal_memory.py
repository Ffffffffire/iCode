# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Personal memory values shared by the runtime and its management surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryKind = Literal["decision", "preference", "lesson", "intention"]
MemoryState = Literal["candidate", "active", "archived", "stale"]
MemoryMode = Literal["auto", "manual", "off"]
FollowUpStatus = Literal["pending", "in_progress", "waiting", "snoozed", "completed", "cancelled"]
MemoryFeedback = Literal["applied", "not_applicable", "helpful", "incorrect"]


@dataclass(frozen=True, slots=True)
class MemoryRelation:
    memory_id: str
    revision: int
    kind: Literal["supports", "exception", "derived_from", "merged_from"]
    reason: str


@dataclass(frozen=True, slots=True)
class MemoryFollowUp:
    status: FollowUpStatus = "pending"
    next_step: str = ""
    remind_at: str = ""


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    title: str
    content: str
    when_to_use: str
    reconsider_when: str = ""
    kind: MemoryKind = "lesson"
    workspace: str = ""
    topics: tuple[str, ...] = ()
    use: Literal["contextual", "always"] = "contextual"
    follow_up: MemoryFollowUp | None = None
    relations: tuple[MemoryRelation, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemorySource:
    session_id: str = ""
    item_id: str = ""
    role: str = "user"
    quote: str = ""


@dataclass(frozen=True, slots=True)
class MemoryRevision:
    revision: int
    draft: MemoryDraft
    source: MemorySource
    updated_at: str


@dataclass(frozen=True, slots=True)
class PersonalMemory:
    id: str
    revision: int
    draft: MemoryDraft
    source: MemorySource
    state: MemoryState
    created_at: str
    updated_at: str
    previous: tuple[MemoryRevision, ...] = ()
    replaces_id: str = ""
    replaces_revision: int = 0
    retired_by: MemorySource | None = None
    review_reason: str = ""


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    memory_id: str
    revision: int
    terms: tuple[str, ...]
    routes: tuple[str, ...] = ()
    layer: Literal["L0", "L1", "L2", "L3"] = "L1"


@dataclass(frozen=True, slots=True)
class MemoryRecall:
    session_id: str
    query: str
    matches: tuple[MemoryMatch, ...]
    recalled_at: str
    turn_id: str = ""
    excluded_ids: tuple[str, ...] = ()
    searches: int = 0
    context_chars: int = 0


@dataclass(frozen=True, slots=True)
class MemoryActivity:
    sequence: int
    action: str
    occurred_at: str
    memory_id: str = ""
    revision: int = 0
    session_id: str = ""
    turn_id: str = ""
    actor: str = "user"
    detail: str = ""
    draft: MemoryDraft | None = None
    source: MemorySource | None = None
    removed_ids: tuple[str, ...] = ()
    memory_source: MemorySource | None = None


@dataclass(frozen=True, slots=True)
class MemoryExposure:
    session_id: str
    turn_id: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class MemoryUse:
    memory_id: str
    revision: int
    exposures: tuple[MemoryExposure, ...] = ()
    skips: tuple[MemoryExposure, ...] = ()
    helpful_at: str = ""
    correction_sessions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryReviewNotice:
    created_at: str
    memory_ids: tuple[str, ...] = ()
    topic: str = ""
    archived_candidates: int = 0


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    mode: MemoryMode = "auto"
    capture: bool = False
    entries: tuple[PersonalMemory, ...] = ()
    recalls: tuple[MemoryRecall, ...] = ()
    generation: int = 0
    auto_save: bool = True
    buddy_notifications: bool = False
    activity: tuple[MemoryActivity, ...] = ()
    activity_sequence: int = 0
    uses: tuple[MemoryUse, ...] = ()
    review_notice: MemoryReviewNotice | None = None
    last_review_at: str = ""
