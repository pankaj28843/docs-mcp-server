"""Unit tests for the tenant indexing pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from docs_mcp_server.search.indexer import (
    DocumentLoadError,
    IndexBuildResult,
    TenantIndexer,
    TenantIndexingContext,
    _extract_url_path,
)
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore


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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
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

    store = SqliteSegmentStore(context.segments_dir)
    latest = store.latest()
    assert latest is not None
    assert latest.doc_count == 1
    # Ensure the blacklisted document is absent
    assert latest.get_document("https://allowed.example/docs/howto/")
    assert latest.get_document("https://allowed.example/docs/releases/2025/") is None


def test_indexer_normalizes_changed_paths(tenant_root: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    absolute = tenant_root / "docs" / "example.md"
    normalized = indexer._normalize_paths([str(absolute), "docs/relative.md"])

    assert Path("docs/example.md") in normalized
    assert Path("docs/relative.md") in normalized


def test_indexer_url_allowed_respects_filters(tenant_root: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="online",
        url_whitelist_prefixes=("https://allowed.example/docs/",),
        url_blacklist_prefixes=("https://allowed.example/docs/blocked/",),
    )
    indexer = TenantIndexer(context)

    assert indexer._url_allowed("https://allowed.example/docs/guide/") is True
    assert indexer._url_allowed("https://allowed.example/docs/blocked/page/") is False
    assert indexer._url_allowed("https://other.example/docs/") is False


def test_indexer_respects_limit(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/one.md",
        title="One",
        body="# One\n\nbody",
    )
    _write_markdown_doc(
        tenant_root,
        "docs/two.md",
        title="Two",
        body="# Two\n\nbody",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment(limit=1)

    assert result.documents_indexed == 1
    assert result.segment_paths


def test_indexer_skips_when_filters_exclude_paths(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/one.md",
        title="One",
        body="# One\n\nbody",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment(changed_paths=["docs/other.md"])

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1


def test_indexer_skips_disallowed_url_for_online(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/blocked.md",
        title="Blocked",
        body="# Blocked\n\nbody",
        url="https://blocked.example/docs/guide/",
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

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1


def test_indexer_records_storage_errors(tenant_root: Path) -> None:
    _write_markdown_doc(
        tenant_root,
        "docs/one.md",
        title="One",
        body="# One\n\nbody",
        url="https://example.com/docs/shared",
    )
    _write_markdown_doc(
        tenant_root,
        "docs/two.md",
        title="Two",
        body="# Two\n\nbody",
        url="https://example.com/docs/shared",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    result = indexer.build_segment()

    assert result.documents_indexed == 1
    assert result.documents_skipped == 1
    assert result.errors


def test_indexer_discover_metadata_files_returns_empty_when_missing(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    assert list(indexer._discover_metadata_files()) == []


def test_indexer_discover_markdown_files_skips_hidden_dirs(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "__docs_metadata").mkdir()
    (docs_root / "__search_segments").mkdir()
    hidden = docs_root / "__docs_metadata" / "hidden.md"
    hidden.write_text("hidden", encoding="utf-8")
    visible = docs_root / "visible.md"
    visible.write_text("visible", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    results = list(indexer._discover_markdown_files())

    assert hidden not in results
    assert visible in results


def test_indexer_resolve_markdown_path_prefers_metadata(tenant_root: Path) -> None:
    markdown = _write_markdown_doc(
        tenant_root,
        "docs/one.md",
        title="One",
        body="# One\n\nbody",
    )
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    resolved = indexer._resolve_markdown_path(markdown.with_suffix(".meta.json"), {"markdown_rel_path": "docs/one.md"})

    assert resolved == markdown.resolve()


def test_indexer_candidate_markdown_path_handles_outside_metadata_root(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    metadata_path = tmp_path / "orphan.meta.json"
    candidate = indexer._candidate_markdown_path(metadata_path)

    assert candidate == (docs_root / "orphan.md").resolve()


def test_indexer_has_changed_detects_metadata_updates(tenant_root: Path) -> None:
    _ = _write_markdown_doc(
        tenant_root,
        "docs/one.md",
        title="One",
        body="# One\n\nbody",
    )
    metadata_path = tenant_root / "__docs_metadata" / "docs" / "one.meta.json"
    payload = TenantIndexer(
        TenantIndexingContext(
            codename="demo",
            docs_root=tenant_root,
            segments_dir=tenant_root / "segments",
            source_type="filesystem",
        )
    )._load_document_from_metadata(metadata_path)

    earlier = datetime.now(timezone.utc) - timedelta(days=1)
    assert TenantIndexer(
        TenantIndexingContext(
            codename="demo",
            docs_root=tenant_root,
            segments_dir=tenant_root / "segments",
            source_type="filesystem",
        )
    )._has_changed(payload, earlier)


def test_indexer_build_payload_raises_when_url_missing(tenant_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    markdown_path = tenant_root / "docs" / "no-url.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("-----\ntitle: No Url\n-----\nbody", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    monkeypatch.setattr(indexer, "_default_url_for", lambda _path: "")

    with pytest.raises(DocumentLoadError):
        indexer._build_payload(markdown_path=markdown_path, metadata_path=None, metadata_payload=None)


def test_indexer_compute_fingerprint_returns_none_without_docs(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    assert indexer.compute_fingerprint() is None


def test_indexer_fingerprint_audit_flags_missing_segment(tenant_root: Path) -> None:
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

    audit = indexer.fingerprint_audit()

    assert audit.needs_rebuild is True
    assert audit.current_segment_id is None


def test_indexer_discover_metadata_files_falls_back_to_rglob(tmp_path: Path, monkeypatch) -> None:
    metadata_root = tmp_path / "__docs_metadata"
    metadata_root.mkdir(parents=True)
    sample = metadata_root / "docs" / "doc.meta.json"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text('{"url": "https://example.com"}', encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    def _raise_file_not_found(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("docs_mcp_server.search.indexer.subprocess.run", _raise_file_not_found)

    results = list(indexer._discover_metadata_files())

    assert sample in results


def test_load_document_from_metadata_requires_url(tenant_root: Path) -> None:
    metadata_path = tenant_root / "__docs_metadata" / "docs" / "missing.meta.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text("{}", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    with pytest.raises(DocumentLoadError):
        indexer._load_document_from_metadata(metadata_path)


def test_load_document_from_metadata_requires_markdown(tenant_root: Path) -> None:
    metadata_path = tenant_root / "__docs_metadata" / "docs" / "missing.meta.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        '{\n  "url": "https://example.com/docs/missing",\n  "metadata": {"markdown_rel_path": "docs/missing.md"}\n}\n',
        encoding="utf-8",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    with pytest.raises(DocumentLoadError):
        indexer._load_document_from_metadata(metadata_path)


def test_relative_to_root_returns_absolute_when_outside(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("content", encoding="utf-8")
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path / "docs",
        segments_dir=tmp_path / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)

    resolved = indexer._relative_to_root(outside)

    assert resolved == outside.resolve()


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


def test_compute_fingerprint_matches_manifest(tenant_root: Path) -> None:
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
    indexer.build_segment()

    fingerprint = indexer.compute_fingerprint()
    store = SqliteSegmentStore(context.segments_dir)
    assert fingerprint == store.latest_segment_id()


def test_fingerprint_audit_detects_mismatch(tenant_root: Path) -> None:
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
    indexer.build_segment()

    markdown_path.write_text(
        "-----\ntitle: Example\nurl: https://example.com/docs/example\n-----\n# Example\n\nupdated",
        encoding="utf-8",
    )

    audit = indexer.fingerprint_audit()
    assert audit.needs_rebuild is True
    assert audit.current_segment_id is not None
    assert audit.current_segment_id != audit.fingerprint


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
    store = SqliteSegmentStore(context.segments_dir)
    first_manifest = store.list_segments()
    first_files = sorted(context.segments_dir.glob("*.db"))

    second_run = indexer.build_segment()
    second_manifest = store.list_segments()
    second_files = sorted(context.segments_dir.glob("*.db"))

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
    store = SqliteSegmentStore(context.segments_dir)
    manifest = store.list_segments()
    assert len(manifest) == 1
    assert manifest[0]["segment_id"] == second_run.segment_ids[0]
    old_path = context.segments_dir / f"{first_run.segment_ids[0]}.db"
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
