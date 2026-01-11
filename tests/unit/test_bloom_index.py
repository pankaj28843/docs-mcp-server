"""Unit tests for bloom filter search index implementation."""

from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.bloom_index import BloomFilterIndex


@pytest.mark.unit
class TestBloomFilterIndex:
    """Test bloom filter search index with negative query filtering."""

    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Create mock database path."""
        return tmp_path / "search.db"

    def _setup_db_mocks(self, mock_connect):
        """Helper to setup database mocking consistently."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        # Mock for build_bloom_filter query
        mock_cursor.__iter__ = Mock(return_value=iter([("test_term",), ("another_term",)]))
        mock_connect.return_value = mock_conn
        return mock_conn

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_init_creates_connection_and_bloom_filter(self, mock_connect, mock_db_path):
        """Test initialization creates connection and builds bloom filter."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path, bloom_size=8000)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)
        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")
        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -4000")
        assert index.bloom_size == 8000
        assert len(index._bloom_filter) == 1000  # 8000 // 8

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_add_to_bloom_sets_bits(self, mock_connect, mock_db_path):
        """Test adding terms to bloom filter sets appropriate bits."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path, bloom_size=8000)

        # Bloom filter should have some bits set from initialization
        assert any(b != 0 for b in index._bloom_filter)

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_might_exist_returns_true_for_added_terms(self, mock_connect, mock_db_path):
        """Test might_exist returns True for terms that were added."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path)

        # Terms from mock setup should exist
        assert index._might_exist("test_term") is True

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    @patch("docs_mcp_server.search.bloom_index.get_analyzer")
    def test_search_with_empty_query(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_analyzer.return_value = lambda x: []

        index = BloomFilterIndex(mock_db_path)
        result = index.search("")

        assert result.results == []

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    @patch("docs_mcp_server.search.bloom_index.get_analyzer")
    def test_search_with_non_existing_terms(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with terms that don't exist in bloom filter."""
        mock_conn = self._setup_db_mocks(mock_connect)

        # Mock analyzer to return tokens that won't exist in bloom filter
        mock_token = Mock()
        mock_token.text = "nonexistent_term_xyz"
        mock_analyzer.return_value = lambda x: [mock_token]

        index = BloomFilterIndex(mock_db_path)
        result = index.search("nonexistent query")

        assert result.results == []

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    @patch("docs_mcp_server.search.bloom_index.get_analyzer")
    def test_search_with_existing_terms(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with terms that exist returns results."""
        mock_conn = Mock()

        # Mock for build_bloom_filter (first execute call)
        mock_build_cursor = Mock()
        mock_build_cursor.__iter__ = Mock(return_value=iter([("test_term",), ("another_term",)]))

        # Mock for search query (later execute call)
        mock_search_cursor = Mock()
        mock_search_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))

        # Set up execute to return build cursor first, then search cursor
        def execute_side_effect(*args, **kwargs):
            if "DISTINCT term" in args[0]:
                return mock_build_cursor
            return mock_search_cursor

        mock_conn.execute.side_effect = execute_side_effect
        mock_connect.return_value = mock_conn

        # Mock analyzer to return existing token
        mock_token = Mock()
        mock_token.text = "test_term"
        mock_analyzer.return_value = lambda x: [mock_token]

        index = BloomFilterIndex(mock_db_path)
        result = index.search("test query")

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].document_url == "http://test.com"
        assert result.results[0].relevance_score == 1.5
        assert result.results[0].match_trace.stage == 1
        assert result.results[0].match_trace.stage_name == "bloom_filtered"

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_build_snippet_with_content_and_tokens(self, mock_connect, mock_db_path):
        """Test snippet building with content and matching tokens."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path)
        content = "This is a test content with some important information about testing."
        tokens = ["test", "important"]

        snippet = index._build_snippet(content, tokens)

        assert "test" in snippet.lower()
        assert len(snippet) <= 200

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_build_snippet_with_empty_content(self, mock_connect, mock_db_path):
        """Test snippet building with empty content."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path)

        snippet = index._build_snippet("", ["test"])
        assert snippet == ""

        snippet = index._build_snippet(None, ["test"])
        assert snippet == ""

    @patch("docs_mcp_server.search.bloom_index.sqlite3.connect")
    def test_close_closes_connection(self, mock_connect, mock_db_path):
        """Test close method closes database connection."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = BloomFilterIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None
