from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime, timedelta
import errno
import json
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

    (tenant_dir / "__search_segments" / "active.db-shm").write_text("runtime shm", encoding="utf-8")
    (tenant_dir / "__search_segments" / "active.db-wal").write_text("runtime wal", encoding="utf-8")

    fourth = sync_tenant_data.build_tenant_source_snapshot(tenant_dir)
    assert fourth["signature"] == third["signature"]
    assert fourth["last_modified_path"] == "__search_segments/active.db"


def test_export_ignore_paths_skips_runtime_only_data() -> None:
    ignored = sync_tenant_data.ignore_export_paths(
        "tenant",
        [
            "__crawl_state",
            ".staging",
            ".staging_abc12345",
            "segment.db-shm",
            "segment.db-wal",
            "segment.db",
            "manifest.json",
            "index.md",
        ],
    )

    assert ignored == {
        "__crawl_state",
        ".staging",
        ".staging_abc12345",
        "segment.db-shm",
        "segment.db-wal",
    }


def test_default_sync_dir_reads_repo_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sync_dir = tmp_path / "downloads"
    (tmp_path / ".env").write_text(f"{sync_tenant_data.SYNC_TENANT_DATA_DIR_ENV}={sync_dir}\n", encoding="utf-8")
    monkeypatch.delenv(sync_tenant_data.SYNC_TENANT_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(sync_tenant_data, "get_script_dir", lambda: tmp_path)

    assert sync_tenant_data.resolve_sync_dir(None) == sync_dir.resolve()


def test_export_and_import_modes_use_dotenv_default_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_dir = tmp_path / "downloads"
    shared_dir.mkdir()
    (tmp_path / ".env").write_text(
        f"{sync_tenant_data.SYNC_TENANT_DATA_DIR_ENV}={shared_dir}\n",
        encoding="utf-8",
    )
    mcp_data_dir = tmp_path / "mcp-data"
    mcp_data_dir.mkdir()
    seen: dict[str, Path] = {}

    monkeypatch.delenv(sync_tenant_data.SYNC_TENANT_DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(sync_tenant_data, "get_script_dir", lambda: tmp_path)
    monkeypatch.setattr(sync_tenant_data, "get_mcp_data_dir", lambda: mcp_data_dir)
    monkeypatch.setattr(sync_tenant_data, "check_7z_installed", lambda: True)
    monkeypatch.setattr(sync_tenant_data, "import_deployment_json", lambda *_args: True)

    def export_success(
        _tenant: str,
        output_dir: Path,
        _mcp_data_dir: Path,
        *_args: object,
        **_kwargs: object,
    ) -> sync_tenant_data.ExportResult:
        seen["export"] = output_dir
        return sync_tenant_data.ExportResult("exported", "dry run")

    def import_success(
        _tenant: str,
        input_dir: Path,
        _mcp_data_dir: Path,
        _dry_run: bool,
        _preserve_local: bool,
    ) -> bool:
        seen["import"] = input_dir
        return True

    monkeypatch.setattr(sync_tenant_data, "export_tenant", export_success)
    monkeypatch.setattr(sync_tenant_data, "export_deployment_json", lambda output_dir, _dry_run: True)
    monkeypatch.setattr(sync_tenant_data, "import_tenant", import_success)

    export_code = sync_tenant_data.export_mode(_export_args(None, tenants=["django"], dry_run=True))
    (shared_dir / "django.7z").write_bytes(b"archive")
    import_code = sync_tenant_data.import_mode(_import_args(None, tenants=["django"], dry_run=True))

    assert export_code == 0
    assert import_code == 0
    assert seen == {"export": shared_dir.resolve(), "import": shared_dir.resolve()}


def test_export_tenant_stages_archive_outside_output_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp_data_dir = tmp_path / "mcp-data"
    tenant_dir = mcp_data_dir / "django"
    tenant_dir.mkdir(parents=True)
    (tenant_dir / "index.md").write_text("# Django\n", encoding="utf-8")
    output_dir = tmp_path / "downloads"

    def create_archive(cmd: list[str], **_kwargs: object) -> Namespace:
        temp_archive = Path(cmd[-2])
        assert temp_archive.parent != output_dir
        temp_archive.write_bytes(b"complete archive")
        return Namespace(returncode=0, stderr="")

    monkeypatch.setattr(sync_tenant_data.subprocess, "run", create_archive)

    result = sync_tenant_data.export_tenant("django", output_dir, mcp_data_dir)

    assert result.status == "exported"
    assert (output_dir / "django.7z").read_bytes() == b"complete archive"
    assert not list(output_dir.glob(".*.7z"))


def test_publish_completed_archive_uses_hidden_tmp_for_cross_device_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.7z"
    source.write_bytes(b"complete archive")
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()
    destination = output_dir / "django.7z"
    path_type = type(source)
    original_replace = path_type.replace

    def replace(self: Path, target: Path) -> Path:
        if self == source:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", replace)

    sync_tenant_data.publish_completed_archive(source, destination)

    assert destination.read_bytes() == b"complete archive"
    assert not list(output_dir.glob("*.tmp"))


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


def test_import_mode_skips_unchanged_manifest_tenant_without_extracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    mcp_data_dir = tmp_path / "mcp-data"
    input_dir.mkdir()
    mcp_data_dir.mkdir()
    manifest = _tenant_manifest("same")
    _write_json(input_dir / "manifest.json", manifest)
    _write_json(mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME, manifest)

    calls: list[str] = []
    monkeypatch.setattr(sync_tenant_data, "check_7z_installed", lambda: True)
    monkeypatch.setattr(sync_tenant_data, "get_mcp_data_dir", lambda: mcp_data_dir)
    monkeypatch.setattr(sync_tenant_data, "import_deployment_json", lambda *_args: True)

    def fail_import(*args: object, **kwargs: object) -> bool:
        calls.append("import_tenant")
        raise AssertionError("unchanged tenant should not be imported")

    monkeypatch.setattr(sync_tenant_data, "import_tenant", fail_import)

    code = sync_tenant_data.import_mode(_import_args(input_dir, dry_run=True))

    assert code == 0
    assert calls == []


def test_import_mode_updates_state_after_successful_changed_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    mcp_data_dir = tmp_path / "mcp-data"
    input_dir.mkdir()
    mcp_data_dir.mkdir()
    (input_dir / "django.7z").write_bytes(b"archive")
    _write_json(input_dir / "manifest.json", _tenant_manifest("new"))
    _write_json(mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME, _tenant_manifest("old"))

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(sync_tenant_data, "check_7z_installed", lambda: True)
    monkeypatch.setattr(sync_tenant_data, "get_mcp_data_dir", lambda: mcp_data_dir)
    monkeypatch.setattr(sync_tenant_data, "import_deployment_json", lambda *_args: True)

    def import_success(
        tenant: str,
        _input_dir: Path,
        _mcp_data_dir: Path,
        dry_run: bool,
        _preserve_local: bool,
    ) -> bool:
        calls.append((tenant, dry_run))
        return True

    monkeypatch.setattr(sync_tenant_data, "import_tenant", import_success)

    code = sync_tenant_data.import_mode(_import_args(input_dir, dry_run=False))

    state = json.loads((mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME).read_text(encoding="utf-8"))
    assert code == 0
    assert calls == [("django", False)]
    assert state["tenants"]["django"]["source_snapshot"]["signature"] == "new"
    assert "imported_at" in state["tenants"]["django"]
    assert "updated_at" in state


def test_import_mode_dry_run_changed_tenant_does_not_update_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    mcp_data_dir = tmp_path / "mcp-data"
    input_dir.mkdir()
    mcp_data_dir.mkdir()
    (input_dir / "django.7z").write_bytes(b"archive")
    _write_json(input_dir / "manifest.json", _tenant_manifest("new"))
    _write_json(mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME, _tenant_manifest("old"))

    monkeypatch.setattr(sync_tenant_data, "check_7z_installed", lambda: True)
    monkeypatch.setattr(sync_tenant_data, "get_mcp_data_dir", lambda: mcp_data_dir)
    monkeypatch.setattr(sync_tenant_data, "import_deployment_json", lambda *_args: True)
    monkeypatch.setattr(sync_tenant_data, "import_tenant", lambda *_args: True)

    code = sync_tenant_data.import_mode(_import_args(input_dir, dry_run=True))

    state = json.loads((mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME).read_text(encoding="utf-8"))
    assert code == 0
    assert state["tenants"]["django"]["source_snapshot"]["signature"] == "old"
    assert "imported_at" not in state["tenants"]["django"]


@pytest.mark.parametrize(
    ("tenants", "force"),
    [(["django"], False), (None, True)],
)
def test_import_mode_explicit_tenants_and_force_bypass_unchanged_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tenants: list[str] | None,
    force: bool,
) -> None:
    input_dir = tmp_path / "input"
    mcp_data_dir = tmp_path / "mcp-data"
    input_dir.mkdir()
    mcp_data_dir.mkdir()
    manifest = _tenant_manifest("same")
    _write_json(input_dir / "manifest.json", manifest)
    _write_json(mcp_data_dir / sync_tenant_data.IMPORT_STATE_NAME, manifest)

    calls: list[str] = []
    monkeypatch.setattr(sync_tenant_data, "check_7z_installed", lambda: True)
    monkeypatch.setattr(sync_tenant_data, "get_mcp_data_dir", lambda: mcp_data_dir)
    monkeypatch.setattr(sync_tenant_data, "import_deployment_json", lambda *_args: True)

    def import_success(tenant: str, *_args: object) -> bool:
        calls.append(tenant)
        return True

    monkeypatch.setattr(sync_tenant_data, "import_tenant", import_success)

    code = sync_tenant_data.import_mode(_import_args(input_dir, tenants=tenants, dry_run=True, force=force))

    assert code == 0
    assert calls == ["django"]


def test_import_deployment_json_skips_unchanged_config_without_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    destination = tmp_path / "deployment.json"
    config = {"tenants": [{"codename": "django"}]}
    _write_json(input_dir / "deployment.json", config)
    _write_json(destination, config)
    monkeypatch.setattr(sync_tenant_data, "get_deployment_json_path", lambda: destination)

    assert sync_tenant_data.import_deployment_json(input_dir, dry_run=True)
    assert sync_tenant_data.import_deployment_json(input_dir, dry_run=False)
    assert list(tmp_path.glob("deployment.json.backup.*")) == []
    assert json.loads(destination.read_text(encoding="utf-8")) == config


def test_import_deployment_json_writes_changed_config_and_preserves_local_only_tenants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    destination = tmp_path / "deployment.json"
    local_config = {"tenants": [{"codename": "django", "url": "old"}, {"codename": "local", "url": "keep"}]}
    remote_config = {"tenants": [{"codename": "django", "url": "new"}, {"codename": "fastapi", "url": "new"}]}
    _write_json(input_dir / "deployment.json", remote_config)
    _write_json(destination, local_config)
    monkeypatch.setattr(sync_tenant_data, "get_deployment_json_path", lambda: destination)

    assert sync_tenant_data.import_deployment_json(input_dir, dry_run=False)

    imported_config = json.loads(destination.read_text(encoding="utf-8"))
    assert imported_config == {
        "tenants": [
            {"codename": "django", "url": "new"},
            {"codename": "fastapi", "url": "new"},
            {"codename": "local", "url": "keep"},
        ]
    }
    assert len(list(tmp_path.glob("deployment.json.backup.*"))) == 1


def _tenant_manifest(signature: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "tenants": {
            "django": {
                "archive": "django.7z",
                "archive_size": 10,
                "source_snapshot": {"signature": signature},
                "tenant": "django",
            }
        },
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _import_args(
    input_dir: Path | None,
    *,
    tenants: list[str] | None = None,
    dry_run: bool,
    force: bool = False,
) -> Namespace:
    return Namespace(
        input=str(input_dir) if input_dir is not None else None,
        tenants=tenants,
        dry_run=dry_run,
        no_preserve_local=False,
        force=force,
    )


def _export_args(
    output_dir: Path | None,
    *,
    tenants: list[str] | None = None,
    dry_run: bool,
    force: bool = False,
) -> Namespace:
    return Namespace(
        output=str(output_dir) if output_dir is not None else None,
        tenants=tenants,
        dry_run=dry_run,
        force=force,
    )


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
