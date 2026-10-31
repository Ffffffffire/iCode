# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Selective personal memory catalog; selection is frozen for a turn."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chrys.kernel import Message
    from chrys.service.personal_memory.runtime import PersonalMemoryRuntime


class PersonalMemorySource:
    name = "personal_memory"
    withdrawn = (
        "Personal memory is disabled or unavailable for this request. "
        "Previously recalled personal memories are withdrawn and must not guide this task."
    )

    def __init__(self, runtime: PersonalMemoryRuntime | None) -> None:
        self._runtime = runtime

    def observe(self, messages: Sequence[Message]) -> None:
        if self._runtime is not None:
            self._runtime.observe(messages)

    async def snapshot(self, messages: Sequence[Message]) -> str | None:
        return await self._runtime.prepare(messages) if self._runtime is not None else None
