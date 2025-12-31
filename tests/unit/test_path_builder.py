"""Unit tests for PathBuilder query-handling behavior."""

from pathlib import Path

import pytest

from docs_mcp_server.utils.path_builder import PathBuilder


pytestmark = pytest.mark.unit


def test_preserves_query_parameters_in_filenames(tmp_path: Path):
    """Different query parameters should map to distinct markdown files."""

    builder = PathBuilder(ignore_query_strings=False)

    url_one = "https://example.com/docs/page/?lang=en&version=1"
    url_two = "https://example.com/docs/page/?lang=fr&version=1"

    path_one = builder.build_markdown_path(url_one, relative_to=tmp_path)
    path_two = builder.build_markdown_path(url_two, relative_to=tmp_path)

    assert path_one != path_two
    assert path_one.name.endswith("__q__lang_en__version_1.md")
    assert path_two.name.endswith("__q__lang_fr__version_1.md")


def test_ignore_query_strings_matches_previous_behavior(tmp_path: Path):
    """Legacy mode still deduplicates URLs that differ only by query params."""

    builder = PathBuilder(ignore_query_strings=True)
    url_a = "https://example.com/guides/install?utm_source=twitter"
    url_b = "https://example.com/guides/install?utm_source=email"

    path_a = builder.build_markdown_path(url_a, relative_to=tmp_path)
    path_b = builder.build_markdown_path(url_b, relative_to=tmp_path)

    assert path_a == path_b


def test_has_file_extension_detection():
    """_has_file_extension should be case-insensitive and skip directories."""

    builder = PathBuilder()
    assert builder._has_file_extension("guide.html")
    assert builder._has_file_extension("README.MD")
    assert not builder._has_file_extension("docs")


def test_build_metadata_path_absolute(tmp_path: Path):
    """build_metadata_path mirrors markdown structure under metadata dir."""

    builder = PathBuilder()
    markdown = tmp_path / "docs.example.com" / "guide.md"
    markdown.parent.mkdir(parents=True)
    markdown.touch()

    metadata_path = builder.build_metadata_path(markdown, relative_to=tmp_path)

    expected = tmp_path / PathBuilder.METADATA_DIR / "docs.example.com" / "guide.meta.json"
    assert metadata_path == expected


def test_build_query_suffix_hashes_long_queries():
    """Very long query suffixes should hash to deterministic value."""

    builder = PathBuilder(ignore_query_strings=False)
    query = "&".join(f"p{i}=value{i}" for i in range(30))

    suffix = builder._build_query_suffix(query)

    assert suffix.startswith("__q__hash_")


def test_truncate_path_hashes_middle_segments():
    """_truncate_path keeps domain/filename and hashes middle segments."""

    builder = PathBuilder()
    parts = ["docs.example.com"] + [f"segment{i}" for i in range(10)] + ["file.md"]
    long_path = Path(*parts)

    truncated = builder._truncate_path(long_path, "file.md")

    assert truncated.parts[0] == "docs.example.com"
    assert truncated.parts[-1] == "file.md"
    # Middle part should be a hash rather than original segment
    assert truncated.parts[1] != parts[1]


def test_build_markdown_path_truncates_excessively_long_urls():
    builder = PathBuilder()
    long_path = "/".join(f"segment-{i:02d}" for i in range(80))
    url = f"https://example.com/{long_path}/"

    result = builder.build_markdown_path(url)

    assert result.parts[0] == "example.com"
    assert len(result.parts) == 3  # domain, hash, filename
    assert len(result.parts[1]) == 16  # truncated hash length
    assert result.name.endswith("segment-79.md")


def test_build_metadata_path_handles_absolute_markdown(tmp_path: Path):
    builder = PathBuilder()
    tenant_root = tmp_path / "tenant"
    tenant_root.mkdir()
    relative_md = Path("example.com/guide.md")
    absolute_md = tenant_root / relative_md

    metadata_path = builder.build_metadata_path(absolute_md, relative_to=tenant_root)

    expected = tenant_root / PathBuilder.METADATA_DIR / relative_md.with_suffix(".meta.json")
    assert metadata_path == expected


def test_apply_query_suffix_handles_non_markdown_files():
    builder = PathBuilder(ignore_query_strings=False)
    suffix = "__q__lang_en"

    assert builder._apply_query_suffix("index", suffix) == "index__q__lang_en"
    assert builder._apply_query_suffix("index.md", suffix) == "index__q__lang_en.md"
    assert builder._apply_query_suffix("index.md", "") == "index.md"


def test_normalized_query_components_handle_blank_values():
    builder = PathBuilder(ignore_query_strings=False)

    components = builder._normalized_query_components("lang=&page=2&sort=")

    assert components == ["lang", "page_2", "sort"]


def test_normalize_segment_strips_traversal_sequences():
    builder = PathBuilder()

    assert builder._normalize_segment("../etc/passwd") == "etc-passwd"
    assert builder._normalize_segment("../..") == "index"


def test_truncate_path_hashes_short_paths():
    builder = PathBuilder()
    short_path = Path("docs.example.com")

    truncated = builder._truncate_path(short_path, "file.md")

    assert truncated.name == "file.md"
    assert truncated.parent.name.startswith("truncated-")
