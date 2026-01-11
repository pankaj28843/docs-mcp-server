"""Unit tests for SIMD-optimized search index implementation."""

from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.simd_index import SIMDSearchIndex


@pytest.mark.unit
class TestSIMDSearchIndex:
    """Test SIMD-optimized search index with vectorized BM25 scoring."""

    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Create mock database path."""
        return tmp_path / "search.db"

    def _setup_db_mocks(self, mock_connect):
        """Helper to setup database mocking consistently."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("Test Title", "http://test.com", "Test content", 1.0, 2.0, 1.5, 100, 150)]
        mock_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))
        mock_connect.return_value = mock_conn
        return mock_conn

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_init_creates_connection_with_simd_optimizations(self, mock_connect, mock_db_path):
        """Test initialization creates connection with SIMD optimizations."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = SIMDSearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)
        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")
        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -4000")
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 16777216")
        assert index.db_path == mock_db_path

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    @patch("docs_mcp_server.search.simd_index.get_analyzer")
    def test_search_with_empty_query(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_analyzer.return_value = lambda x: []

        index = SIMDSearchIndex(mock_db_path)
        result = index.search("")

        assert result.results == []

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    @patch("docs_mcp_server.search.simd_index.get_analyzer")
    def test_search_with_rows_but_no_numpy_uses_fallback(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with database rows but no numpy uses fallback path."""
        mock_conn = self._setup_db_mocks(mock_connect)

        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer.return_value = lambda x: [mock_token]

        # Ensure HAS_NUMPY is False to force fallback
        with patch("docs_mcp_server.search.simd_index.HAS_NUMPY", False):
            index = SIMDSearchIndex(mock_db_path)
            result = index.search("test")

            assert len(result.results) == 1
            assert result.results[0].document_title == "Test Title"
            assert result.results[0].match_trace.stage_name == "fallback"

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    @patch("docs_mcp_server.search.simd_index.get_analyzer")
    @patch("docs_mcp_server.search.simd_index.HAS_NUMPY", False)
    def test_search_without_numpy_uses_fallback(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search without numpy uses fallback path."""
        mock_conn = self._setup_db_mocks(mock_connect)

        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer.return_value = lambda x: [mock_token]

        index = SIMDSearchIndex(mock_db_path)
        result = index.search("test")

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].match_trace.stage_name == "fallback"

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    @patch("docs_mcp_server.search.simd_index.get_analyzer")
    def test_search_with_no_rows_uses_fallback(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with no database rows uses fallback path."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []  # No rows
        mock_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))
        mock_connect.return_value = mock_conn

        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer.return_value = lambda x: [mock_token]

        index = SIMDSearchIndex(mock_db_path)
        result = index.search("test")

        assert len(result.results) == 1
        assert result.results[0].match_trace.stage_name == "fallback"

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_fallback_search_executes_query(self, mock_connect, mock_db_path):
        """Test fallback_search executes database query correctly."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = SIMDSearchIndex(mock_db_path)
        result = index._fallback_search(["test"], 10)

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].match_trace.stage_name == "fallback"

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_build_snippet_with_content_and_tokens(self, mock_connect, mock_db_path):
        """Test snippet building with content and matching tokens."""
        index = SIMDSearchIndex(mock_db_path)
        content = "This is a test content with some important information."
        tokens = ["test", "important"]

        snippet = index._build_snippet(content, tokens)

        assert "test" in snippet.lower()
        assert len(snippet) <= 200

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_build_snippet_with_empty_content(self, mock_connect, mock_db_path):
        """Test snippet building with empty content."""
        index = SIMDSearchIndex(mock_db_path)

        snippet = index._build_snippet("", ["test"])
        assert snippet == ""

        snippet = index._build_snippet(None, ["test"])
        assert snippet == ""

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_close_closes_connection(self, mock_connect, mock_db_path):
        """Test close method closes database connection."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = SIMDSearchIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None

    @patch("docs_mcp_server.search.simd_index.sqlite3.connect")
    def test_simd_optimization_pragmas(self, mock_connect, mock_db_path):
        """Test SIMD-specific SQLite optimizations are applied."""
        mock_conn = self._setup_db_mocks(mock_connect)

        SIMDSearchIndex(mock_db_path)

        # Verify SIMD-specific optimizations
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 16777216")  # 16MB mmap
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -4000")  # 4MB cache
