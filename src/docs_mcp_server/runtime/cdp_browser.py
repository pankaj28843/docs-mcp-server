"""Process-wide rendered-page runtime over Chrome DevTools Protocol."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import aiohttp


logger = logging.getLogger(__name__)

_DISCOVERY_ATTEMPTS = 5
_DISCOVERY_RETRY_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """Final rendered DOM and main-document HTTP status."""

    html: str
    status_code: int


class BrowserRuntimeProtocol(Protocol):
    """Small boundary consumed by fetch and discovery policy."""

    async def fetch(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None = None,
        timeout_seconds: float,
    ) -> RenderedPage: ...


class CdpProtocolError(RuntimeError):
    """Chrome rejected a CDP command."""


@dataclass(slots=True)
class _PendingCommand:
    generation: int
    future: asyncio.Future[dict[str, Any]]


class CdpBrowserRuntime:
    """Borrow one persistent Chrome while owning only per-fetch resources."""

    def __init__(self, endpoint: str, capacity: int) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._endpoint_label = self._sanitize_endpoint(endpoint)
        self._capacity = capacity
        self._semaphore = asyncio.Semaphore(capacity)
        self._state = "stopped"
        self._state_condition = asyncio.Condition()
        self._connection_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._http: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._generation = 0
        self._next_command_id = 0
        self._pending: dict[int, _PendingCommand] = {}
        self._events: dict[tuple[int, str], asyncio.Queue[dict[str, Any]]] = {}
        self._owned_contexts: set[tuple[int, str]] = set()
        self._owned_targets: set[tuple[int, str]] = set()
        self._active = 0
        self._acquired = 0
        self._released = 0
        self._cleanup_failures = 0
        self._reconnects = 0
        self._last_failure: str | None = None

    async def start(self) -> None:
        """Connect to the externally owned browser and validate its protocol."""
        async with self._state_condition:
            if self._state == "ready":
                return
            self._state = "starting"
        if self._http is None:
            timeout = aiohttp.ClientTimeout(total=10, connect=5, sock_connect=5)
            self._http = aiohttp.ClientSession(timeout=timeout)
        try:
            await self._ensure_connection()
        except Exception as exc:
            self._record_failure(exc)
            await self._close_connection()
            if self._http is not None:
                await self._http.close()
                self._http = None
            async with self._state_condition:
                self._state = "disconnected"
            raise
        async with self._state_condition:
            self._state = "ready"

    async def drain(self, timeout_seconds: float) -> bool:
        """Reject new leases and wait for existing leases to finish."""
        async with self._state_condition:
            self._state = "draining"

            async def _wait_for_zero() -> None:
                while self._active:
                    await self._state_condition.wait()

            try:
                async with asyncio.timeout(timeout_seconds):
                    await _wait_for_zero()
            except TimeoutError:
                return False
        return True

    async def stop(self) -> None:
        """Disconnect without closing the borrowed browser process."""
        async with self._state_condition:
            self._state = "draining"
        await self._close_connection()
        if self._http is not None:
            await self._http.close()
            self._http = None
        async with self._state_condition:
            self._state = "stopped"

    async def fetch(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None = None,
        timeout_seconds: float,
    ) -> RenderedPage:
        """Render one URL in an isolated disposable browser context."""
        await self._acquire()
        try:
            async with asyncio.timeout(timeout_seconds):
                generation = await self._ensure_connection()
                return await self._render(
                    generation,
                    url,
                    user_agent=user_agent,
                    proxy=proxy,
                    timeout_seconds=timeout_seconds,
                )
        except Exception as exc:
            self._record_failure(exc)
            raise
        finally:
            await self._release()

    def snapshot(self) -> dict[str, Any]:
        """Return secret-safe lifecycle and capacity telemetry."""
        return {
            "mode": "native_cdp",
            "endpoint": self._endpoint_label,
            "state": self._state,
            "ready": self._state == "ready" and self._connection_usable(),
            "active": self._active,
            "capacity": self._capacity,
            "acquired": self._acquired,
            "released": self._released,
            "cleanup_failures": self._cleanup_failures,
            "reconnects": self._reconnects,
            "owned_contexts": len(self._owned_contexts),
            "owned_targets": len(self._owned_targets),
            "last_failure": self._last_failure,
        }

    async def _acquire(self) -> None:
        async with self._state_condition:
            if self._state not in {"ready", "disconnected"}:
                raise RuntimeError(f"Browser runtime does not accept leases while {self._state}")
        await self._semaphore.acquire()
        async with self._state_condition:
            if self._state not in {"ready", "disconnected"}:
                self._semaphore.release()
                raise RuntimeError(f"Browser runtime does not accept leases while {self._state}")
            self._active += 1
            self._acquired += 1

    async def _release(self) -> None:
        async with self._state_condition:
            self._active -= 1
            self._released += 1
            self._semaphore.release()
            self._state_condition.notify_all()

    async def _ensure_connection(self) -> int:
        async with self._connection_lock:
            if self._connection_usable():
                return self._generation
            if self._http is None:
                raise RuntimeError("Browser runtime has not been started")

            if self._generation:
                self._reconnects += 1
            await self._close_connection()
            websocket_url = await self._discover_with_retry()
            websocket = await self._http.ws_connect(
                websocket_url,
                headers={"Host": "localhost"},
                max_msg_size=16 * 1024 * 1024,
            )
            self._generation += 1
            generation = self._generation
            self._websocket = websocket
            self._reader_task = asyncio.create_task(
                self._read_messages(websocket, generation),
                name=f"cdp-browser-reader-{generation}",
            )
            try:
                await self._probe_protocol(generation)
            except BaseException:
                await self._close_connection()
                raise
            if self._state == "disconnected":
                self._state = "ready"
            return generation

    def _connection_usable(self) -> bool:
        return bool(
            self._websocket is not None
            and not self._websocket.closed
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    async def _discover(self) -> str:
        assert self._http is not None
        async with self._http.get(
            f"{self._endpoint}/json/version",
            headers={"Host": "localhost"},
        ) as response:
            response.raise_for_status()
            version = await response.json()
        if version.get("Protocol-Version") != "1.3":
            raise RuntimeError(f"Browser CDP protocol version is not supported: {version.get('Protocol-Version')!r}")
        advertised = urlsplit(version["webSocketDebuggerUrl"])
        configured = urlsplit(self._endpoint)
        scheme = "wss" if configured.scheme == "https" else "ws"
        return urlunsplit((scheme, configured.netloc, advertised.path, advertised.query, ""))

    async def _discover_with_retry(self) -> str:
        for attempt in range(1, _DISCOVERY_ATTEMPTS + 1):
            try:
                return await self._discover()
            except (aiohttp.ClientError, TimeoutError):
                if attempt == _DISCOVERY_ATTEMPTS:
                    raise
                await asyncio.sleep(_DISCOVERY_RETRY_SECONDS)
        raise AssertionError("unreachable")

    async def _probe_protocol(self, generation: int) -> None:
        """Fail startup unless every command used by rendered fetches succeeds."""
        async with self._page_lease(
            generation,
            user_agent="docs-mcp-server-cdp-probe",
            proxy=None,
        ) as session_id:
            await self._call(
                generation,
                "Page.navigate",
                {"url": "about:blank"},
                session_id=session_id,
            )
            await self._call(
                generation,
                "Runtime.evaluate",
                {"expression": "1", "returnByValue": True},
                session_id=session_id,
            )

    async def _read_messages(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        generation: int,
    ) -> None:
        failure: Exception = ConnectionError("Browser CDP websocket disconnected")
        try:
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(message.data)
                    command_id = payload.get("id")
                    if isinstance(command_id, int):
                        pending = self._pending.pop(command_id, None)
                        if pending and pending.generation == generation and not pending.future.done():
                            pending.future.set_result(payload)
                        continue
                    session_id = payload.get("sessionId")
                    params = payload.get("params", {})
                    if (
                        isinstance(session_id, str)
                        and payload.get("method") == "Network.responseReceived"
                        and params.get("type") == "Document"
                    ):
                        queue = self._events.get((generation, session_id))
                        if queue is not None:
                            queue.put_nowait(payload)
                elif message.type == aiohttp.WSMsgType.ERROR:
                    failure = websocket.exception() or failure
                    break
        except Exception as exc:  # pragma: no cover - aiohttp transport boundary
            failure = exc
        finally:
            intentional_close = self._state in {"draining", "stopped"}
            if not intentional_close:
                self._record_failure(failure)
            for command_id, pending in list(self._pending.items()):
                if pending.generation != generation:
                    continue
                self._pending.pop(command_id, None)
                if not pending.future.done():
                    pending.future.set_exception(failure)
            if self._generation == generation and self._websocket is websocket:
                self._websocket = None
                if not intentional_close and self._state == "ready":
                    self._state = "disconnected"

    async def _call(
        self,
        generation: int,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._write_lock:
            if generation != self._generation or not self._connection_usable():
                raise ConnectionError("Browser CDP connection generation changed")
            assert self._websocket is not None
            self._next_command_id += 1
            command_id = self._next_command_id
            payload: dict[str, Any] = {
                "id": command_id,
                "method": method,
                "params": dict(params or {}),
            }
            if session_id is not None:
                payload["sessionId"] = session_id
            future = asyncio.get_running_loop().create_future()
            self._pending[command_id] = _PendingCommand(generation, future)
            try:
                await self._websocket.send_json(payload)
            except Exception:
                self._pending.pop(command_id, None)
                raise
        try:
            response = await future
        except BaseException:
            self._pending.pop(command_id, None)
            raise
        if error := response.get("error"):
            raise CdpProtocolError(f"{method} failed: {error.get('message', 'CDP error')}")
        return response.get("result", {})

    async def _render(
        self,
        generation: int,
        url: str,
        *,
        user_agent: str,
        proxy: str | None,
        timeout_seconds: float,
    ) -> RenderedPage:
        session_id: str | None = None
        try:
            async with self._page_lease(
                generation,
                user_agent=user_agent,
                proxy=proxy,
            ) as session_id:
                events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
                self._events[(generation, session_id)] = events
                navigation = await self._call(
                    generation,
                    "Page.navigate",
                    {"url": url},
                    session_id=session_id,
                )
                if error_text := navigation.get("errorText"):
                    raise RuntimeError(f"Browser navigation failed: {error_text}")
                return await self._wait_for_document(
                    generation,
                    session_id,
                    events,
                    frame_id=navigation.get("frameId"),
                    loader_id=navigation.get("loaderId"),
                    timeout_seconds=timeout_seconds,
                )
        finally:
            if session_id is not None:
                self._events.pop((generation, session_id), None)

    @asynccontextmanager
    async def _page_lease(
        self,
        generation: int,
        *,
        user_agent: str,
        proxy: str | None,
    ) -> AsyncIterator[str]:
        context_id: str | None = None
        target_id: str | None = None
        primary_error: BaseException | None = None
        try:
            context_params: dict[str, Any] = {"disposeOnDetach": True}
            if proxy:
                context_params["proxyServer"] = proxy
            context = await self._call(generation, "Target.createBrowserContext", context_params)
            context_id = context["browserContextId"]
            self._owned_contexts.add((generation, context_id))
            target = await self._call(
                generation,
                "Target.createTarget",
                {
                    "url": "about:blank",
                    "browserContextId": context_id,
                    "background": True,
                    "focus": False,
                },
            )
            target_id = target["targetId"]
            self._owned_targets.add((generation, target_id))
            attached = await self._call(
                generation,
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
            )
            session_id = attached["sessionId"]
            await self._call(generation, "Network.enable", session_id=session_id)
            await self._call(generation, "Page.enable", session_id=session_id)
            await self._call(
                generation,
                "Emulation.setUserAgentOverride",
                {"userAgent": user_agent},
                session_id=session_id,
            )
            yield session_id
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                await self._cleanup_lease(generation, target_id, context_id)
            except Exception as cleanup_error:
                self._cleanup_failures += 1
                logger.error("CDP lease cleanup failed: %s", cleanup_error)
                if primary_error is None:
                    raise

    async def _wait_for_document(
        self,
        generation: int,
        session_id: str,
        events: asyncio.Queue[dict[str, Any]],
        *,
        frame_id: str | None,
        loader_id: str | None,
        timeout_seconds: float,
    ) -> RenderedPage:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        status_code: int | None = None
        previous_html: str | None = None
        stable_checks = 0

        while True:
            while not events.empty():
                event = events.get_nowait()
                params = event.get("params", {})
                if frame_id and params.get("frameId") != frame_id:
                    continue
                if loader_id and params.get("loaderId") != loader_id:
                    continue
                status_code = int(params["response"]["status"])

            evaluated = await self._call(
                generation,
                "Runtime.evaluate",
                {
                    "expression": (
                        "({readyState: document.readyState, "
                        "html: document.documentElement ? document.documentElement.outerHTML : ''})"
                    ),
                    "returnByValue": True,
                },
                session_id=session_id,
            )
            value = evaluated.get("result", {}).get("value", {})
            html = value.get("html", "")
            ready = value.get("readyState") in {"interactive", "complete"}
            stable_checks = stable_checks + 1 if html == previous_html else 0
            previous_html = html
            if ready and status_code is not None and stable_checks >= 1:
                return RenderedPage(html=html, status_code=status_code)

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Rendered document did not stabilize before timeout")
            try:
                event = await asyncio.wait_for(events.get(), timeout=min(0.25, remaining))
            except TimeoutError:
                continue
            events.put_nowait(event)

    async def _cleanup_lease(
        self,
        generation: int,
        target_id: str | None,
        context_id: str | None,
    ) -> None:
        same_connection = generation == self._generation and self._connection_usable()
        try:
            if target_id is not None and same_connection:
                await self._call(generation, "Target.closeTarget", {"targetId": target_id})
            if context_id is not None and same_connection:
                await self._call(
                    generation,
                    "Target.disposeBrowserContext",
                    {"browserContextId": context_id},
                )
        finally:
            if target_id is not None:
                self._owned_targets.discard((generation, target_id))
            if context_id is not None:
                self._owned_contexts.discard((generation, context_id))

    async def _close_connection(self) -> None:
        websocket = self._websocket
        reader = self._reader_task
        self._websocket = None
        self._reader_task = None
        if websocket is not None and not websocket.closed:
            await websocket.close()
        if reader is not None and reader is not asyncio.current_task():
            try:
                await reader
            except asyncio.CancelledError:
                pass

    def _record_failure(self, exc: BaseException) -> None:
        self._last_failure = exc.__class__.__name__

    @staticmethod
    def _sanitize_endpoint(endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname or "invalid"
        if ":" in hostname:
            hostname = f"[{hostname}]"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{hostname}{port}"
