# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Isolated, opt-in real-model memory trial and real TUI demo. See the memory test guide."""

# ruff: noqa: RUF001 -- Demo inputs deliberately use natural Chinese punctuation.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from rich.cells import cell_len

from chrys.foundation.platform import get_platform
from chrys.kernel import Message
from chrys.orchestration.session_host import ChrysSessionHost
from chrys.orchestration.startup import RuntimeBootstrap, bootstrap_runtime
from chrys.service.llm.observer import WireCall, WireCallObserver
from chrys.service.personal_memory.store import PersonalMemoryStore
from chrys.service.profiles.agents.registry import AgentProfileRegistry
from chrys.service.profiles.agents.schema import AgentProfile, CompactionConfig, ModelConfig, SkillsConfig, ToolsConfig
from chrys.service.profiles.models.registry import ModelProfileRegistry
from chrys.service.state.store import JsonFileStateStore

if TYPE_CHECKING:
    from chrys.app.tui.app import ChrysApp

QUESTION = "我准备把评审流程改成自动发布，请给一个决策建议。"
SAVE = (
    "请帮我记住：跨项目给我做评审决策时，用橙桥检查：先指出会推翻建议的证据，"
    "再给可逆的小实验，最后才建议扩大投入。如果只是润色文字就不要套用。"
)
UPDATE = (
    "请帮我更新这条记忆：橙桥检查的新顺序是先做可逆的小实验，再指出会推翻建议的证据，"
    "最后才建议扩大投入。适用范围仍是跨项目的评审决策；只润色文字时仍不要套用。"
)
PROJECT_SAVE = "请记住：当前石杉项目的发布核对清单名称是杉叶47，仅在本项目发布核对时使用，项目结束就停止使用。"
PROJECT_QUESTION = "石杉项目的发布核对清单叫什么？"


def _save_screenshot(app: ChrysApp, root: Path, name: str) -> None:
    svg = app.export_screenshot()
    (root / f"{name}.raw.svg").write_text(svg, encoding="utf-8")
    tree = ET.fromstring(svg)
    # Rich positions text using terminal cells, but its SVG textLength uses
    # len(text). Correct only that export metric so CJK glyphs do not overlap.
    for node in tree.iter("{http://www.w3.org/2000/svg}text"):
        text = node.text or ""
        length = node.get("textLength")
        if text and length is not None:
            cell_width = float(length) / len(text)
            node.set("textLength", str(cell_width * cell_len(text)))
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    (root / f"{name}.svg").write_text(ET.tostring(tree, encoding="unicode"), encoding="utf-8")


