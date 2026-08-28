"""Behavioral contracts for the process-wide native CDP runtime."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import suppress
import json
from typing import Any

from aiohttp import WSMsgType, web
import pytest

from docs_mcp_server.runtime.cdp_browser import CdpBrowserRuntime


class FakeChrome:
    """Tiny protocol peer that records ownership without browser internals."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.runner: web.AppRunner | None = None
        self.websockets: set[web.WebSocketResponse] = set()
        self.commands: list[dict[str, Any]] = []
        self.command_events: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self.contexts: set[str] = set()
        self.targets: set[str] = {"human-target"}
        self.max_owned_targets = 0
        self.next_context = 0
        self.next_target = 0
        self.evaluate_delay = 0.0
        self.navigation_error: str | None = None
        self.protocol_error_method: str | None = None
        self.disconnect_method: str | None = None
        self.disconnect_cleanup = asyncio.Event()
        self.protocol_version = "1.3"
        self.version_failures = 0
        self.version_requests = 0
        self.version_host: str | None = None
        self.websocket_host: str | None = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/json/version", self._version)
        app.router.add_get("/devtools/browser/token", self._websocket)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        assert self.runner is not None
        await asyncio.gather(*(websocket.close() for websocket in self.websockets))
        await self.runner.cleanup()

    async def _version(self, request: web.Request) -> web.Response:
        self.version_requests += 1
        self.version_host = request.headers["Host"]
        if self.version_failures:
            self.version_failures -= 1
            raise web.HTTPInternalServerError
        return web.json_response(
            {
                "Browser": "FakeChrome/1",
                "Protocol-Version": self.protocol_version,
                "webSocketDebuggerUrl": "ws://advertised.invalid:1/devtools/browser/token",
            }
        )

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        self.websocket_host = request.headers["Host"]
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        self.websockets.add(websocket)
        disposable_contexts: set[str] = set()
        disposable_targets: set[str] = set()
        try:
            async for message in websocket:
                if message.type != WSMsgType.TEXT:
                    continue
                command = json.loads(message.data)
                self.commands.append(command)
                method = command["method"]
                self.command_events[method].set()
                if method == self.disconnect_method:
                    await websocket.close()
                    break
                if method == self.protocol_error_method:
                    await websocket.send_json({"id": command["id"], "error": {"message": "command rejected"}})
                    continue
                result, events = await self._handle(command, disposable_contexts, disposable_targets)
                await websocket.send_json({"id": command["id"], "result": result})
                for event in events:
                    await websocket.send_json(event)
        finally:
            self.websockets.discard(websocket)
            self.contexts.difference_update(disposable_contexts)
            self.targets.difference_update(disposable_targets)
            self.disconnect_cleanup.set()
        return websocket

    async def _handle(
        self,
        command: dict[str, Any],
        disposable_contexts: set[str],
        disposable_targets: set[str],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        method = command["method"]
        params = command.get("params", {})
        events: list[dict[str, Any]] = []
        if method == "Target.createBrowserContext":
            self.next_context += 1
            context_id = f"context-{self.next_context}"
            self.contexts.add(context_id)
            if params.get("disposeOnDetach"):
                disposable_contexts.add(context_id)
            return {"browserContextId": context_id}, events
        if method == "Target.createTarget":
            self.next_target += 1
            target_id = f"target-{self.next_target}"
            self.targets.add(target_id)
            disposable_targets.add(target_id)
            self.max_owned_targets = max(self.max_owned_targets, len(self.targets - {"human-target"}))
            return {"targetId": target_id}, events
        if method == "Target.attachToTarget":
            return {"sessionId": f"session-{params['targetId']}"}, events
        if method == "Page.navigate":
            result = {"frameId": "main-frame", "loaderId": "main-loader"}
            if self.navigation_error:
                result["errorText"] = self.navigation_error
            events.append(
                {
                    "sessionId": command["sessionId"],
                    "method": "Network.responseReceived",
                    "params": {
                        "type": "Document",
                        "frameId": "main-frame",
                        "loaderId": "main-loader",
                        "response": {"status": 200},
                    },
                }
            )
            return result, events
        if method == "Runtime.evaluate":
            await asyncio.sleep(self.evaluate_delay)
            return {
                "result": {
                    "value": {
                        "readyState": "complete",
                        "html": "<html><body>rendered</body></html>",
                    }
                }
            }, events
        if method == "Target.closeTarget":
            self.targets.discard(params["targetId"])
            disposable_targets.discard(params["targetId"])
            return {"success": True}, events
        if method == "Target.disposeBrowserContext":
            self.contexts.discard(params["browserContextId"])
            disposable_contexts.discard(params["browserContextId"])
        return {}, events

    async def wait_for(self, method: str) -> None:
        await asyncio.wait_for(self.command_events[method].wait(), timeout=1)


@pytest.fixture
async def fake_chrome(unused_tcp_port: int):
    chrome = FakeChrome(unused_tcp_port)
    await chrome.start()
    try:
        yield chrome
    finally:
        await chrome.stop()


async def _runtime(chrome: FakeChrome, *, capacity: int = 2) -> CdpBrowserRuntime:
    runtime = CdpBrowserRuntime(chrome.endpoint, capacity)
    await runtime.start()
    chrome.command_events.clear()
    return runtime


@pytest.mark.unit
async def test_fetch_owns_only_exact_disposable_resources(fake_chrome: FakeChrome):
    runtime = await _runtime(fake_chrome)

    page = await runtime.fetch(
        "https://docs.example.test/",
        user_agent="test-agent",
        proxy="http://proxy.example.test:8080",
        timeout_seconds=2,
    )

    assert page.html == "<html><body>rendered</body></html>"
    assert page.status_code == 200
    assert fake_chrome.targets == {"human-target"}
    assert fake_chrome.contexts == set()
    assert "Browser.close" not in [command["method"] for command in fake_chrome.commands]
    context_command = next(
        command
        for command in fake_chrome.commands
        if command["method"] == "Target.createBrowserContext" and command["params"].get("proxyServer")
    )
    assert context_command["params"] == {
        "disposeOnDetach": True,
        "proxyServer": "http://proxy.example.test:8080",
    }
    user_agent_command = next(
        command
        for command in fake_chrome.commands
        if command["method"] == "Emulation.setUserAgentOverride" and command["params"]["userAgent"] == "test-agent"
    )
    assert user_agent_command["params"] == {"userAgent": "test-agent"}
    assert runtime.snapshot() == {
        "mode": "native_cdp",
        "endpoint": fake_chrome.endpoint,
        "state": "ready",
        "ready": True,
        "active": 0,
        "capacity": 2,
        "acquired": 1,
        "released": 1,
        "cleanup_failures": 0,
        "reconnects": 0,
        "owned_contexts": 0,
        "owned_targets": 0,
        "last_failure": None,
    }
    await runtime.stop()


@pytest.mark.unit
async def test_concurrent_fetches_respect_capacity_and_isolate_contexts(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 0.02
    runtime = await _runtime(fake_chrome, capacity=2)

    pages = await asyncio.gather(
        *(
            runtime.fetch(
                f"https://docs.example.test/{index}",
                user_agent="agent",
                timeout_seconds=2,
            )
            for index in range(5)
        )
    )

    assert len(pages) == 5
    assert fake_chrome.max_owned_targets == 2
    assert fake_chrome.next_context == 6
    assert runtime.snapshot()["acquired"] == runtime.snapshot()["released"] == 5
    await runtime.stop()


@pytest.mark.unit
async def test_navigation_failure_still_cleans_exact_resources(fake_chrome: FakeChrome):
    fake_chrome.navigation_error = "name not resolved"
    runtime = await _runtime(fake_chrome)

    with pytest.raises(RuntimeError, match="navigation failed"):
        await runtime.fetch(
            "https://unreachable.example.test/",
            user_agent="agent",
            timeout_seconds=2,
        )

    assert fake_chrome.targets == {"human-target"}
    assert fake_chrome.contexts == set()
    assert runtime.snapshot()["active"] == 0
    assert runtime.snapshot()["last_failure"] == "RuntimeError"
    await runtime.stop()
    assert runtime._http is None


@pytest.mark.unit
async def test_timeout_cleans_and_releases_capacity(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 0.2
    runtime = await _runtime(fake_chrome, capacity=1)

    with pytest.raises(TimeoutError):
        await runtime.fetch(
            "https://slow.example.test/",
            user_agent="agent",
            timeout_seconds=0.05,
        )

    assert fake_chrome.targets == {"human-target"}
    assert fake_chrome.contexts == set()
    assert runtime.snapshot()["active"] == 0
    await runtime.stop()


@pytest.mark.unit
async def test_normal_stop_does_not_report_a_disconnect(fake_chrome: FakeChrome):
    runtime = await _runtime(fake_chrome)

    await runtime.stop()

    assert runtime.snapshot()["state"] == "stopped"
    assert runtime.snapshot()["last_failure"] is None


@pytest.mark.unit
async def test_drain_rejects_new_leases_and_waits_for_active_one(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 0.05
    runtime = await _runtime(fake_chrome, capacity=1)
    active = asyncio.create_task(
        runtime.fetch(
            "https://docs.example.test/active",
            user_agent="agent",
            timeout_seconds=2,
        )
    )
    await fake_chrome.wait_for("Target.createBrowserContext")

    drain = asyncio.create_task(runtime.drain(1))
    await asyncio.sleep(0)
    assert runtime.snapshot()["state"] == "draining"
    with pytest.raises(RuntimeError, match="draining"):
        await runtime.fetch(
            "https://docs.example.test/rejected",
            user_agent="agent",
            timeout_seconds=2,
        )

    await active
    assert await drain is True
    await runtime.stop()


@pytest.mark.unit
async def test_drain_rejects_a_lease_already_waiting_for_capacity(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 0.05
    runtime = await _runtime(fake_chrome, capacity=1)
    active = asyncio.create_task(
        runtime.fetch(
            "https://docs.example.test/active",
            user_agent="agent",
            timeout_seconds=2,
        )
    )
    await fake_chrome.wait_for("Target.createBrowserContext")
    waiting = asyncio.create_task(
        runtime.fetch(
            "https://docs.example.test/waiting",
            user_agent="agent",
            timeout_seconds=2,
        )
    )
    await asyncio.sleep(0)

    drained = asyncio.create_task(runtime.drain(1))

    await active
    with pytest.raises(RuntimeError, match="draining"):
        await waiting
    assert await drained is True
    assert runtime.snapshot()["acquired"] == 1
    await runtime.stop()


@pytest.mark.unit
async def test_drain_timeout_is_visible_while_lease_remains_active(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 0.05
    runtime = await _runtime(fake_chrome, capacity=1)
    active = asyncio.create_task(
        runtime.fetch(
            "https://docs.example.test/active",
            user_agent="agent",
            timeout_seconds=2,
        )
    )
    await fake_chrome.wait_for("Runtime.evaluate")

    assert await runtime.drain(0.001) is False

    await active
    await runtime.stop()


@pytest.mark.unit
async def test_disconnect_disposes_lease_then_lazily_reconnects(fake_chrome: FakeChrome):
    runtime = await _runtime(fake_chrome)
    fake_chrome.disconnect_method = "Page.navigate"

    with pytest.raises(ConnectionError):
        await runtime.fetch(
            "https://docs.example.test/disconnect",
            user_agent="agent",
            timeout_seconds=2,
        )
    await asyncio.wait_for(fake_chrome.disconnect_cleanup.wait(), timeout=1)
    assert fake_chrome.targets == {"human-target"}
    assert fake_chrome.contexts == set()

    fake_chrome.disconnect_method = None
    page = await runtime.fetch(
        "https://docs.example.test/reconnected",
        user_agent="agent",
        timeout_seconds=2,
    )

    assert page.status_code == 200
    assert runtime.snapshot()["reconnects"] == 1
    await runtime.stop()


@pytest.mark.unit
async def test_start_rejects_browser_missing_required_protocol_command(fake_chrome: FakeChrome):
    fake_chrome.protocol_error_method = "Target.disposeBrowserContext"
    runtime = CdpBrowserRuntime(fake_chrome.endpoint, capacity=1)

    with pytest.raises(RuntimeError, match="command rejected"):
        await runtime.start()

    assert runtime.snapshot()["state"] == "disconnected"
    assert runtime.snapshot()["last_failure"] == "CdpProtocolError"
    await runtime.stop()


@pytest.mark.unit
async def test_start_rejects_incompatible_protocol_version(fake_chrome: FakeChrome):
    fake_chrome.protocol_version = "2.0"
    runtime = CdpBrowserRuntime(fake_chrome.endpoint, capacity=1)

    with pytest.raises(RuntimeError, match="protocol version is not supported"):
        await runtime.start()

    assert runtime.snapshot()["state"] == "disconnected"
    await runtime.stop()


@pytest.mark.unit
async def test_start_retries_transient_discovery_failures(fake_chrome: FakeChrome):
    fake_chrome.version_failures = 2
    runtime = CdpBrowserRuntime(fake_chrome.endpoint, capacity=1)

    await runtime.start()

    assert fake_chrome.version_requests == 3
    assert fake_chrome.version_host == "localhost"
    assert fake_chrome.websocket_host == "localhost"
    assert runtime.snapshot()["ready"] is True
    await runtime.stop()


@pytest.mark.unit
async def test_protocol_error_cleans_a_partially_created_lease(fake_chrome: FakeChrome):
    runtime = await _runtime(fake_chrome)
    fake_chrome.protocol_error_method = "Target.createTarget"

    with pytest.raises(RuntimeError, match="command rejected"):
        await runtime.fetch(
            "https://docs.example.test/rejected",
            user_agent="agent",
            timeout_seconds=2,
        )

    assert fake_chrome.contexts == set()
    assert fake_chrome.targets == {"human-target"}
    assert runtime.snapshot()["cleanup_failures"] == 0
    await runtime.stop()


@pytest.mark.unit
async def test_cancelled_fetch_returns_resources(fake_chrome: FakeChrome):
    fake_chrome.evaluate_delay = 1
    runtime = await _runtime(fake_chrome)
    task = asyncio.create_task(
        runtime.fetch(
            "https://docs.example.test/cancelled",
            user_agent="agent",
            timeout_seconds=2,
        )
    )
    await fake_chrome.wait_for("Runtime.evaluate")
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert fake_chrome.targets == {"human-target"}
    assert fake_chrome.contexts == set()
    assert runtime.snapshot()["active"] == 0
    await runtime.stop()
