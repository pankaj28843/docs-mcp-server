"""Tests for storage factory."""

from pathlib import Path
import tempfile

from docs_mcp_server.search.storage_factory import create_segment_store, get_latest_doc_count, has_search_index


class TestStorageFactory:
    """Test storage factory functionality."""

    def test_create_segment_store(self):
        """Test creating segment store."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            store = create_segment_store(segments_dir)

            assert store is not None
            assert hasattr(store, "latest_doc_count")

    def test_get_latest_doc_count_empty(self):
        """Test getting document count from empty directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            count = get_latest_doc_count(segments_dir)

            assert count is None

    def test_has_search_index_nonexistent_dir(self):
        """Test checking search index in non-existent directory."""
        nonexistent_dir = Path("/nonexistent/path")

        result = has_search_index(nonexistent_dir)

        assert result is False

    def test_has_search_index_empty_dir(self):
        """Test checking search index in empty directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            result = has_search_index(segments_dir)

            assert result is False

    def test_create_segment_store_with_kwargs(self):
        """Test creating segment store with additional kwargs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            store = create_segment_store(segments_dir, extra_param="value")

            assert store is not None

    def test_get_latest_doc_count_with_kwargs(self):
        """Test getting document count with additional kwargs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            count = get_latest_doc_count(segments_dir, extra_param="value")

            assert count is None

    def test_has_search_index_with_kwargs(self):
        """Test checking search index with additional kwargs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            segments_dir = Path(tmp_dir)

            result = has_search_index(segments_dir, extra_param="value")

            assert result is False
