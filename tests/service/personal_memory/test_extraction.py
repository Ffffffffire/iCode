# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Semantic extraction must produce useful, attributable and policy-controlled writes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import ChatMiddlewareLayer, Message
from chrys.service.llm.mock import MockChatClient, MockResponse
from chrys.service.personal_memory.extraction import MemoryExtraction, MemoryExtractor
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore
from tests.support.transcript_invariants import InvariantCheckedToolLoopLayer

PREFERENCE = "For technical slides I prefer dense diagrams with explanatory labels."


def _result(**fields) -> str:
    return json.dumps(
        {
            "memories": [
                {
                    "title": "Technical slides",
                    "content": "Prefer dense, labelled diagrams in technical slides.",
                    "when_to_use": "Designing technical slides",
                    "source_quote": PREFERENCE,
                    "kind": "preference",
                    "project_only": False,
                    "basis": "stated",
                    **fields,
                }
            ]
        }
    )


def _runtime(tmp_path: Path, *responses: str):
    store = PersonalMemoryStore(tmp_path / "memory.json")
    bus = EventBus()
    client = MockChatClient([MockResponse(text=response) for response in responses])
    extractor = MemoryExtractor(client)
    runtime = PersonalMemoryRuntime(
        bus=bus, session_id="current", workspace=str(tmp_path), store=store, extractor=extractor
    )
    return runtime, store, bus, client, extractor


@pytest.mark.parametrize(
    ("auto_save", "basis", "kind", "expected"),
    [
        (True, "stated", "preference", "active"),
        (False, "stated", "preference", "candidate"),
        (True, "inferred", "lesson", "candidate"),
        (True, "stated", "decision", "candidate"),
    ],
)
async def test_policy_controls_activation_and_emits_an_inspectable_receipt(
    tmp_path: Path, auto_save: bool, basis: str, kind: str, expected: str
) -> None:
    runtime, store, bus, client, _ = _runtime(tmp_path, _result(basis=basis, kind=kind))
    store.configure("auto", True, auto_save=auto_save)
    events: list[PersonalMemoryChanged] = []
    await bus.subscribe(PersonalMemoryChanged, events.append)
    messages = [Message("user", [PREFERENCE])]
    runtime.observe(messages)
    reminder = await runtime.prepare(messages)
    (entry,) = store.load().entries
    assert entry.state == expected and entry.source.quote == PREFERENCE and entry.draft.workspace == ""
    assert entry.source.session_id == "current"
    assert any(event.saved_memory_id == entry.id for event in events)
    assert events[0].processing and not events[-1].processing
    assert reminder and entry.id in reminder and expected in reminder
    # Retrying a model pass must neither re-extract nor apply the correction twice.
    await runtime.prepare(messages)
    assert len(client.call_history) == 1 and store.load().entries == (entry,)


@pytest.mark.parametrize(
    ("mode", "capture", "prompt"),
    [
        ("auto", False, PREFERENCE),
        ("off", True, PREFERENCE),
        ("auto", True, "Do not remember: " + PREFERENCE),
    ],
)
async def test_disabled_or_declined_capture_does_not_call_model(
    tmp_path: Path, mode: str, capture: bool, prompt: str
) -> None:
    runtime, store, _, client, _ = _runtime(tmp_path, _result())
    store.configure(mode, capture)
    messages = [Message("user", [prompt])]
    runtime.observe(messages)
    await runtime.prepare(messages)
    assert store.load().entries == () and client.call_history == []


async def test_semantic_followup_saves_polished_preference_without_a_keyword_gate(tmp_path: Path) -> None:
    runtime, store, _, _, _ = _runtime(tmp_path, _result(basis="request"))
    runtime.observe([Message("user", [PREFERENCE]), Message("user", ["把这个偏好留着, 下回也按这个来。"])])
    result = await runtime.propose_memory(
        title="Slides",
        content=PREFERENCE,
        when_to_use="Technical slides",
        source_quote=PREFERENCE,
        kind="preference",
        save_now=True,
    )
    assert not result.startswith("Error:")
    (entry,) = store.load().entries
    assert entry.state == "active" and entry.source.quote == PREFERENCE and entry.draft.content != PREFERENCE
    assert store.load().capture is False


async def test_semantic_extraction_repairs_a_rough_tool_draft_using_actual_user_evidence(tmp_path: Path) -> None:
    runtime, store, _, client, _ = _runtime(tmp_path, _result(basis="request"))
    runtime.observe([Message("user", [PREFERENCE]), Message("user", ["Keep this preference for next time."])])
    result = await runtime.propose_memory(
        title="Slides",
        content="Verbose draft " * 70,
        when_to_use="",
        source_quote="Polished paraphrase, not an actual quotation",
        kind="preference",
        save_now=True,
    )
    assert not result.startswith("Error:")
    assert len(client.call_history) == 1
    (entry,) = store.load().entries
    assert entry.source.quote == PREFERENCE and len(entry.draft.content) < 600


