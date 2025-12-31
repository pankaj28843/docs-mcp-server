from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

import cleanup_segments as cli


pytestmark = pytest.mark.unit


def _make_segments_dir(tmp_path: Path, name: str = "tenant") -> Path:
    segments_dir = tmp_path / name / cli.SEGMENTS_SUBDIR_DEFAULT
    segments_dir.mkdir(parents=True)
    manifest = {
        "latest_segment_id": "active",
        "segments": [
            {
                "segment_id": "active",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ],
        "updated_at": "2024-01-01T00:00:00+00:00",
    }
    (segments_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (segments_dir / "active.json").write_text("{}", encoding="utf-8")
    return segments_dir


def _backdate(path: Path, *, year: int = 2023) -> None:
    ts = datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(path, (ts, ts))


def test_cleanup_removes_orphan_segments(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path)
    orphan = segments_dir / "stale.json"
    orphan.write_text("{}", encoding="utf-8")
    _backdate(orphan)

    summary, reports = cli.cleanup_directories([segments_dir])

    assert not orphan.exists()
    assert summary.files_removed == 1
    assert summary.cleaned == 1
    assert reports[0].cleaned is True


def test_cleanup_respects_dry_run(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path, name="dryrun")
    orphan = segments_dir / "stale.json"
    orphan.write_text("{}", encoding="utf-8")
    _backdate(orphan)

    summary, reports = cli.cleanup_directories([segments_dir], dry_run=True)

    assert orphan.exists(), "dry run should not delete files"
    assert summary.files_removed == 1
    assert reports[0].cleaned is True


def test_collect_tenant_targets_combines_sources(tmp_path: Path) -> None:
    root_dir = tmp_path / "mcp-data"
    tenant_dir = root_dir / "django"
    segments_dir = tenant_dir / cli.SEGMENTS_SUBDIR_DEFAULT
    segments_dir.mkdir(parents=True)
    (segments_dir / "manifest.json").write_text("{}", encoding="utf-8")

    external_docs = tmp_path / "external" / "docs"
    external_segments = external_docs / cli.SEGMENTS_SUBDIR_DEFAULT
    external_segments.mkdir(parents=True)
    (external_segments / "manifest.json").write_text("{}", encoding="utf-8")

    config_path = tmp_path / "deployment.json"
    config_path.write_text(
        json.dumps(
            {
                "tenants": [
                    {"codename": "django"},
                    {"codename": "external", "docs_root_dir": str(external_docs)},
                ]
            }
        ),
        encoding="utf-8",
    )

    targets = cli.collect_tenant_targets(root=root_dir, config_path=config_path)

    segment_dirs = {target.segments_dir.resolve() for target in targets}
    assert segment_dirs == {segments_dir.resolve(), external_segments.resolve()}
    metadata_dirs = {target.metadata_dir.resolve() for target in targets}
    assert metadata_dirs == {
        (segments_dir.parent / cli.SYNC_METADATA_SUBDIR_DEFAULT).resolve(),
        (external_segments.parent / cli.SYNC_METADATA_SUBDIR_DEFAULT).resolve(),
    }


def test_cleanup_skips_missing_manifest(tmp_path: Path) -> None:
    segments_dir = tmp_path / "missing" / cli.SEGMENTS_SUBDIR_DEFAULT
    segments_dir.mkdir(parents=True)

    summary, reports = cli.cleanup_directories([segments_dir])

    assert summary.cleaned == 0
    assert reports[0].skipped_reason == "manifest missing"


def test_cleanup_reports_manifest_errors(tmp_path: Path) -> None:
    segments_dir = tmp_path / "broken" / cli.SEGMENTS_SUBDIR_DEFAULT
    segments_dir.mkdir(parents=True)
    (segments_dir / "manifest.json").write_text("not json", encoding="utf-8")

    summary, reports = cli.cleanup_directories([segments_dir])

    assert summary.errors, "invalid manifest should be reported"
    assert reports[0].errors


def test_cleanup_removes_all_unreferenced_segments(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path, name="multi")
    stale_one = segments_dir / "stale-1.json"
    stale_one.write_text("{}", encoding="utf-8")
    _backdate(stale_one)
    stale_two = segments_dir / "stale-2.json"
    stale_two.write_text("{}", encoding="utf-8")
    _backdate(stale_two, year=2022)

    summary, _ = cli.cleanup_directories([segments_dir])

    assert summary.files_removed == 2
    assert not stale_one.exists()
    assert not stale_two.exists()


def test_cleanup_skips_recent_unreferenced_segments(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path, name="recent")
    orphan = segments_dir / "fresh.json"
    orphan.write_text("{}", encoding="utf-8")

    manifest_path = segments_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["updated_at"] = "2024-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fresh_ts = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc).timestamp()
    os.utime(orphan, (fresh_ts, fresh_ts))

    summary, _ = cli.cleanup_directories([segments_dir])

    assert orphan.exists(), "recent orphan should be preserved until manifest catches up"
    assert summary.cleaned == 0


def test_cleanup_respects_manifest_file_list(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path, name="sharded")
    shard_path = segments_dir / "shard-1.json"
    (segments_dir / "active.json").replace(shard_path)

    manifest_path = segments_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["segments"][0]["files"] = [shard_path.name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    summary, _ = cli.cleanup_directories([segments_dir])

    assert shard_path.exists(), "manifest-listed shards must be preserved"
    assert summary.cleaned == 0


def _make_metadata_dir(tmp_path: Path, name: str = "tenant") -> Path:
    metadata_dir = tmp_path / name / cli.SYNC_METADATA_SUBDIR_DEFAULT
    metadata_dir.mkdir(parents=True)
    return metadata_dir


def _make_docs_metadata_dir(tmp_path: Path, name: str = "tenant") -> Path:
    docs_meta_dir = tmp_path / name / cli.DOCS_METADATA_SUBDIR_DEFAULT
    docs_meta_dir.mkdir(parents=True)
    return docs_meta_dir


def _write_metadata_entry(directory: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    path = directory / f"url_{digest}.json"
    path.write_text(json.dumps({"url": url}), encoding="utf-8")
    return path


def test_metadata_cleanup_enforces_whitelist(tmp_path: Path) -> None:
    metadata_dir = _make_metadata_dir(tmp_path, name="meta-whitelist")
    keep_url = "https://docs.example.com/page"
    stale_url = "https://blog.example.com/post"
    keep_path = _write_metadata_entry(metadata_dir, keep_url)
    stale_path = _write_metadata_entry(metadata_dir, stale_url)

    report = cli.cleanup_metadata_directory(
        metadata_dir,
        whitelist=["https://docs.example.com/"],
        blacklist=[],
    )

    assert report.cleaned is True
    assert keep_path.exists()
    assert not stale_path.exists()


def test_metadata_cleanup_respects_blacklist(tmp_path: Path) -> None:
    metadata_dir = _make_metadata_dir(tmp_path, name="meta-blacklist")
    safe_url = "https://docs.example.com/page"
    blocked_url = "https://docs.example.com/releases/notes"
    _write_metadata_entry(metadata_dir, safe_url)
    blocked_path = _write_metadata_entry(metadata_dir, blocked_url)

    report = cli.cleanup_metadata_directory(
        metadata_dir,
        whitelist=[],
        blacklist=["https://docs.example.com/releases/"],
    )

    assert report.cleaned is True
    assert not blocked_path.exists()


def test_docs_metadata_cleanup_reports_missing_markdown(tmp_path: Path) -> None:
    docs_meta_dir = _make_docs_metadata_dir(tmp_path, name="docs-missing")
    docs_root = docs_meta_dir.parent
    meta_path = docs_meta_dir / "docs.example.com/page.meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "url": "https://docs.example.com/page",
                "metadata": {"markdown_rel_path": "docs.example.com/page.md"},
            }
        ),
        encoding="utf-8",
    )

    report = cli.cleanup_docs_metadata_directory(
        docs_meta_dir,
        docs_root=docs_root,
        whitelist=("https://docs.example.com/",),
        blacklist=(),
        scheduler_dir=docs_root / cli.SYNC_METADATA_SUBDIR_DEFAULT,
    )

    assert report.missing_markdown == 1
    assert report.cleaned is True
    assert not meta_path.exists()


def test_docs_metadata_cleanup_removes_disallowed_markdown_and_scheduler(tmp_path: Path) -> None:
    docs_meta_dir = _make_docs_metadata_dir(tmp_path, name="docs-disallowed")
    docs_root = docs_meta_dir.parent
    markdown_path = docs_root / "docs.example.com" / "page.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("content", encoding="utf-8")
    url = "https://blog.example.com/page"
    meta_path = docs_meta_dir / "blog.example.com/page.meta.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(
            {
                "url": url,
                "metadata": {"markdown_rel_path": str(markdown_path.relative_to(docs_root))},
            }
        ),
        encoding="utf-8",
    )
    scheduler_dir = docs_root / cli.SYNC_METADATA_SUBDIR_DEFAULT
    scheduler_dir.mkdir(parents=True)
    digest = hashlib.sha256(url.encode()).hexdigest()
    scheduler_path = scheduler_dir / f"url_{digest}.json"
    scheduler_path.write_text(json.dumps({"url": url}), encoding="utf-8")

    report = cli.cleanup_docs_metadata_directory(
        docs_meta_dir,
        docs_root=docs_root,
        whitelist=("https://docs.example.com/",),
        blacklist=(),
        scheduler_dir=scheduler_dir,
    )

    assert report.disallowed_urls == 1
    assert not meta_path.exists()
    assert not markdown_path.exists()
    assert not scheduler_path.exists()


