# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory activity stays visible without claiming that every call saved a memory."""

from __future__ import annotations

import json

import pytest

from chrys.app.tui.widgets.chat.fold_rows import ToolTally, tool_category
from chrys.app.tui.widgets.chat.panel import ChatPanel
from chrys.app.tui.widgets.chat.process_block import ProcessBlock
from chrys.app.tui.widgets.chat.single_call_row import single_call_row
from chrys.app.tui.widgets.chat.tool_call import ToolGroup, ToolGroupTitle
from chrys.foundation.i18n import Localizer
from chrys.foundation.tool_kinds import KIND_CONTEXT, KIND_MCP, TOOL_CALL_KIND_METADATA_KEY
from chrys.foundation.tool_result_metadata import TOOL_RESULT_METADATA_KEY
from tests.support.tui_helpers import ChatPanelApp, resize_when_settled
from tests.support.waiting import wait_for


def test_memory_calls_have_separate_counts_without_changing_tool_kind() -> None:
    calls = [
        (tool_category(KIND_CONTEXT, tool_name=name), outcome)
        for name, outcome in (
            ("recall_memory", ""),
            ("propose_memory", "failed"),
            ("pause_memory", "interrupted"),
        )
    ]
    tally = ToolTally.of(calls)
    assert tally.count_words(Localizer("en")) == ("1 memory lookup", "1 memory write", "1 memory pause")
    assert tally.failed == 1
    assert tally.interrupted == 1
    assert tool_category(KIND_MCP, tool_name="propose_memory") == "mcp"
    assert tool_category(KIND_CONTEXT, "mcp", tool_name="propose_memory") == "mcp"


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        ({"state": "active", "changed": True}, "Saved memory: Diagram-first slides"),
        ({"state": "candidate", "changed": True}, "Memory to review: Diagram-first slides"),
        ({"state": "active", "changed": False}, "Memory unchanged: Diagram-first slides"),
        ({}, "Processed memory: Diagram-first slides"),
    ],
)
def test_write_row_uses_receipt_not_requested_action(receipt: dict, expected: str) -> None:
    row = single_call_row(
        Localizer("en"),
        "propose_memory",
        KIND_CONTEXT,
        {"title": "Diagram-first slides", "save_now": True},
        result=json.dumps(receipt),
    )
    assert row is not None
    assert row.words == expected


def test_related_memory_inspection_is_not_reported_as_advice_used() -> None:
    row = single_call_row(Localizer("en"), "recall_memory", KIND_CONTEXT, {"query": "slides", "for_update": True})
    assert row is not None
    assert row.words == "Checked related memories: slides"


@pytest.mark.parametrize(
    ("name", "receipt", "expected"),
    [
        ("review_memory", {"outcome": "applied"}, "Reported memory use: abcdef12"),
        ("review_memory", {"outcome": "incorrect"}, "Recorded memory feedback: abcdef12"),
        ("update_follow_up", {"changed": True, "follow_up": {"status": "completed"}}, "Updated follow-up: abcdef12"),
        ("organize_memory", {"changed": True, "state": "candidate"}, "Memory to review: abcdef12"),
    ],
)
def test_management_receipts_are_in_native_memory_fold(name: str, receipt: dict, expected: str) -> None:
    row = single_call_row(Localizer("en"), name, KIND_CONTEXT, {"memory_id": "abcdef12"}, result=json.dumps(receipt))
    assert row is not None and row.words == expected
    assert tool_category(KIND_CONTEXT, tool_name=name) == "memory_write"


def test_invalid_receipt_does_not_claim_success() -> None:
    for result in ("not a receipt", "[" * 1500 + "0" + "]" * 1500):
        row = single_call_row(Localizer("en"), "pause_memory", KIND_CONTEXT, {"memory_id": "12345678"}, result=result)
        assert row is not None
        assert "Paused" not in row.words


