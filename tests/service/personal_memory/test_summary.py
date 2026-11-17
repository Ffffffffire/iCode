# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Compression reuses one generation, stages grounded memories, and respects commit and review boundaries."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.history_markers import HistoryMarkerKind
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.trajectory.metadata import ANALYTICS_ITEM_ID_KEY
from chrys.kernel import AgentSession, LastWordsCompletion, Message, SessionContext
from chrys.service.context.compaction import UnifiedContextStrategy
from chrys.service.context.compaction.last_words import _CUT_OFF_NOTICE, LastWordsGenerator
from chrys.service.context.compaction.scoped import ScopedGroup
from chrys.service.context.providers.context_management import ContextManagementProvider
from chrys.service.context.providers.history import CompressibleHistoryProvider
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.personal_memory.summary import PersonalMemorySummary
from chrys.service.profiles.models.resolver import default_profile
from tests.service.context.compaction._last_words_helpers import FakeCompleter, long_structured_note

_QUOTE = "I prefer diagrams with dense information for technical presentations."
_NOTE = long_structured_note()


def _message(text: str = _QUOTE, role: str = "user", identity: str = "a" * 32) -> Message:
    return Message(role, [text], additional_properties={ANALYTICS_ITEM_ID_KEY: identity})


def _summary(**overrides: str) -> str:
    item = {
        "scope": "personal",
        "kind": "preference",
        "title": "Technical slides",
        "content": "Prefer diagrams and high information density.",
        "when_to_use": "Technical presentations",
        "reconsider_when": "A simple projection deck is requested",
        "source_quote": _QUOTE,
    }
    item.update(overrides)
    return _NOTE + "\n## Personal memory suggestions\n" + json.dumps([item])


async def _setup(tmp_path: Path) -> tuple[PersonalMemorySummary, PersonalMemoryStore, list[PersonalMemoryChanged]]:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    bus = EventBus()
    events: list[PersonalMemoryChanged] = []

    async def changed(event: PersonalMemoryChanged) -> None:
        events.append(event)

    await bus.subscribe(PersonalMemoryChanged, changed)
    return PersonalMemorySummary(store, bus, "session-one"), store, events


@pytest.mark.parametrize("extend_request", [False, True])
async def test_generated_note_is_not_a_commit_and_commit_is_candidate_only(
    tmp_path: Path, extend_request: bool
) -> None:
    bridge, store, events = await _setup(tmp_path)
    completer = FakeCompleter([_summary()])
    generator = LastWordsGenerator(default_profile(), summary_extension=bridge)
    message = _message()
    groups = [ScopedGroup("user", "user", (message,), True)]
    note = await generator.generate(
        groups,
        None,
        degraded_opener=False,
        has_continuation_nudges=False,
        completer=completer,
        entry_messages=[message] if extend_request else None,
    )
    assert note == _NOTE
    assert store.load().entries == ()
    assert len(completer.calls) == 1
    assert completer.calls[0]["keep_tool_choice"] is extend_request
    assert "Personal memory suggestions" in completer.calls[0]["instruction"]
    await generator.publish_committed()
    await generator.publish_committed()
    (entry,) = store.load().entries
    assert entry.state == "candidate"
    assert entry.source == MemorySource("session-one", "a" * 32, "user", _QUOTE)
    assert entry.draft.workspace == ""
    assert [event.saved_memory_id for event in events] == [entry.id]


async def test_cut_off_note_keeps_task_context_without_staging_memory(tmp_path: Path) -> None:
    bridge, store, events = await _setup(tmp_path)
    completer = FakeCompleter([LastWordsCompletion(_summary(), cut_off=True)])
    generator = LastWordsGenerator(default_profile(), summary_extension=bridge)
    message = _message()
    note = await generator.generate(
        [ScopedGroup("user", "user", (message,), True)],
        None,
        degraded_opener=False,
        has_continuation_nudges=False,
        completer=completer,
        entry_messages=[message],
    )
    assert note == f"{_NOTE}\n\n{_CUT_OFF_NOTICE}"
    assert len(completer.calls) == 2
    await generator.publish_committed()
    assert store.load().entries == () and not events


