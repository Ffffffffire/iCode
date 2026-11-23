# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Bus-facing personal memory operations; filesystem work stays off the UI loop."""

from __future__ import annotations

import asyncio
from typing import Literal

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import (
    PersonalMemoryChanged,
    PersonalMemoryCommand,
    PersonalMemoryTrace,
)
from chrys.foundation.models.personal_memory import MemorySnapshot, MemorySource

from .consent import shared_queue
from .store import MemoryStoreError, PersonalMemoryStore


class PersonalMemoryController:
    def __init__(self, bus: EventBus, store: PersonalMemoryStore | None = None) -> None:
        self._bus = bus
        self._store = store if store is not None else PersonalMemoryStore()
        self._traced: list[tuple[Literal["save_committed", "consent_resolved"], str]] = []

    async def handle(self, event: PersonalMemoryCommand) -> None:
        try:
            reply = await asyncio.to_thread(self._reply, event)
        except MemoryStoreError as error:
            reply = PersonalMemoryChanged(
                request_id=event.event_id, error=str(error), error_code=error.code, session_id=event.session_id
            )
        except OSError:
            reply = PersonalMemoryChanged(
                request_id=event.event_id,
                error="Personal memory could not be saved. Check local file access.",
                error_code="memory_unavailable",
                session_id=event.session_id,
            )
        await self._bus.publish(reply)
        for kind, outcome in self._traced:
            await self._bus.publish(
                PersonalMemoryTrace(kind=kind, outcome=outcome, session_id=event.session_id)  # type: ignore[arg-type]
            )
        self._traced.clear()

    def _reply(self, event: PersonalMemoryCommand) -> PersonalMemoryChanged:
        history = None
        revisions = None
        consents = None
        saved_memory_id = ""
        if event.action == "consent_list":
            consents = tuple((item.id, item.title) for item in shared_queue().pending(event.session_id or ""))
            return PersonalMemoryChanged(
                request_id=event.event_id,
                snapshot=self._store.load(),
                session_id=event.session_id,
                consents=consents,
            )
        previous = self._store.load() if event.action == "save" else None
        if event.action == "history":
            snapshot, history = self._store.history_page(before=event.before_sequence)
        elif event.action == "revisions":
            revisions = self._store.revisions(
                event.memory_id, before_revision=event.before_revision, expected_revision=event.revision
            )
            snapshot = self._store.load()
        else:
            snapshot, saved_memory_id = self._apply(event)
        return PersonalMemoryChanged(
            request_id=event.event_id,
            snapshot=snapshot,
            session_id=event.session_id,
            saved_memory_id=saved_memory_id,
            saved_changed=previous is None or previous.entries != snapshot.entries,
            used_bytes=self._store.used_bytes,
            history=history,
            revisions=revisions,
            consents=tuple((item.id, item.title) for item in shared_queue().pending(event.session_id or "")),
        )

    def _apply(self, event: PersonalMemoryCommand) -> tuple[MemorySnapshot, str]:
        saved_memory_id = ""
        if event.action == "load":
            return self._store.maintain(notify=False), ""
        if event.action in {"consent_confirm", "consent_decline"}:
            targets = (
                [event.consent_id]
                if event.consent_id
                else [item.id for item in shared_queue().pending(event.session_id or "")]
            )
            if not targets:
                raise MemoryStoreError("No memory proposal is waiting.", code="memory_consent_missing")
            last = ""
            for consent_id in targets:
                item = shared_queue().take(consent_id)
                if item is None:
                    raise MemoryStoreError(
                        "That memory proposal already expired or was answered.", code="memory_consent_missing"
                    )
                if event.action == "consent_confirm":
                    last = self._store.save(item.draft, item.source, authorization="consent").id
                    self._traced.append(("save_committed", "consent"))
                    self._traced.append(("consent_resolved", "confirmed"))
                else:
                    self._traced.append(("consent_resolved", "declined"))
            return self._store.load(), last
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
            return self._store.set_state(
                event.memory_id, event.revision, event.state, session_id=event.session_id or ""
            ), ""
        elif event.action == "forget":
            return self._store.forget(event.memory_id, event.revision), ""
        elif event.action == "batch_forget":
            return self._store.forget_many(event.references), ""
        elif event.action == "batch_state":
            return self._store.set_states(event.references, event.state, session_id=event.session_id or ""), ""
        elif event.action == "settings":
            return self._store.configure(event.mode, event.capture, auto_save=event.auto_save), ""
        elif event.action == "notifications":
            return self._store.set_buddy_notifications(event.buddy_notifications), ""
        elif event.action == "dismiss_review":
            return self._store.dismiss_review(), ""
        elif event.action == "feedback":
            return self._store.feedback(
                event.memory_id,
                event.revision,
                event.outcome,
                session_id=event.session_id or "",
                turn_id=event.turn_id,
                source=MemorySource(session_id=event.session_id or "", role="user"),
            ), ""
        elif event.action == "follow_up":
            if event.follow_up is None:
                raise MemoryStoreError("Follow-up details are required.")
            updated = self._store.update_follow_up(
                event.memory_id,
                event.revision,
                event.follow_up,
                MemorySource(session_id=event.session_id or "", role="user"),
            )
            saved_memory_id = updated.id
        return self._store.load(), saved_memory_id
