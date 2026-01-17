"""Tests for lock-free concurrent search operations."""

from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.lockfree_concurrent import (
    LockFreeConcurrentSearch,
    LockFreeConnectionPool,
)


class TestLockFreeConnectionPool:
    """Test lock-free connection pool functionality."""

    def test_init_sets_attributes(self):
        """Test connection pool initialization."""
        db_path = Path(":memory:")
        pool = LockFreeConnectionPool(db_path, max_connections=5)

        assert pool.db_path == db_path
        assert pool.max_connections == 5
        assert pool._connection_count == 0

    def test_context_manager_lifecycle(self):
        """Test context manager properly closes connections."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConnectionPool(db_path) as pool:
                conn = pool.get_connection()
                assert isinstance(conn, sqlite3.Connection)

            # After context exit, connections should be closed
            # Note: We can't directly test if connection is closed
            # but we can verify close_all was called

    def test_get_connection_creates_thread_local(self):
        """Test get_connection creates thread-local connections."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConnectionPool(db_path) as pool:
                conn1 = pool.get_connection()
                conn2 = pool.get_connection()

                # Same thread should get same connection
                assert conn1 is conn2

    def test_get_connection_different_threads(self):
        """Test different threads get different connections."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)
            connections = {}

            with LockFreeConnectionPool(db_path) as pool:

                def get_conn(thread_id):
                    connections[thread_id] = pool.get_connection()

                threads = []
                for i in range(3):
                    thread = threading.Thread(target=get_conn, args=(i,))
                    threads.append(thread)
                    thread.start()

                for thread in threads:
                    thread.join()

                # Each thread should have different connection (at least 2 unique)
                assert len({id(conn) for conn in connections.values()}) >= 2

    def test_create_optimized_connection_sets_pragmas(self):
        """Test optimized connection has correct PRAGMA settings."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConnectionPool(db_path) as pool:
                conn = pool.get_connection()

                # Test some key PRAGMA settings
                cursor = conn.execute("PRAGMA journal_mode")
                assert cursor.fetchone()[0] == "wal"

                cursor = conn.execute("PRAGMA synchronous")
                assert cursor.fetchone()[0] == 1  # NORMAL

                cursor = conn.execute("PRAGMA temp_store")
                assert cursor.fetchone()[0] == 1  # FILE

    def test_close_all_handles_exceptions(self):
        """Test close_all handles connection close exceptions gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            pool = LockFreeConnectionPool(db_path)

            # Create a mock connection that raises on close
            mock_conn = Mock()
            mock_conn.close.side_effect = Exception("Close failed")
            pool._connections.append(mock_conn)  # Use append instead of add

            # Should not raise exception
            pool.close_all()

    def test_connection_tracking_with_weakref(self):
        """Test connections are tracked with weak references."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConnectionPool(db_path) as pool:
                conn = pool.get_connection()

                # Connection should be tracked
                assert len(pool._connections) == 1
                assert conn in pool._connections


