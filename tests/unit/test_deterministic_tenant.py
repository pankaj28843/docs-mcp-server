"""Unit tests for deterministic search index implementation."""

import sqlite3
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deterministic_tenant import DeterministicSearchIndex, DeterministicTenant


@pytest.mark.unit
class TestDeterministicSearchIndex:
    """Test deterministic search index with fixed behavior."""

    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Create mock database path."""
        return tmp_path / "search.db"

    def _setup_db_mocks(self, mock_connect):
        """Helper to setup database mocking consistently."""
        mock_conn = Mock()
        mock_cursor = Mock()
        # Make cursor iterable - return empty list for timeout test
        mock_cursor.__iter__ = Mock(return_value=iter([]))
        mock_conn.execute.return_value = mock_cursor

        # Mock prepared statement that returns iterable cursor
        mock_stmt = Mock()
        mock_stmt.execute.return_value = iter([])  # Empty iterator for timeout test
        mock_conn.prepare.return_value = mock_stmt

        mock_connect.return_value = mock_conn
        return mock_conn

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_init_creates_connection_with_optimizations(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test initialization creates optimized SQLite connection."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path, max_results=50)

        # Verify connection created
        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

        # Verify SQLite optimizations applied
        expected_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -4000",
            "PRAGMA mmap_size = 16777216",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA cache_spill = FALSE",
        ]

        for pragma in expected_pragmas:
            mock_conn.execute.assert_any_call(pragma)

        assert index.db_path == mock_db_path

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_init_default_max_results(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test initialization with default max results."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)

        # Verify default max_results is 100
        assert index.max_results == 100

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_connection_stored_for_reuse(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test connection is stored for reuse."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)

        assert index._conn is mock_conn

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_init_handles_connection_error(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test initialization handles connection errors."""
        mock_connect.side_effect = sqlite3.Error("Connection failed")

        with pytest.raises(sqlite3.Error, match="Connection failed"):
            DeterministicSearchIndex(mock_db_path)

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_fixed_cache_size_configuration(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test fixed cache size for deterministic behavior."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        # Verify fixed 4MB cache size
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -4000")

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_fixed_mmap_size_configuration(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test fixed mmap size for deterministic behavior."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        # Verify fixed 16MB mmap size
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 16777216")

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_memory_temp_store_configuration(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test memory temp store for deterministic behavior."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA temp_store = MEMORY")

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_cache_spill_disabled(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test cache spill disabled for deterministic behavior."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA cache_spill = FALSE")

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_token_buffer_pre_allocation(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test token buffer is pre-allocated."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)

        # Verify token buffer
        assert len(index._token_buffer) == 10
        assert all(token == "" for token in index._token_buffer)

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_deterministic_configuration_eliminates_variability(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test deterministic configuration eliminates performance variability."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        # Verify deterministic settings
        deterministic_pragmas = [
            "PRAGMA cache_size = -4000",  # Fixed cache
            "PRAGMA mmap_size = 16777216",  # Fixed mmap
            "PRAGMA cache_spill = FALSE",  # No spill variability
            "PRAGMA temp_store = MEMORY",  # Consistent temp storage
        ]

        for pragma in deterministic_pragmas:
            mock_conn.execute.assert_any_call(pragma)

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_statement_preparation(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test search statement is prepared for deterministic execution."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        DeterministicSearchIndex(mock_db_path)

        # Verify statement preparation
        mock_conn.prepare.assert_called_once()

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_analyzer_pre_loading(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test analyzer is pre-loaded for deterministic behavior."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_analyzer = Mock()
        mock_get_analyzer.return_value = mock_analyzer

        index = DeterministicSearchIndex(mock_db_path)

        # Verify analyzer pre-loading
        mock_get_analyzer.assert_called_once_with("default")
        assert index._analyzer is mock_analyzer

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    @patch("docs_mcp_server.deterministic_tenant.time.perf_counter")
    def test_search_empty_query_returns_empty_response(self, mock_time, mock_get_analyzer, mock_connect, mock_db_path):
        """Test search with empty query returns empty response."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_analyzer = Mock()
        mock_analyzer.return_value = []  # No tokens
        mock_get_analyzer.return_value = mock_analyzer
        mock_time.return_value = 0.001

        index = DeterministicSearchIndex(mock_db_path)
        response = index.search("")

        assert response.results == []

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    @patch("docs_mcp_server.deterministic_tenant.time.perf_counter")
    def test_search_with_results(self, mock_time, mock_get_analyzer, mock_connect, mock_db_path):
        """Test search returns results correctly."""
        mock_conn = self._setup_db_mocks(mock_connect)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock time
        mock_time.return_value = 0.001

        # Mock prepared statement execution
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [("Test Title", "http://test.com", "Test content", 1.5)]
        mock_conn.prepare.return_value = mock_stmt

        index = DeterministicSearchIndex(mock_db_path)
        response = index.search("test")

        assert len(response.results) == 1
        assert response.results[0].document_title == "Test Title"
        assert response.results[0].document_url == "http://test.com"
        assert response.results[0].relevance_score == 1.5

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    @patch("docs_mcp_server.deterministic_tenant.time.perf_counter")
    def test_search_timeout_handling(self, mock_time, mock_get_analyzer, mock_connect, mock_db_path):
        """Test search handles timeout correctly."""
        mock_conn = self._setup_db_mocks(mock_connect)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock time to exceed timeout
        mock_time.side_effect = [0.0, 0.006]  # Exceeds 5ms timeout

        index = DeterministicSearchIndex(mock_db_path)
        response = index.search("test")

        # Should return empty due to timeout
        assert response.results == []

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_build_snippet_deterministic_with_token_match(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test deterministic snippet building with token match."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)
        content = "This is a test content with some important information"
        tokens = ["test"]

        snippet = index._build_snippet_deterministic(content, tokens)

        # Should find "test" and build snippet around it
        assert "test" in snippet
        assert len(snippet) <= 200

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_build_snippet_deterministic_no_match(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test deterministic snippet building without token match."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)
        content = "This is content without the search term"
        tokens = ["missing"]

        snippet = index._build_snippet_deterministic(content, tokens)

        # Should return first 200 chars when no match
        assert snippet == content[:200]

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_build_snippet_deterministic_empty_content(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test deterministic snippet building with empty content."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)

        snippet = index._build_snippet_deterministic("", ["test"])
        assert snippet == ""

        snippet = index._build_snippet_deterministic("content", [])
        assert snippet == "content"

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_close_connection(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test connection is closed properly."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None

    @patch("docs_mcp_server.deterministic_tenant.sqlite3.connect")
    @patch("docs_mcp_server.deterministic_tenant.get_analyzer")
    def test_close_already_closed(self, mock_get_analyzer, mock_connect, mock_db_path):
        """Test closing already closed connection."""
        mock_conn = self._setup_db_mocks(mock_connect)
        mock_get_analyzer.return_value = Mock()

        index = DeterministicSearchIndex(mock_db_path)
        index._conn = None

        # Should not raise error
        index.close()


@pytest.mark.unit
class TestDeterministicTenant:
    """Test deterministic tenant implementation."""

    @pytest.fixture
    def mock_data_path(self, tmp_path):
        """Create mock data path."""
        return tmp_path / "tenant_data"

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    def test_init_with_existing_search_db(self, mock_search_index, mock_data_path):
        """Test initialization with existing search database."""
        # Setup search db path
        search_path = mock_data_path / "__search_segments" / "search.db"
        search_path.parent.mkdir(parents=True)
        search_path.touch()

        tenant = DeterministicTenant("test", str(mock_data_path))

        assert tenant.codename == "test"
        mock_search_index.assert_called_once_with(search_path)

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    def test_init_without_search_db(self, mock_search_index, mock_data_path):
        """Test initialization without search database."""
        tenant = DeterministicTenant("test", str(mock_data_path))

        assert tenant.codename == "test"
        assert tenant._search_index is None
        mock_search_index.assert_not_called()

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    def test_search_no_index(self, mock_search_index, mock_data_path):
        """Test search without search index."""
        tenant = DeterministicTenant("test", str(mock_data_path))

        result = tenant.search("query", 10, False)

        assert result["results"] == []
        assert result["error"] == "No search index for test"
        assert result["query"] == "query"

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    @patch("docs_mcp_server.deterministic_tenant.time.perf_counter")
    @patch("docs_mcp_server.deterministic_tenant.logger")
    def test_search_with_index_success(self, mock_logger, mock_time, mock_search_index, mock_data_path):
        """Test successful search with index."""
        # Setup search db path
        search_path = mock_data_path / "__search_segments" / "search.db"
        search_path.parent.mkdir(parents=True)
        search_path.touch()

        # Mock search response
        mock_result = Mock()
        mock_result.document_title = "Test Title"
        mock_result.document_url = "http://test.com"
        mock_result.snippet = "Test snippet"
        mock_result.relevance_score = 1.5

        mock_response = Mock()
        mock_response.results = [mock_result]

        mock_index = Mock()
        mock_index.search.return_value = mock_response
        mock_search_index.return_value = mock_index

        # Mock timing
        mock_time.side_effect = [0.0, 0.005]  # 5ms execution

        tenant = DeterministicTenant("test", str(mock_data_path))
        result = tenant.search("query", 10, False)

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Test Title"
        assert result["results"][0]["url"] == "http://test.com"
        assert result["results"][0]["snippet"] == "Test snippet"
        assert result["results"][0]["score"] == 1.5
        mock_index.search.assert_called_once_with("query", 10)

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    @patch("docs_mcp_server.deterministic_tenant.time.perf_counter")
    @patch("docs_mcp_server.deterministic_tenant.logger")
    def test_search_exceeds_deterministic_bound(self, mock_logger, mock_time, mock_search_index, mock_data_path):
        """Test search that exceeds deterministic time bound."""
        # Setup search db path
        search_path = mock_data_path / "__search_segments" / "search.db"
        search_path.parent.mkdir(parents=True)
        search_path.touch()

        mock_response = Mock()
        mock_response.results = []

        mock_index = Mock()
        mock_index.search.return_value = mock_response
        mock_search_index.return_value = mock_index

        # Mock timing to exceed 10ms bound
        mock_time.side_effect = [0.0, 0.015]  # 15ms execution

        tenant = DeterministicTenant("test", str(mock_data_path))
        tenant.search("query", 10, False)

        mock_logger.warning.assert_called_once_with("Search exceeded deterministic bound: 0.015s")

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    @patch("docs_mcp_server.deterministic_tenant.logger")
    def test_search_exception_handling(self, mock_logger, mock_search_index, mock_data_path):
        """Test search exception handling."""
        # Setup search db path
        search_path = mock_data_path / "__search_segments" / "search.db"
        search_path.parent.mkdir(parents=True)
        search_path.touch()

        mock_index = Mock()
        mock_index.search.side_effect = Exception("Search failed")
        mock_search_index.return_value = mock_index

        tenant = DeterministicTenant("test", str(mock_data_path))
        result = tenant.search("query", 10, False)

        assert result["results"] == []
        assert result["error"] == "Search failed"
        assert result["query"] == "query"
        mock_logger.error.assert_called_once_with("Deterministic search failed for test: Search failed")

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    def test_close_with_index(self, mock_search_index, mock_data_path):
        """Test closing tenant with search index."""
        # Setup search db path
        search_path = mock_data_path / "__search_segments" / "search.db"
        search_path.parent.mkdir(parents=True)
        search_path.touch()

        mock_index = Mock()
        mock_search_index.return_value = mock_index

        tenant = DeterministicTenant("test", str(mock_data_path))
        tenant.close()

        mock_index.close.assert_called_once()
        assert tenant._search_index is None

    @patch("docs_mcp_server.deterministic_tenant.DeterministicSearchIndex")
    def test_close_without_index(self, mock_search_index, mock_data_path):
        """Test closing tenant without search index."""
        tenant = DeterministicTenant("test", str(mock_data_path))

        # Should not raise error
        tenant.close()
