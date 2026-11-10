# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"""Memory receipts cross ACP without exposing the global private library."""

from __future__ import annotations

from chrys.app.acp.server import ChrysAcpServer
from chrys.foundation.events.bus import EventBus
from chrys.foundation.events.personal_memory import PersonalMemoryChanged
from chrys.foundation.models.personal_memory import MemoryDraft, MemorySnapshot, MemorySource, PersonalMemory
from chrys.orchestration.session_host import allows_headless_event
from tests.app.acp._server_fakes import _FakeClient, _FakeHost, _FakeManager


async def test_acp_receipt_contains_only_the_saved_entry_and_no_source_content() -> None:
    host = _FakeHost(event_bus=EventBus())
    client = _FakeClient()
    server = ChrysAcpServer(_FakeManager(host), initial_vision=False)  # type: ignore[arg-type]
    server.on_connect(client)
    private = PersonalMemory(
        "private",
        1,
        MemoryDraft("Other project", "Secret", "other", workspace="other"),
        MemorySource(quote="Private evidence"),
        "active",
        "",
        "",
    )
    saved = PersonalMemory("saved", 1, MemoryDraft("Slides", "Diagrams", "slides"), MemorySource(), "candidate", "", "")
    event = PersonalMemoryChanged(
        session_id="s1", snapshot=MemorySnapshot(entries=(private, saved)), saved_memory_id=saved.id
    )
    assert allows_headless_event(event)
    assert await server._handle_chrys_extension_event("s1", event)
    assert client.ext_notifications == [
        (
            "chrys/personal_memory",
            {"sessionId": "s1", "memoryId": "saved", "revision": 1, "state": "candidate", "title": "Slides"},
        )
    ]
    await server._handle_chrys_extension_event("s1", PersonalMemoryChanged(session_id="s1", snapshot=event.snapshot))
    assert len(client.ext_notifications) == 1
    failed = PersonalMemoryChanged(
        session_id="s1", attempted_title="Slides", error_code="memory_source_missing", error="Evidence missing"
    )
    assert allows_headless_event(failed)
    await server._handle_chrys_extension_event("s1", failed)
    assert client.ext_notifications[-1] == (
        "chrys/personal_memory",
        {
            "sessionId": "s1",
            "attemptedTitle": "Slides",
            "errorCode": "memory_source_missing",
            "error": "Evidence missing",
        },
    )


async def test_real_host_routes_memory_receipts_to_acp_and_cli_without_other_session_data(
    tmp_path, monkeypatch
) -> None:
    import io

    from acp import schema as acp_schema
    from rich.console import Console

    from chrys.app.cli.progress import ProgressWriter, RunContext, TurnProgress
    from chrys.kernel import FunctionTool, Message
    from chrys.orchestration.session_host import ChrysSessionHost
    from chrys.service.llm.mock import MockChatClient, MockResponse
    from chrys.service.personal_memory.runtime import PersonalMemoryRuntime
    from chrys.service.personal_memory.store import PersonalMemoryStore
    from chrys.service.state.store import JsonFileStateStore
    from tests.orchestration._session_host_helpers import (
        _make_agent_registry,
        _make_profile,
        _make_settings_and_models,
        _patch_runtime,
    )

    bus = EventBus()
    store = PersonalMemoryStore(tmp_path / "memory.json")
    store.save(
        MemoryDraft("PRIVATE_TITLE", "PRIVATE_BODY", "private", workspace=str(tmp_path / "other")),
        MemorySource(quote="PRIVATE_QUOTE"),
    )
    calls = 0
    quote = "Remember my slide preference."

    async def save_memory_probe() -> str:
        nonlocal calls
        calls += 1
        await bus.publish(
            PersonalMemoryChanged(session_id="unrelated", attempted_title="OTHER_SESSION", error="OTHER_ERROR")
        )
        runtime = PersonalMemoryRuntime(bus=bus, session_id=host.session_id, workspace=str(tmp_path), store=store)
        runtime.observe([Message("user", [quote])])
        return await runtime.propose_memory(
            "Slides", "Use diagrams", "Technical slides", quote if calls == 1 else "Invented", save_now=True
        )

    model = MockChatClient(
        responses=[
            MockResponse(tool_calls=[("save_memory_probe", "one", {})]),
            MockResponse(text="Saved"),
            MockResponse(tool_calls=[("save_memory_probe", "two", {})]),
            MockResponse(text="Could not save"),
        ]
    )
    _patch_runtime(monkeypatch, [model], [FunctionTool(func=save_memory_probe, name="save_memory_probe")])
    settings, models = _make_settings_and_models()
    host = ChrysSessionHost(
        profile_name="Headless",
        settings=settings,
        event_bus=bus,
        agent_registry=_make_agent_registry(_make_profile()),
        model_registry=models,
        state_store=JsonFileStateStore(tmp_path / "sessions"),
        cwd=str(tmp_path),
    )
    try:
        await host.start()
        manager = _FakeManager(host)  # type: ignore[arg-type]
        manager._session.session_id = host.session_id

        def get_session(session_id):
            assert session_id == host.session_id
            return manager._session

        monkeypatch.setattr(manager, "get", get_session)
        client = _FakeClient()
        server = ChrysAcpServer(manager, initial_vision=False)  # type: ignore[arg-type]
        server.on_connect(client)
        response = await server.prompt([acp_schema.TextContentBlock(type="text", text=quote)], host.session_id)
        assert response.stop_reason == "end_turn"
        receipts = [payload for name, payload in client.ext_notifications if name == "chrys/personal_memory"]
        assert len(receipts) == 1 and receipts[0]["title"] == "Slides"
        assert receipts[0]["sessionId"] == host.session_id and receipts[0]["state"] == "active"
        assert "PRIVATE_" not in str(receipts) and "OTHER_" not in str(receipts)
        output = io.StringIO()
        progress = TurnProgress(
            ProgressWriter(Console(file=output, width=400, markup=False, color_system=None)),
            render=str,
            context=RunContext,
        )
        result = await host.run_until_final(quote, timeout=45, on_event=progress.handle)
        assert result.text == "Could not save"
        assert "Memory not saved: Slides" in output.getvalue()
        assert "PRIVATE_" not in output.getvalue() and "OTHER_" not in output.getvalue()
    finally:
        await host.shutdown()
