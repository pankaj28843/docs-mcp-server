"""Tests for tenant browse helper utilities."""

from pathlib import Path

import pytest

from docs_mcp_server.tenant import (
    MAX_BROWSE_DEPTH,
    _build_browse_nodes,
    _has_visible_children,
    _load_metadata_for_relative_path,
    _should_skip_entry,
)


@pytest.mark.unit
class TestBrowseHelpers:
    """Unit tests for browse helper functions."""

    def test_should_skip_entry_covers_hidden_patterns(self, tmp_path: Path) -> None:
        storage_root = tmp_path
        metadata_dir = storage_root / "__docs_metadata"
        metadata_dir.mkdir()

        staging = storage_root / ".staging_tmp"
        staging.mkdir()
        hashed = storage_root / ("a" * 64 + ".md")
        hashed.write_text("hashed", encoding="utf-8")
        meta_file = storage_root / "doc.meta.json"
        meta_file.write_text("{}", encoding="utf-8")
        visible = storage_root / "doc.md"
        visible.write_text("# doc", encoding="utf-8")

        assert _should_skip_entry(metadata_dir, storage_root) is True
        assert _should_skip_entry(staging, storage_root) is True
        assert _should_skip_entry(hashed, storage_root) is True
        assert _should_skip_entry(meta_file, storage_root) is True
        assert _should_skip_entry(visible, storage_root) is False

    def test_has_visible_children_ignores_hidden_nodes(self, tmp_path: Path) -> None:
        parent = tmp_path / "docs"
        parent.mkdir()
        hidden = parent / "__docs_metadata"
        hidden.mkdir()

        assert _has_visible_children(parent, tmp_path) is False

        visible = parent / "guide.md"
        visible.write_text("content", encoding="utf-8")

        assert _has_visible_children(parent, tmp_path) is True

    def test_load_metadata_handles_missing_and_invalid(self, tmp_path: Path) -> None:
        metadata_root = tmp_path / "__docs_metadata"
        metadata_root.mkdir()

        relative_path = Path("guide/readme.md")
        meta_path = metadata_root / "guide"
        meta_path.mkdir(parents=True)
        (meta_path / "readme.meta.json").write_text('{"title": "Guide"}', encoding="utf-8")

        data = _load_metadata_for_relative_path(metadata_root, relative_path)
        assert data == {"title": "Guide"}

        bad_file = metadata_root / "guide/broken.meta.json"
        bad_file.write_text("{invalid", encoding="utf-8")
        assert _load_metadata_for_relative_path(metadata_root, Path("guide/broken.md")) is None

        missing_root = tmp_path / "missing"
        assert _load_metadata_for_relative_path(missing_root, relative_path) is None

    def test_build_browse_nodes_respects_depth_and_metadata(self, tmp_path: Path) -> None:
        storage_root = tmp_path / "docs"
        storage_root.mkdir()
        metadata_root = storage_root / "__docs_metadata"
        metadata_root.mkdir()

        guide_dir = storage_root / "guide"
        guide_dir.mkdir()
        readme = guide_dir / "README.md"
        readme.write_text("# Intro", encoding="utf-8")
        chapter_dir = guide_dir / "chapter-1"
        chapter_dir.mkdir()
        (chapter_dir / "topic.md").write_text("# Topic", encoding="utf-8")

        staging_dir = storage_root / ".staging_1234"
        staging_dir.mkdir()

        hashed = storage_root / ("b" * 64 + ".md")
        hashed.write_text("# hashed", encoding="utf-8")

        (metadata_root / "guide").mkdir(parents=True, exist_ok=True)
        (metadata_root / "guide.meta.json").write_text(
            '{"title": "Guide", "url": "https://example.com/guide"}',
            encoding="utf-8",
        )
        (metadata_root / "guide/README.meta.json").write_text('{"title": "Guide Intro"}', encoding="utf-8")
        (metadata_root / "guide/chapter-1.meta.json").write_text('{"title": "Chapter 1"}', encoding="utf-8")

        nodes = _build_browse_nodes(storage_root, storage_root, metadata_root, depth=2)
        assert len(nodes) == 1
        guide_node = nodes[0]
        assert guide_node.name == "guide"
        assert guide_node.title == "Guide"
        assert guide_node.url == "https://example.com/guide"
        assert guide_node.has_children is True
        assert guide_node.children is not None
        assert len(guide_node.children) == 2  # README + chapter directory
        child_names = {child.name for child in guide_node.children}
        assert {"README.md", "chapter-1"} == child_names

        depth_one_nodes = _build_browse_nodes(storage_root, storage_root, metadata_root, depth=1)
        assert depth_one_nodes[0].children is None

        assert _build_browse_nodes(storage_root, storage_root, metadata_root, depth=0) == []

        assert MAX_BROWSE_DEPTH >= 5  # sanity check constant accessible for future tests

    def test_build_browse_nodes_handles_valueerror_relative_to(self, tmp_path: Path, monkeypatch) -> None:
        """Handle ValueError when entry.relative_to(storage_root) fails."""
        storage_root = tmp_path / "docs"
        storage_root.mkdir()
        metadata_root = storage_root / "__docs_metadata"
        metadata_root.mkdir()

        # Create a regular file that should be processed
        regular_file = storage_root / "doc.md"
        regular_file.write_text("# doc", encoding="utf-8")

        # Mock Path.relative_to to raise ValueError for this specific file
        def mock_relative_to(self, other, *args, **kwargs):
            if self == regular_file:
                raise ValueError("Not within the tree")
            return Path.relative_to(self, other, *args, **kwargs)

        monkeypatch.setattr("pathlib.Path.relative_to", mock_relative_to)

        # Should skip the entry that causes ValueError but process others
        nodes = _build_browse_nodes(storage_root, storage_root, metadata_root, depth=1)
        # The first entry (doc.md) should be skipped due to ValueError, no other entries
        assert len(nodes) == 0