@pytest.mark.parametrize("flush", [False, True])
async def test_compress_context_uses_actual_committed_range(tmp_path: Path, flush: bool) -> None:
    bridge, store, events = await _setup(tmp_path)
    state = {"messages": [_message()], "compressed_msgs": [], "turn_counter": 0}
    CompressibleHistoryProvider.insert_marker(state, 1)
    strategy = UnifiedContextStrategy()
    strategy.bind_state(state)
    provider = ContextManagementProvider(default_profile(), strategy)
    provider.summary_extension = bridge
    session = AgentSession()
    session.state[CompressibleHistoryProvider.DEFAULT_SOURCE_ID] = state
    context = SessionContext(input_messages=[])
    await provider.before_run(agent=None, session=session, context=context, state={})
    marker = strategy.list_compressed()["markers"][0]["marker_id"]
    result = await provider._compress_context(marker, _summary())
    assert not result.startswith("Error:")
    assert store.load().entries == ()
    if flush:
        assert await strategy.flush_pending_compressions()
    else:
        assert await strategy._compression.run_queued(list(state["messages"]))
    assert len(store.load().entries) == len(events) == 1
    assert "Personal memory suggestions" not in state["compressed_msgs"][0].summary_text
    assert not await strategy.flush_pending_compressions()


@pytest.mark.parametrize("setting", ["capture-off", "memory-off"])
async def test_policy_rechecked_at_commit(tmp_path: Path, setting: str) -> None:
    bridge, store, events = await _setup(tmp_path)
    prepared = bridge.prepare(_summary(), [_message()])
    store.configure("off" if setting == "memory-off" else "auto", setting != "capture-off")
    assert await bridge.instructions() == ""
    await prepared.committed()
    assert store.load().entries == ()
    assert events == []


@pytest.mark.parametrize(
    "case", ["assistant", "tool", "summary", "reminder", "quoted", "refused", "no-identity", "continuation"]
)
async def test_only_original_user_evidence_can_support_summary_memory(tmp_path: Path, case: str) -> None:
    bridge, store, _ = await _setup(tmp_path)
    message = _message()
    if case in ("assistant", "tool"):
        message = _message(role=case)
    elif case == "summary":
        message = _message(role="assistant")
        message.additional_properties[HistoryMarkerKind.KEY] = HistoryMarkerKind.SUMMARY
    elif case == "reminder":
        message = _message("Please continue.\n<system-reminder>" + _QUOTE + "</system-reminder>")
    elif case == "quoted":
        message = _message("Translate this example:\n> " + _QUOTE)
    elif case == "refused":
        message = _message("Do not remember: " + _QUOTE)
    elif case == "no-identity":
        message = _message(identity="")
    elif case == "continuation":
        message.additional_properties[HistoryMarkerKind.CONTINUATION_KEY] = True
    await bridge.prepare(_summary(), [message]).committed()
    assert store.load().entries == ()


@pytest.mark.parametrize("appendix", ["not JSON", "[{}]", "[]", "{}", "[" + " " * 6000 + "]"])
async def test_bad_appendix_is_ignored_without_retrying_good_summary(tmp_path: Path, appendix: str) -> None:
    bridge, store, _ = await _setup(tmp_path)
    completer = FakeCompleter([_NOTE + "\n## Personal memory suggestions\n" + appendix])
    generator = LastWordsGenerator(default_profile(), summary_extension=bridge)
    note = await generator.generate(
        [ScopedGroup("u", "user", (_message(),), True)],
        None,
        degraded_opener=False,
        has_continuation_nudges=False,
        completer=completer,
    )
    await generator.publish_committed()
    assert note == _NOTE
    assert len(completer.calls) == 1
    assert store.load().entries == ()


async def test_same_evidence_does_not_multiply_suggestions_or_revive_paused_entries(tmp_path: Path) -> None:
    bridge, store, events = await _setup(tmp_path)
    await bridge.prepare(_summary(), [_message()]).committed()
    (entry,) = store.load().entries
    store.set_state(entry.id, entry.revision, "archived")
    await bridge.prepare(
        _summary(title="Better technical slides", content="Use diagrams, densely."), [_message()]
    ).committed()
    assert len(store.load().entries) == 1
    assert store.load().entries[0].state == "archived"
    assert len(events) == 1


