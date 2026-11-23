# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""A proposal without an explicit request waits for confirmation instead of failing."""

from __future__ import annotations

import json

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.consent import ConsentQueue, shared_queue
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore

_DRAFT = MemoryDraft("提交前先跑测试", "提交前先跑测试", "")


@pytest.fixture(autouse=True)
def _empty_queue():
    shared_queue().clear()
    yield
    shared_queue().clear()


def test_a_span_of_the_latest_message_is_queued_not_refused() -> None:
    queue = ConsentQueue()
    item = queue.offer(title="T", draft=_DRAFT, source=MemorySource(), span="the results are in")
    assert queue.pending() == (item,)
    assert queue.take(item.id) is item
    assert queue.take(item.id) is None


def test_expired_proposals_disappear_instead_of_surfacing_later() -> None:
    now = [0.0]
    queue = ConsentQueue(ttl_seconds=10, clock=lambda: now[0])
    item = queue.offer(title="T", draft=_DRAFT, source=MemorySource(), span="s")
    now[0] = 11.0
    assert queue.pending() == ()
    assert queue.take(item.id) is None


def test_the_queue_drops_the_oldest_proposal_past_its_limit() -> None:
    now = [0.0]
    queue = ConsentQueue(limit=2, clock=lambda: now[0])
    first = queue.offer(title="A", draft=_DRAFT, source=MemorySource(), span="s")
    now[0] = 1.0
    queue.offer(title="B", draft=_DRAFT, source=MemorySource(), span="s")
    now[0] = 2.0
    queue.offer(title="C", draft=_DRAFT, source=MemorySource(), span="s")
    assert [item.title for item in queue.pending()] == ["B", "C"]
    assert first.id not in {item.id for item in queue.pending()}


def _runtime(tmp_path) -> tuple[PersonalMemoryRuntime, PersonalMemoryStore]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="one", workspace=str(tmp_path), store=store)
    return runtime, store


_PROMPT = "The rollback drill notes live in the release checklist, and the staging pass confirmed them."


async def test_a_grounded_span_without_a_save_request_is_queued(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [_PROMPT])])
    await runtime.prepare([Message("user", [_PROMPT])])
    result = await runtime.propose_memory(
        title="Rollback drill",
        content="Verify rollback before release",
        when_to_use="release",
        kind="preference",
        source_quote="the staging pass confirmed them",
        save_now=True,
        intent_quote="the staging pass confirmed them",
    )
    payload = json.loads(result)
    assert payload["state"] == "awaiting-confirmation"
    assert payload["queued"]
    assert store.load().entries == ()
    assert len(shared_queue().pending()) == 1


async def test_an_invented_span_is_still_refused(tmp_path) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [_PROMPT])])
    await runtime.prepare([Message("user", [_PROMPT])])
    result = await runtime.propose_memory(
        title="Rollback drill",
        content="Verify rollback before release",
        when_to_use="release",
        kind="preference",
        source_quote="the staging pass confirmed them",
        save_now=True,
        intent_quote="we agreed to store this in memory",
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()
    assert shared_queue().pending() == ()
