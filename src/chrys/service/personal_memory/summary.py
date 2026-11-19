# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Reuse a committed summary's bounded, source-grounded suggestions without another model call."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from functools import partial

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.foundation.models.turns import is_injected_message, opens_turn
from chrys.foundation.trajectory.metadata import read_analytics_item_id
from chrys.kernel import Message
from chrys.service.context.compaction.summary_extension import PreparedSummary
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore

from .write_intent import declines_memory, unquoted_text, user_quote_occurs

_log = logging.getLogger(__name__)
_HEADING = "\n## Personal memory suggestions\n"
_MAX_APPENDIX = 6000
_GUIDANCE = """Optional personal memory reuse, only while producing a context summary:
Finish the task summary first, within its existing output budget. Do not compress earlier just to extract memories.
If the original user messages contain a durable personal preference, decision rationale, reusable lesson,
or enduring unfinished intention that will help in a future situation, you may append one final section:
## Personal memory suggestions
A JSON array (no code fence), at most two objects with exactly these fields:
scope (must be "personal"), kind (preference/decision/lesson/intention), title (max 100 characters),
content (concise, max 600 characters), when_to_use, reconsider_when, source_quote (verbatim user words).
Condense only claims supported by the quotation, retaining its reasons, conditions and exceptions.
For a reusable lesson, retain a concrete action and the detail that makes it usable, such as a setting,
threshold, example or expected result. Omit a lesson if the summary can only preserve headings or general advice.
Keep the original subject, scope and strength: a preference for one output format is not a rule for other formats.
Do not add implementation advice, examples or stronger prescriptions, even if sensible.
Use an empty reconsider_when when the user gave no exception or invalidating condition.
Exclude ordinary task instructions, progress, paths, temporary environment facts, project-only conventions,
assistant speculation, quoted examples, sensitive secrets, and content the user declined to remember.
Do not reproduce existing memory suggestions or treat previous summaries as fresh evidence.
Omit this entire section when there is no strong, reusable personal signal or insufficient output space.
Suggestions are reviewed before activation; this is not permission to change existing memories.
For compress_context, the optional section belongs inside its summary argument and must cite the folded range."""


class PersonalMemorySummary:
    def __init__(self, store: PersonalMemoryStore, bus: EventBus, session_id: str) -> None:
        self._store = store
        self._bus = bus
        self._session_id = session_id

    async def instructions(self) -> str:
        try:
            state = await asyncio.to_thread(self._store.load)
        except MemoryStoreError, OSError:
            return ""
        return _GUIDANCE if state.capture and state.mode != "off" else ""

    def split(self, summary: str) -> tuple[str, str]:
        # Only the reserved final appendix is a contribution. No arbitrary JSON scraping.
        text, separator, payload = summary.partition(_HEADING)
        return (text.rstrip(), separator + payload) if separator else (summary, "")

    def prepare(self, summary: str, messages: Sequence[Message]) -> PreparedSummary:
        text, appendix = self.split(summary)
        if not appendix or len(appendix) > _MAX_APPENDIX:
            return PreparedSummary(text)
        try:
            raw = json.loads(appendix[len(_HEADING) :])
        except ValueError, RecursionError:
            return PreparedSummary(text)
        if not isinstance(raw, list) or len(raw) > 2:
            return PreparedSummary(text)
        # Share the chat tool's refusal/example checks, but use only the actual
        # compressed messages, never mutable current-turn evidence or recalled text.
        evidence: list[tuple[str, str, str]] = []
        for message in messages:
            if not (opens_turn(message) or is_injected_message(message)):
                continue
            item_id = read_analytics_item_id(message.additional_properties)
            user_text = (message.text or "").split("<system-reminder>", 1)[0]
            if item_id and not declines_memory(user_text):
                evidence.append((user_text, unquoted_text(user_text), item_id))
        suggestions: list[tuple[MemoryDraft, MemorySource]] = []
        fields = {"scope", "kind", "title", "content", "when_to_use", "reconsider_when", "source_quote"}
        for item in raw:
            if not isinstance(item, dict) or set(item) != fields or not all(isinstance(v, str) for v in item.values()):
                continue
            kind = item["kind"]
            if item["scope"] != "personal" or kind not in ("preference", "decision", "lesson", "intention"):
                continue
            quote = item["source_quote"].strip()
            if not 1 <= len(quote) <= 1200 or not item["when_to_use"].strip():
                continue
            if not 1 <= len(item["content"]) <= 600 or not 1 <= len(item["title"]) <= 100:
                continue
            item_id = next(
                (
                    identity
                    for user_text, unquoted, identity in evidence
                    if user_quote_occurs(user_text, unquoted, quote)
                ),
                "",
            )
            if not item_id:
                continue
            draft = MemoryDraft(item["title"], item["content"], item["when_to_use"], item["reconsider_when"], kind)
            source = MemorySource(self._session_id, item_id, "user", quote)
            suggestions.append((draft, source))
        return PreparedSummary(text, partial(self._save, tuple(suggestions))) if suggestions else PreparedSummary(text)

    async def _save(self, suggestions: tuple[tuple[MemoryDraft, MemorySource], ...]) -> None:
        for draft, source in suggestions:
            try:
                before = await asyncio.to_thread(self._store.load)
                saved = await asyncio.to_thread(
                    self._store.save, draft, source, candidate=True, authorization="summary"
                )
                if any(entry.id == saved.id for entry in before.entries):
                    continue
                snapshot = await asyncio.to_thread(self._store.load)
                await self._bus.publish(
                    PersonalMemoryChanged(
                        snapshot=snapshot,
                        session_id=self._session_id,
                        saved_memory_id=saved.id,
                        used_bytes=self._store.used_bytes,
                    )
                )
            except MemoryStoreError:
                # Policy changes, duplicate paused facts and overlap are normal rejection paths.
                _log.debug("Summary memory suggestion was not accepted", exc_info=True)
            except OSError:
                _log.warning("Summary memory suggestion could not be written", exc_info=True)
                await self._bus.publish(
                    PersonalMemoryChanged(
                        session_id=self._session_id,
                        error="A memory suggestion from compression could not be saved.",
                    )
                )
