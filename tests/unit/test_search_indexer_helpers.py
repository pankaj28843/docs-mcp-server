"""Unit tests for search indexer helper functions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from docs_mcp_server.search.indexer import (
    _coerce_tags,
    _derive_title,
    _detect_language,
    _DocsFingerprintBuilder,
    _extract_excerpt,
    _extract_headings,
    _extract_tiered_headings,
    _extract_url_path,
    _iterate_paragraphs,
    _resolve_timestamp,
    _strip_heading_tail,
)
from docs_mcp_server.search.schema import create_default_schema


pytestmark = pytest.mark.unit


def test_extract_tiered_headings_splits_levels() -> None:
    markdown = "# Title\n\n## Subtitle\n\n### Detail\n"

    tiered = _extract_tiered_headings(markdown)

    assert tiered.h1 == "Title"
    assert tiered.h2 == "Subtitle"
    assert tiered.h3_plus == "Detail"


def test_extract_headings_combines_levels() -> None:
    markdown = "# Title\n\n## Subtitle\n\n### Detail\n"

    headings = _extract_headings(markdown)

    assert headings.splitlines() == ["Title", "Subtitle", "Detail"]


def test_strip_heading_tail_removes_anchor() -> None:
    assert _strip_heading_tail("Overview [¶](#overview)") == "Overview"


def test_extract_excerpt_uses_first_text_paragraph() -> None:
    markdown = "# Title\n\nFirst paragraph here.\n\nSecond paragraph."

    excerpt = _extract_excerpt(markdown, max_length=50)

    assert excerpt == "First paragraph here."


def test_derive_title_prefers_heading() -> None:
    markdown = "# Getting Started\n\nBody"

    assert _derive_title(markdown, Path("guide.md")) == "Getting Started"


def test_derive_title_falls_back_to_filename() -> None:
    markdown = "No headings here"

    assert _derive_title(markdown, Path("getting-started.md")) == "getting started"


def test_coerce_tags_handles_multiple_inputs() -> None:
    assert _coerce_tags(["a", 2]) == ["a", "2"]
    assert _coerce_tags("tag") == ["tag"]
    assert _coerce_tags(None) == []


def test_iterate_paragraphs_skips_headings_and_code() -> None:
    markdown = "# Title\n\nFirst line\nSecond line\n\n```\ncode\n```\n\nNext paragraph"

    paragraphs = list(_iterate_paragraphs(markdown))

    assert paragraphs == ["First line Second line", "code", "Next paragraph"]


def test_resolve_timestamp_prefers_metadata_timestamp(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("content", encoding="utf-8")
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    resolved = _resolve_timestamp({"last_fetched_at": now.isoformat()}, target)

    assert resolved == int(now.timestamp())


def test_resolve_timestamp_handles_naive_string(tmp_path: Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("content", encoding="utf-8")
    raw = "2024-01-01T00:00:00"

    resolved = _resolve_timestamp({"indexed_at": raw}, target)

    assert resolved == int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


def test_extract_url_path_handles_empty_and_file_urls() -> None:
    assert _extract_url_path("") == ""
    assert _extract_url_path("file:///tmp/docs/readme.md") == "/tmp/docs/readme.md"


def test_docs_fingerprint_builder_is_deterministic() -> None:
    schema = create_default_schema()
    builder_one = _DocsFingerprintBuilder(schema)
    builder_two = _DocsFingerprintBuilder(schema)

    builder_one.add_document("a", {"url": "a", "title": "A"})
    builder_one.add_document("b", {"url": "b", "title": "B"})

    builder_two.add_document("b", {"url": "b", "title": "B"})
    builder_two.add_document("a", {"url": "a", "title": "A"})

    assert builder_one.digest() == builder_two.digest()


def test_docs_fingerprint_builder_empty_digest() -> None:
    schema = create_default_schema()
    builder = _DocsFingerprintBuilder(schema)

    assert builder.digest() == ""


def test_detect_language_respects_front_matter_and_url() -> None:
    assert _detect_language("https://example.com/docs/", {"language": "FR"}) == "fr"
    assert _detect_language("https://example.com/ja/docs/", {}) == "ja"
    assert _detect_language("", {}) == "en"
