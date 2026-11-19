# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
"""The organize queue derives the four review reasons from one loaded snapshot.

These tests pin duplicate grouping, condition review, source revisions and
the warning counts derived from the same snapshot.
"""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path

from chrys.foundation.models.personal_memory import MemoryDraft, MemoryRelation, MemorySource
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory.lifecycle import condition_review_ids
from chrys.service.personal_memory.organize import (
    OrganizeQueue,
    OrganizeReason,
    normalize_content,
    organize_ids,
    organize_items,
)
from chrys.service.personal_memory.store import PersonalMemoryStore

_DUPLICATE = OrganizeReason.DUPLICATE
_SOURCE_CHANGED = OrganizeReason.SOURCE_CHANGED
_REPEATED_SKIPS = OrganizeReason.REPEATED_SKIPS
_NEEDS_REVIEW = OrganizeReason.NEEDS_REVIEW


def _draft(title: str, content: str, when: str = "technical slides", **overrides: object) -> MemoryDraft:
    return MemoryDraft(title, content, when, **overrides)  # type: ignore[arg-type]


def _reasons(state, memory_id: str) -> tuple[OrganizeReason, ...]:
    return next((item.reasons for item in organize_items(state) if item.memory_id == memory_id), ())


def _queue_ids(state) -> list[str]:
    return [item.memory_id for item in organize_items(state)]


def _write_entries(store: PersonalMemoryStore, changes: dict[str, dict[str, object]]) -> None:
    """Rewrite saved entries the way an older policy left them on disk."""
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    for entry in payload["entries"]:
        fields = changes.get(entry["id"])
        if fields:
            entry.update(fields)
    atomic_write_owner_only_text(store.path, json.dumps(payload))


def _skip_turn(store: PersonalMemoryStore, memory_id: str, revision: int, query: str, turn: str, *, user: bool = True):
    store.recall(query, "", session_id="one", turn_id=turn)
    return store.feedback(
        memory_id,
        revision,
        "not_applicable",
        session_id="one",
        turn_id=turn,
        source=MemorySource(role="user") if user else None,
    )


def _bytes(store: PersonalMemoryStore) -> tuple[bytes, bytes, bytes]:
    return (
        store.path.read_bytes(),
        store.receipts_path.read_bytes(),
        store.activity_path.read_bytes(),
    )


