# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Bus-facing personal memory operations; filesystem work stays off the UI loop."""

from __future__ import annotations

import asyncio

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand
from chrys.foundation.models.personal_memory import MemorySnapshot, MemorySource

from .store import MemoryStoreError, PersonalMemoryStore


class PersonalMemoryController:
    def __init__(self, bus: EventBus, store: PersonalMemoryStore | None = None) -> None:
        self._bus = bus
        self._store = store if store is not None else PersonalMemoryStore()

    async def handle(self, event: PersonalMemoryCommand) -> None:
        try:
            snapshot, saved_memory_id = await asyncio.to_thread(self._apply, event)
            reply = PersonalMemoryChanged(
                request_id=event.event_id,
                snapshot=snapshot,
                session_id=event.session_id,
                saved_memory_id=saved_memory_id,
            )
        except MemoryStoreError as error:
            reply = PersonalMemoryChanged(request_id=event.event_id, error=str(error), session_id=event.session_id)
        except OSError:
            reply = PersonalMemoryChanged(
                request_id=event.event_id,
                error="Personal memory could not be saved. Check local file access.",
                session_id=event.session_id,
            )
        await self._bus.publish(reply)

    def _apply(self, event: PersonalMemoryCommand) -> tuple[MemorySnapshot, str]:
        saved_memory_id = ""
        if event.action == "save":
            if event.draft is None:
                raise MemoryStoreError("Memory content is required.")
            saved = self._store.save(
                event.draft,
                MemorySource(session_id=event.session_id or "", role="user"),
                memory_id=event.memory_id,
                revision=event.revision,
            )
            saved_memory_id = saved.id
        elif event.action == "state":
            return self._store.set_state(event.memory_id, event.revision, event.state), ""
        elif event.action == "forget":
            return self._store.forget(event.memory_id, event.revision), ""
        elif event.action == "settings":
            return self._store.configure(event.mode, event.capture, auto_save=event.auto_save), ""
        return self._store.load(), saved_memory_id
