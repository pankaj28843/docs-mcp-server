"""Tests for SQLite storage components."""
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from docs_mcp_server.search.sqlite_storage import SQLiteConnectionPool


@pytest.mark.unit
def test_connection_pool_close_all_with_error():
    """Test close_all handles SQLite errors gracefully."""
    pool = SQLiteConnectionPool(Path(":memory:"), max_connections=1)
    
    # Create a mock connection that raises an error on close
    mock_conn = Mock()
    mock_conn.close.side_effect = sqlite3.Error("Close error")
    
    pool._local.connection = mock_conn
    
    # Should not raise an exception
    pool.close_all()
    
    # Connection should be set to None
    assert pool._local.connection is None


@pytest.mark.unit
def test_connection_pool_close_all_no_connection():
    """Test close_all when no connection exists."""
    pool = SQLiteConnectionPool(Path(":memory:"), max_connections=1)
    
    # Should not raise an exception
    pool.close_all()


@pytest.mark.unit
def test_connection_pool_close_all_no_local_attr():
    """Test close_all when _local has no connection attribute."""
    pool = SQLiteConnectionPool(Path(":memory:"), max_connections=1)
    
    # Ensure no connection attribute exists
    if hasattr(pool._local, "connection"):
        delattr(pool._local, "connection")
    
    # Should not raise an exception
    pool.close_all()
