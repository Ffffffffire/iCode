# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Attributable feedback, commitments and methods through the agent's real tools."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryFollowUp, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import MemoryReference, PersonalMemoryRuntime
from chrys.service.personal_memory.store import PersonalMemoryStore


def runtime_for(store: PersonalMemoryStore, workspace: Path) -> PersonalMemoryRuntime:
    return PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace=str(workspace), store=store)


async def test_application_and_user_correction_have_separate_evidence(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache versions", "Check versions first", "cache stale"), MemorySource())
    runtime = runtime_for(store, tmp_path)
    await runtime.prepare([Message("user", ["Diagnose stale cache versions"])])
    assert '"outcome": "applied"' in await runtime.review_memory(entry.id, 1, "applied", "Start by checking versions")
    assert (await runtime.review_memory(entry.id, 1, "helpful", "Assumed approval")).startswith("Error:")
    runtime.observe([Message("user", ["That memory is incorrect; our cache has no versions."])])
    result = await runtime.review_memory(entry.id, 1, "incorrect", "No versioned cache", "That memory is incorrect")
    assert '"outcome": "incorrect"' in result
    assert store.load().entries[0].state == "archived"
    events = store.load().activity
    assert any(e.action == "applied" and e.actor == "agent" for e in events)
    assert any(
        e.action == "incorrect" and e.actor == "user" and e.source.quote == "That memory is incorrect"
        for e in events
        if e.source
    )
    assert not store.recall("cache stale", str(tmp_path), record=False)


async def test_identical_text_on_new_turn_has_new_receipt_and_exclusion_scope(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache versions", "Check versions first", "cache stale"), MemorySource())
    runtime = runtime_for(store, tmp_path)
    first = Message("user", ["Check stale cache versions"])
    await runtime.prepare([first])
    turn = store.load().recalls[-1].turn_id
    await runtime.review_memory(entry.id, 1, "not_applicable", "This attempt has no cache")
    assert entry.id not in (await runtime.prepare([first]) or "")
    await runtime.prepare([first, Message("user", [first.text])])
    assert store.load().recalls[-1].turn_id != turn
    assert store.load().recalls[-1].matches[0].memory_id == entry.id


async def test_follow_up_requires_user_for_activation_and_completion(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    runtime = runtime_for(store, tmp_path)
    runtime.observe(
        [Message("user", ["Review the release"]), Message("assistant", ["We could test rollback next week."])]
    )
    candidate = json.loads(
        await runtime.propose_memory(
            "Rollback drill",
            "Test rollback",
            "Next release",
            "We could test rollback next week.",
            kind="intention",
            follow_up=True,
            next_step="Run a staging rollback",
        )
    )
    assert candidate["state"] == "candidate"
    assert not store.recall("release rollback", str(tmp_path), record=False)
    store.set_state(candidate["id"], 1, "active")
    assert (
        await runtime.update_follow_up(candidate["id"], 2, "completed", "We could test rollback next week.")
    ).startswith("Error:")
    runtime.observe([Message("user", ["The rollback drill is done."])])
    result = json.loads(await runtime.update_follow_up(candidate["id"], 2, "completed", "The rollback drill is done."))
    assert result["follow_up"]["status"] == "completed"
    assert not store.recall("release rollback", str(tmp_path), record=False)
    assert store.inspect(candidate["id"], str(tmp_path))[1]


async def test_derived_method_is_reviewed_and_loses_eligibility_with_source_change(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    a = store.save(MemoryDraft("IR consumers", "Start with a consumer", "design IR", topics=("IR",)), MemorySource())
    b = store.save(
        MemoryDraft("Schema budget", "Add only consumed fields", "design schema", topics=("IR",)), MemorySource()
    )
    runtime = runtime_for(store, tmp_path)
    runtime.observe([Message("user", ["Organize these experiences into a reusable method."])])
    await runtime.recall_memory("IR schema", for_update=True)
    result = json.loads(
        await runtime.organize_memory(
            "derive",
            [MemoryReference(memory_id=e.id, revision=e.revision) for e in (a, b)],
            "Both require an identified consumer",
            title="Consumer first",
            content="Identify a consumer before adding IR fields.",
            when_to_use="Design a new intermediate representation",
            source_quote="Organize these experiences into a reusable method.",
        )
    )
    assert result["state"] == "candidate" and len(result["relations"]) == 2
    store.set_state(result["id"], 1, "active")
    assert result["id"] in {e.id for e, _ in store.recall("IR consumers", str(tmp_path), record=False)}
    store.save(replace(a.draft, content="Verify two consumers"), MemorySource(), memory_id=a.id, revision=1)
    assert result["id"] not in {e.id for e, _ in store.recall(result["id"], str(tmp_path), record=False)}
    await runtime.recall_memory("IR schema", for_update=True)
    corrected = json.loads(
        await runtime.organize_memory(
            "derive",
            [MemoryReference(memory_id=a.id, revision=2), MemoryReference(memory_id=b.id, revision=1)],
            "Both require identified consumers",
            title="Consumer first",
            content="Verify two consumers before adding IR fields.",
            when_to_use="Design a new intermediate representation",
            source_quote="Organize these experiences into a reusable method.",
            replaces_id=result["id"],
            replaces_revision=2,
        )
    )
    assert corrected["state"] == "candidate"
    store.set_state(corrected["id"], 1, "active")
    assert result["id"] in {e.id for e, _ in store.recall(result["id"], str(tmp_path), record=False)}


async def test_wording_correction_preserves_follow_up_and_topics(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft(
            "Rollback",
            "Test rollback",
            "release",
            kind="intention",
            topics=("release",),
            follow_up=MemoryFollowUp(
                status="waiting", next_step="Wait for staging", remind_at="2030-01-01T09:00:00+08:00"
            ),
        ),
        MemorySource(),
    )
    runtime = runtime_for(store, tmp_path)
    runtime.observe([Message("user", ["Update this memory: test staging rollback before release."])])
    await runtime.recall_memory(entry.id, for_update=True)
    result = json.loads(
        await runtime.propose_memory(
            "Rollback",
            "Test staging rollback before release.",
            "release",
            "test staging rollback before release.",
            kind="intention",
            replaces_id=entry.id,
            replaces_revision=1,
            save_now=True,
        )
    )
    assert result["state"] == "active"
    assert store.load().entries[0].draft.follow_up == entry.draft.follow_up
    assert store.load().entries[0].draft.topics == entry.draft.topics


async def test_management_cannot_cross_project_or_turn_agent_guess_into_user_feedback(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Other project", "Private lesson", "deployment", workspace=str(tmp_path / "other")), MemorySource()
    )
    runtime = runtime_for(store, tmp_path)
    runtime.observe([Message("user", ["That is wrong."])])
    result = await runtime.review_memory(entry.id, 1, "incorrect", "Correction", "That is wrong.")
    assert result.startswith("Error:")
    assert store.load().entries[0].state == "active"


def test_full_activity_survives_ui_tail_and_recovers_torn_append(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache", "Inspect cache version", "stale cache"), MemorySource())
    for index in range(130):
        store.recall("stale cache", str(tmp_path), session_id="s", turn_id=str(index))
    assert len(store.load().activity) == 128
    rows = [json.loads(line) for line in store.activity_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 131 and rows[0]["action"] == "created"
    with store.activity_path.open("ab") as stream:
        stream.write(b'{"sequence":')
    store.forget(entry.id, 1)
    rows = [json.loads(line) for line in store.activity_path.read_text(encoding="utf-8").splitlines()]
    assert [row["action"] for row in rows] == ["forgotten"]
    assert "Inspect cache version" not in store.activity_path.read_text(encoding="utf-8")


async def test_standing_preference_needs_explicit_choice(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    runtime = runtime_for(store, tmp_path)
    runtime.observe([Message("user", ["I prefer Chinese technical explanations."])])
    result = await runtime.propose_memory(
        "Language",
        "Use Chinese",
        "Technical explanations",
        "I prefer Chinese technical explanations.",
        kind="preference",
        basis="stated",
        use="always",
    )
    assert result.startswith("Error:")
    assert store.load().entries == ()


def test_miss_is_audited_without_copying_ordinary_task_text_into_full_journal(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(MemoryDraft("Cache", "Inspect versions", "stale cache"), MemorySource())
    store.recall("ordinary_task_private_marker sailing weather", "", session_id="s", turn_id="task")
    event = store.load().activity[-1]
    assert event.action == "no_match" and event.turn_id == "task"
    assert "ordinary_task_private_marker" not in store.activity_path.read_text(encoding="utf-8")


def test_existing_intention_is_not_implicitly_a_commitment(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    payload = {
        "version": 1,
        "mode": "auto",
        "capture": False,
        "entries": [
            {
                "id": "b" * 16,
                "revision": 1,
                "draft": {
                    "title": "Future exploration",
                    "content": "May investigate caching",
                    "when_to_use": "cache",
                    "kind": "intention",
                },
                "source": {},
                "state": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    atomic_write_owner_only_text(store.path, json.dumps(payload))
    entry = store.load().entries[0]
    assert entry.draft.follow_up is None and entry.draft.topics == ()
    assert entry.draft.follow_up != MemoryFollowUp()
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 1
    store.save(
        replace(entry.draft, content="Investigate cache validity"), MemorySource(), memory_id=entry.id, revision=1
    )
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 4
    assert store.load().entries[0].id == entry.id