def test_duplicate_group_lists_active_candidate_and_stale_members_and_skips_archived(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    first = store.save(_draft("Density", "Use  dense diagrams"), MemorySource())
    second = store.save(_draft("Density, revised", "use dense diagrams"), MemorySource())
    candidate = store.save(
        _draft("Density, inferred", "\uff35\uff33\uff25 dense diagrams"), MemorySource(), candidate=True
    )
    other_kind = store.save(_draft("Density preference", "Use dense diagrams", kind="preference"), MemorySource())
    other_project = store.save(
        _draft("Density elsewhere", "Use dense diagrams", workspace=str(tmp_path / "other-project")), MemorySource()
    )
    archived = store.save(_draft("Density, paused", "Use dense diagrams"), MemorySource())
    store.set_state(archived.id, archived.revision, "archived")

    state = store.load()
    items = {item.memory_id: item for item in organize_items(state)}

    assert set(items) == {first.id, second.id, candidate.id}
    assert all(item.reasons == (_DUPLICATE,) for item in items.values())
    assert items[candidate.id].revision == candidate.revision
    assert _reasons(state, other_kind.id) == ()
    assert _reasons(state, other_project.id) == ()
    assert _reasons(state, archived.id) == ()
    # The candidate keeps its own state: joining the queue never promotes it.
    assert next(entry for entry in state.entries if entry.id == candidate.id).state == "candidate"


def test_source_changed_follows_every_relation_kind_multiple_hops_and_candidates(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    changed = store.save(_draft("Changed source", "Write the checksum report"), MemorySource())
    derived = store.save(
        _draft(
            "Derived requirement",
            "Compare both report checksums",
            relations=(MemoryRelation(changed.id, 1, "derived_from", "Comes from the checksum rule"),),
        ),
        MemorySource(),
    )
    current = store.save(_draft("Current source", "Keep the manifest tidy"), MemorySource())
    current_derived = store.save(
        _draft(
            "Current derived",
            "Read the manifest before editing",
            relations=(MemoryRelation(current.id, 1, "derived_from", "Comes from the manifest rule"),),
        ),
        MemorySource(),
    )
    paused = store.save(_draft("Paused source", "Prefer sparse tables"), MemorySource())
    supported = store.save(
        _draft(
            "Supported claim",
            "Sparse tables read faster",
            relations=(MemoryRelation(paused.id, 1, "supports", "Evidence for the claim"),),
        ),
        MemorySource(),
    )
    exceptional = store.save(
        _draft(
            "Exceptional claim",
            "Dense tables sometimes win",
            relations=(MemoryRelation(paused.id, 1, "exception", "Counterexample to the claim"),),
        ),
        MemorySource(),
    )
    root = store.save(_draft("Chain root", "Use the canonical path"), MemorySource())
    middle = store.save(
        _draft(
            "Chain middle",
            "Resolve links through the canonical path",
            relations=(MemoryRelation(root.id, 1, "derived_from", "Follows the canonical path"),),
        ),
        MemorySource(),
    )
    top = store.save(
        _draft(
            "Chain top",
            "Rebuild the index from resolved links",
            relations=(MemoryRelation(middle.id, 1, "derived_from", "Follows the chain middle"),),
        ),
        MemorySource(),
    )
    candidate_source = store.save(_draft("Candidate source", "Measure the cache first"), MemorySource())
    candidate_derived = store.save(
        _draft(
            "Candidate derived",
            "Cache the measured page",
            relations=(MemoryRelation(candidate_source.id, 1, "derived_from", "Comes from the cache rule"),),
        ),
        MemorySource(),
        candidate=True,
    )
    merged_first = store.save(_draft("Merge first", "Use annotated diagrams"), MemorySource())
    merged_second = store.save(_draft("Merge second", "Keep details dense"), MemorySource())
    merged = store.merge(
        ((merged_first.id, 1), (merged_second.id, 1)),
        _draft("Merged layout", "Use dense annotated diagrams for close reading"),
        MemorySource(),
    )
    plain = store.save(_draft("Unrelated", "Run the tests before merging"), MemorySource())

    # Break the relationship targets only after the relations themselves were valid.
    store.save(
        replace(changed.draft, content="Write the checksum report twice"),
        MemorySource(),
        memory_id=changed.id,
        revision=1,
    )
    store.set_state(paused.id, paused.revision, "archived")
    store.save(
        replace(root.draft, content="Use the canonical path everywhere"), MemorySource(), memory_id=root.id, revision=1
    )
    store.save(
        replace(candidate_source.draft, content="Measure the cache twice"),
        MemorySource(),
        memory_id=candidate_source.id,
        revision=1,
    )

    state = store.load()
    assert _reasons(state, derived.id) == (_SOURCE_CHANGED,)
    assert _reasons(state, current_derived.id) == ()
    assert _reasons(state, supported.id) == (_SOURCE_CHANGED,)
    assert _reasons(state, exceptional.id) == (_SOURCE_CHANGED,)
    # Two hops away from the changed root: only walking the chain finds it.
    assert _reasons(state, top.id) == (_SOURCE_CHANGED,)
    assert _reasons(state, candidate_derived.id) == (_SOURCE_CHANGED,)
    # merged_from into an archived source is still current evidence.
    assert _reasons(state, merged.id) == ()
    assert _reasons(state, plain.id) == ()


def test_repeated_skips_need_three_user_reports_on_the_current_active_revision(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    skipped = store.save(_draft("Density", "Prefer dense density in the appendix"), MemorySource())
    twice = store.save(_draft("Spacing", "Keep spacing uniform in the appendix"), MemorySource())
    agent_skipped = store.save(_draft("Headings", "Number headings in the appendix"), MemorySource())
    revised = store.save(_draft("Captions", "Caption figures in the appendix"), MemorySource())
    excluded = store.save(_draft("Margins", "Widen margins in the appendix"), MemorySource())

    for turn in range(3):
        _skip_turn(store, skipped.id, 1, "density appendix", str(turn))
    for turn in range(2):
        _skip_turn(store, twice.id, 1, "spacing appendix", f"twice-{turn}")
    for turn in range(3):
        _skip_turn(store, agent_skipped.id, 1, "headings appendix", f"agent-{turn}", user=False)
    for turn in range(3):
        _skip_turn(store, revised.id, 1, "captions appendix", f"revised-{turn}")
    store.save(
        replace(revised.draft, content="Caption figures in the appendix with units"),
        MemorySource(),
        memory_id=revised.id,
        revision=1,
    )
    for turn in range(3):
        _skip_turn(store, excluded.id, 1, "margins appendix", f"excluded-{turn}")
    store.recall("margins appendix", "", session_id="one", turn_id="helpful", automatic=False)
    store.feedback(
        excluded.id,
        1,
        "helpful",
        session_id="one",
        turn_id="helpful",
        source=MemorySource(role="user"),
    )

    state = store.load()
    assert condition_review_ids(state) == {skipped.id}
    assert _reasons(state, skipped.id) == (_REPEATED_SKIPS,)
    for quiet in (twice, agent_skipped, revised, excluded):
        assert _reasons(state, quiet.id) == ()


def test_marked_for_review_follows_the_load_maintenance_rules(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    explicit = store.save(_draft("Explicit pause", "Prefer sparse tables in reviews"), MemorySource())
    store.pause(explicit.id, 1, MemorySource(role="user", quote="This no longer applies"), str(tmp_path))
    empty_reason = store.save(_draft("No reason", "Keep the changelog short"), MemorySource())
    archived = store.save(_draft("Withdrawn claim", "Use the old publisher"), MemorySource())
    healthy = store.save(_draft("Healthy", "Run the tests twice"), MemorySource())
    legacy = store.save(_draft("Legacy quarantine", "Prefer the classic renderer"), MemorySource())
    _write_entries(
        store,
        {
            explicit.id: {"state": "stale", "review_reason": "repeated_mismatch"},
            empty_reason.id: {"state": "stale", "review_reason": ""},
            archived.id: {"state": "archived", "review_reason": "incorrect"},
            legacy.id: {"state": "stale", "review_reason": "repeated_mismatch", "revision": 2, "retired_by": None},
        },
    )

    # What the panel's load runs, with notifications off.
    state = store.maintain()
    entries = {entry.id: entry for entry in state.entries}

    assert entries[explicit.id].state == "stale" and entries[explicit.id].review_reason == "repeated_mismatch"
    assert entries[empty_reason.id].state == "stale"
    assert entries[legacy.id].state == "active" and entries[legacy.id].revision == 3
    assert _reasons(state, explicit.id) == (_NEEDS_REVIEW,)
    assert _reasons(state, empty_reason.id) == (_NEEDS_REVIEW,)
    assert _reasons(state, archived.id) == ()
    assert _reasons(state, healthy.id) == ()
    assert _reasons(state, legacy.id) == ()


def test_several_reasons_stay_one_row_in_a_fixed_order(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(_draft("Density source", "Measure the density baseline"), MemorySource())
    many = store.save(
        _draft(
            "Density",
            "Use  density charts",
            relations=(MemoryRelation(source.id, 1, "derived_from", "Comes from the density rule"),),
        ),
        MemorySource(),
    )
    partner = store.save(_draft("Density, second copy", "use density charts"), MemorySource())
    for turn in range(3):
        _skip_turn(store, many.id, 1, "density charts", str(turn))
    store.save(
        replace(source.draft, content="Measure the density baseline twice"),
        MemorySource(),
        memory_id=source.id,
        revision=1,
    )

    state = store.load()
    rows = [item for item in organize_items(state) if item.memory_id == many.id]

    assert len(rows) == 1
    assert rows[0].reasons == (_DUPLICATE, _SOURCE_CHANGED, _REPEATED_SKIPS)
    assert rows[0].revision == many.revision
    assert [entry.id for entry in OrganizeQueue(state).duplicate_partners(many.id)] == [partner.id]
    assert _reasons(state, partner.id) == (_DUPLICATE,)


def test_age_silence_provision_and_plain_candidates_are_not_reasons(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    old = store.save(_draft("Vendor", "Recall the legacy vendor name"), MemorySource())
    twice = store.save(_draft("Spacing", "Keep spacing uniform in the appendix"), MemorySource())
    store.save(_draft("Plain suggestion", "Group logs by request id"), MemorySource(), candidate=True)
    store.save(_draft("Topic note", "Use a checklist for releases", topics=("releases",)), MemorySource())
    for turn in range(4):
        store.recall("vendor name", "", session_id="one", turn_id=f"provided-{turn}")
    for turn in range(2):
        _skip_turn(store, twice.id, 1, "spacing appendix", f"twice-{turn}")
    _write_entries(
        store, {old.id: {"created_at": "2024-01-01T00:00:00+00:00", "updated_at": "2024-01-01T00:00:00+00:00"}}
    )

    state = store.load()

    assert organize_items(state) == ()
    assert organize_ids(state) == frozenset()


def test_duplicate_partners_name_hidden_members_and_never_cross_workspaces(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    slides = store.save(_draft("Slides", "Use  a single chart", topics=("slides",)), MemorySource())
    hidden = store.save(_draft("Release notes", "use a single chart", topics=("release",)), MemorySource())
    third = store.save(_draft("Charts", "\uff35\uff33\uff25 a single chart", topics=("release",)), MemorySource())
    elsewhere = store.save(
        _draft("Other project chart", "Use a single chart", workspace=str(tmp_path / "other-project")), MemorySource()
    )
    alone = store.save(_draft("Lonely", "Run the tests twice"), MemorySource())

    state = store.load()
    queue = OrganizeQueue(state)
    partners = queue.duplicate_partners(slides.id)

    assert [entry.id for entry in partners] == [hidden.id, third.id]
    assert {entry.draft.title for entry in partners} == {"Release notes", "Charts"}
    assert elsewhere.id not in {entry.id for entry in partners}
    assert queue.duplicate_partners(alone.id) == ()
    assert normalize_content("  UsE\u3000a single chart ") == normalize_content("use a single chart")


def test_duplicate_grouping_agrees_with_the_footer_health_count(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.configure("auto", True)
    pair_a = store.save(_draft("Pair A", "Use  paired charts"), MemorySource())
    pair_b = store.save(_draft("Pair B", "use paired charts"), MemorySource())
    trio_a = store.save(_draft("Trio A", "Keep trio notes"), MemorySource())
    trio_b = store.save(_draft("Trio B", "keep  trio notes"), MemorySource())
    trio_c = store.save(_draft("Trio C", "KEEP TRIO NOTES"), MemorySource(), candidate=True)
    paused = store.save(_draft("Paused pair", "Use paired charts"), MemorySource())
    store.set_state(paused.id, paused.revision, "archived")
    store.save(_draft("Unrelated", "Run the tests twice"), MemorySource())

    state = store.load()
    grouped_states = ("active", "candidate", "stale")

    def key(entry) -> tuple[str, str, str]:
        words = "".join(unicodedata.normalize("NFKC", entry.draft.content).casefold().split())
        return entry.draft.workspace, entry.draft.kind, words

    counts = Counter(key(entry) for entry in state.entries if entry.state in grouped_states)
    expected_duplicates = sum(count - 1 for count in counts.values() if count > 1)
    duplicated = {entry.id for entry in state.entries if entry.state in grouped_states and counts[key(entry)] > 1}
    queue = OrganizeQueue(state)
    rows = [item for item in queue.items() if _DUPLICATE in item.reasons]

    assert queue.duplicate_count == expected_duplicates == 3
    assert queue.needs_review and queue.review_count == 0
    assert {item.memory_id for item in rows} == duplicated == {pair_a.id, pair_b.id, trio_a.id, trio_b.id, trio_c.id}
    assert paused.id not in duplicated


def test_the_queue_is_a_deterministic_read_only_projection_of_the_snapshot(tmp_path: Path) -> None:
    store = PersonalMemoryStore(tmp_path / "memory.json")
    source = store.save(_draft("Read-only source", "Measure the read latency"), MemorySource())
    derived = store.save(
        _draft(
            "Read-only derived",
            "Record the measured latency",
            relations=(MemoryRelation(source.id, 1, "derived_from", "Comes from the measurement"),),
        ),
        MemorySource(),
    )
    store.save(_draft("Read-only partner", "record the measured latency"), MemorySource())
    for turn in range(3):
        _skip_turn(store, derived.id, 1, "derived latency", str(turn))

    before = store.load()
    files = _bytes(store)

    first = organize_items(before)
    second = organize_items(before)

    assert first == second
    assert organize_ids(before) == frozenset(item.memory_id for item in first)
    assert [item.memory_id for item in first] == [
        entry.id for entry in before.entries if entry.id in organize_ids(before)
    ]
    assert _bytes(store) == files
    assert store.load() == before
