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
class PersonalMemoryTrace(Event):
    """One memory tool outcome, recorded in the trajectory by whoever owns the recorder.

    Payload fields carry counts and codes only; titles and bodies never leave the store.
    """

    kind: Literal["save_committed", "save_rejected", "recall_served", "consent_asked", "consent_resolved"] = (
        "recall_served"
    )
    code: str = ""
    view: str = ""
    entries: int = 0
    characters: int = 0
    outcome: str = ""
    turn_id: str = ""


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
        "consent_list",
        "consent_confirm",
        "consent_decline",
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
    consent_id: str = ""


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
    consents: tuple[tuple[str, str], ...] | None = None
