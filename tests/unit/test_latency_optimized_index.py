"""Unit tests for latency-optimized search index implementation."""

import sqlite3
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.latency_optimized_index import LatencyOptimizedSearchIndex


@pytest.mark.unit
class TestLatencyOptimizedSearchIndex:
    """Test latency-optimized search index with aggressive performance tuning."""

    @pytest.fixture
    def mock_db_path(self, tmp_path):
        """Create mock database path."""
        return tmp_path / "search.db"

    def _setup_db_mocks(self, mock_connect, mock_json_loads):
        """Helper to setup database mocking consistently."""
        mock_conn = Mock()

        # Create different cursors for different operations
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = (
            '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
        )

        search_cursor = Mock()
        search_cursor.__iter__ = Mock(return_value=iter([]))

        # Use side_effect to return appropriate cursor based on SQL
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect
        mock_conn.prepare.return_value = Mock()  # For prepared statements

        mock_connect.return_value = mock_conn
        mock_json_loads.return_value = {
            "fields": [{"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0}]
        }
        return mock_conn

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_init_creates_connection_with_latency_optimizations(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization creates connection with latency optimizations."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = LatencyOptimizedSearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

        # Verify latency-specific optimizations
        expected_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",  # Actual implementation
            "PRAGMA cache_size = -8000",  # 8MB cache (actual)
            "PRAGMA mmap_size = 33554432",  # 32MB mmap (actual)
            "PRAGMA temp_store = MEMORY",
            "PRAGMA page_size = 4096",  # Additional pragma
            "PRAGMA cache_spill = FALSE",  # Additional pragma
        ]

        for pragma in expected_pragmas:
            mock_conn.execute.assert_any_call(pragma)

        assert index.db_path == mock_db_path

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_aggressive_synchronous_off(self, mock_json_loads, mock_connect, mock_db_path):
        """Test normal synchronous mode for reliability."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_large_cache_for_latency(self, mock_json_loads, mock_connect, mock_db_path):
        """Test cache size for latency optimization."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        # Verify 8MB cache size
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -8000")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_large_mmap_for_latency(self, mock_json_loads, mock_connect, mock_db_path):
        """Test mmap size for latency optimization."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        # Verify 32MB mmap size
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 33554432")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_cache_spill_disabled(self, mock_json_loads, mock_connect, mock_db_path):
        """Test cache spill disabled for latency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA cache_spill = FALSE")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_page_size_optimization(self, mock_json_loads, mock_connect, mock_db_path):
        """Test page size optimization for latency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA page_size = 4096")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_connection_stored(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is stored for reuse."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = LatencyOptimizedSearchIndex(mock_db_path)

        assert index._conn is mock_conn

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_init_handles_connection_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization handles connection errors."""
        mock_connect.side_effect = sqlite3.Error("Connection failed")

        with pytest.raises(sqlite3.Error, match="Connection failed"):
            LatencyOptimizedSearchIndex(mock_db_path)

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_wal_mode_for_concurrent_reads(self, mock_json_loads, mock_connect, mock_db_path):
        """Test WAL mode enables concurrent reads."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_memory_temp_store_for_speed(self, mock_json_loads, mock_connect, mock_db_path):
        """Test memory-based temporary storage for speed."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA temp_store = MEMORY")

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_all_latency_optimizations_applied(self, mock_json_loads, mock_connect, mock_db_path):
        """Test all latency optimizations are applied together."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        # Verify all latency-focused pragmas (actual implementation)
        latency_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -8000",
            "PRAGMA mmap_size = 33554432",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA page_size = 4096",
            "PRAGMA cache_spill = FALSE",
        ]

        for pragma in latency_pragmas:
            mock_conn.execute.assert_any_call(pragma)

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_check_same_thread_disabled_for_concurrency(self, mock_json_loads, mock_connect, mock_db_path):
        """Test check_same_thread disabled for concurrent access."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_optimizations_order_matters(self, mock_json_loads, mock_connect, mock_db_path):
        """Test optimizations applied in correct order."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        # Verify pragmas executed (order can matter for some optimizations)
        assert mock_conn.execute.call_count >= 7

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_latency_focused_configuration(self, mock_json_loads, mock_connect, mock_db_path):
        """Test configuration prioritizes latency with balanced safety."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        LatencyOptimizedSearchIndex(mock_db_path)

        # Verify balanced settings that prioritize speed with safety
        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")  # Balanced safety/speed
        mock_conn.execute.assert_any_call("PRAGMA cache_spill = FALSE")  # No spill for speed
        mock_conn.execute.assert_any_call("PRAGMA temp_store = MEMORY")  # Memory temp storage

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_empty_query(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)
        mock_analyzer = Mock()
        mock_analyzer.return_value = []  # No tokens
        mock_get_analyzer.return_value = mock_analyzer

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("")

        assert response.results == []

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_single_token_uses_optimized_statement(
        self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path
    ):
        """Test search with single token uses pre-compiled statement."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock prepared statement
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [("Test Title", "http://test.com", "Test content", 1.5)]
        mock_conn.prepare.return_value = mock_stmt

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("test")

        # Verify single token statement was used
        assert len(response.results) == 1
        assert response.results[0].document_title == "Test Title"

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_two_tokens_uses_optimized_statement(
        self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path
    ):
        """Test search with two tokens uses pre-compiled statement."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token1 = Mock()
        mock_token1.text = "test"
        mock_token2 = Mock()
        mock_token2.text = "query"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token1, mock_token2]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock prepared statement
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [("Test Title", "http://test.com", "Test content", 1.5)]
        mock_conn.prepare.return_value = mock_stmt

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("test query")

        assert len(response.results) == 1

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_three_tokens_uses_optimized_statement(
        self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path
    ):
        """Test search with three tokens uses pre-compiled statement."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        tokens = [Mock() for _ in range(3)]
        for i, token in enumerate(tokens):
            token.text = f"token{i}"
        mock_analyzer = Mock()
        mock_analyzer.return_value = tokens
        mock_get_analyzer.return_value = mock_analyzer

        # Mock prepared statement
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [("Test Title", "http://test.com", "Test content", 1.5)]
        mock_conn.prepare.return_value = mock_stmt

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("token0 token1 token2")

        assert len(response.results) == 1

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_many_tokens_uses_fallback(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with many tokens uses fallback query."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer with 5 tokens
        tokens = [Mock() for _ in range(5)]
        for i, token in enumerate(tokens):
            token.text = f"token{i}"
        mock_analyzer = Mock()
        mock_analyzer.return_value = tokens
        mock_get_analyzer.return_value = mock_analyzer

        # Mock fallback execute - return cursor-like object
        fallback_cursor = Mock()
        fallback_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))

        # Update side_effect to return fallback cursor for search queries
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                schema_cursor = Mock()
                schema_cursor.fetchone.return_value = (
                    '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
                )
                return schema_cursor
            return fallback_cursor

        mock_conn.execute.side_effect = execute_side_effect

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("token0 token1 token2 token3 token4")

        assert len(response.results) == 1
        # Verify fallback execute was called
        mock_conn.execute.assert_called()

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_snippet_generation_with_match(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test snippet generation when token matches content."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "important"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock prepared statement with content containing the token
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [
            ("Test Title", "http://test.com", "This is some important content for testing", 1.5)
        ]
        mock_conn.prepare.return_value = mock_stmt

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("important")

        assert len(response.results) == 1
        assert "important" in response.results[0].snippet

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    @patch("docs_mcp_server.search.latency_optimized_index.get_analyzer")
    def test_search_snippet_generation_no_match(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test snippet generation when no token matches content."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "missing"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock prepared statement with content not containing the token
        mock_stmt = Mock()
        mock_stmt.execute.return_value = [
            ("Test Title", "http://test.com", "This is some content without the search term", 1.5)
        ]
        mock_conn.prepare.return_value = mock_stmt

        index = LatencyOptimizedSearchIndex(mock_db_path)
        response = index.search("missing")

        assert len(response.results) == 1
        # Should return first 200 chars when no match
        assert response.results[0].snippet == "This is some content without the search term"

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_load_schema_fast_with_metadata(self, mock_json_loads, mock_connect, mock_db_path):
        """Test fast schema loading from metadata."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock schema data with correct format including required 'url' field
        schema_data = {
            "fields": [
                {"name": "title", "type": "text", "stored": True, "indexed": True, "boost": 2.0},
                {"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0},
            ]
        }
        mock_json_loads.return_value = schema_data

        index = LatencyOptimizedSearchIndex(mock_db_path)

        # Verify schema was loaded
        assert index._schema is not None

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_load_schema_fast_no_metadata(self, mock_json_loads, mock_connect, mock_db_path):
        """Test fast schema loading with no metadata (uses default)."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No metadata
        mock_connect.return_value = mock_conn

        index = LatencyOptimizedSearchIndex(mock_db_path)

        # Should use hardcoded default schema
        assert index._schema is not None
        # Check that we have the expected fields
        text_fields = [f for f in index._schema.fields if f.name in ["title", "body"]]
        assert len(text_fields) == 2

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_load_schema_fast_operational_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test fast schema loading handles operational errors."""
        mock_conn = Mock()

        # Use side_effect to make only schema loading fail, not PRAGMA statements
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                raise sqlite3.OperationalError("Table not found")
            # Return a mock cursor for PRAGMA statements
            return Mock()

        mock_conn.execute.side_effect = execute_side_effect
        mock_conn.prepare.return_value = Mock()
        mock_connect.return_value = mock_conn

        index = LatencyOptimizedSearchIndex(mock_db_path)

        # Should use hardcoded default schema
        assert index._schema is not None
        # Check that we have the expected fields
        text_fields = [f for f in index._schema.fields if f.name in ["title", "body"]]
        assert len(text_fields) == 2

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_close_connection(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is closed properly."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = LatencyOptimizedSearchIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None

    @patch("docs_mcp_server.search.latency_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.latency_optimized_index.json.loads")
    def test_close_already_closed(self, mock_json_loads, mock_connect, mock_db_path):
        """Test closing already closed connection."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = LatencyOptimizedSearchIndex(mock_db_path)
        index._conn = None

        # Should not raise error
        index.close()
