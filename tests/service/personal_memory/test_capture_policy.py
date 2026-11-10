# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Agent-selected memory writes stay local, attributable and revision-safe."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore, review_key

PREFERENCE = "I prefer dense diagrams for technical slides."


def _runtime(tmp_path: Path):
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="current", workspace=str(tmp_path), store=store)
    runtime.observe([Message("user", [PREFERENCE])])
    return runtime, store


@pytest.mark.parametrize(
    ("capture", "auto_save", "basis", "expected"),
    [
        (True, True, "stated", "active"),
        (True, False, "stated", "candidate"),
        (True, True, "inferred", "candidate"),
        (False, True, "stated", None),
    ],
)
async def test_only_the_selected_tool_writes_and_policy_controls_activation(
    tmp_path: Path, capture, auto_save, basis, expected
) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", capture, auto_save=auto_save)
    await runtime.prepare([Message("user", [PREFERENCE])])
    assert store.load().entries == ()
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Prefer dense diagrams.",
        when_to_use="Technical slides",
        source_quote=PREFERENCE,
        kind="preference",
        project_only=False,
        basis=basis,
    )
    if expected is None:
        assert result.startswith("Error:") and store.load().entries == ()
    else:
        (entry,) = store.load().entries
        assert entry.state == expected and entry.source.quote == PREFERENCE
        assert json.loads(result)["changed"] is True


@pytest.mark.parametrize(
    "prompt",
    [
        "下次也照这个习惯来。",
        "如果方便，下次也照这个习惯来。",  # noqa: RUF001 -- Preserve natural Chinese requests.
        "如果下次再做技术 PPT，就按这个偏好来。",  # noqa: RUF001 -- Preserve natural Chinese requests.
        "If possible, keep this preference for next time.",
    ],
)
async def test_natural_save_intent_can_reference_earlier_evidence_without_keyword_gate(
    tmp_path: Path, prompt: str
) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [PREFERENCE]), Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Technical slides",
        content="Prefer dense diagrams.",
        when_to_use="Technical slides",
        source_quote=PREFERENCE,
        kind="preference",
        project_only=False,
        save_now=True,
        intent_quote=prompt,
    )
    assert not result.startswith("Error:"), result
    (entry,) = store.load().entries
    assert entry.state == "active" and entry.source.quote == PREFERENCE
    assert store.load().capture is False


@pytest.mark.parametrize("prompt", ['Translate: "Keep this for next time."', "Do not remember this."])
async def test_intent_quote_does_not_override_examples_or_negation(tmp_path: Path, prompt: str) -> None:
    runtime, store = _runtime(tmp_path)
    runtime.observe([Message("user", [PREFERENCE]), Message("user", [prompt])])
    result = await runtime.propose_memory(
        title="Slides",
        content="Dense diagrams",
        when_to_use="Technical slides",
        source_quote=PREFERENCE,
        save_now=True,
        intent_quote="Keep this for next time.",
    )
    assert result.startswith("Error:") and store.load().entries == ()


