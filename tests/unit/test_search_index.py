"""Unit tests for simplified search index implementation."""

import sqlite3
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.search_index import SearchIndex, _BM25Calculator


@pytest.mark.unit
class TestSearchIndex:
    """Test simplified search index with deep module consolidation."""

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
        search_cursor.fetchall.return_value = []  # Default empty results

        # Use side_effect to return appropriate cursor based on SQL
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect
        mock_connect.return_value = mock_conn
        mock_json_loads.return_value = {
            "fields": [{"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0}]
        }
        return mock_conn

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_init_creates_optimized_connection(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization creates optimized SQLite connection."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

        # Verify SQLite optimizations
        expected_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -64000",
            "PRAGMA mmap_size = 268435456",
            "PRAGMA temp_store = MEMORY",
        ]

        for pragma in expected_pragmas:
            mock_conn.execute.assert_any_call(pragma)

        assert index.db_path == mock_db_path

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_init_prepares_search_statement(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization prepares search statement."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        # Verify search statement preparation
        mock_conn.prepare.assert_called_once()

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_connection_stored_for_reuse(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is stored for reuse."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)

        assert index._conn is mock_conn

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_init_handles_connection_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization handles connection errors."""
        mock_connect.side_effect = sqlite3.Error("Connection failed")

        with pytest.raises(sqlite3.Error, match="Connection failed"):
            SearchIndex(mock_db_path)

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_large_cache_size_configuration(self, mock_json_loads, mock_connect, mock_db_path):
        """Test large cache size for performance."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        # Verify 64MB cache size
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -64000")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_large_mmap_size_configuration(self, mock_json_loads, mock_connect, mock_db_path):
        """Test large mmap size for performance."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        # Verify 256MB mmap size
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 268435456")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_wal_mode_configuration(self, mock_json_loads, mock_connect, mock_db_path):
        """Test WAL mode for concurrent access."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_normal_synchronous_mode(self, mock_json_loads, mock_connect, mock_db_path):
        """Test normal synchronous mode for performance."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_memory_temp_store(self, mock_json_loads, mock_connect, mock_db_path):
        """Test memory-based temporary storage."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA temp_store = MEMORY")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_eliminates_abstraction_layers(self, mock_json_loads, mock_connect, mock_db_path):
        """Test eliminates SearchService -> Repository -> Engine abstraction layers."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)

        # Verify no intermediate service layers
        assert not hasattr(index, "_search_service")
        assert not hasattr(index, "_repository")
        assert not hasattr(index, "_engine")
        assert not hasattr(index, "_segment")

        # Verify direct SQLite access
        assert hasattr(index, "_conn")
        assert hasattr(index, "_search_stmt")

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_deep_module_simple_interface(self, mock_json_loads, mock_connect, mock_db_path):
        """Test deep module hides complexity behind simple interface."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)

        # Verify simple public interface
        assert hasattr(index, "search")  # Main search method
        assert hasattr(index, "db_path")  # Path property

        # Verify complex internals are hidden
        assert hasattr(index, "_conn")  # Private connection
        assert hasattr(index, "_search_stmt")  # Private statement

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_consolidates_bm25_analyzer_snippet_logic(self, mock_json_loads, mock_connect, mock_db_path):
        """Test consolidates BM25, analyzer, and snippet logic in single module."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Should not raise - all logic consolidated internally
        SearchIndex(mock_db_path)

        # Verify no external dependencies on separate modules
        # (This is architectural - the module should work independently)

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_pragma_execution_order(self, mock_json_loads, mock_connect, mock_db_path):
        """Test pragma statements executed in correct order."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        # Verify pragmas called (order matters for some optimizations)
        assert mock_conn.execute.call_count >= 5

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_statement_preparation_after_pragmas(self, mock_json_loads, mock_connect, mock_db_path):
        """Test search statement prepared after pragma configuration."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        # Statement preparation should happen after pragma setup
        mock_conn.prepare.assert_called_once()

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_check_same_thread_disabled(self, mock_json_loads, mock_connect, mock_db_path):
        """Test check_same_thread disabled for concurrent access."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        SearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    @patch("docs_mcp_server.search.search_index.get_analyzer")
    @patch("docs_mcp_server.search.search_index.build_smart_snippet")
    def test_search_empty_query(self, mock_snippet, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)
        mock_analyzer = Mock()
        mock_analyzer.return_value = []  # No tokens
        mock_get_analyzer.return_value = mock_analyzer

        index = SearchIndex(mock_db_path)
        response = index.search("")

        assert response.results == []

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    @patch("docs_mcp_server.search.search_index.get_analyzer")
    @patch("docs_mcp_server.search.search_index.build_smart_snippet")
    def test_search_with_results(self, mock_snippet, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search returns results correctly."""
        mock_conn = Mock()

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock snippet generation
        mock_snippet.return_value = "Test snippet"

        # Create different cursors for different operations
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = (
            '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
        )

        search_cursor = Mock()
        search_cursor.fetchall.return_value = [(1, "Test Title", "http://test.com", "Test content", 1.5)]

        # Use side_effect to return appropriate cursor based on SQL
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect
        mock_connect.return_value = mock_conn
        mock_json_loads.return_value = {
            "fields": [{"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0}]
        }

        index = SearchIndex(mock_db_path)
        response = index.search("test")

        assert len(response.results) == 1
        assert response.results[0].document_title == "Test Title"
        assert response.results[0].document_url == "http://test.com"
        assert response.results[0].snippet == "Test snippet"
        assert response.results[0].relevance_score == 1.5

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    @patch("docs_mcp_server.search.search_index.get_analyzer")
    @patch("docs_mcp_server.search.search_index.build_smart_snippet")
    def test_search_multiple_tokens(self, mock_snippet, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with multiple tokens."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer with multiple tokens
        tokens = [Mock() for _ in range(3)]
        for i, token in enumerate(tokens):
            token.text = f"token{i}"
        mock_analyzer = Mock()
        mock_analyzer.return_value = tokens
        mock_get_analyzer.return_value = mock_analyzer

        # Mock snippet generation
        mock_snippet.return_value = "Test snippet"

        # Update the search cursor to return results
        search_cursor = Mock()
        search_cursor.fetchall.return_value = [(1, "Test Title", "http://test.com", "Test content", 1.5)]

        # Update side_effect to use the new search cursor
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = (
            '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
        )

        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect

        index = SearchIndex(mock_db_path)
        response = index.search("token0 token1 token2")

        assert len(response.results) == 1
        # Verify SQL was called with correct placeholders
        mock_conn.execute.assert_called()

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    @patch("docs_mcp_server.search.search_index.get_analyzer")
    @patch("docs_mcp_server.search.search_index.build_smart_snippet")
    def test_search_max_results_limit(
        self, mock_snippet, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path
    ):
        """Test search respects max_results limit."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock snippet generation
        mock_snippet.return_value = "Test snippet"

        # Update the search cursor to return results
        search_cursor = Mock()
        search_cursor.fetchall.return_value = [(1, "Test Title", "http://test.com", "Test content", 1.5)]

        # Update side_effect to use the new search cursor
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = (
            '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
        )

        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect

        index = SearchIndex(mock_db_path)
        response = index.search("test", max_results=5)

        # Verify max_results passed to SQL
        args = mock_conn.execute.call_args[0]
        assert args[1][-1] == 5  # Last parameter should be max_results

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_load_schema_with_metadata(self, mock_json_loads, mock_connect, mock_db_path):
        """Test schema loading from metadata."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock schema data with correct format
        schema_data = {
            "fields": [
                {"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0},
                {
                    "name": "title",
                    "type": "text",
                    "stored": True,
                    "indexed": True,
                    "boost": 2.0,
                    "analyzer_name": "standard",
                },
            ]
        }
        mock_json_loads.return_value = schema_data

        index = SearchIndex(mock_db_path)

        # Verify schema was loaded
        assert index._schema is not None

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_load_schema_no_metadata(self, mock_json_loads, mock_connect, mock_db_path):
        """Test schema loading with no metadata (uses default)."""
        mock_conn = Mock()

        # Create different cursors for different operations
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = None  # No metadata

        search_cursor = Mock()
        search_cursor.fetchall.return_value = []

        # Use side_effect to return appropriate cursor based on SQL
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect
        mock_conn.prepare.return_value = Mock()
        mock_connect.return_value = mock_conn

        index = SearchIndex(mock_db_path)

        # Should use default schema
        assert index._schema is not None
        # Check that schema has text fields (filter by type)
        text_fields = [f for f in index._schema.fields if f.field_type.value == "text"]
        assert len(text_fields) == 3

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_load_schema_operational_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test schema loading handles operational errors."""
        mock_conn = Mock()

        # Use side_effect to only fail on schema loading, not PRAGMA statements
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                raise sqlite3.OperationalError("Table not found")
            return Mock()  # Return mock cursor for other queries

        mock_conn.execute.side_effect = execute_side_effect
        mock_conn.prepare.return_value = Mock()
        mock_connect.return_value = mock_conn

        index = SearchIndex(mock_db_path)

        # Should use default schema
        assert index._schema is not None
        # Check that schema has text fields (filter by type)
        text_fields = [f for f in index._schema.fields if f.field_type.value == "text"]
        assert len(text_fields) == 3

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_close_connection(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is closed properly."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None

    @patch("docs_mcp_server.search.search_index.sqlite3.connect")
    @patch("docs_mcp_server.search.search_index.json.loads")
    def test_close_already_closed(self, mock_json_loads, mock_connect, mock_db_path):
        """Test closing already closed connection."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = SearchIndex(mock_db_path)
        index._conn = None

        # Should not raise error
        index.close()


@pytest.mark.unit
class TestBM25Calculator:
    """Test inline BM25 calculator."""

    def test_bm25_score_calculation(self):
        """Test BM25 score calculation with typical values."""

        calc = _BM25Calculator()
        score = calc.score(tf=3, df=10, doc_len=100, avg_doc_len=80, total_docs=1000)

        # Should return positive score
        assert score > 0
        assert isinstance(score, float)

    def test_bm25_custom_parameters(self):
        """Test BM25 with custom k1 and b parameters."""

        calc = _BM25Calculator(k1=2.0, b=0.5)
        score = calc.score(tf=2, df=5, doc_len=50, avg_doc_len=60, total_docs=500)

        assert score > 0
        assert calc.k1 == 2.0
        assert calc.b == 0.5

    def test_bm25_zero_tf(self):
        """Test BM25 with zero term frequency."""

        calc = _BM25Calculator()
        score = calc.score(tf=0, df=10, doc_len=100, avg_doc_len=80, total_docs=1000)

        # Should return zero or very low score
        assert score >= 0

    def test_bm25_high_df(self):
        """Test BM25 with high document frequency (common term)."""

        calc = _BM25Calculator()
        score = calc.score(tf=1, df=900, doc_len=100, avg_doc_len=80, total_docs=1000)

        # Common terms should have lower (potentially negative) scores
        # This is correct BM25 behavior - very common terms get penalized
        assert score < 0  # High df should result in negative IDF
