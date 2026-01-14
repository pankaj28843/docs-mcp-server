"""Additional unit tests for PathBuilder edge cases."""

from pathlib import Path

import pytest

from docs_mcp_server.utils.path_builder import PathBuilder


@pytest.mark.unit
def test_build_path_terminal_segment_without_extension(monkeypatch):
    builder = PathBuilder()
    monkeypatch.setattr(builder, "canonicalize_url", lambda url: url)
    path = builder.build_markdown_path("https://example.com/docs/guide")

    assert path.as_posix().endswith("docs/guide.md")


@pytest.mark.unit
def test_build_metadata_path_handles_unrelated_absolute_path(tmp_path: Path):
    builder = PathBuilder()
    base_dir = tmp_path / "base"
    other_dir = tmp_path / "other"
    base_dir.mkdir()
    other_dir.mkdir()

    markdown_path = other_dir / "doc.md"
    metadata_path = builder.build_metadata_path(markdown_path, relative_to=base_dir)

    assert metadata_path.name.endswith(".meta.json")


@pytest.mark.unit
def test_build_metadata_path_returns_relative_when_no_base():
    builder = PathBuilder()
    metadata_path = builder.build_metadata_path(Path("docs/example.md"))

    assert metadata_path.as_posix().startswith(Path(builder.METADATA_DIR).as_posix())


@pytest.mark.unit
def test_build_query_suffix_empty_query_returns_empty_string():
    builder = PathBuilder()
    assert builder._build_query_suffix("") == ""


@pytest.mark.unit
def test_normalize_segment_truncates_long_segments():
    builder = PathBuilder()
    long_segment = "a" * (builder.MAX_SEGMENT_LENGTH + 20)
    normalized = builder._normalize_segment(long_segment)

    assert len(normalized) <= builder.MAX_SEGMENT_LENGTH
