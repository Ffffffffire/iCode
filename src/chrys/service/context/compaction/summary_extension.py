# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Optional contributions to an existing summary, consumed only after compression commits."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from chrys.kernel import Message

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedSummary:
    text: str
    on_commit: Callable[[], Awaitable[None]] | None = None

    async def committed(self) -> None:
        if self.on_commit is None:
            return
        try:
            await self.on_commit()
        except Exception:
            # A failed optional consumer must not invalidate a committed context fold.
            _log.warning("Summary contribution could not be saved", exc_info=True)


class SummaryExtension(Protocol):
    async def instructions(self) -> str: ...

    def split(self, summary: str) -> tuple[str, str]: ...

    def prepare(self, summary: str, messages: Sequence[Message]) -> PreparedSummary: ...
