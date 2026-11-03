"""Managed snapshots refresh and replace their searchable corpus."""

import asyncio

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.snapshots import rxjs_api
from docs_mcp_server.tenant import TenantApp


@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapshot_refresh_reindexes_and_retires_old_documents(tmp_path, monkeypatch):
    root = tmp_path / "tenant"
    root.mkdir()
    (root / "old.md").write_text("# Legacy\n\nlegacyonly", encoding="utf-8")
    version = 1

    async def export(path):
        path.mkdir(exist_ok=True)
        (path / "release.md").write_text(f"# Release\n\nversion{version}only", encoding="utf-8")

    monkeypatch.setattr(rxjs_api, "export_snapshot", export)
    app = TenantApp(
        TenantConfig(
            source_type="filesystem",
            codename="example",
            docs_name="Example",
            docs_root_dir=str(root),
            snapshot_source="rxjs_api",
        )
    )
    try:
        assert (await app.scheduler_service.trigger_sync())["success"]
        assert (await app.search("version1only", 10, False)).results
        assert not (await app.search("legacyonly", 10, False)).results
        version = 2
        assert (await app.scheduler_service.trigger_sync())["success"]
        assert (await app.search("version2only", 10, False)).results
        result = (await app.search("version2only", 10, False)).results[0]
        assert "version2only" in (await app.fetch(result.url)).content
        assert all(
            "version1only" not in result.snippet for result in (await app.search("version1only", 10, False)).results
        )
        assert app.scheduler_service.stats["total_syncs"] == 2
    finally:
        await app.shutdown()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapshot_failure_is_reported_without_advancing_success(tmp_path, monkeypatch):
    async def fail(path):
        raise ValueError("upstream unavailable")

    monkeypatch.setattr(rxjs_api, "export_snapshot", fail)
    app = TenantApp(
        TenantConfig(
            source_type="filesystem",
            codename="example",
            docs_name="Example",
            docs_root_dir=str(tmp_path),
            snapshot_source="rxjs_api",
        )
    )
    try:
        result = await app.scheduler_service.trigger_sync()
        assert not result["success"]
        assert app.scheduler_service.stats["last_error"] == "upstream unavailable"
        assert app.scheduler_service.stats["last_sync_at"] is None
        assert app.scheduler_service.stats["errors"] == 1
    finally:
        await app.shutdown()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_initial_refresh_starts_retry_scheduler(tmp_path, monkeypatch):
    async def fail(path):
        raise ValueError("offline")

    monkeypatch.setattr(rxjs_api, "export_snapshot", fail)
    app = TenantApp(
        TenantConfig(
            source_type="filesystem",
            codename="example",
            docs_name="Example",
            docs_root_dir=str(tmp_path),
            snapshot_source="rxjs_api",
            refresh_schedule="0 0 * * *",
        )
    )
    try:
        assert not await app.scheduler_service.initialize()
        assert app.scheduler_service.running
        assert app.scheduler_service.stats["errors"] == 1
        await asyncio.sleep(0)
        assert app.scheduler_service.stats["next_sync_at"] is not None
    finally:
        await app.shutdown()
    assert not app.scheduler_service.running


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_initial_refresh_schedules_next_run_once(tmp_path, monkeypatch):
    exports = []

    async def export(path):
        exports.append(path)
        path.mkdir(exist_ok=True)
        (path / "release.md").write_text("# Release\n\nCurrent version", encoding="utf-8")

    monkeypatch.setattr(rxjs_api, "export_snapshot", export)
    app = TenantApp(
        TenantConfig(
            source_type="filesystem",
            codename="example",
            docs_name="Example",
            docs_root_dir=str(tmp_path),
            snapshot_source="rxjs_api",
            refresh_schedule="0 0 * * *",
        )
    )
    try:
        assert await app.scheduler_service.initialize()
        assert await app.scheduler_service.initialize()
        await asyncio.sleep(0)
        status = await app.scheduler_service.get_status_snapshot()
        assert status["scheduler_initialized"]
        assert status["scheduler_running"]
        assert status["stats"]["next_sync_at"] is not None
        assert len(exports) == 1
    finally:
        await app.shutdown()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_index_failure_is_reported(tmp_path, monkeypatch):
    async def empty(path):
        path.mkdir()

    monkeypatch.setattr(rxjs_api, "export_snapshot", empty)
    app = TenantApp(
        TenantConfig(
            source_type="filesystem",
            codename="example",
            docs_name="Example",
            docs_root_dir=str(tmp_path),
            snapshot_source="rxjs_api",
        )
    )
    try:
        result = await app.scheduler_service.trigger_sync()
        assert not result["success"]
        assert app.scheduler_service.stats["last_sync_at"] is None
    finally:
        await app.shutdown()