async def test_correction_preserves_identity_scope_history_and_does_not_repeat_on_retry(tmp_path: Path) -> None:
    runtime, store, _, client, _ = _runtime(tmp_path)
    old = store.save(
        MemoryDraft("Technical slides", "Use sparse layouts", "Designing technical slides"), MemorySource(role="user")
    )
    client.add_response(MockResponse(text=_result(replaces_id=old.id, replaces_revision=old.revision)))
    store.configure("auto", True)
    messages = [Message("user", [PREFERENCE])]
    runtime.observe(messages)
    await runtime.prepare(messages)
    await runtime.prepare(messages)
    (entry,) = store.load().entries
    assert entry.id == old.id and entry.revision == 2 and entry.draft.workspace == ""
    assert entry.previous[0].draft == old.draft and len(client.call_history) == 1


@pytest.mark.parametrize("output", ["invalid JSON", _result(source_quote="Invented evidence")])
async def test_invalid_extraction_does_not_write_or_block_the_main_turn(tmp_path: Path, output: str) -> None:
    runtime, store, bus, _, _ = _runtime(tmp_path, output)
    store.configure("auto", True)
    events: list[PersonalMemoryChanged] = []
    await bus.subscribe(PersonalMemoryChanged, events.append)
    messages = [Message("user", [PREFERENCE])]
    runtime.observe(messages)
    reminder = await runtime.prepare(messages)
    assert store.load().entries == ()
    assert reminder and "did not complete" in reminder
    assert any(event.error for event in events) and not events[-1].processing


async def test_settings_are_rechecked_when_extraction_finishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, store, _, _, extractor = _runtime(tmp_path)
    store.configure("auto", True)

    async def switched_off(*args):
        store.configure("off", False)
        return MemoryExtraction.model_validate_json(_result())

    monkeypatch.setattr(extractor, "extract", switched_off)
    messages = [Message("user", [PREFERENCE])]
    runtime.observe(messages)
    assert await runtime.prepare(messages) is None
    assert store.load().entries == ()


async def test_cancellation_clears_processing_without_a_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, store, bus, _, extractor = _runtime(tmp_path)
    store.configure("auto", True)
    monkeypatch.setattr(extractor, "extract", AsyncMock(side_effect=asyncio.CancelledError))
    events: list[PersonalMemoryChanged] = []
    await bus.subscribe(PersonalMemoryChanged, events.append)
    messages = [Message("user", [PREFERENCE])]
    runtime.observe(messages)
    with pytest.raises(asyncio.CancelledError):
        await runtime.prepare(messages)
    assert events[0].processing and not events[-1].processing and store.load().entries == ()


async def test_extractor_uses_a_bounded_stateless_request(tmp_path: Path) -> None:
    client = MockChatClient([MockResponse(text='{"memories": []}')])
    extractor = MemoryExtractor(
        client, {"conversation_id": "private-parent-chain", "instructions": "parent", "store": True}
    )
    await extractor.extract(PREFERENCE, [("assistant", "x" * 20000)] * 30, [])
    messages, options = client.call_history[0]
    assert len(messages) == 2
    assert len(messages[-1].text) < 13000
    assert "conversation_id" not in options and "instructions" not in options and options["store"] is False


async def test_extractor_works_through_the_production_client_layers() -> None:
    wire = MockChatClient([MockResponse(text='{"memories": []}')])
    client = InvariantCheckedToolLoopLayer(ChatMiddlewareLayer(wire))
    extractor = MemoryExtractor(client)
    result = await extractor.extract(PREFERENCE, [], [])
    assert result.memories == [] and len(wire.call_history) == 1


async def test_nested_options_cannot_attach_extraction_to_the_main_conversation() -> None:
    client = MockChatClient([MockResponse(text='{"memories": []}')])
    extra = {
        "store": True,
        "previous_response_id": "parent",
        "text": {"format": "parent"},
        "thinking": {"type": "disabled"},
    }
    await MemoryExtractor(client, {"extra_body": extra}).extract(PREFERENCE, [], [])
    options = client.call_history[0][1]
    assert options["extra_body"] == {"store": False, "thinking": {"type": "disabled"}}
    assert extra["store"] is True and extra["previous_response_id"] == "parent"


def test_legacy_enabled_capture_migrates_to_clear_preference_auto_save(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload.pop("auto_save")
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.load().capture and store.load().auto_save