class Trial:
    def __init__(
        self, root: Path, bootstrap: RuntimeBootstrap, agents: AgentProfileRegistry, models: ModelProfileRegistry
    ):
        self.root = root
        self.bootstrap = bootstrap
        self.agents = agents
        self.models = models
        self.store = PersonalMemoryStore()
        evidence = root / "trial.json"
        self.records: list[dict[str, Any]] = (
            json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else []
        )

    def host(self, project: str = "project-a") -> ChrysSessionHost:
        workspace = self.root / project
        workspace.mkdir(exist_ok=True)
        return ChrysSessionHost(
            profile_name="MemoryDemo",
            loaded_settings=self.bootstrap.loaded,
            agent_registry=self.agents,
            model_registry=self.models,
            state_store=JsonFileStateStore(self.root / "sessions"),
            cwd=str(workspace),
        )

    async def run(self, name: str, prompt: str, *, project: str = "project-a") -> dict[str, Any]:
        requests: list[list[dict[str, Any]]] = []
        begin = WireCallObserver.begin

        def observe(
            observer: WireCallObserver,
            messages: Sequence[Message],
            options: Mapping[str, Any],
            *,
            stream: bool,
            forwarded_trace: object,
        ) -> WireCall:
            # Message evidence only. Never record model profiles, headers or HTTP credentials.
            requests.append([message.to_dict() for message in messages])
            return begin(observer, messages, options, stream=stream, forwarded_trace=forwarded_trace)

        host = self.host(project)
        started = time.monotonic()
        record: dict[str, Any] = {"case": name, "prompt": prompt, "project": project}
        try:
            with patch.object(WireCallObserver, "begin", observe):
                result = await host.run_until_final(prompt, timeout=180)
            record.update(session_id=result.session_id, answer=result.text)
        except Exception as error:
            record["error_type"] = type(error).__name__
            raise
        finally:
            await host.shutdown()
            record.update(
                seconds=round(time.monotonic() - started, 2),
                requests=requests,
                snapshot=asdict(self.store.load()),
            )
            self.records.append(record)
            (self.root / "trial.json").write_text(
                json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"{name}: {record['seconds']}s, {len(requests)} provider acquisitions", flush=True)  # noqa: T201
        return record

    async def live(self) -> None:
        if self.store.load().entries:
            raise ValueError("Live trial needs a new --output directory; use --tui to explore an existing demo.")
        self.store.configure("off", False)
        await self.run("01-without-memory", QUESTION)
        self.store.configure("auto", False)
        await self.run("02-explicit-save", SAVE)
        personal = next(entry for entry in self.store.load().entries if entry.state == "active")
        await self.run("03-fresh-session-recall", QUESTION)
        await self.run("04-current-exception", "我准备把评审流程改成自动发布。这一轮只写一句发布公告，不要给决策建议。")
        await self.run("05-correction", UPDATE)
        await self.run("06-corrected-recall", QUESTION)
        await self.run("07-project-save", PROJECT_SAVE)
        await self.run("08-same-project", PROJECT_QUESTION)
        await self.run("09-other-project", PROJECT_QUESTION, project="project-b")
        await self.run("10-unrelated", "如何把一列数字从小到大排列？")
        self.store.configure("manual", False)
        await self.run("11-manual-no-request", QUESTION)
        await self.run("12-manual-explicit-request", "请查一下个人记忆，再回答：" + QUESTION)
        self.store.configure("off", False)
        await self.run("13-off-with-saved-memory", QUESTION)
        self.store.configure("auto", True)
        await self.run("14-declined", "不要记住：这次报告只是临时采用蓝色。请回答收到即可。")
        await self.run(
            "15-candidate",
            "我们反复试过，给北窗项目写运行指南时，以可复制的命令开头比先铺背景更有效。"
            "请从这句话提出一条待我确认的项目记忆建议，先不要正式启用。",
        )
        await self.run("16-unapproved-candidate", "北窗项目的运行指南怎么开头？")
        personal = next(entry for entry in self.store.load().entries if entry.id == personal.id)
        self.store.set_state(personal.id, personal.revision, "archived")
        await self.run("17-paused", QUESTION)
        personal = next(entry for entry in self.store.load().entries if entry.id == personal.id)
        self.store.set_state(personal.id, personal.revision, "active")
        project = next(entry for entry in self.store.load().entries if "杉叶47" in entry.draft.content)
        self.store.forget(project.id, project.revision)
        await self.run("18-forgotten", PROJECT_QUESTION)
        self.store.configure("auto", False)

    def app(self):
        from chrys.app.tui.app import ChrysApp

        host = self.host()
        return ChrysApp(
            event_bus=host.event_bus,
            engine=host.engine,
            settings=self.bootstrap.settings,
            profile_name="MemoryDemo",
            state_store=JsonFileStateStore(self.root / "sessions"),
            agent_registry=self.agents,
            model_registry=self.models,
            settings_handle=host.engine.settings_handle,
            gc_freeze_enabled=False,
        )

    async def capture_tui(self) -> None:
        from textual.widgets import Button, Collapsible, Tabs, TextArea

        from chrys.app.tui.screens.personal_memory.screen import PersonalMemoryScreen
        from chrys.app.tui.widgets.chrome.input_bar import InputBar
        from chrys.foundation.events.types import InvocationMessage
        from tests.support.tui_helpers import click_when_settled, resize_when_settled
        from tests.support.waiting import wait_for

        app = self.app()

        async with app.run_test(size=(120, 42)) as pilot:
            await wait_for(
                lambda: app._main_screen is not None and bool(app._engine.session_id),
                pilot=pilot,
                timeout=30,
                description="real engine started",
            )
            if app._startup_task is not None:
                await app._startup_task
            main = app._main_screen
            assert main is not None
            bar = main.query_one(InputBar)
            final: asyncio.Future[str] = asyncio.get_running_loop().create_future()

            async def answered(event: InvocationMessage) -> None:
                if event.is_final and event.origin.kind == "turn" and not final.done():
                    final.set_result(event.text)

            await app._bus.subscribe(InvocationMessage, answered)
            bar.focus_input()
            bar.query_one("#chat-input", TextArea).load_text(QUESTION)
            await click_when_settled(pilot, bar.query_one("#send-btn", Button))
            answer = await asyncio.wait_for(final, timeout=180)
            (self.root / "tui-answer.txt").write_text(answer, encoding="utf-8")
            await pilot.pause()
            _save_screenshot(app, self.root, "chat")
            bar.focus_input()
            bar.query_one("#chat-input", TextArea).load_text("/memory")
            await click_when_settled(pilot, bar.query_one("#send-btn", Button))
            await wait_for(
                lambda: isinstance(app.screen, PersonalMemoryScreen), pilot=pilot, description="slash memory"
            )
            screen = app.screen
            assert isinstance(screen, PersonalMemoryScreen)
            await wait_for(lambda: bool(screen.snapshot.entries), pilot=pilot, description="memory loaded")
            screen.query_one("#memory-view", Tabs).active = "memory-view-recalled"
            await pilot.pause()
            for width, height in ((120, 42), (80, 32), (60, 28)):
                await resize_when_settled(pilot, width, height)
                _save_screenshot(app, self.root, f"memory-{width}")
            await resize_when_settled(pilot, 120, 42)
            screen.query_one("#memory-view", Tabs).active = "memory-view-candidate"
            await pilot.pause()
            if any(entry.state == "candidate" for entry in screen.snapshot.entries):
                assert not screen.query_one("#memory-evidence", Collapsible).collapsed
                _save_screenshot(app, self.root, "candidate")
                await click_when_settled(pilot, screen.query_one("#memory-accept", Button))
                await wait_for(
                    lambda: not any(entry.state == "candidate" for entry in screen.snapshot.entries),
                    pilot=pilot,
                    description="candidate accepted through UI",
                )
            (self.root / "tui-snapshot.json").write_text(
                json.dumps(asdict(self.store.load()), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(  # noqa: T201 -- Progress for this opt-in command-line demo.
                "Real TUI: submitted prompt, opened /memory, captured 120/80/60 columns, reviewed candidate.",
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--model", required=True, help="An existing local model profile ID; credentials stay in memory."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tui", action="store_true", help="Open the real interactive TUI on this isolated demo library.")
    mode.add_argument("--capture-tui", action="store_true", help="Run one real TUI turn and save SVG screenshots.")
    mode.add_argument("--query", help="Run one new-session prompt against this demo library and append its evidence.")
    args = parser.parse_args()
    models = ModelProfileRegistry()
    models.load_all()
    profile = models.get(args.model)
    if profile is None:
        parser.error("--model must name an existing local model profile ID.")
    # An explicit registry keeps unrelated model profiles out of the isolated demo.
    models = ModelProfileRegistry()
    models.register(profile)
    root = args.output.resolve()
    marker = root / ".memory-demo"
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        parser.error("Use an empty output directory or one created by this demo.")
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text("Synthetic personal memory demo\n", encoding="utf-8")
    workspace = root / "project-a"
    workspace.mkdir(exist_ok=True)
    config = root / "config"
    config.mkdir(exist_ok=True)
    platform = replace(get_platform(), config_dir=config, data_dir=config)
    agents = AgentProfileRegistry()
    agents.register(
        AgentProfile(
            name="MemoryDemo",
            id="memory-demo",
            instructions="Help the user make concrete decisions. Reply concisely in Chinese. Distinguish evidence from assumptions.",
            model=ModelConfig(profile_id=profile.id),
            tools=ToolsConfig(builtins=[]),
            skills=SkillsConfig(auto_load_user_agents_skills=False, auto_load_cwd_agents_skills=False),
            compaction=CompactionConfig(enabled=False),
        )
    )
    os.chdir(workspace)
    with (
        patch("chrys.foundation.platform.detect_platform", return_value=platform),
        patch.dict(
            os.environ,
            {
                "CHRYS_SESSION_ROOT_DIR": str(root),
                "CHRYS_DEBUG_LLM_RAW_HTTP_LOG": "false",
                "CHRYS_MAX_TRANSIENT_RETRIES": "1",
                "CHRYS_LOCALE": "zh-Hans",
            },
        ),
    ):
        get_platform.cache_clear()
        if args.capture_tui:
            # Match the existing UI test fixture rather than the outer CI/agent console.
            for name in ("FORCE_COLOR", "COLORTERM", "NO_COLOR", "CLICOLOR_FORCE"):
                os.environ.pop(name, None)
        bootstrap = bootstrap_runtime(
            dotenv_override=False, dotenv_cwd=workspace, setup_telemetry=False, project_root=workspace
        )
        trial = Trial(root, bootstrap, agents, models)
        if args.tui:
            trial.app().run()
        elif args.query:
            asyncio.run(trial.run("query", args.query))
        else:
            asyncio.run(trial.capture_tui() if args.capture_tui else trial.live())


if __name__ == "__main__":
    main()