@pytest.mark.parametrize("replay", [False, True])
async def test_memory_receipt_reaches_live_and_replayed_folded_rows(replay: bool) -> None:
    args = {"title": "Diagrams [dense]"}
    receipt = json.dumps({"state": "candidate", "changed": True})
    async with ChatPanelApp(fold_finished_turns=lambda: True).run_test(size=(100, 24)) as pilot:
        panel = pilot.app.query_one(ChatPanel)
        if replay:
            await panel.replay_history(
                [
                    {"role": "user", "contents": [{"type": "text", "text": "My slide preference"}]},
                    {
                        "role": "assistant",
                        "contents": [
                            {
                                "type": "function_call",
                                "name": "propose_memory",
                                "call_id": "m",
                                "arguments": args,
                                "additional_properties": {TOOL_CALL_KIND_METADATA_KEY: KIND_CONTEXT},
                            }
                        ],
                    },
                    {"role": "tool", "contents": [{"type": "function_result", "call_id": "m", "result": receipt}]},
                    {"role": "assistant", "contents": [{"type": "text", "text": "Done."}]},
                ]
            )
            await panel.wait_replay_complete()
        else:
            await panel.add_user_message("My slide preference")
            await panel.add_tool_start("m", "propose_memory", KIND_CONTEXT, args=args)
            title = panel.query_one(ToolGroupTitle)
            assert "Preparing memory: Diagrams [dense]" in title.render().plain
            await panel.add_tool_result("m", "propose_memory", receipt)
            await panel.add_agent_message("Done.")
        group = panel.query_one(ToolGroup)
        title = group.query_one(ToolGroupTitle)
        await wait_for(
            lambda: "Memory to review: Diagrams [dense]" in title.render().plain,
            pilot=pilot,
            description="memory receipt in the existing group row",
        )
        group.collapsed = True
        assert group._title_row().head == "▸ "
        assert "memory write" in panel.query_one(ProcessBlock).render().plain


async def test_memory_failures_stay_visible_in_narrow_folded_group() -> None:
    async with ChatPanelApp().run_test(size=(100, 24)) as pilot:
        panel = pilot.app.query_one(ChatPanel)
        await panel.add_user_message("Check my preference")
        await panel.add_tool_start("r", "recall_memory", KIND_CONTEXT, args={"query": "slides"})
        await panel.add_tool_result("r", "recall_memory", "No matching memories.")
        await panel.add_tool_start("w", "propose_memory", KIND_CONTEXT, args={"title": "Technical slides"})
        await panel.add_tool_result("w", "propose_memory", "Error: stale revision")
        await panel.add_agent_message("Please review the correction.")
        title = panel.query_one(ToolGroupTitle)
        await wait_for(lambda: "1 failed" in title.render().plain, pilot=pilot, description="failed memory write count")
        assert "memory lookup" in title.render().plain
        assert "memory write" in title.render().plain
        await resize_when_settled(pilot, 40, 24)
        assert title.render().plain.endswith("1 failed")
        assert title.render().cell_len <= title.content_size.width


@pytest.mark.parametrize("count", [1, 2])
async def test_replayed_memory_deferral_never_claims_a_file_was_written(count: int) -> None:
    metadata = {"memory_review": True, "executed": False}
    calls = [
        {
            "type": "function_call",
            "name": "write_file",
            "call_id": str(i),
            "arguments": {"path": "not-written.txt", "content": "Unsafe"},
            "additional_properties": {TOOL_CALL_KIND_METADATA_KEY: "filesystem.write"},
        }
        for i in range(count)
    ]
    results = [
        {
            "type": "function_result",
            "call_id": str(i),
            "result": "Action NOT EXECUTED. Review memories first.",
            "additional_properties": {TOOL_RESULT_METADATA_KEY: metadata},
        }
        for i in range(count)
    ]
    async with ChatPanelApp(fold_finished_turns=lambda: True).run_test(size=(100, 24)) as pilot:
        panel = pilot.app.query_one(ChatPanel)
        await panel.replay_history(
            [
                {"role": "user", "contents": [{"type": "text", "text": "Fix the failure"}]},
                {"role": "assistant", "contents": calls},
                {"role": "tool", "contents": results},
                {"role": "assistant", "contents": [{"type": "text", "text": "I reconsidered the action."}]},
            ]
        )
        await panel.wait_replay_complete()
        group = panel.query_one(ToolGroup)
        title = group.query_one(ToolGroupTitle)
        assert "deferred" in title.render().plain.lower()
        assert "Wrote" not in title.render().plain
        assert "edited" not in " ".join(group.tool_tally.action_words(Localizer("en")))
        group.collapsed = False
        await wait_for(lambda: bool(group.query("#tc-body")), pilot=pilot)
        assert not group.query("#ft-panel")
