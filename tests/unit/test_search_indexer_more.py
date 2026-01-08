from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from docs_mcp_server.search.indexer import (
    DocumentLoadError,
    TenantIndexer,
    TenantIndexingContext,
    _extract_tiered_headings,
)
from docs_mcp_server.search.schema import create_default_schema


@pytest.mark.unit
def test_discover_metadata_files_falls_back_to_rglob(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata_root = tmp_path / "__docs_metadata"
    metadata_root.mkdir()
    meta_path = metadata_root / "doc.meta.json"
    meta_path.write_text('{"url": "https://example.com"}', encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", raise_missing)

    indexer = TenantIndexer(context)
    discovered = list(indexer._discover_metadata_files())  # pylint: disable=protected-access

    assert meta_path in discovered


@pytest.mark.unit
def test_discover_metadata_files_uses_ripgrep_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metadata_root = tmp_path / "__docs_metadata"
    metadata_root.mkdir()
    meta_path = metadata_root / "doc.meta.json"
    meta_path.write_text('{"url": "https://example.com"}', encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    completed = subprocess.CompletedProcess(
        args=["rg"],
        returncode=0,
        stdout=f"{meta_path}\n",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    indexer = TenantIndexer(context)
    discovered = list(indexer._discover_metadata_files())  # pylint: disable=protected-access

    assert discovered == [meta_path]


@pytest.mark.unit
def test_build_segment_reports_metadata_missing_url(tmp_path: Path) -> None:
    docs_root = tmp_path
    metadata_root = docs_root / "__docs_metadata"
    metadata_root.mkdir()
    meta_path = metadata_root / "missing.meta.json"
    meta_path.write_text("{}", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1
    assert any("Metadata missing url field" in error for error in result.errors)


@pytest.mark.unit
def test_build_segment_persist_false_returns_fingerprint(tmp_path: Path) -> None:
    docs_root = tmp_path
    markdown_path = docs_root / "doc.md"
    markdown_path.write_text("# Title\n\nBody", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.documents_indexed == 1
    assert result.segment_ids
    assert result.segment_paths == ()


@pytest.mark.unit
def test_extract_tiered_headings_splits_levels() -> None:
    markdown = "# H1\n\n## H2 [¶](#h2)\n\n### H3\n\n#### H4"

    tiered = _extract_tiered_headings(markdown)

    assert tiered.h1 == "H1"
    assert tiered.h2 == "H2"
    assert "H3" in tiered.h3_plus
    assert "H4" in tiered.h3_plus


@pytest.mark.unit
def test_load_document_from_markdown_missing_file(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)

    with pytest.raises(DocumentLoadError):
        indexer._load_document_from_markdown(tmp_path / "missing.md")  # pylint: disable=protected-access


@pytest.mark.unit
def test_build_segment_respects_limit(tmp_path: Path) -> None:
    docs_root = tmp_path
    (docs_root / "one.md").write_text("# One", encoding="utf-8")
    (docs_root / "two.md").write_text("# Two", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(limit=1, persist=False)

    assert result.documents_indexed == 1


@pytest.mark.unit
def test_build_segment_limit_zero_returns_empty(tmp_path: Path) -> None:
    docs_root = tmp_path
    (docs_root / "one.md").write_text("# One", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(limit=0, persist=False)

    assert result.documents_indexed == 0
    assert result.segment_ids == ()


@pytest.mark.unit
def test_build_segment_skips_filtered_paths(tmp_path: Path) -> None:
    docs_root = tmp_path
    (docs_root / "one.md").write_text("# One", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(changed_paths=["missing.md"], persist=False)

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1


@pytest.mark.unit
def test_build_segment_skips_disallowed_urls(tmp_path: Path) -> None:
    docs_root = tmp_path
    (docs_root / "doc.md").write_text("-----\nurl: https://example.com/doc\n-----\n# Doc", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
        url_whitelist_prefixes=("https://allowed/",),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1


@pytest.mark.unit
def test_build_segment_online_limit_breaks_metadata_loop(tmp_path: Path) -> None:
    docs_root = tmp_path
    metadata_root = docs_root / "__docs_metadata"
    metadata_root.mkdir()
    (docs_root / "doc1.md").write_text("# One", encoding="utf-8")
    (docs_root / "doc2.md").write_text("# Two", encoding="utf-8")
    (metadata_root / "doc1.meta.json").write_text(
        '{"url": "https://example.com/one", "metadata": {"markdown_rel_path": "doc1.md"}}',
        encoding="utf-8",
    )
    (metadata_root / "doc2.meta.json").write_text(
        '{"url": "https://example.com/two", "metadata": {"markdown_rel_path": "doc2.md"}}',
        encoding="utf-8",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(limit=1, persist=False)

    assert result.documents_indexed == 1


@pytest.mark.unit
def test_build_segment_skips_markdown_seen_from_metadata(tmp_path: Path) -> None:
    docs_root = tmp_path
    metadata_root = docs_root / "__docs_metadata"
    metadata_root.mkdir()
    (docs_root / "doc.md").write_text("# One", encoding="utf-8")
    (metadata_root / "doc.meta.json").write_text(
        '{"url": "https://example.com/one", "metadata": {"markdown_rel_path": "doc.md"}}',
        encoding="utf-8",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.documents_indexed == 1


@pytest.mark.unit
def test_build_segment_handles_markdown_load_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    docs_root = tmp_path

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    monkeypatch.setattr(indexer, "_discover_markdown_files", lambda: iter([docs_root / "missing.md"]))

    result = indexer.build_segment(persist=False)

    assert result.documents_skipped == 1


@pytest.mark.unit
def test_build_segment_reports_metadata_missing_markdown(tmp_path: Path) -> None:
    docs_root = tmp_path
    metadata_root = docs_root / "__docs_metadata"
    metadata_root.mkdir()
    meta_path = metadata_root / "doc.meta.json"
    meta_path.write_text(
        '{"url": "https://example.com", "metadata": {"markdown_rel_path": "missing.md"}}',
        encoding="utf-8",
    )

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.documents_skipped == 1
    assert any("Markdown missing" in error for error in result.errors)


@pytest.mark.unit
def test_compute_fingerprint_returns_none_when_empty(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)

    assert indexer.compute_fingerprint() is None


@pytest.mark.unit
def test_fingerprint_audit_needs_rebuild_when_missing_segment(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# Title\n\nBody", encoding="utf-8")
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    audit = indexer.fingerprint_audit()

    assert audit.needs_rebuild is True


@pytest.mark.unit
def test_fingerprint_audit_returns_no_rebuild_when_empty(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    audit = indexer.fingerprint_audit()

    assert audit.needs_rebuild is False


@pytest.mark.unit
def test_candidate_markdown_path_builds_from_metadata_path(tmp_path: Path) -> None:
    docs_root = tmp_path
    metadata_root = docs_root / "__docs_metadata"
    metadata_root.mkdir()
    meta_path = metadata_root / "guide.meta.json"
    meta_path.write_text('{"url": "https://example.com"}', encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
    )
    indexer = TenantIndexer(context)

    candidate = indexer._candidate_markdown_path(meta_path)  # pylint: disable=protected-access

    assert candidate.name == "guide.md"


@pytest.mark.unit
def test_relative_to_root_handles_external_paths(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )
    indexer = TenantIndexer(context)

    external = tmp_path / "external.md"
    external.write_text("# External", encoding="utf-8")

    relative = indexer._relative_to_root(external)  # pylint: disable=protected-access

    assert relative == external.resolve()


@pytest.mark.unit
def test_normalize_paths_handles_absolute_external(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )
    indexer = TenantIndexer(context)

    external = tmp_path / "external.md"
    normalized = indexer._normalize_paths([str(external)])  # pylint: disable=protected-access

    assert external.resolve() in normalized


@pytest.mark.unit
def test_url_allowed_applies_whitelist_and_blacklist(tmp_path: Path) -> None:
    context = TenantIndexingContext(
        codename="demo",
        docs_root=tmp_path,
        segments_dir=tmp_path / "__search_segments",
        source_type="online",
        schema=create_default_schema(),
        url_whitelist_prefixes=("https://allowed/",),
        url_blacklist_prefixes=("https://allowed/bad",),
    )
    indexer = TenantIndexer(context)

    assert indexer._url_allowed("https://allowed/doc") is True  # pylint: disable=protected-access
    assert indexer._url_allowed("https://allowed/bad/doc") is False  # pylint: disable=protected-access
    assert indexer._url_allowed("") is False  # pylint: disable=protected-access


@pytest.mark.unit
def test_extract_tiered_headings_skips_empty_heading() -> None:
    markdown = "### [¶](#anchor)"

    tiered = _extract_tiered_headings(markdown)

    assert tiered.h3_plus == ""


@pytest.mark.unit
def test_build_segment_skips_unchanged_when_changed_only(tmp_path: Path) -> None:
    docs_root = tmp_path
    markdown_path = docs_root / "doc.md"
    markdown_path.write_text("# Doc", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    first = indexer.build_segment(persist=True)
    assert first.segment_paths

    old_time = markdown_path.stat().st_mtime - 3600
    markdown_path.touch()
    os.utime(markdown_path, (old_time, old_time))

    result = indexer.build_segment(changed_only=True, persist=False)

    assert result.documents_indexed == 0
    assert result.documents_skipped == 1


@pytest.mark.unit
def test_build_segment_records_storage_errors(tmp_path: Path) -> None:
    docs_root = tmp_path
    (docs_root / "one.md").write_text("-----\nurl: https://example.com/doc\n-----\n# One", encoding="utf-8")
    (docs_root / "two.md").write_text("-----\nurl: https://example.com/doc\n-----\n# Two", encoding="utf-8")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=docs_root,
        segments_dir=docs_root / "__search_segments",
        source_type="filesystem",
        schema=create_default_schema(),
    )

    indexer = TenantIndexer(context)
    result = indexer.build_segment(persist=False)

    assert result.errors
    assert result.documents_skipped == 1
