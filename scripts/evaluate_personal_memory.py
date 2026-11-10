# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Offline layer-by-layer memory recall evaluation; no model or user-store writes.

Run with --cases <json> --output <json>. Labels include their provenance and
review status; an authored paraphrase must never be labelled a historical miss.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from chrys.foundation.events.bus import EventBus
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySnapshot, MemorySource, PersonalMemory
from chrys.foundation.platform.files import atomic_write_owner_only_text
from chrys.foundation.tool_kinds import set_tool_kind
from chrys.kernel import FunctionTool, Message
from chrys.kernel.middleware import FunctionInvocationContext
from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
from chrys.service.personal_memory.store import STORE_VERSION, PersonalMemoryStore, workspace_key


async def evaluate(dataset: dict) -> dict:
    if dataset.get("schema_version") != 1 or len({c["id"] for c in dataset["cases"]}) != len(dataset["cases"]):
        raise ValueError("Evaluation cases need a known schema and unique IDs")
    counts = {"opening_hits": 0, "action_recoveries": 0, "standing_injections": 0, "explicit_hits": 0}
    results = []
    with TemporaryDirectory(prefix="icode-memory-evaluation-") as temporary:
        root = Path(temporary)
        entries = tuple(
            PersonalMemory(
                m["id"],
                1,
                MemoryDraft(
                    **{
                        **m["draft"],
                        "workspace": workspace_key(str(root / m["draft"]["workspace"]))
                        if m["draft"].get("workspace")
                        else "",
                    }
                ),
                MemorySource(quote=m.get("source_quote", "")),
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            )
            for m in dataset["memories"]
        )
        known = {e.id for e in entries}
        if len(known) != len(entries):
            raise ValueError("Evaluation memories need unique IDs")
        for case in dataset["cases"]:
            expected = case["expected"]
            labelled = {mid for ids in expected.values() for mid in ids}
            if (
                any(layer not in ("L0", "L1", "L2", "L3") for layer in expected)
                or not labelled <= known
                or not set(case.get("forbidden", ())) <= known
                or labelled & set(case.get("forbidden", ()))
            ):
                raise ValueError("Evaluation labels must name known layers/memories and cannot contradict each other")
            store = PersonalMemoryStore(root / f"{len(results)}.json")
            atomic_write_owner_only_text(
                store.path,
                json.dumps(
                    {"version": STORE_VERSION, **asdict(MemorySnapshot(mode=case.get("mode", "auto"), entries=entries))}
                ),
            )
            runtime = PersonalMemoryRuntime(
                bus=EventBus(),
                session_id="evaluation",
                workspace=str(root / case.get("workspace", "icode")),
                store=store,
            )
            await runtime.prepare([Message("user", [case["query"]])])
            if case.get("action"):
                action = case["action"]
                function = FunctionTool(name=action["name"], func=lambda: "Completed")
                set_tool_kind(function, action["kind"])
                context = FunctionInvocationContext(function, action["arguments"])

                async def complete(tool_context: FunctionInvocationContext = context) -> None:
                    tool_context.result = "Completed"

                await runtime.process(context, complete)
            search_errors = []
            for search in case.get("searches", ()):
                response = await runtime.recall_memory(search["query"], for_update=search.get("for_update", False))
                if response.startswith("Error: "):
                    search_errors.append(response)
            state = store.load()
            matches = state.recalls[-1].matches if state.recalls else ()
            actual = {layer: {m.memory_id for m in matches if m.layer == layer} for layer in ("L0", "L1", "L2", "L3")}
            missing = {
                layer: sorted(set(ids) - actual[layer]) for layer, ids in expected.items() if set(ids) - actual[layer]
            }
            unlabelled = {m.memory_id for m in matches} - labelled
            unexpected = sorted(
                (set(case.get("forbidden", ())) & {m.memory_id for m in matches})
                | (unlabelled if case.get("strict", False) else set())
            )
            counts["opening_hits"] += len(actual["L1"] & set(expected.get("L1", ())))
            counts["action_recoveries"] += len(actual["L2"] & set(expected.get("L2", ())))
            counts["standing_injections"] += len(actual["L0"])
            counts["explicit_hits"] += len(actual["L3"] & set(expected.get("L3", ())))
            results.append(
                {
                    "case": case["id"],
                    "actual": {k: sorted(v) for k, v in actual.items()},
                    "missing": missing,
                    "unexpected": unexpected,
                    "unlabelled": sorted(unlabelled),
                    "search_errors": search_errors,
                }
            )
    return {
        "cases": len(results),
        "labelled_by": dataset.get("labelled_by", "unknown"),
        "strict_cases": sum(bool(case.get("strict")) for case in dataset["cases"]),
        **counts,
        "failed_cases": sum(bool(r["missing"] or r["unexpected"] or r["search_errors"]) for r in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/service/personal_memory/fixtures/recall_cases.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.cases.read_bytes()
    report = asyncio.run(evaluate(json.loads(raw)))
    report["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))  # noqa: T201 -- Developer CLI result.
    return int(bool(report["failed_cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
