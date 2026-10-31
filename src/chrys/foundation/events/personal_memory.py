# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Personal memory commands and replies on the frontend/backend event bus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from chrys.foundation.events.types import Event
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryMode, MemorySnapshot, MemoryState


@dataclass(kw_only=True)
class PersonalMemoryCommand(Event):
    action: Literal["load", "save", "state", "forget", "settings"] = "load"
    memory_id: str = ""
    revision: int = 0
    draft: MemoryDraft | None = None
    state: MemoryState = "active"
    mode: MemoryMode = "auto"
    capture: bool = True


@dataclass(kw_only=True)
class PersonalMemoryChanged(Event):
    request_id: str = ""
    snapshot: MemorySnapshot | None = None
    error: str = ""
