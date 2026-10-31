# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Personal memory values shared by the runtime and its management surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryKind = Literal["decision", "preference", "lesson", "intention"]
MemoryState = Literal["candidate", "active", "archived"]
MemoryMode = Literal["auto", "manual", "off"]


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    title: str
    content: str
    when_to_use: str
    reconsider_when: str = ""
    kind: MemoryKind = "lesson"
    workspace: str = ""


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


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    memory_id: str
    revision: int
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryRecall:
    session_id: str
    query: str
    matches: tuple[MemoryMatch, ...]
    recalled_at: str


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    mode: MemoryMode = "auto"
    capture: bool = True
    entries: tuple[PersonalMemory, ...] = ()
    recalls: tuple[MemoryRecall, ...] = ()
    generation: int = 0