def test_cleanup_tenants_combines_segments_and_metadata(tmp_path: Path) -> None:
    segments_dir = _make_segments_dir(tmp_path, name="combo")
    docs_root = segments_dir.parent
    orphan = segments_dir / "orphan.json"
    orphan.write_text("{}", encoding="utf-8")
    _backdate(orphan)

    metadata_dir = docs_root / cli.SYNC_METADATA_SUBDIR_DEFAULT
    metadata_dir.mkdir(parents=True)
    stale_meta = _write_metadata_entry(metadata_dir, "https://example.com/blog/entry")
    docs_metadata_dir = docs_root / cli.DOCS_METADATA_SUBDIR_DEFAULT
    docs_metadata_dir.mkdir(parents=True)

    target = cli.TenantTarget(
        codename="combo",
        docs_root=docs_root,
        segments_dir=segments_dir,
        metadata_dir=metadata_dir,
        docs_metadata_dir=docs_metadata_dir,
        whitelist=("https://example.com/docs/",),
        blacklist=("https://example.com/blog/",),
    )

    summary, reports = cli.cleanup_tenants([target])

    assert not orphan.exists()
    assert not stale_meta.exists()
    assert summary.files_removed == 1
    assert summary.metadata_files_removed == 1
    assert reports[0].segment_report.cleaned is True
    assert reports[0].metadata_report.cleaned is True
