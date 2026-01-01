"""Unit tests for the boot-time index audit helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.index_audit import audit_single_tenant
from docs_mcp_server.search.indexer import TenantIndexer, TenantIndexingContext


@pytest.fixture
def tenant_root(tmp_path: Path) -> Path:
    (tmp_path / "__docs_metadata").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_audit_single_tenant_reports_ok(tenant_root: Path) -> None:
    markdown_path = tenant_root / "docs" / "example.md"
    _write_markdown_doc(markdown_path, title="Example", body="# Example\n\ncontent")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    TenantIndexer(context).build_segment()

    report = audit_single_tenant(context, rebuild=False)
    assert report.status == "ok"
    assert report.fingerprint == report.current_segment_id
    assert report.rebuilt is False
    assert report.error is None


def test_audit_single_tenant_rebuilds_when_needed(tenant_root: Path) -> None:
    markdown_path = tenant_root / "docs" / "stale.md"
    _write_markdown_doc(markdown_path, title="Stale", body="# Stale\n\ncontent")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)
    indexer.build_segment()

    markdown_path.write_text(
        "-----\ntitle: Stale\nurl: https://example.com/docs/stale\n-----\n# Stale\n\nupdated",
        encoding="utf-8",
    )

    stale_report = audit_single_tenant(context, rebuild=False)
    assert stale_report.needs_rebuild is True
    assert stale_report.rebuilt is False

    rebuild_report = audit_single_tenant(context, rebuild=True)
    assert rebuild_report.rebuilt is True
    assert rebuild_report.needs_rebuild is False
    assert rebuild_report.documents_indexed == 1
    assert rebuild_report.error is None


def _write_markdown_doc(path: Path, *, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = (
        path.parent.parent / "__docs_metadata" / path.relative_to(path.parent.parent).with_suffix(".meta.json")
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://example.com/{path.relative_to(path.parent.parent).with_suffix('').as_posix()}"
    path.write_text(f"-----\ntitle: {title}\nurl: {url}\n-----\n{body}", encoding="utf-8")
    metadata_path.write_text(
        (
            "{\n"
            f'  "url": "{url}",\n'
            f'  "title": "{title}",\n'
            '  "metadata": {\n'
            f'    "markdown_rel_path": "{path.relative_to(path.parent.parent)}",\n'
            '    "last_fetched_at": "2025-01-01T00:00:00+00:00"\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
