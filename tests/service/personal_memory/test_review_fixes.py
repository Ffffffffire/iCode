# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Review regressions at the storage and actual agent-tool boundaries."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemoryFollowUp, MemoryRelation, MemorySource
from chrys.kernel import Message
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import MemoryStoreError, PersonalMemoryStore


@pytest.mark.parametrize(("authorization", "candidate"), [("capture", True), ("capture", False), ("request", False)])
@pytest.mark.parametrize("metadata", [{"topics": ("ppt",)}, {"aliases": ("slide layout",)}, {"use": "always"}])
def test_paused_fact_cannot_return_without_its_metadata(tmp_path: Path, authorization, candidate, metadata) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True, auto_save=True)
    draft = MemoryDraft("Slides", "Use dense diagrams", "Technical slides", kind="preference", **metadata)
    entry = store.save(draft, MemorySource())
    store.set_state(entry.id, entry.revision, "archived")
    before = store.load()
    with pytest.raises(MemoryStoreError, match="paused"):
        store.save(
            MemoryDraft("A new title", draft.content, draft.when_to_use, kind="preference"),
            MemorySource(role="user", quote="Remember my slide preference"),
            candidate=candidate,
            authorization=authorization,
        )
    assert store.load() == before


def test_same_fact_metadata_requires_revision_of_existing_identity(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    draft = MemoryDraft("Slides", "Use dense diagrams", "Technical slides", topics=("ppt",))
    entry = store.save(draft, MemorySource(), candidate=True)
    changed = replace(draft, title="Another title", topics=("presentations",), aliases=("slide layout",))
    before = store.load()
    with pytest.raises(MemoryStoreError, match=entry.id):
        store.save(changed, MemorySource(), candidate=True)
    assert store.load() == before
    updated = store.save(changed, MemorySource(), memory_id=entry.id, revision=entry.revision)
    assert updated.id == entry.id and updated.revision == entry.revision + 1
    assert updated.draft == changed
    assert len(store.load().entries) == 1


def test_paused_fact_cannot_be_reintroduced_through_another_identity_or_automatic_revision(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    original = store.save(MemoryDraft("Slides", "Use diagrams", "Slides", topics=("ppt",)), MemorySource())
    paused = store.set_state(original.id, original.revision, "archived").entries[0]
    other = store.save(MemoryDraft("Tea", "Oolong", "Tea"), MemorySource())
    before = store.load()
    with pytest.raises(MemoryStoreError, match="paused"):
        store.save(
            replace(paused.draft, topics=()),
            MemorySource(role="user"),
            memory_id=other.id,
            revision=other.revision,
            authorization="request",
        )
    with pytest.raises(MemoryStoreError, match="paused"):
        store.save(
            replace(paused.draft, content="Use larger diagrams"),
            MemorySource(role="user"),
            candidate=True,
            replaces_id=paused.id,
            replaces_revision=paused.revision,
            authorization="capture",
        )
    assert store.load() == before


async def test_history_reply_keeps_its_read_generation_if_forgetting_races_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chrys.foundation.events.personal_memory import PersonalMemoryCommand
    from chrys.service.personal_memory.controller import PersonalMemoryController

    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache", "Private old content", "Cache"), MemorySource())
    original_page = store.history_page

    def page_then_forget(*, before=0):
        snapshot, page = original_page(before=before)
        store.forget(entry.id, entry.revision)
        return snapshot, page

    monkeypatch.setattr(store, "history_page", page_then_forget)
    bus = EventBus()
    replies: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        replies.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    await PersonalMemoryController(bus, store).handle(PersonalMemoryCommand(action="history"))
    reply = replies[0]
    assert reply.snapshot.generation < store.load().generation
    assert reply.history[0].draft.content == "Private old content"
    assert not store.load().entries


async def test_success_resets_failure_dedup_and_idempotent_save_acknowledges_existing_memory(tmp_path: Path) -> None:
    bus = EventBus()
    events: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        events.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=bus, session_id="s", workspace="", store=store)
    quote = "Remember my preference for slide diagrams."
    runtime.observe([Message("user", [quote])])
    for iteration in range(2):
        for _ in range(2):
            assert (await runtime.propose_memory("Slides", "Diagrams", "Slides", "Invented", save_now=True)).startswith(
                "Error:"
            )
        if iteration:
            await runtime.recall_memory("Slides", for_update=True)
        assert not (await runtime.propose_memory("Slides", "Diagrams", "Slides", quote, save_now=True)).startswith(
            "Error:"
        )
    failed = [e for e in events if e.error]
    saved = [e for e in events if e.saved_memory_id]
    assert len(failed) == 2
    assert len(saved) == 2 and saved[0].saved_changed and not saved[1].saved_changed
    assert saved[0].saved_memory_id == saved[1].saved_memory_id
    assert len(store.load().entries) == 1


async def test_read_failure_is_reported_once_until_store_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = EventBus()
    events: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        events.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    load = store.load

    def fail():
        raise OSError("Disk unavailable")

    runtime = PersonalMemoryRuntime(bus=bus, session_id="s", workspace="", store=store)
    monkeypatch.setattr(store, "load", fail)
    for i in range(3):
        assert await runtime.prepare([Message("user", [f"Task {i}"])]) is None
    assert len(events) == 1 and events[0].error_code == "memory_unavailable"
    monkeypatch.setattr(store, "load", load)
    assert await runtime.prepare([Message("user", ["Try again"])])
    monkeypatch.setattr(store, "load", fail)
    assert await runtime.prepare([Message("user", ["Another task"])]) is None
    assert len([event for event in events if event.error]) == 2


async def test_tool_alias_update_changes_retrieval_and_runtime_restart_keeps_search_budget(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Diagrams", "Slides", aliases=("演讲布局",)), MemorySource())
    prompt = Message(
        "user",
        ["Update this memory: use architecture visuals for slides."],
        additional_properties={"_chrys_analytics_item_id": "a" * 32},
    )
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    runtime.observe([prompt])
    await runtime.recall_memory(entry.id, for_update=True)
    result = await runtime.propose_memory(
        "Slides",
        "Diagrams",
        "Slides",
        "architecture visuals for slides",
        save_now=True,
        replaces_id=entry.id,
        replaces_revision=entry.revision,
        aliases=["架构配图"],
    )
    assert not result.startswith("Error:"), result
    assert not store.recall("演讲布局", "", record=False)
    assert store.recall("架构配图", "", record=False)[0][0].id == entry.id
    for _ in range(3):
        assert entry.id in await runtime.recall_memory("Slides")
    restarted = PersonalMemoryRuntime(
        bus=EventBus(), session_id="s", workspace="", store=PersonalMemoryStore(store.path)
    )
    restarted.observe([prompt])
    assert "budget" in (await restarted.recall_memory("Slides")).lower()


def test_batch_limit_and_page_size_are_enforced_without_partial_writes(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entries = [store.save(MemoryDraft(f"Item {i}", f"Fact {i}", f"Situation {i}"), MemorySource()) for i in range(26)]
    before = store.load()
    refs = tuple((e.id, e.revision) for e in entries)
    for operation in (lambda: store.set_states(refs, "archived"), lambda: store.forget_many(refs)):
        with pytest.raises(MemoryStoreError, match="25"):
            operation()
        assert store.load() == before
    state = store.set_states(refs[:25], "archived")
    assert sum(e.state == "archived" for e in state.entries) == 25
    entry = entries[-1]
    for i in range(60):
        entry = store.save(
            replace(entry.draft, content=f"Updated {i}"), MemorySource(), memory_id=entry.id, revision=entry.revision
        )
    page = store.history()
    assert len(page) == 100
    older = store.history(before=page[0].sequence)
    assert older and older[-1].sequence < page[0].sequence


def test_distinct_memory_budget_and_closed_follow_up_cannot_be_bypassed_by_save(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entries = [store.save(MemoryDraft(f"Item {i}", f"Fact {i}", f"Situation {i}"), MemorySource()) for i in range(16)]
    supplied = set()
    for entry in entries:
        supplied.update(e.id for e, _ in store.recall(entry.id, "", session_id="s", turn_id="t"))
    assert len(supplied) == 15
    assert not store.recall(entries[-1].id, "", session_id="s", turn_id="t")
    closed = store.save(
        MemoryDraft(
            "Release", "Finish tests", "Release", kind="intention", follow_up=MemoryFollowUp(status="completed")
        ),
        MemorySource(),
    )
    before = store.load()
    draft = replace(closed.draft, follow_up=MemoryFollowUp())
    with pytest.raises(MemoryStoreError, match="reopen"):
        store.save(
            draft, MemorySource(role="user"), memory_id=closed.id, revision=closed.revision, authorization="request"
        )
    assert store.load() == before
    reopened = store.save(
        draft,
        MemorySource(role="user"),
        memory_id=closed.id,
        revision=closed.revision,
        authorization="request",
        reopen=True,
    )
    assert reopened.draft.follow_up.status == "pending"


def test_merged_from_can_use_paused_sources_but_still_checks_their_versions(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(MemoryDraft("Source", "Evidence", "Source"), MemorySource())
    paused = store.set_state(source.id, source.revision, "archived").entries[0]
    draft = MemoryDraft(
        "Method",
        "Apply evidence",
        "Method",
        relations=(MemoryRelation(paused.id, paused.revision, "merged_from", "Combined experience"),),
    )
    method = store.save(draft, MemorySource())
    assert store.recall(method.id, "", record=False)
    store.save(
        replace(paused.draft, content="Corrected evidence"),
        MemorySource(),
        memory_id=paused.id,
        revision=paused.revision,
    )
    assert not store.recall(method.id, "", record=False)


async def test_explicit_save_can_cite_earlier_still_visible_user_evidence(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    quote = "I prefer diagrams in technical presentations."
    runtime.observe(
        [
            Message("user", [quote]),
            *(Message("assistant", [f"Work step {i}"]) for i in range(30)),
            Message("user", ["Remember my presentation preference."]),
        ]
    )
    result = await runtime.propose_memory(
        "Presentations", "Use diagrams", "Technical presentations", quote, kind="preference", save_now=True
    )
    assert not result.startswith("Error:"), result
    assert store.load().entries[0].source.quote == quote


async def test_failed_save_is_observable_without_repeated_notifications(tmp_path: Path) -> None:
    bus = EventBus()
    events: list[PersonalMemoryChanged] = []

    async def receive(event: PersonalMemoryChanged) -> None:
        events.append(event)

    await bus.subscribe(PersonalMemoryChanged, receive)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=bus, session_id="s", workspace="", store=store)
    runtime.observe([Message("user", ["Remember my slide preference."])])
    for _ in range(2):
        result = await runtime.propose_memory("Slides [red]", "Use diagrams", "Slides", "Invented quote", save_now=True)
        assert result.startswith("Error:")
    assert len(events) == 1
    assert events[0].attempted_title == "Slides [red]"
    assert events[0].error_code == "memory_source_missing"
    assert events[0].session_id == "s"
    assert store.load().entries == ()


def test_competing_candidates_require_review_of_existing_identity(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    draft = MemoryDraft("Slides", "Dense diagrams", "Technical presentations")
    first = store.save(draft, MemorySource(), candidate=True)
    with pytest.raises(MemoryStoreError, match=first.id):
        store.save(replace(draft, content="Prefer detailed diagrams"), MemorySource(), candidate=True)
    assert len(store.load().entries) == 1


@pytest.mark.parametrize("relation", ["supports", "exception"])
def test_changed_linked_evidence_suspends_dependent_recall(tmp_path: Path, relation) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(MemoryDraft("Projection", "Use fewer labels", "Projected slides"), MemorySource())
    dependent = store.save(
        MemoryDraft(
            "Diagrams",
            "Use dense diagrams",
            "Technical slides",
            relations=(MemoryRelation(source.id, 1, relation, "Projection constrains density"),),
        ),
        MemorySource(),
    )
    assert store.recall(dependent.id, "", record=False)
    store.save(replace(source.draft, content="Use large labels"), MemorySource(), memory_id=source.id, revision=1)
    assert not store.recall(dependent.id, "", record=False)
    assert store.inspect(dependent.id, "")[1]


def test_terminal_follow_up_requires_explicit_reopen_and_cannot_skip_pending(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft(
            "Release", "Test rollback", "release", kind="intention", follow_up=MemoryFollowUp(status="completed")
        ),
        MemorySource(),
    )
    source = MemorySource(role="user", quote="Reopen this follow-up")
    with pytest.raises(MemoryStoreError, match="reopen"):
        store.update_follow_up(entry.id, 1, MemoryFollowUp(), source, workspace="")
    with pytest.raises(MemoryStoreError, match="pending"):
        store.update_follow_up(entry.id, 1, MemoryFollowUp(status="in_progress"), source, workspace="", reopen=True)
    updated = store.update_follow_up(entry.id, 1, MemoryFollowUp(), source, workspace="", reopen=True)
    assert updated.draft.follow_up.status == "pending"


def test_commit_hash_is_not_an_automatic_memory_reference(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Tea", "Prefer oolong", "Drinking tea"), MemorySource())
    assert not store.recall(f"Review commit {entry.id}", "", record=False)
    assert store.recall(f"Recall memory {entry.id}", "", record=False)[0][0].id == entry.id
    assert store.recall(entry.id[:8], "", record=False, automatic=False)[0][0].id == entry.id


async def test_tool_recall_has_shared_turn_budget_and_resets_on_new_turn(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "Technical slides"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    runtime.observe([Message("user", ["Help with slides"])])
    for _ in range(3):
        assert entry.id in await runtime.recall_memory("slides")
    assert "budget" in (await runtime.recall_memory("slides")).lower()
    assert entry.id in await runtime.recall_memory(entry.id, for_update=True)
    runtime.observe([Message("user", ["Help with slides"])])
    assert entry.id in await runtime.recall_memory("slides")


def test_inspection_has_its_own_larger_budget(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    for index in range(8):
        store.save(MemoryDraft(f"Cache {index}", f"Check layer {index}", f"cache layer {index}"), MemorySource())
    assert len(store.inspect("cache", "")[1]) == 8
    assert len(store.recall("cache", "", record=False)) == 5


def test_custom_retrieval_terms_are_local_and_revision_aware(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(
        MemoryDraft("Slides", "Use diagrams", "Technical slides", aliases=("讲清楚架构",)), MemorySource()
    )
    assert store.recall("请帮我讲清楚架构", "", record=False)[0][0].id == entry.id
    store.save(replace(entry.draft, aliases=("演讲配图",)), MemorySource(), memory_id=entry.id, revision=1)
    assert not store.recall("讲清楚架构", "", record=False)
    assert store.recall("演讲配图", "", record=False)[0][0].id == entry.id


async def test_natural_continuation_uses_latest_task_not_old_matching_topic(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "Technical slides"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    assert entry.id in (
        await runtime.prepare([Message("user", ["Make slides"]), Message("user", ["继续写下一节"])]) or ""
    )
    result = await runtime.prepare(
        [Message("user", ["Make slides"]), Message("user", ["改聊茶叶"]), Message("user", ["继续"])]
    )
    assert entry.id not in (result or "")
    result = await runtime.prepare([Message("user", ["Make slides"]), *(Message("user", ["继续"]) for _ in range(10))])
    assert entry.id in (result or "")


async def test_long_original_task_keeps_tail_retrieval_terms(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Slides", "Use diagrams", "Technical slides"), MemorySource())
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    prompt = "Detailed task input. " * 300 + "\nPlease make slides."
    assert entry.id in (await runtime.prepare([Message("user", [prompt])]) or "")


def test_batch_review_is_atomic_when_one_version_changed(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    entries = [
        store.save(MemoryDraft(f"Cache {i}", f"Inspect layer {i}", "cache"), MemorySource(), candidate=True)
        for i in range(3)
    ]
    store.save(
        replace(entries[1].draft, content="Changed elsewhere"), MemorySource(), memory_id=entries[1].id, revision=1
    )
    before = store.load()
    with pytest.raises(MemoryStoreError, match="changed elsewhere"):
        store.set_states(tuple((e.id, 1) for e in entries), "active")
    assert store.load() == before
    active = store.set_states(tuple((e.id, e.revision) for e in before.entries), "active")
    assert all(e.state == "active" for e in active.entries)


def test_batch_forget_handles_link_cleanup_and_erases_activity(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    a = store.save(MemoryDraft("Source", "Private first fact", "source"), MemorySource())
    b = store.save(
        MemoryDraft(
            "Related", "Private second fact", "related", relations=(MemoryRelation(a.id, 1, "supports", "Evidence"),)
        ),
        MemorySource(),
    )
    assert store.forget_many(((a.id, 1), (b.id, 1))).entries == ()
    text = store.activity_path.read_text(encoding="utf-8")
    assert "Private first fact" not in text and "Private second fact" not in text


def test_full_activity_pages_survive_snapshot_tail_and_respect_forgetting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chrys.service.personal_memory import activity

    monkeypatch.setattr(activity, "RECENT_ACTIVITY", 4)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache", "Original", "cache"), MemorySource())
    for i in range(8):
        entry = store.save(
            replace(entry.draft, content=f"Version {i}"), MemorySource(), memory_id=entry.id, revision=entry.revision
        )
    state = store.load()
    assert len(state.activity) == 4
    earlier = store.history(before=state.activity[0].sequence)
    assert len(earlier) == 5 and earlier[0].action == "created"
    assert earlier[-1].sequence < state.activity[0].sequence
    store.forget(entry.id, entry.revision)
    assert all(e.draft is None for e in store.history())


def test_feedback_summary_separates_actor_and_versions(tmp_path: Path) -> None:
    from chrys.service.personal_memory.activity import recent_usage

    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("Cache", "Check versions", "cache"), MemorySource())
    for turn in ("one", "two"):
        store.recall("cache", "", session_id="s", turn_id=turn)
        store.feedback(
            entry.id,
            1,
            "not_applicable",
            session_id="s",
            turn_id=turn,
            source=MemorySource(role="user") if turn == "one" else None,
        )
    usage = recent_usage(store.load(), entry.id, 1)
    assert (usage.provided, usage.user_skipped, usage.agent_skipped) == (2, 1, 1)
    assert (usage.helpful, usage.applied) == (0, 0)
    revised = store.save(
        replace(entry.draft, content="Check versions before retrying"), MemorySource(), memory_id=entry.id, revision=1
    )
    assert recent_usage(store.load(), entry.id, revised.revision).provided == 0


def test_recall_budget_survives_runtime_restart_and_manual_fallback_is_one_search(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("manual", False)
    entry = store.save(MemoryDraft("Cache", "Check versions", "cache"), MemorySource())
    for _ in range(3):
        assert (
            store.recall(
                "unmatched",
                "",
                session_id="s",
                turn_id="t",
                automatic=False,
                extend_record=True,
                fallback_query="cache",
            )[0][0].id
            == entry.id
        )
    restarted = PersonalMemoryStore(store.path)
    with pytest.raises(MemoryStoreError, match="budget"):
        restarted.recall("cache", "", session_id="s", turn_id="t", automatic=False)
    assert restarted.recall("cache", "", session_id="s", turn_id="next", automatic=False)


def test_library_search_uses_aliases_and_has_no_recall_shortlist_limit(tmp_path: Path) -> None:
    from chrys.service.personal_memory.retrieval import MemoryRetriever

    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    for i in range(35):
        store.save(MemoryDraft(f"Slide {i}", f"Diagram style {i}", "Technical slides"), MemorySource(), candidate=True)
    before = store.load()
    matches = MemoryRetriever().browse(before.entries, "幻灯片")
    assert len(matches) == 35 and store.load() == before


@pytest.mark.parametrize(
    "user_prompt",
    [
        "Do not, even if the formatting sounds like a lasting preference, remember this.",
        "Translate: 'Remember my preference.'",
    ],
)
async def test_quoted_or_distant_negated_commands_do_not_authorize_saving(tmp_path: Path, user_prompt: str) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    runtime.observe([Message("user", ["I prefer diagrams."]), Message("user", [user_prompt])])
    result = await runtime.propose_memory(
        "Slides", "Diagrams", "Slides", "I prefer diagrams.", save_now=True, intent_quote="Remember my preference."
    )
    assert result.startswith("Error:") and not store.load().entries


def test_v2_library_is_read_without_mutation_and_upgraded_on_write(tmp_path: Path) -> None:
    import json

    from chrys.foundation.platform.files import atomic_write_owner_only_text

    path = tmp_path / "memory.json"
    payload = json.dumps({"version": 2, "mode": "auto", "capture": False, "entries": []})
    atomic_write_owner_only_text(path, payload)
    store = PersonalMemoryStore(path)
    assert store.load().entries == ()
    assert path.read_text(encoding="utf-8") == payload
    store.save(MemoryDraft("Slides", "Diagrams", "slides", aliases=("Technical talks",)), MemorySource())
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 4
    assert PersonalMemoryStore(path).load().entries[0].draft.aliases == ("Technical talks",)


async def test_auto_capture_does_not_activate_a_preference_quoted_as_an_example(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    runtime = PersonalMemoryRuntime(bus=EventBus(), session_id="s", workspace="", store=store)
    quote = "I prefer dense slide diagrams."
    runtime.observe([Message("user", [f'Translate this example: "{quote}"'])])
    result = await runtime.propose_memory(
        "Slides", "Use dense diagrams", "Technical slides", quote, kind="preference", basis="stated"
    )
    assert not result.startswith("Error:")
    assert store.load().entries[0].state == "candidate"


def test_repeated_automatic_preparation_cannot_bypass_the_turn_character_budget(tmp_path: Path) -> None:
    from chrys.service.personal_memory.store import MAX_TURN_CONTEXT_CHARS, render_memory

    store = PersonalMemoryStore(tmp_path / "memory.json")
    entries = [
        store.save(MemoryDraft(f"Subject {i}", str(i) + "x" * 2200, f"subject {i}"), MemorySource()) for i in range(10)
    ]
    supplied = {}
    for entry in entries:
        for item, match in store.recall(entry.id, "", session_id="s", turn_id="t"):
            supplied[item.id] = len(render_memory(item, match.terms))
    assert len(supplied) < len(entries)
    assert sum(supplied.values()) <= MAX_TURN_CONTEXT_CHARS
    before = store.load().recalls[-1].context_chars
    assert store.recall(entries[0].id, "", session_id="s", turn_id="t")
    assert store.load().recalls[-1].context_chars == before


def test_large_fanout_forget_is_rejected_before_losing_journal_outbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chrys.service.personal_memory import activity

    monkeypatch.setattr(activity, "RECENT_ACTIVITY", 4)
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(MemoryDraft("Source", "Source claim", "source"), MemorySource())
    for i in range(5):
        store.save(
            MemoryDraft(
                f"Dependent {i}", str(i), "related", relations=(MemoryRelation(source.id, 1, "supports", "Evidence"),)
            ),
            MemorySource(),
        )
    before = store.path.read_bytes()
    journal = store.activity_path.read_bytes()
    with pytest.raises(MemoryStoreError, match="too many activity records"):
        store.forget(source.id, 1)
    assert store.path.read_bytes() == before
    assert store.activity_path.read_bytes() == journal
    store.save(MemoryDraft("New", "Still writable", "future"), MemorySource())
    assert len(store.load().entries) == 7


def test_activity_pagination_preserves_multibyte_records_across_read_blocks(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    entry = store.save(MemoryDraft("版本记录", "初始内容", "审核"), MemorySource())
    for i in range(20):
        entry = store.save(
            replace(entry.draft, content=f"{i}:" + "版本依据" * 500),
            MemorySource(),
            memory_id=entry.id,
            revision=entry.revision,
        )
    assert store.activity_path.stat().st_size > 65536
    page = store.history(before=15)
    assert [e.sequence for e in page] == list(range(1, 15))
    assert page[0].draft.content == "初始内容"
    assert page[-1].draft.content == "12:" + "版本依据" * 500
