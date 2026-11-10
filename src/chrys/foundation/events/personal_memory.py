# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Personal memory commands and replies on the frontend/backend event bus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from chrys.foundation.events.types import Event
from chrys.foundation.models.personal_memory import (
    MemoryActivity,
    MemoryDraft,
    MemoryFeedback,
    MemoryFollowUp,
    MemoryMode,
    MemoryRevision,
    MemorySnapshot,
    MemoryState,
)


@dataclass(kw_only=True)
class PersonalMemoryCommand(Event):
    action: Literal[
        "load",
        "save",
        "state",
        "forget",
        "settings",
        "notifications",
        "feedback",
        "follow_up",
        "history",
        "batch_state",
        "batch_forget",
        "revisions",
        "dismiss_review",
    ] = "load"
    memory_id: str = ""
    revision: int = 0
    draft: MemoryDraft | None = None
    state: MemoryState = "active"
    mode: MemoryMode = "auto"
    capture: bool = False
    auto_save: bool | None = None
    buddy_notifications: bool = False
    outcome: MemoryFeedback = "not_applicable"
    turn_id: str = ""
    follow_up: MemoryFollowUp | None = None
    references: tuple[tuple[str, int], ...] = ()
    before_sequence: int = 0
    before_revision: int = 0


@dataclass(kw_only=True)
class PersonalMemoryChanged(Event):
    request_id: str = ""
    snapshot: MemorySnapshot | None = None
    error: str = ""
    saved_memory_id: str = ""
    saved_changed: bool = True
    attempted_title: str = ""
    error_code: str = ""
    used_bytes: int = 0
    history: tuple[MemoryActivity, ...] | None = None
    revisions: tuple[MemoryRevision, ...] | None = None
