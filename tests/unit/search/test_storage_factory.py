"""Tests for storage factory module."""

from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from docs_mcp_server.search.storage_factory import (
    create_segment_store,
    get_latest_doc_count,
    has_search_index,
)


class TestStorageFactory:
    """Test storage factory functions."""

    def test_create_segment_store(self):
        """Test creating a segment store."""
        with tempfile.TemporaryDirectory() as temp_dir:
            segments_dir = Path(temp_dir)

            store = create_segment_store(segments_dir)

            # Should return a SqliteSegmentStore instance
            assert store is not None
            assert hasattr(store, "directory")
            assert store.directory == segments_dir

    def test_create_segment_store_with_kwargs(self):
        """Test creating segment store with additional kwargs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            segments_dir = Path(temp_dir)

            # Should ignore extra kwargs
            store = create_segment_store(segments_dir, extra_param="ignored")

            assert store is not None
            assert store.directory == segments_dir

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_get_latest_doc_count_success(self, mock_create_store):
        """Test getting latest document count successfully."""
        mock_store = Mock()
        mock_store.latest_doc_count.return_value = 42
        mock_create_store.return_value = mock_store

        segments_dir = Path("/fake/path")

        result = get_latest_doc_count(segments_dir)

        assert result == 42
        mock_create_store.assert_called_once_with(segments_dir)
        mock_store.latest_doc_count.assert_called_once()

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_get_latest_doc_count_none(self, mock_create_store):
        """Test getting latest document count when None."""
        mock_store = Mock()
        mock_store.latest_doc_count.return_value = None
        mock_create_store.return_value = mock_store

        segments_dir = Path("/fake/path")

        result = get_latest_doc_count(segments_dir)

        assert result is None

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_get_latest_doc_count_with_kwargs(self, mock_create_store):
        """Test getting latest document count with kwargs."""
        mock_store = Mock()
        mock_store.latest_doc_count.return_value = 100
        mock_create_store.return_value = mock_store

        segments_dir = Path("/fake/path")

        result = get_latest_doc_count(segments_dir, extra_param="ignored")

        assert result == 100

    def test_has_search_index_directory_not_exists(self):
        """Test has_search_index when directory doesn't exist."""
        non_existent_dir = Path("/non/existent/directory")

        result = has_search_index(non_existent_dir)

        assert result is False

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_has_search_index_no_segments(self, mock_create_store):
        """Test has_search_index when no segments exist."""
        mock_store = Mock()
        mock_store.latest_segment_id.return_value = None
        mock_create_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as temp_dir:
            segments_dir = Path(temp_dir)

            result = has_search_index(segments_dir)

            assert result is False
            mock_create_store.assert_called_once_with(segments_dir)
            mock_store.latest_segment_id.assert_called_once()

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_has_search_index_with_segments(self, mock_create_store):
        """Test has_search_index when segments exist."""
        mock_store = Mock()
        mock_store.latest_segment_id.return_value = "segment_123"
        mock_create_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as temp_dir:
            segments_dir = Path(temp_dir)

            result = has_search_index(segments_dir)

            assert result is True

    @patch("docs_mcp_server.search.storage_factory.create_segment_store")
    def test_has_search_index_with_kwargs(self, mock_create_store):
        """Test has_search_index with kwargs."""
        mock_store = Mock()
        mock_store.latest_segment_id.return_value = "segment_456"
        mock_create_store.return_value = mock_store

        with tempfile.TemporaryDirectory() as temp_dir:
            segments_dir = Path(temp_dir)

            result = has_search_index(segments_dir, extra_param="ignored")

            assert result is True
