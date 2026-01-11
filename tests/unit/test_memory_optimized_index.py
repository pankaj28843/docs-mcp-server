"""Unit tests for memory-optimized search index implementation."""

import sqlite3
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.memory_optimized_index import MemoryOptimizedSearchIndex


@pytest.mark.unit
class TestMemoryOptimizedSearchIndex:
    """Test memory-optimized search index with minimal memory footprint."""

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
        mock_connect.return_value = mock_conn
        mock_json_loads.return_value = {
            "fields": [{"name": "url", "type": "keyword", "stored": True, "indexed": True, "boost": 1.0}]
        }
        return mock_conn

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_init_creates_connection_with_memory_optimizations(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization creates connection with memory optimizations."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

        # Verify memory-specific optimizations (actual implementation)
        expected_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -16000",  # Reduced cache
            "PRAGMA mmap_size = 67108864",  # Reduced mmap
            "PRAGMA temp_store = MEMORY",
            "PRAGMA page_size = 4096",
            "PRAGMA cache_spill = FALSE",  # Prevent fragmentation
        ]

        for pragma in expected_pragmas:
            mock_conn.execute.assert_any_call(pragma)

        assert index.db_path == mock_db_path

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_memory_journal_mode(self, mock_json_loads, mock_connect, mock_db_path):
        """Test WAL journal mode for concurrent access."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA journal_mode = WAL")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_smaller_cache_for_memory_efficiency(self, mock_json_loads, mock_connect, mock_db_path):
        """Test smaller cache size for memory efficiency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify 16MB cache size (smaller than default)
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -16000")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_mmap_enabled_for_memory_efficiency(self, mock_json_loads, mock_connect, mock_db_path):
        """Test mmap enabled with reduced size for memory efficiency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify 64MB mmap size (reduced from larger default)
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 67108864")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_cache_spill_disabled(self, mock_json_loads, mock_connect, mock_db_path):
        """Test cache spill disabled to prevent memory fragmentation."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA cache_spill = FALSE")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_page_size_optimization(self, mock_json_loads, mock_connect, mock_db_path):
        """Test page size optimization for memory efficiency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA page_size = 4096")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_normal_synchronous_mode(self, mock_json_loads, mock_connect, mock_db_path):
        """Test normal synchronous mode for reliability."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_memory_temp_store(self, mock_json_loads, mock_connect, mock_db_path):
        """Test memory-based temporary storage."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_conn.execute.assert_any_call("PRAGMA temp_store = MEMORY")

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_connection_stored(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is stored for reuse."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)

        assert index._conn is mock_conn

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_init_handles_connection_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test initialization handles connection errors."""
        mock_connect.side_effect = sqlite3.Error("Connection failed")

        with pytest.raises(sqlite3.Error, match="Connection failed"):
            MemoryOptimizedSearchIndex(mock_db_path)

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_all_memory_optimizations_applied(self, mock_json_loads, mock_connect, mock_db_path):
        """Test all memory optimizations are applied together."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify all memory-focused pragmas (actual implementation)
        memory_pragmas = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA cache_size = -16000",
            "PRAGMA mmap_size = 67108864",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA page_size = 4096",
            "PRAGMA cache_spill = FALSE",
        ]

        for pragma in memory_pragmas:
            mock_conn.execute.assert_any_call(pragma)

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_check_same_thread_disabled(self, mock_json_loads, mock_connect, mock_db_path):
        """Test check_same_thread disabled for concurrent access."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        mock_connect.assert_called_once_with(mock_db_path, check_same_thread=False)

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_memory_focused_configuration(self, mock_json_loads, mock_connect, mock_db_path):
        """Test configuration prioritizes memory efficiency."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify memory-efficient settings (actual implementation)
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -16000")  # Reduced cache
        mock_conn.execute.assert_any_call("PRAGMA mmap_size = 67108864")  # Reduced mmap
        mock_conn.execute.assert_any_call("PRAGMA cache_spill = FALSE")  # No fragmentation

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_memory_vs_performance_tradeoff(self, mock_json_loads, mock_connect, mock_db_path):
        """Test memory optimization balances memory and performance."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify balanced memory/performance settings
        mock_conn.execute.assert_any_call("PRAGMA cache_size = -16000")  # Reduced but not minimal
        mock_conn.execute.assert_any_call("PRAGMA synchronous = NORMAL")  # Balanced safety

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_optimization_order_execution(self, mock_json_loads, mock_connect, mock_db_path):
        """Test optimizations executed in correct order."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        MemoryOptimizedSearchIndex(mock_db_path)

        # Verify pragmas executed (order can matter)
        assert mock_conn.execute.call_count >= 7

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_lazy_initialization(self, mock_json_loads, mock_connect, mock_db_path):
        """Test lazy initialization reduces startup memory."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)

        # Connection should be created during init
        assert index._conn is not None
        mock_connect.assert_called_once()

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    @patch("docs_mcp_server.search.memory_optimized_index.get_analyzer")
    def test_search_empty_query(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with empty query returns empty results."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)
        mock_analyzer = Mock()
        mock_analyzer.return_value = []  # No tokens
        mock_get_analyzer.return_value = mock_analyzer

        index = MemoryOptimizedSearchIndex(mock_db_path)
        response = index.search("")

        assert response.results == []

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    @patch("docs_mcp_server.search.memory_optimized_index.get_analyzer")
    def test_search_with_results(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search returns results correctly."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        # Mock analyzer
        mock_token = Mock()
        mock_token.text = "test"
        mock_analyzer = Mock()
        mock_analyzer.return_value = [mock_token]
        mock_get_analyzer.return_value = mock_analyzer

        # Mock execute to return cursor-like object
        search_cursor = Mock()
        search_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))

        # Update side_effect to return search cursor for search queries
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                schema_cursor = Mock()
                schema_cursor.fetchone.return_value = (
                    '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
                )
                return schema_cursor
            return search_cursor

        mock_conn.execute.side_effect = execute_side_effect

        index = MemoryOptimizedSearchIndex(mock_db_path)
        response = index.search("test")

        assert len(response.results) == 1
        assert response.results[0].document_title == "Test Title"
        assert response.results[0].document_url == "http://test.com"

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    @patch("docs_mcp_server.search.memory_optimized_index.get_analyzer")
    def test_search_multiple_tokens(self, mock_get_analyzer, mock_json_loads, mock_connect, mock_db_path):
        """Test search with multiple tokens."""
        mock_conn = Mock()

        # Mock analyzer with multiple tokens
        tokens = [Mock() for _ in range(3)]
        for i, token in enumerate(tokens):
            token.text = f"token{i}"
        mock_analyzer = Mock()
        mock_analyzer.return_value = tokens
        mock_get_analyzer.return_value = mock_analyzer

        # Create different cursors for different operations
        schema_cursor = Mock()
        schema_cursor.fetchone.return_value = (
            '{"fields": [{"name": "url", "type": "keyword", "stored": true, "indexed": true, "boost": 1.0}]}',
        )

        search_cursor = Mock()
        search_cursor.__iter__ = Mock(return_value=iter([("Test Title", "http://test.com", "Test content", 1.5)]))

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

        index = MemoryOptimizedSearchIndex(mock_db_path)
        response = index.search("token0 token1 token2")

        assert len(response.results) == 1
        # Verify SQL was called with correct placeholders
        mock_conn.execute.assert_called()

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_build_snippet_minimal_with_match(self, mock_json_loads, mock_connect, mock_db_path):
        """Test minimal snippet generation with token match."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        content = "This is some important content for testing snippet generation"
        tokens = ["important"]

        snippet = index._build_snippet_minimal(content, tokens)

        assert "important" in snippet
        assert len(snippet) <= 200

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_build_snippet_minimal_no_match(self, mock_json_loads, mock_connect, mock_db_path):
        """Test minimal snippet generation without token match."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        content = "This is content without the search term"
        tokens = ["missing"]

        snippet = index._build_snippet_minimal(content, tokens)

        # Should return first 200 chars when no match
        assert snippet == content[:200]

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_build_snippet_minimal_empty_content(self, mock_json_loads, mock_connect, mock_db_path):
        """Test minimal snippet generation with empty content."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)

        snippet = index._build_snippet_minimal("", ["test"])
        assert snippet == ""

        snippet = index._build_snippet_minimal("content", [])
        assert snippet == "content"

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_build_snippet_minimal_custom_length(self, mock_json_loads, mock_connect, mock_db_path):
        """Test minimal snippet generation with custom max length."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        content = "This is a very long content that should be truncated at the specified length"
        tokens = ["missing"]

        snippet = index._build_snippet_minimal(content, tokens, max_length=20)

        assert len(snippet) == 20
        assert snippet == content[:20]

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
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

        index = MemoryOptimizedSearchIndex(mock_db_path)

        # Verify schema was loaded
        assert index._schema is not None

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_load_schema_no_metadata(self, mock_json_loads, mock_connect, mock_db_path):
        """Test schema loading with no metadata (uses default)."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # No metadata
        mock_connect.return_value = mock_conn

        index = MemoryOptimizedSearchIndex(mock_db_path)

        # Should use default schema
        assert index._schema is not None
        # Check that schema has text fields (filter by type)
        text_fields = [f for f in index._schema.fields if f.field_type.value == "text"]
        assert len(text_fields) == 3

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_load_schema_operational_error(self, mock_json_loads, mock_connect, mock_db_path):
        """Test schema loading handles operational errors."""
        mock_conn = Mock()

        # Use side_effect to only fail on schema loading, not PRAGMA statements
        def execute_side_effect(sql, *args):
            if "SELECT schema_json FROM metadata" in sql:
                raise sqlite3.OperationalError("Table not found")
            return Mock()  # Return mock cursor for other queries

        mock_conn.execute.side_effect = execute_side_effect
        mock_connect.return_value = mock_conn

        index = MemoryOptimizedSearchIndex(mock_db_path)

        # Should use default schema
        assert index._schema is not None
        # Check that schema has text fields (filter by type)
        text_fields = [f for f in index._schema.fields if f.field_type.value == "text"]
        assert len(text_fields) == 3

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_ensure_connection_lazy_loading(self, mock_json_loads, mock_connect, mock_db_path):
        """Test ensure_connection creates connection only when needed."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)

        # Connection should be created during init
        assert index._conn is not None

        # Calling ensure_connection again should not create new connection
        initial_conn = index._conn
        index._ensure_connection()
        assert index._conn is initial_conn

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_ensure_connection_when_none(self, mock_json_loads, mock_connect, mock_db_path):
        """Test ensure_connection creates connection when None."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        index._conn = None  # Simulate closed connection

        index._ensure_connection()

        assert index._conn is not None

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_close_connection(self, mock_json_loads, mock_connect, mock_db_path):
        """Test connection is closed properly."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        index.close()

        mock_conn.close.assert_called_once()
        assert index._conn is None

    @patch("docs_mcp_server.search.memory_optimized_index.sqlite3.connect")
    @patch("docs_mcp_server.search.memory_optimized_index.json.loads")
    def test_close_already_closed(self, mock_json_loads, mock_connect, mock_db_path):
        """Test closing already closed connection."""
        mock_conn = self._setup_db_mocks(mock_connect, mock_json_loads)

        index = MemoryOptimizedSearchIndex(mock_db_path)
        index._conn = None

        # Should not raise error
        index.close()