async def test_review_finds_pending_and_paused_without_recalling_them(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    draft = MemoryDraft("Technical slides", "Dense diagrams", "Technical slides")
    pending = store.save(draft, MemorySource(), candidate=True)
    archived = store.save(replace(draft, title="Projection slides", content="Sparse diagrams"), MemorySource())
    store.set_state(archived.id, archived.revision, "archived")
    before = store.load()
    result = json.loads(await runtime.recall_memory("slides", for_update=True))
    assert {row["id"] for row in result["memories"]} == {pending.id, archived.id}
    assert {row["state"] for row in result["memories"]} == {"candidate", "archived"}
    assert store.load() == before
    assert store.recall("slides", str(tmp_path), record=False) == ()


async def test_merge_preserves_identity_conditions_and_original_evidence(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    old = store.save(
        MemoryDraft("Technical slides", "Dense diagrams", "Technical slides", "Except projection", "preference"),
        MemorySource(quote="Original choice"),
    )
    store.configure("auto", True)
    quote = "I still prefer dense diagrams for technical slides, and now want labels on each connection."
    runtime.observe([Message("user", [quote])])
    await runtime.recall_memory("Technical slides", for_update=True)
    result = await runtime.propose_memory(
        title=old.draft.title,
        content="Prefer dense diagrams with labelled connections.",
        when_to_use=old.draft.when_to_use,
        reconsider_when=old.draft.reconsider_when,
        kind="preference",
        source_quote=quote,
        basis="stated",
        replaces_id=old.id,
        replaces_revision=old.revision,
    )
    assert not result.startswith("Error:"), result
    (entry,) = store.load().entries
    assert entry.id == old.id and entry.revision == 2
    assert entry.draft.reconsider_when == old.draft.reconsider_when and entry.draft.workspace == ""
    assert entry.previous[0].draft == old.draft and entry.previous[0].source == old.source


async def test_duplicate_does_not_refresh_age_or_create_evidence(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    draft = MemoryDraft("Slides", "Prefer dense diagrams.", "Technical slides", kind="preference")
    old = store.save(draft, MemorySource(quote=PREFERENCE))
    await runtime.recall_memory("slides", for_update=True)
    result = json.loads(
        await runtime.propose_memory(
            title="Another title",
            content=draft.content,
            when_to_use=draft.when_to_use,
            source_quote=PREFERENCE,
            kind="preference",
            project_only=False,
            basis="stated",
        )
    )
    assert result["changed"] is False and store.load().entries == (old,)


async def test_write_requires_review_again_after_a_concurrent_change(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    await runtime.recall_memory("slides", for_update=True)
    old = store.save(MemoryDraft("Slides", "Sparse diagrams", "Technical slides", kind="preference"), MemorySource())
    result = await runtime.propose_memory(
        title="Slides",
        content="Dense diagrams",
        when_to_use="Technical slides",
        source_quote=PREFERENCE,
        kind="preference",
        basis="stated",
        replaces_id=old.id,
        replaces_revision=old.revision,
    )
    assert "for_update=true" in result and store.load().entries == (old,)


def test_store_rechecks_review_under_the_write_lock(tmp_path: Path) -> None:
    _, store = _runtime(tmp_path)
    key = review_key(store.load(), str(tmp_path))
    store.save(MemoryDraft("Slides", "Sparse diagrams", "Technical slides"), MemorySource())
    with pytest.raises(MemoryStoreError, match="changed"):
        store.save(
            MemoryDraft("Diagrams", "Dense diagrams", "Technical slides"),
            MemorySource(),
            reviewed_catalog=key,
            request_workspace=str(tmp_path),
        )


async def test_completed_intention_is_paused_with_evidence_and_can_be_restored(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    old = store.save(
        MemoryDraft("Graph research", "Investigate graph learning", "Research planning", kind="intention"),
        MemorySource(quote="Original intention"),
    )
    quote = "The graph research is complete; stop reminding me about this goal."
    runtime.observe([Message("user", [quote])])
    await runtime.recall_memory(old.id, for_update=True)
    result = json.loads(await runtime.pause_memory(old.id, old.revision, quote))
    assert result["state"] == "archived"
    (paused,) = PersonalMemoryStore(store.path).load().entries
    assert paused.draft == old.draft and paused.source == old.source
    assert paused.retired_by is not None and paused.retired_by.quote == quote
    assert store.recall("Graph research", str(tmp_path), record=False) == ()
    restored = store.set_state(paused.id, paused.revision, "active").entries[0]
    assert restored.retired_by is None and restored.draft == old.draft


async def test_chat_cannot_recreate_a_paused_fact(tmp_path: Path) -> None:
    runtime, store = _runtime(tmp_path)
    store.configure("auto", True)
    draft = MemoryDraft("Slides", "Dense diagrams", "Technical slides", kind="preference")
    old = store.save(draft, MemorySource())
    store.set_state(old.id, old.revision, "archived")
    await runtime.recall_memory("slides", for_update=True)
    result = await runtime.propose_memory(
        title="New title",
        content=draft.content,
        when_to_use=draft.when_to_use,
        source_quote=PREFERENCE,
        kind="preference",
        basis="stated",
        project_only=False,
    )
    assert result.startswith("Error:") and len(store.load().entries) == 1
