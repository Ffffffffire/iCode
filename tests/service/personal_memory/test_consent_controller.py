# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""The panel lists, confirms and drops proposals that waited for consent."""

from __future__ import annotations

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged, PersonalMemoryCommand, PersonalMemoryTrace
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.service.personal_memory.consent import shared_queue
from chrys.service.personal_memory.controller import PersonalMemoryController
from chrys.service.personal_memory.store import PersonalMemoryStore

_DRAFT = MemoryDraft("提交前先跑测试", "提交前先跑测试", "")


@pytest.fixture(autouse=True)
def _empty_queue():
    shared_queue().clear()
    yield
    shared_queue().clear()


async def _setup(tmp_path) -> tuple[PersonalMemoryController, PersonalMemoryStore, list[PersonalMemoryChanged]]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    bus = EventBus()
    replies: list[PersonalMemoryChanged] = []

    async def record(event: PersonalMemoryChanged) -> None:
        replies.append(event)

    await bus.subscribe(PersonalMemoryChanged, record)
    return PersonalMemoryController(bus, store), store, replies


def _queue_one() -> str:
    item = shared_queue().offer(title=_DRAFT.title, draft=_DRAFT, source=MemorySource(), span="s", session_id="one")
    return item.id


async def _send(controller: PersonalMemoryController, **kwargs) -> None:
    await controller.handle(PersonalMemoryCommand(session_id="one", **kwargs))


async def test_listing_shows_waiting_proposals(tmp_path) -> None:
    controller, _store, replies = await _setup(tmp_path)
    consent_id = _queue_one()
    await _send(controller, action="consent_list")
    assert replies[-1].consents == ((consent_id, "提交前先跑测试"),)


async def test_confirming_writes_the_entry_and_empties_the_queue(tmp_path) -> None:
    controller, store, replies = await _setup(tmp_path)
    consent_id = _queue_one()
    await _send(controller, action="consent_confirm", consent_id=consent_id)
    assert shared_queue().pending() == ()
    assert [entry.draft.title for entry in store.load().entries] == ["提交前先跑测试"]
    assert replies[-1].saved_memory_id


async def test_declining_writes_nothing(tmp_path) -> None:
    controller, store, _replies = await _setup(tmp_path)
    consent_id = _queue_one()
    await _send(controller, action="consent_decline", consent_id=consent_id)
    assert store.load().entries == ()
    assert shared_queue().pending() == ()


async def test_answering_twice_reports_the_missing_proposal(tmp_path) -> None:
    controller, _store, replies = await _setup(tmp_path)
    consent_id = _queue_one()
    await _send(controller, action="consent_confirm", consent_id=consent_id)
    await _send(controller, action="consent_confirm", consent_id=consent_id)
    assert replies[-1].error_code == "memory_consent_missing"


async def test_confirming_records_a_consent_trace(tmp_path) -> None:
    controller, _store, _replies = await _setup(tmp_path)
    traces = []

    async def collect(event) -> None:
        traces.append(event)

    await controller._bus.subscribe(PersonalMemoryTrace, collect)
    consent_id = _queue_one()
    await _send(controller, action="consent_confirm", consent_id=consent_id)
    assert [(trace.kind, trace.outcome) for trace in traces] == [
        ("save_committed", "consent"),
        ("consent_resolved", "confirmed"),
    ]


async def test_declining_records_that_it_was_declined(tmp_path) -> None:
    controller, _store, _replies = await _setup(tmp_path)
    traces = []

    async def collect(event) -> None:
        traces.append(event)

    await controller._bus.subscribe(PersonalMemoryTrace, collect)
    consent_id = _queue_one()
    await _send(controller, action="consent_decline", consent_id=consent_id)
    assert [(trace.kind, trace.outcome) for trace in traces] == [("consent_resolved", "declined")]
