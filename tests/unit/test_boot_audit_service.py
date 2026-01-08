from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from docs_mcp_server.service_layer.boot_audit_service import (
    BootAuditService,
    _is_truthy,
    _resolve_boot_audit_timeout,
)


async def _noop_runner(cmd: list[str], timeout: int) -> int:  # pragma: no cover - used in skips
    return 0


@pytest.mark.unit
def test_schedule_skips_when_no_tenants(tmp_path: Path) -> None:
    service = BootAuditService(config_path=tmp_path / "deployment.json", tenant_count=0, runner=_noop_runner)

    task = service.schedule()

    assert task is None
    status = service.get_status()
    assert status.state == "skipped"
    assert status.skip_reason and "No tenants" in status.skip_reason


@pytest.mark.unit
def test_schedule_skips_when_env_opted_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOCS_SKIP_BOOT_AUDIT", "true")
    config_path = tmp_path / "deployment.json"
    config_path.write_text("{}", encoding="utf-8")

    service = BootAuditService(config_path=config_path, tenant_count=1, runner=_noop_runner)

    task = service.schedule()

    assert task is None
    status = service.get_status()
    assert status.state == "skipped"
    assert status.skip_reason and "DOCS_SKIP_BOOT_AUDIT" in status.skip_reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_runs_in_background(tmp_path: Path) -> None:
    config_path = tmp_path / "deployment.json"
    config_path.write_text("{}", encoding="utf-8")
    calls: list[tuple[list[str], int]] = []

    async def runner(cmd: list[str], timeout: int) -> int:
        calls.append((cmd, timeout))
        await asyncio.sleep(0)
        return 0

    service = BootAuditService(config_path=config_path, tenant_count=2, runner=runner)

    task = service.schedule()
    assert task is not None

    await task

    status = service.get_status()
    assert status.state == "succeeded"
    assert status.completed_tenants == 2
    assert status.exit_code == 0
    assert calls and "--config" in calls[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_reports_failure(tmp_path: Path) -> None:
    config_path = tmp_path / "deployment.json"
    config_path.write_text("{}", encoding="utf-8")

    async def failing_runner(cmd: list[str], timeout: int) -> int:
        await asyncio.sleep(0)
        return 3

    service = BootAuditService(config_path=config_path, tenant_count=1, runner=failing_runner)

    task = service.schedule()
    assert task is not None

    await task

    status = service.get_status()
    assert status.state == "failed"
    assert status.exit_code == 3
    assert status.error == "Exit code 3"


@pytest.mark.unit
def test_is_truthy_handles_known_values() -> None:
    assert _is_truthy("true") is True
    assert _is_truthy(" YES ") is True
    assert _is_truthy("0") is False
    assert _is_truthy(None) is False


@pytest.mark.unit
def test_resolve_boot_audit_timeout_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_BOOT_AUDIT_TIMEOUT", "120")
    assert _resolve_boot_audit_timeout(tenant_count=1) == 120


@pytest.mark.unit
def test_resolve_boot_audit_timeout_invalid_env_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_BOOT_AUDIT_TIMEOUT", "oops")
    assert _resolve_boot_audit_timeout(tenant_count=2) == 600


@pytest.mark.unit
def test_schedule_skips_when_config_missing(tmp_path: Path) -> None:
    service = BootAuditService(config_path=tmp_path / "deployment.json", tenant_count=1, runner=_noop_runner)

    task = service.schedule()

    assert task is None
    status = service.get_status()
    assert status.state == "skipped"
    assert status.skip_reason and "missing" in status.skip_reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_reports_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "deployment.json"
    config_path.write_text("{}", encoding="utf-8")

    async def timeout_runner(cmd: list[str], timeout: int) -> int:
        raise asyncio.TimeoutError

    service = BootAuditService(config_path=config_path, tenant_count=1, runner=timeout_runner)

    task = service.schedule()
    assert task is not None

    await task

    status = service.get_status()
    assert status.state == "failed"
    assert status.error and "Timed out" in status.error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_marks_service_cancelled(tmp_path: Path) -> None:
    config_path = tmp_path / "deployment.json"
    config_path.write_text("{}", encoding="utf-8")

    async def slow_runner(cmd: list[str], timeout: int) -> int:
        await asyncio.sleep(0.1)
        return 0

    service = BootAuditService(config_path=config_path, tenant_count=1, runner=slow_runner)
    task = service.schedule()
    assert task is not None

    service.cancel()

    status = service.get_status()
    assert status.state == "cancelled"
