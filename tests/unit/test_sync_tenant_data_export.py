from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

import pytest

import sync_tenant_data


pytestmark = pytest.mark.unit


def test_source_snapshot_ignores_runtime_crawl_state(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "mcp-data" / "django"
    (tenant_dir / "docs").mkdir(parents=True)
    (tenant_dir / "docs" / "index.md").write_text("# Django\n", encoding="utf-8")

    first = sync_tenant_data.build_tenant_source_snapshot(tenant_dir)

    crawl_state_dir = tenant_dir / "__crawl_state"
    crawl_state_dir.mkdir()
    (crawl_state_dir / "crawl.sqlite").write_text("runtime-only", encoding="utf-8")

    second = sync_tenant_data.build_tenant_source_snapshot(tenant_dir)
    assert second["signature"] == first["signature"]

    (tenant_dir / "__search_segments").mkdir()
    (tenant_dir / "__search_segments" / "active.db").write_text("index", encoding="utf-8")

    third = sync_tenant_data.build_tenant_source_snapshot(tenant_dir)
    assert third["signature"] != first["signature"]
    assert third["last_modified_path"] == "__search_segments/active.db"


def test_export_tenant_skips_unchanged_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mcp_data_dir = tmp_path / "mcp-data"
    tenant_dir = mcp_data_dir / "django"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "index.md").write_text("# Django\n", encoding="utf-8")

    output_dir = tmp_path / "export"
    output_dir.mkdir()
    archive_path = output_dir / "django.7z"
    archive_path.write_bytes(b"existing archive")

    snapshot = sync_tenant_data.build_tenant_source_snapshot(tenant_dir)
    manifest = {
        "schema_version": 1,
        "tenants": {
            "django": {
                "archive": "django.7z",
                "archive_size": archive_path.stat().st_size,
                "source_snapshot": snapshot,
            }
        },
    }

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("7z should not run for unchanged tenant export")

    monkeypatch.setattr(sync_tenant_data.subprocess, "run", fail_if_called)

    result = sync_tenant_data.export_tenant(
        "django",
        output_dir,
        mcp_data_dir,
        manifest=manifest,
        skip_unchanged=True,
    )

    assert result.status == "skipped"
    assert result.reason == "unchanged"


def test_export_tenant_skips_active_crawler_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mcp_data_dir = tmp_path / "mcp-data"
    tenant_dir = mcp_data_dir / "django"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "index.md").write_text("# Django\n", encoding="utf-8")
    _write_crawler_lock(tenant_dir, expires_at=datetime.now(UTC) + timedelta(minutes=10))

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("7z should not run while crawler lock is active")

    monkeypatch.setattr(sync_tenant_data.subprocess, "run", fail_if_called)

    result = sync_tenant_data.export_tenant("django", tmp_path / "export", mcp_data_dir)

    assert result.status == "skipped"
    assert result.reason is not None
    assert "crawler lock held by worker-1" in result.reason


def test_active_crawler_reason_ignores_expired_lock(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "mcp-data" / "django"
    tenant_dir.mkdir(parents=True)
    _write_crawler_lock(tenant_dir, expires_at=datetime.now(UTC) - timedelta(minutes=1))

    assert sync_tenant_data.active_crawler_reason(tenant_dir) is None


def _write_crawler_lock(tenant_dir: Path, *, expires_at: datetime) -> None:
    db_dir = tenant_dir / "__crawl_state"
    db_dir.mkdir()
    with sqlite3.connect(db_dir / "crawl.sqlite") as conn:
        conn.execute(
            """
            CREATE TABLE crawl_locks (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO crawl_locks (name, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
            ("crawler", "worker-1", now, expires_at.isoformat()),
        )
