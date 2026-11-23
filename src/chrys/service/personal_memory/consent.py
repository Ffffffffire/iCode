# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Pending consent for saves the assistant proposed without an explicit request.

A proposal whose span is a real, unpasted, short excerpt of the user's latest
message is not refused: it waits here until the user confirms it. The queue is
process-local and time-bounded, so a missed confirmation expires instead of
surfacing days later.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource

TTL_SECONDS = 24 * 60 * 60
MAX_PENDING = 20


@dataclass(frozen=True, slots=True)
class PendingConsent:
    """One proposed save waiting for the user to confirm or drop it."""

    id: str
    title: str
    draft: MemoryDraft
    source: MemorySource
    span: str
    session_id: str
    created_at: float


class ConsentQueue:
    """Time-bounded, size-bounded store of proposals awaiting confirmation."""

    def __init__(
        self,
        *,
        ttl_seconds: float = TTL_SECONDS,
        limit: int = MAX_PENDING,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._limit = limit
        self._clock = clock
        self._items: dict[str, PendingConsent] = {}

    def offer(
        self,
        *,
        title: str,
        draft: MemoryDraft,
        source: MemorySource,
        span: str,
        session_id: str = "",
    ) -> PendingConsent:
        """Queue one proposal, dropping the oldest ones past the size limit."""

        self._sweep()
        item = PendingConsent(
            id=secrets.token_hex(8),
            title=title,
            draft=draft,
            source=source,
            span=span,
            session_id=session_id,
            created_at=self._clock(),
        )
        self._items[item.id] = item
        while len(self._items) > self._limit:
            oldest = min(self._items.values(), key=lambda entry: entry.created_at)
            self._items.pop(oldest.id, None)
        return item

    def pending(self, session_id: str = "") -> tuple[PendingConsent, ...]:
        """Proposals still awaiting an answer, oldest first."""

        self._sweep()
        items = self._items.values()
        if session_id:
            items = (item for item in items if item.session_id == session_id)
        return tuple(sorted(items, key=lambda entry: entry.created_at))

    def take(self, consent_id: str) -> PendingConsent | None:
        """Remove and return one proposal; a second call for the same id finds nothing."""

        self._sweep()
        return self._items.pop(consent_id, None)

    def clear(self) -> None:
        self._items.clear()

    def _sweep(self) -> None:
        cutoff = self._clock() - self._ttl
        expired = [key for key, item in self._items.items() if item.created_at <= cutoff]
        for key in expired:
            self._items.pop(key, None)


_SHARED = ConsentQueue()


def shared_queue() -> ConsentQueue:
    """The process-wide queue the tool, the controller and the panel all read."""

    return _SHARED
