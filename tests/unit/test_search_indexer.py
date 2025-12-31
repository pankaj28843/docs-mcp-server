"""Unit tests for the tenant indexing pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs_mcp_server.search.indexer import (
    IndexBuildResult,
    TenantIndexer,
    TenantIndexingContext,
    _extract_url_path,
)
from docs_mcp_server.search.storage import JsonSegmentStore


@pytest.fixture
def tenant_root(tmp_path: Path) -> Path:
    (tmp_path / "__docs_metadata").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_indexer_builds_segment_from_filesystem(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "site/docs/getting-started.md",
        title="Getting Started",
        body="# Intro\n\nContent paragraph here.",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert isinstance(result, IndexBuildResult)
    assert result.documents_indexed == 1
    assert result.segment_paths

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1
    # "Getting" is stemmed to "gett" by StandardAnalyzer
    postings = latest.get_postings("title", "gett")
    assert postings


def test_indexer_skips_when_changed_only_has_no_updates(tenant_root: Path) -> None:
    markdown_path = _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\ncontent",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    first_run = indexer.build_segment()
    assert first_run.documents_indexed == 1

    second_run = indexer.build_segment(changed_only=True)
    assert second_run.documents_indexed == 0
    assert not second_run.segment_paths

    markdown_path.write_text(markdown_path.read_text() + "\nUpdated", encoding="utf-8")
    third_run = indexer.build_segment(changed_only=True)
    assert third_run.documents_indexed == 1


def test_indexer_respects_changed_paths_filter(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/first.md",
        title="First",
        body="# First\n\nalpha",
    )
    _write_markdown_doc(
        tenant_root,
        "docs/second.md",
        title="Second",
        body="# Second\n\nbeta",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment(changed_paths=["docs/first.md"])
    assert result.documents_indexed == 1
    assert result.segment_paths

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1
    assert latest.get_document("https://example.com/docs/first")


def test_indexer_can_skip_persisting_segments(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/ephemeral.md",
        title="Ephemeral",
        body="# Ephemeral\n\nbody",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment(persist=False)
    assert result.documents_indexed == 1
    assert not result.segment_paths

    store = JsonSegmentStore(context.segments_dir)
    assert store.latest() is None


def test_indexer_reads_markdown_without_metadata(tenant_root: Path) -> None:
    markdown_path = tenant_root / "docs" / "untracked.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("# Plain Title\n\nBody text.", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert result.documents_indexed == 1

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1


def test_indexer_deduplicates_metadata_and_markdown(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\ncontent",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="online",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert result.documents_indexed == 1

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1


def test_indexer_skips_urls_outside_whitelist_for_online_tenants(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/allowed.md",
        title="Allowed",
        body="# Allowed\n\nOk",
        url="https://allowed.example/docs/guide/",
    )
    _write_markdown_doc(
        tenant_root,
        "docs/blocked.md",
        title="Blocked",
        body="# Blocked\n\nNope",
        url="https://other.example/docs/off-topic/",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="online",
        url_whitelist_prefixes=("https://allowed.example/docs/",),
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert result.documents_indexed == 1

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1
    assert latest.get_document("https://allowed.example/docs/guide/")
    assert latest.get_document("https://other.example/docs/off-topic/") is None


def test_indexer_skips_blacklisted_urls_for_online_tenants(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/good.md",
        title="Good",
        body="# Good\n\nOk",
        url="https://allowed.example/docs/howto/",
    )
    _write_markdown_doc(
        tenant_root,
        "docs/bad.md",
        title="Bad",
        body="# Bad\n\nNo",
        url="https://allowed.example/docs/releases/2025/",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="online",
        url_whitelist_prefixes=("https://allowed.example/docs/",),
        url_blacklist_prefixes=("https://allowed.example/docs/releases/",),
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert result.documents_indexed == 1

    store = JsonSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1
    # Ensure the blacklisted document is absent
    assert latest.get_document("https://allowed.example/docs/howto/")
    assert latest.get_document("https://allowed.example/docs/releases/2025/") is None


def test_indexer_uses_fingerprint_segment_ids(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\ncontent",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()
    assert result.segment_ids
    assert len(result.segment_ids[0]) == 64  # sha256 hex digest


def test_indexer_does_not_create_duplicate_segment_on_repeat_run(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\ncontent",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    first_run = indexer.build_segment()
    store = JsonSegmentStore(context.segments_dir)
    first_manifest = store.list_segments()
    first_files = sorted(context.segments_dir.glob("*.json"))

    second_run = indexer.build_segment()
    second_manifest = store.list_segments()
    second_files = sorted(context.segments_dir.glob("*.json"))

    assert first_run.segment_ids == second_run.segment_ids
    assert first_manifest == second_manifest
    assert first_files == second_files


def test_indexer_prunes_manifest_to_latest_segment(tenant_root: Path) -> None:
    markdown_path = _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\ncontent",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    first_run = indexer.build_segment()
    assert first_run.segment_ids

    _write_markdown_doc(
        tenant_root,
        "docs/example.md",
        title="Example",
        body="# Example\n\nupdated",
    )

    second_run = indexer.build_segment()
    assert second_run.segment_ids
    store = JsonSegmentStore(context.segments_dir)
    manifest = store.list_segments()
    assert len(manifest) == 1
    assert manifest[0]["segment_id"] == second_run.segment_ids[0]
    old_path = context.segments_dir / f"{first_run.segment_ids[0]}.json"
    assert not old_path.exists()


# --- helpers --------------------------------------------------------------


def _write_markdown_doc(
    root: Path,
    relative_path: str,
    *,
    title: str,
    body: str,
    url: str | None = None,
) -> Path:
    markdown_path = root / relative_path
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    doc_url = url or f"https://example.com/{relative_path.replace('.md', '')}"
    markdown_path.write_text(
        f"-----\ntitle: {title}\nurl: {doc_url}\n-----\n{body}\n",
        encoding="utf-8",
    )

    metadata_path = root / "__docs_metadata" / (Path(relative_path).with_suffix(".meta.json"))
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": doc_url,
        "title": title,
        "metadata": {
            "markdown_rel_path": relative_path,
            "last_fetched_at": "2025-01-01T00:00:00+00:00",
        },
    }
    metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return markdown_path


@pytest.mark.unit
class TestExtractUrlPath:
    """Unit tests for _extract_url_path helper function."""

    def test_extracts_path_from_http_url(self):
        url = "https://docs.djangoproject.com/en/5.1/topics/forms/"
        assert _extract_url_path(url) == "/en/5.1/topics/forms/"

    def test_extracts_path_from_file_url(self):
        url = "file:///home/user/docs/chapter1.md"
        assert _extract_url_path(url) == "/home/user/docs/chapter1.md"

    def test_handles_empty_url(self):
        assert _extract_url_path("") == ""

    def test_handles_url_without_path(self):
        url = "https://example.com"
        assert _extract_url_path(url) == ""

    def test_handles_root_path(self):
        url = "https://example.com/"
        assert _extract_url_path(url) == "/"
