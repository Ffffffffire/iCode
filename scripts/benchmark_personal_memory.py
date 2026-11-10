# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Measure local recall and legacy history import, using disposable data only.

Run: uv run python scripts/benchmark_personal_memory.py --output <report.json>
Latency includes secure store access, ranking and rendering; the receipt case also
includes an atomic write. Cold means a new store/index, not a cold OS disk cache.
These are observations on this machine, not portable CI timing assertions.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from chrys.foundation.models.personal_memory import (
    MemoryDraft,
    MemoryRevision,
    MemorySnapshot,
    MemorySource,
    PersonalMemory,
)
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.service.personal_memory.retrieval import MemoryRetriever
from chrys.service.personal_memory.store import PersonalMemoryStore


def _samples(action: Callable[[int], object], count: int) -> dict[str, float]:
    elapsed = []
    for index in range(count):
        start = perf_counter_ns()
        action(index)
        elapsed.append((perf_counter_ns() - start) / 1_000_000)
    ordered = sorted(elapsed)
    return {
        "p50_ms": round(statistics.median(elapsed), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "max_ms": round(ordered[-1], 3),
    }


def benchmark(size: int, iterations: int, *, revisions: int) -> dict[str, object]:
    with TemporaryDirectory(prefix="icode-memory-benchmark-") as temporary:
        path = Path(temporary) / "memory.json"
        source = MemorySource(quote="A synthetic maintenance example. " * 6)
        entries = []
        for index in range(size):
            draft = MemoryDraft(
                f"Component {index} cache policy",
                f"Inspect component {index} and its parser version before publishing cached output. " * 12,
                f"Cache invalidation for component {index}",
            )
            entries.append(
                PersonalMemory(
                    f"{index:016x}",
                    revisions + 1,
                    draft,
                    source,
                    "active",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                    tuple(
                        MemoryRevision(number + 1, draft, source, "2026-01-01T00:00:00+00:00")
                        for number in range(revisions)
                    ),
                )
            )
        state = MemorySnapshot(entries=tuple(entries))
        atomic_write_owner_only_text(path, json.dumps({"version": 1, **asdict(state)}, indent=2))
        query = f"component {size // 2} cache policy"
        cold = _samples(lambda _: PersonalMemoryStore(path).recall(query, "", record=False), 5)
        store = PersonalMemoryStore(path)
        store.recall(query, "", record=False)
        hot = _samples(lambda _: store.recall(query, "", record=False), iterations)
        uncached = _samples(lambda i: store.recall(query + f" request{i}", "", record=False), iterations)
        browser = MemoryRetriever()
        library_cold = _samples(lambda _: MemoryRetriever().browse(state.entries, query), 5)
        browser.browse(state.entries, query)
        library_search = _samples(lambda i: browser.browse(state.entries, query + f" request{i}"), iterations)
        initial_bytes = path.stat().st_size
        start = perf_counter_ns()
        store.recall(query, "", session_id="benchmark-seed")
        import_ms = (perf_counter_ns() - start) / 1_000_000
        receipts = _samples(lambda i: store.recall(query + " " * (i + 1), "", session_id="benchmark"), iterations)
        other = PersonalMemoryStore(path)
        original = other.load().entries[size // 2]
        revised = other.save(
            replace(original.draft, content="Check the revised parser contract."),
            source,
            memory_id=original.id,
            revision=original.revision,
        )
        start = perf_counter_ns()
        result = store.recall(query, "", record=False)
        changed_ms = (perf_counter_ns() - start) / 1_000_000
        if not result or result[0][0] != revised:
            raise RuntimeError("Recall did not return the externally corrected memory.")
        tracemalloc.start()
        index = MemoryRetriever()
        index.search(state.entries, query, "", automatic=True)
        retained, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return {
            "entries": size,
            "previous_revisions_per_entry": revisions,
            "samples": iterations,
            "store_bytes": path.stat().st_size,
            "initial_store_bytes": initial_bytes,
            "first_receipt_including_history_import_ms": round(import_ms, 3),
            "new_instance": cold,
            "hot_read": hot,
            "uncached_query": uncached,
            "library_search_cold": library_cold,
            "library_search_warm": library_search,
            "receipt_write": receipts,
            "first_read_after_external_correction_ms": round(changed_ms, 3),
            "derived_index_retained_bytes": retained,
            "derived_index_peak_bytes": peak,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.size < 10 or not 5 <= args.iterations <= 200:
        parser.error("size must be at least10; iterations must be 5..200")
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "measurement": "milliseconds, nearest-rank p95; OS file cache is not flushed; synthetic data only",
        "cases": [benchmark(args.size, args.iterations, revisions=revisions) for revisions in (0, 5)],
    }
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        parser.exit(message=payload)


if __name__ == "__main__":
    main()
