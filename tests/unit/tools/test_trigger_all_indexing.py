"""Unit tests for trigger_all_indexing CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3

import pytest

import trigger_all_indexing


@pytest.fixture
def base_infra() -> dict[str, object]:
    return {}


def test_main_indexes_all_tenants(tmp_path: Path, base_infra: dict[str, object]) -> None:
    first_root = tmp_path / "first"
    _write_markdown_doc(first_root, "docs/start.md")

    second_root = tmp_path / "second"
    _write_markdown_doc(second_root, "docs/another.md")

    config_path = _write_config(
        tmp_path,
        base_infra,
        tenants=[
            _tenant_cfg("first", first_root),
            _tenant_cfg("second", second_root),
        ],
    )

    exit_code = trigger_all_indexing.main(["--config", str(config_path)])
    assert exit_code == 0

    first_segments = first_root / "__search_segments"
    second_segments = second_root / "__search_segments"
    assert first_segments.exists()
    assert second_segments.exists()

    # Check for SQLite files
    first_db_files = list(first_segments.glob("*.db"))
    second_db_files = list(second_segments.glob("*.db"))
    assert len(first_db_files) > 0
    assert len(second_db_files) > 0


def test_main_respects_tenant_filter(tmp_path: Path, base_infra: dict[str, object]) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_markdown_doc(first_root, "docs/one.md")
    _write_markdown_doc(second_root, "docs/two.md")

    config_path = _write_config(
        tmp_path,
        base_infra,
        tenants=[
            _tenant_cfg("first", first_root),
            _tenant_cfg("second", second_root),
        ],
    )

    exit_code = trigger_all_indexing.main(["--config", str(config_path), "--tenants", "second"])
    assert exit_code == 0

    first_segments = first_root / "__search_segments"
    second_segments = second_root / "__search_segments"

    # Only second should be indexed
    assert second_segments.exists()
    second_db_files = list(second_segments.glob("*.db"))
    assert len(second_db_files) > 0

    # First should not exist or be empty
    if first_segments.exists():
        first_db_files = list(first_segments.glob("*.db"))
        assert len(first_db_files) == 0


def test_main_dry_run_skips_persist(tmp_path: Path, base_infra: dict[str, object]) -> None:
    docs_root = tmp_path / "docs"
    _write_markdown_doc(docs_root, "content/page.md")

    config_path = _write_config(
        tmp_path,
        base_infra,
        tenants=[_tenant_cfg("docs", docs_root)],
    )

    exit_code = trigger_all_indexing.main(["--config", str(config_path), "--dry-run"])
    assert exit_code == 0

    segments_dir = docs_root / "__search_segments"
    if segments_dir.exists():
        db_files = list(segments_dir.glob("*.db"))
        assert len(db_files) == 0


def test_main_indexes_plain_markdown(tmp_path: Path, base_infra: dict[str, object]) -> None:
    docs_root = tmp_path / "docs"
    markdown_path = docs_root / "handbook" / "plain.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("# Title\n\nBody", encoding="utf-8")

    config_path = _write_config(
        tmp_path,
        base_infra,
        tenants=[_tenant_cfg("docs", docs_root)],
    )

    exit_code = trigger_all_indexing.main(["--config", str(config_path)])
    assert exit_code == 0

    manifest = docs_root / "__search_segments" / "manifest.json"
    assert manifest.exists()


def test_main_prunes_stale_segments_when_no_new_segment(tmp_path: Path, base_infra: dict[str, object]) -> None:
    docs_root = tmp_path / "docs"
    relative_path = "content/page.md"
    _write_markdown_doc(docs_root, relative_path)

    config_path = _write_config(
        tmp_path,
        base_infra,
        tenants=[_tenant_cfg("docs", docs_root)],
    )

    exit_code = trigger_all_indexing.main(["--config", str(config_path)])
    assert exit_code == 0

    segments_dir = docs_root / "__search_segments"
    manifest = json.loads((segments_dir / "manifest.json").read_text(encoding="utf-8"))
    latest_id = manifest["latest_segment_id"]

    stale_db = segments_dir / "stale.db"
    stale_db.write_text("fake db", encoding="utf-8")
    stale_wal = segments_dir / "stale.db-wal"
    stale_shm = segments_dir / "stale.db-shm"
    stale_wal.write_text("wal", encoding="utf-8")
    stale_shm.write_text("shm", encoding="utf-8")
    stale_ts = 946684800  # 2000-01-01T00:00:00Z
    os.utime(stale_db, (stale_ts, stale_ts))
    os.utime(stale_wal, (stale_ts, stale_ts))
    os.utime(stale_shm, (stale_ts, stale_ts))

    markdown_path = docs_root / relative_path
    metadata_path = docs_root / "__docs_metadata" / (Path(relative_path).with_suffix(".meta.json"))
    old_ts = 946684800  # 2000-01-01T00:00:00Z
    os.utime(markdown_path, (old_ts, old_ts))
    os.utime(metadata_path, (old_ts, old_ts))

    exit_code = trigger_all_indexing.main(["--config", str(config_path), "--changed-only"])
    assert exit_code == 0

    assert not stale_db.exists()
    assert not (segments_dir / "stale.db-wal").exists()
    assert not (segments_dir / "stale.db-shm").exists()
    assert (segments_dir / f"{latest_id}.db").exists()


def test_schema_honors_analyzer_profile(tmp_path: Path, base_infra: dict[str, object]) -> None:
    docs_root = tmp_path / "docs"
    _write_markdown_doc(docs_root, "content/custom.md")

    tenant = _tenant_cfg("docs", docs_root)
    tenant["search"] = {
        "enabled": True,
        "engine": "bm25",
        "analyzer_profile": "code-friendly",
    }

    config_path = _write_config(tmp_path, base_infra, tenants=[tenant])

    exit_code = trigger_all_indexing.main(["--config", str(config_path)])
    assert exit_code == 0

    manifest = docs_root / "__search_segments" / "manifest.json"
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    latest_id = manifest_data["latest_segment_id"]

    # Read from SQLite database instead of JSON file
    segment_db_path = docs_root / "__search_segments" / f"{latest_id}.db"
    assert segment_db_path.exists(), f"Expected SQLite segment file at {segment_db_path}"

    # Connect to SQLite and read schema
    conn = sqlite3.connect(segment_db_path)
    cursor = conn.execute("SELECT value FROM metadata WHERE key = 'schema'")
    schema_row = cursor.fetchone()
    conn.close()

    assert schema_row, "No schema found in metadata table"
    schema_data = json.loads(schema_row[0])

    analyzer_names = {
        field["name"]: field.get("analyzer_name") for field in schema_data["fields"] if field["type"] == "text"
    }
    assert analyzer_names  # ensure text fields exist
    assert all(value == "code-friendly" for value in analyzer_names.values())


# --- helpers --------------------------------------------------------------


def _write_markdown_doc(root: Path, relative_path: str) -> None:
    markdown_path = root / relative_path
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        "-----\n"
        "title: Example\n"
        f"url: https://example.com/{relative_path.replace('.md', '')}\n"
        "-----\n"
        "# Heading\n\nBody text.\n",
        encoding="utf-8",
    )

    metadata_path = root / "__docs_metadata" / (Path(relative_path).with_suffix(".meta.json"))
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": f"https://example.com/{relative_path.replace('.md', '')}",
        "title": "Example",
        "metadata": {
            "markdown_rel_path": relative_path,
            "last_fetched_at": "2025-01-01T00:00:00+00:00",
        },
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tenant_cfg(codename: str, docs_root: Path) -> dict[str, object]:
    return {
        "source_type": "filesystem",
        "codename": codename,
        "docs_name": f"Docs {codename}",
        "docs_root_dir": str(docs_root),
        "docs_sitemap_url": "https://example.com/sitemap.xml",
        "url_whitelist_prefixes": "https://example.com/",
    }


def _write_config(tmp_path: Path, infra: dict[str, object], *, tenants: list[dict[str, object]]) -> Path:
    payload = {
        "infrastructure": infra,
        "tenants": tenants,
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
