from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from docs_mcp_server.service_layer.boot_audit_service import (
    BootAuditService,
    _is_truthy,
    _log_subprocess_stream,
    _resolve_boot_audit_timeout,
    _run_index_audit_subprocess,
)


@pytest.mark.unit
def test_resolve_boot_audit_timeout_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_BOOT_AUDIT_TIMEOUT", "45")

    assert _resolve_boot_audit_timeout(1) == 45


@pytest.mark.unit
def test_is_truthy_accepts_falsey_values() -> None:
    assert _is_truthy("nope") is False


@pytest.mark.unit
def test_log_subprocess_stream_logs_lines(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    _log_subprocess_stream(b"line1\nline2", prefix="[index_audit]", level=logging.INFO)

    assert "[index_audit] line1" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_index_audit_subprocess_logs_output(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FakeProc:
        def __init__(self) -> None:
            self.returncode = 0
            self.wait_calls = 0

        async def communicate(self):
            return (b"ok", b"")

        async def wait(self):
            self.wait_calls += 1
            return self.returncode

        def kill(self):
            return None

    proc = FakeProc()

    async def fake_create(*args, **kwargs):
        return proc

    async def fake_wait_for(awaitable, timeout: int):
        return await awaitable

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    caplog.set_level(logging.INFO)
    exit_code = await _run_index_audit_subprocess(["echo", "ok"], timeout=1)

    assert exit_code == 0
    assert "[index_audit] ok" in caplog.text
    assert proc.wait_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_index_audit_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProc:
        def __init__(self) -> None:
            self.returncode = 1
            self.killed = False
            self.wait_calls = 0

        async def communicate(self):
            return (b"", b"")

        async def wait(self):
            self.wait_calls += 1
            return self.returncode

        def kill(self):
            self.killed = True

    proc = FakeProc()

    async def fake_create(*args, **kwargs):
        return proc

    async def fake_wait_for(awaitable, timeout: int):
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(asyncio.TimeoutError):
        await _run_index_audit_subprocess(["echo", "ok"], timeout=1)
    assert proc.wait_calls == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_index_audit_subprocess_reaps_process_when_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProc:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.communicate_calls = 0
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0

        async def communicate(self):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise asyncio.CancelledError
            self.returncode = -15
            return (b"", b"")

        async def wait(self):
            self.wait_calls += 1
            return self.returncode

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

    proc = FakeProc()

    async def fake_create(*args, **kwargs):
        return proc

    async def fake_wait_for(awaitable, timeout: int):
        del timeout
        return await awaitable

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(asyncio.CancelledError):
        await _run_index_audit_subprocess(["echo", "ok"], timeout=1)

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 0
    assert proc.communicate_calls == 2
    assert proc.wait_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_schedule_returns_existing_task(tmp_path: Path) -> None:
    service = BootAuditService(config_path=tmp_path / "config.json", tenant_count=1)
    task = asyncio.create_task(asyncio.sleep(0))
    service._task = task

    assert service.schedule() is task


@pytest.mark.unit
def test_cancel_noops_when_done(tmp_path: Path) -> None:
    service = BootAuditService(config_path=tmp_path / "config.json", tenant_count=1)
    service._task = None

    service.cancel()

    assert service.status.state == "pending"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_running_reflects_task(tmp_path: Path) -> None:
    service = BootAuditService(config_path=tmp_path / "config.json", tenant_count=1)
    service._task = asyncio.create_task(asyncio.sleep(0))

    assert service.is_running() is True
