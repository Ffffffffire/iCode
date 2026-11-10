# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Grounded labels are consumed by the same runtime as automatic recall."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluate_personal_memory import evaluate


async def test_curated_cases_cover_all_four_layers_and_strict_negative_labels() -> None:
    dataset = json.loads((Path(__file__).parent / "fixtures/recall_cases.json").read_text(encoding="utf-8"))
    result = await evaluate(dataset)
    assert result["cases"] >= 88 and result["strict_cases"] >= 24
    assert result["failed_cases"] == 0, [
        r for r in result["results"] if r["missing"] or r["unexpected"] or r["search_errors"]
    ]
    assert result["opening_hits"] > 0 and result["action_recoveries"] > 0 and result["standing_injections"] > 0
    assert result["explicit_hits"] > 0


async def test_incorrect_gold_label_is_reported_as_a_failure() -> None:
    dataset = json.loads((Path(__file__).parent / "fixtures/recall_cases.json").read_text(encoding="utf-8"))
    case = next(c for c in dataset["cases"] if c.get("mode") == "off")
    case["expected"] = {"L1": [dataset["memories"][0]["id"]]}
    case["forbidden"] = []
    dataset["cases"] = [case]
    result = await evaluate(dataset)
    assert result["failed_cases"] == 1 and result["results"][0]["missing"] == case["expected"]


async def test_explicit_queries_are_exercised_instead_of_only_accepting_l3_labels() -> None:
    result = await evaluate(
        {
            "schema_version": 1,
            "memories": [
                {
                    "id": "0000000000000001",
                    "draft": {"title": "Slides", "content": "Use dense diagrams", "when_to_use": "Preparing slides"},
                }
            ],
            "cases": [
                {
                    "id": "explicit",
                    "mode": "manual",
                    "query": "Proceed",
                    "searches": [{"query": "0000000000000001"}],
                    "expected": {"L3": ["0000000000000001"]},
                    "strict": True,
                }
            ],
        }
    )
    assert result["failed_cases"] == 0, result["results"]
    assert result["explicit_hits"] == 1


async def test_strict_labels_fail_when_an_unlabelled_memory_is_also_injected() -> None:
    result = await evaluate(
        {
            "schema_version": 1,
            "memories": [
                {
                    "id": "0000000000000001",
                    "draft": {"title": "Cache keys", "content": "Check cache keys", "when_to_use": "Changing cache"},
                },
                {
                    "id": "0000000000000002",
                    "draft": {"title": "Cache files", "content": "Check cache files", "when_to_use": "Changing cache"},
                },
            ],
            "cases": [{"id": "extra", "query": "cache", "expected": {"L1": ["0000000000000001"]}, "strict": True}],
        }
    )
    assert result["failed_cases"] == 1
    assert result["results"][0]["unexpected"] == ["0000000000000002"]


async def test_search_budget_errors_fail_evaluation_instead_of_being_ignored() -> None:
    result = await evaluate(
        {
            "schema_version": 1,
            "memories": [
                {
                    "id": "0000000000000001",
                    "draft": {"title": "Slides", "content": "Use diagrams", "when_to_use": "Slides"},
                }
            ],
            "cases": [
                {
                    "id": "budget",
                    "mode": "manual",
                    "query": "Proceed",
                    "searches": [{"query": "0000000000000001"}] * 4,
                    "expected": {"L3": ["0000000000000001"]},
                    "strict": True,
                }
            ],
        }
    )
    assert result["failed_cases"] == 1
    assert len(result["results"][0]["search_errors"]) == 1
    assert "Memory recall budget reached" in result["results"][0]["search_errors"][0]