async def test_summary_cannot_overwrite_active_memory_or_save_project_only_fact(tmp_path: Path) -> None:
    bridge, store, _ = await _setup(tmp_path)
    old = store.save(
        MemoryDraft("Technical slides", "Keep slides sparse", "Technical presentations", kind="preference"),
        MemorySource(),
    )
    await bridge.prepare(_summary(), [_message()]).committed()
    await bridge.prepare(_summary(scope="project"), [_message()]).committed()
    assert store.load().entries == (old,)


async def test_cancelled_generation_does_not_write(tmp_path: Path) -> None:
    bridge, store, _ = await _setup(tmp_path)

    async def status(event):
        if event.stage == "finished":
            raise asyncio.CancelledError

    generator = LastWordsGenerator(default_profile(), summary_extension=bridge, publish_status=status)
    with pytest.raises(asyncio.CancelledError):
        await generator.generate(
            [ScopedGroup("u", "user", (_message(),), True)],
            None,
            degraded_opener=False,
            has_continuation_nudges=False,
            completer=FakeCompleter([_summary()]),
        )
    await generator.publish_committed()
    assert store.load().entries == ()


async def test_memory_appendix_cannot_pad_short_task_summary(tmp_path: Path) -> None:
    bridge, _, _ = await _setup(tmp_path)
    generator = LastWordsGenerator(default_profile(), summary_extension=bridge)
    assert generator._note_shortfall(_summary().replace(_NOTE, "## Task\nx\n## Progress\ny\n## Next\nz")) is not None


async def test_a_later_message_cannot_ground_an_earlier_fold(tmp_path: Path) -> None:
    bridge, store, _ = await _setup(tmp_path)
    state = {"messages": [_message("Build this feature.", identity="b" * 32)], "compressed_msgs": [], "turn_counter": 0}
    CompressibleHistoryProvider.insert_marker(state, 1)
    state["messages"].append(_message())
    strategy = UnifiedContextStrategy()
    strategy.bind_state(state)
    marker = strategy.list_compressed()["markers"][0]["marker_id"]
    strategy.queue_compression(marker, _summary(), summary_extension=bridge)
    assert await strategy.flush_pending_compressions()
    assert store.load().entries == ()


async def test_store_error_does_not_undo_committed_compression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, store, events = await _setup(tmp_path)
    state = {"messages": [_message()], "compressed_msgs": [], "turn_counter": 0}
    CompressibleHistoryProvider.insert_marker(state, 1)
    strategy = UnifiedContextStrategy()
    strategy.bind_state(state)
    marker = strategy.list_compressed()["markers"][0]["marker_id"]
    strategy.queue_compression(marker, _summary(), summary_extension=bridge)

    def unavailable(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "save", unavailable)
    assert await strategy.flush_pending_compressions()
    assert state["compressed_msgs"][0].summary_text == _NOTE
    assert store.load().entries == ()
    assert events[-1].error


async def test_injected_user_preference_is_evidence_and_normal_task_note_stays_empty(tmp_path: Path) -> None:
    bridge, store, _ = await _setup(tmp_path)
    message = _message()
    message.additional_properties[HistoryMarkerKind.INJECTED_KEY] = True
    await bridge.prepare(_NOTE, [message]).committed()
    assert store.load().entries == ()
    await bridge.prepare(_summary(), [message]).committed()
    assert len(store.load().entries) == 1


async def test_appendix_cannot_supply_missing_task_section_content(tmp_path: Path) -> None:
    bridge, _, _ = await _setup(tmp_path)
    generator = LastWordsGenerator(default_profile(), summary_extension=bridge)
    incomplete = "## Task\nDo it\n## Progress\nDone\n## Next\n"
    violation, _ = generator._validate_summary_format(_summary().replace(_NOTE, incomplete), cut_off=False)
    assert violation is not None


@pytest.mark.parametrize("repeat_after_example", [False, True])
@pytest.mark.parametrize(
    "quote",
    [
        'For technical slides I prefer "diagrams with dense information", except for distant projection.',
        "我喜欢深色。",
    ],
)
async def test_user_preference_can_contain_quoted_style_terms(
    tmp_path: Path, repeat_after_example: bool, quote: str
) -> None:
    bridge, store, _ = await _setup(tmp_path)
    text = f"> {quote}\n\n{quote}" if repeat_after_example else quote
    await bridge.prepare(_summary(source_quote=quote, content=quote), [_message(text)]).committed()
    assert len(store.load().entries) == 1
    assert store.load().entries[0].source.quote == quote