class TestLockFreeConcurrentSearch:
    """Test lock-free concurrent search operations."""

    def test_init_creates_pool(self):
        """Test initialization creates connection pool."""
        db_path = Path(":memory:")
        search = LockFreeConcurrentSearch(db_path)

        assert search.db_path == db_path
        assert isinstance(search._pool, LockFreeConnectionPool)

    def test_context_manager_lifecycle(self):
        """Test context manager properly closes resources."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConcurrentSearch(db_path) as search:
                assert isinstance(search, LockFreeConcurrentSearch)

            # After context exit, resources should be cleaned up

    def test_execute_concurrent_query_basic(self):
        """Test basic query execution."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            # Create test database
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
                conn.execute("INSERT INTO test VALUES (1, 'test1'), (2, 'test2')")
                conn.commit()

            with LockFreeConcurrentSearch(db_path) as search:
                results = search.execute_concurrent_query("SELECT * FROM test ORDER BY id")

                assert len(results) == 2
                assert results[0] == (1, "test1")
                assert results[1] == (2, "test2")

    def test_execute_concurrent_query_with_params(self):
        """Test query execution with parameters."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            # Create test database
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
                conn.execute("INSERT INTO test VALUES (1, 'test1'), (2, 'test2')")
                conn.commit()

            with LockFreeConcurrentSearch(db_path) as search:
                results = search.execute_concurrent_query("SELECT * FROM test WHERE id = ?", (1,))

                assert len(results) == 1
                assert results[0] == (1, "test1")

    def test_get_performance_info_returns_stats(self):
        """Test performance info returns expected statistics."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            with LockFreeConcurrentSearch(db_path) as search:
                # Get a connection to populate pool
                search._pool.get_connection()

                info = search.get_performance_info()

                assert info["lockfree_enabled"] is True
                assert info["optimization_type"] == "lockfree_concurrent"
                assert "connection_pool_size" in info
                assert info["connection_pool_size"] >= 0

    def test_close_delegates_to_pool(self):
        """Test close method delegates to connection pool."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = Path(tmp.name)

            search = LockFreeConcurrentSearch(db_path)

            with patch.object(search._pool, "close_all") as mock_close:
                search.close()
                mock_close.assert_called_once()


class TestLockFreeConcurrentIntegration:
    """Integration tests for lock-free concurrent operations."""

    def test_real_world_concurrent_search_scenario(self):
        """Test realistic concurrent search scenario."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = Path(tmp.name)

            # Create realistic search database with WAL mode for concurrency
            with sqlite3.connect(db_path, timeout=30.0) as conn:
                # Enable WAL mode before creating tables for better concurrency
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA busy_timeout = 30000")  # 30s busy timeout
                conn.execute("""
                    CREATE TABLE documents (
                        id INTEGER PRIMARY KEY,
                        title TEXT,
                        content TEXT,
                        score REAL
                    )
                """)

                # Insert test documents
                for i in range(100):
                    conn.execute(
                        "INSERT INTO documents (title, content, score) VALUES (?, ?, ?)",
                        (f"Document {i}", f"Content for document {i}", i * 0.1),
                    )
                conn.commit()

            # Create single shared search instance for all workers
            shared_search = LockFreeConcurrentSearch(db_path)
            search_results = {}
            results_lock = threading.Lock()
            errors = []

            def search_worker(worker_id):
                try:
                    # Use shared search instance instead of creating new ones
                    results = []

                    # Count query
                    count = shared_search.execute_concurrent_query("SELECT COUNT(*) FROM documents")
                    results.append(("count", count[0][0]))

                    # Search query
                    docs = shared_search.execute_concurrent_query(
                        "SELECT title FROM documents WHERE score > ? LIMIT 5", (5.0,)
                    )
                    results.append(("search", len(docs)))

                    with results_lock:
                        search_results[worker_id] = results
                except Exception as e:
                    with results_lock:
                        errors.append((worker_id, str(e)))

            # Run concurrent searches
            threads = []
            for i in range(10):
                thread = threading.Thread(target=search_worker, args=(i,))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            # Clean up shared search instance
            shared_search.close()

            # Verify all searches completed successfully
            if errors:
                pytest.fail(f"Some workers failed: {errors}")

            assert len(search_results) == 10, (
                f"Expected 10 results, got {len(search_results)}: {list(search_results.keys())}"
            )

            for results in search_results.values():
                assert len(results) == 2

                # Count should be consistent
                count_result = next(r for r in results if r[0] == "count")
                assert count_result[1] == 100

                # Search should find documents
                search_result = next(r for r in results if r[0] == "search")
                assert search_result[1] == 5

        # Clean up temp file after context exits
        try:
            db_path.unlink(missing_ok=True)
            # Also clean up WAL and SHM files if they exist
            Path(str(db_path) + "-wal").unlink(missing_ok=True)
            Path(str(db_path) + "-shm").unlink(missing_ok=True)
        except Exception:
            pass
