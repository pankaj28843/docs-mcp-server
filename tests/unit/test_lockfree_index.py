"""Unit tests for lock-free concurrent search index implementation."""

from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.search.lockfree_index import LockFreeSearchIndex


@pytest.mark.unit
class TestLockFreeSearchIndex:
    """Test lock-free search index with concurrent access patterns."""

    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Create mock database path."""
        return tmp_path / "search.db"

    def _setup_db_mocks(self, mock_connect):
        """Helper to setup database mocking consistently."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))
        mock_connect.return_value = mock_conn
        return mock_conn

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_init_creates_executor_and_analyzer(self, mock_connect, mock_db_path):
        """Test initialization creates thread pool executor and analyzer."""
        index = LockFreeSearchIndex(mock_db_path, max_workers=2)

        assert index.db_path == mock_db_path
        assert index.max_workers == 2
        assert index._executor is not None
        assert index._analyzer is not None

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_get_connection_creates_thread_local_connection(self, mock_connect, mock_db_path):
        """Test get_connection creates thread-local database connection."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = LockFreeSearchIndex(mock_db_path)
        conn = index._get_connection()

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)
        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")
        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -2000")
        assert conn is mock_conn

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    @patch("docs_mcp_server.search.lockfree_index.get_analyzer")
    def test_search_with_empty_query(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_analyzer.return_value = lambda x: []

        index = LockFreeSearchIndex(mock_db_path)
        result = index.search("")

        assert result.results == []

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    @patch("docs_mcp_server.search.lockfree_index.get_analyzer")
    def test_search_single_token_uses_single_search(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with single token uses single search path."""
        mock_conn = self._setup_db_mocks(mock_connect)

        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer.return_value = lambda x: [mock_token]

        index = LockFreeSearchIndex(mock_db_path)
        result = index.search("test")

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].match_trace.stage_name == "single"

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    @patch("docs_mcp_server.search.lockfree_index.get_analyzer")
    def test_search_multiple_tokens_uses_parallel_search(self, mock_analyzer, mock_connect, mock_db_path):
        """Test search with multiple tokens uses parallel search path."""
        mock_conn = self._setup_db_mocks(mock_connect)

        mock_tokens = [Mock(), Mock()]
        mock_tokens[0].text = "test"
        mock_tokens[1].text = "query"
        mock_analyzer.return_value = lambda x: mock_tokens

        index = LockFreeSearchIndex(mock_db_path, max_workers=2)

        # Mock the executor submit to return a future-like object
        mock_result = SearchResult(
            document_title="Test",
            document_url="http://test.com",
            snippet="test snippet",
            relevance_score=1.5,
            match_trace=MatchTrace(
                stage=1,
                stage_name="parallel",
                query_variant="chunk_search",
                match_reason="chunk",
                ranking_factors={"chunk_id": 0},
            ),
        )

        mock_future = Mock()
        mock_future.result.return_value = SearchResponse(results=[mock_result])
        index._executor.submit = Mock(return_value=mock_future)

        result = index.search("test query")

        assert index._executor.submit.called

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_search_chunk_executes_query(self, mock_connect, mock_db_path):
        """Test search_chunk executes database query correctly."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = LockFreeSearchIndex(mock_db_path)
        result = index._search_chunk(["test", "query"], 10)

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].match_trace.stage_name == "parallel"

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_single_search_executes_query(self, mock_connect, mock_db_path):
        """Test single_search executes database query correctly."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = LockFreeSearchIndex(mock_db_path)
        result = index._single_search(["test"], 10)

        assert len(result.results) == 1
        assert result.results[0].document_title == "Test Title"
        assert result.results[0].match_trace.stage_name == "single"

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_build_snippet_with_content_and_tokens(self, mock_connect, mock_db_path):
        """Test snippet building with content and matching tokens."""
        index = LockFreeSearchIndex(mock_db_path)
        content = "This is a test content with some important information."
        tokens = ["test", "important"]

        snippet = index._build_snippet(content, tokens)

        assert "test" in snippet.lower()
        assert len(snippet) <= 200

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_build_snippet_with_empty_content(self, mock_connect, mock_db_path):
        """Test snippet building with empty content."""
        index = LockFreeSearchIndex(mock_db_path)

        snippet = index._build_snippet("", ["test"])
        assert snippet == ""

        snippet = index._build_snippet(None, ["test"])
        assert snippet == ""

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_close_shuts_down_executor(self, mock_connect, mock_db_path):
        """Test close method shuts down thread pool executor."""
        index = LockFreeSearchIndex(mock_db_path)
        index._executor.shutdown = Mock()

        index.close()

        index._executor.shutdown.assert_called_once_with(wait=True)

    @patch("docs_mcp_server.search.lockfree_index.sqlite3.connect")
    def test_close_closes_thread_local_connection(self, mock_connect, mock_db_path):
        """Test close method closes thread-local connection if exists."""
        mock_conn = self._setup_db_mocks(mock_connect)

        index = LockFreeSearchIndex(mock_db_path)
        # Trigger connection creation
        index._get_connection()

        index.close()

        mock_conn.close.assert_called_once()
