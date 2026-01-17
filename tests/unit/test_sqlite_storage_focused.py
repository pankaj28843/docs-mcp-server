"""Focused tests for SQLite storage coverage."""

from array import array
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.sqlite_storage import (
    SQLiteConnectionPool,
    SqliteSegment,
    SqliteSegmentStore,
    SqliteSegmentWriter,
)


@pytest.mark.unit
def test_sqlite_connection_pool_create_connection():
    """Test connection creation with optimizations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        pool = SQLiteConnectionPool(db_path)

        with pool.get_connection() as conn:
            # Verify connection works
            result = conn.execute("SELECT 1").fetchone()
            assert result[0] == 1


@pytest.mark.unit
def test_sqlite_segment_get_postings():
    """Test getting postings from SQLite segment."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        # Create segment with data
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.execute(
            "CREATE TABLE postings (field TEXT, term TEXT, doc_id TEXT, tf INTEGER, doc_length INTEGER, positions_blob BLOB)"
        )
        positions = array("I", [1, 2, 3])
        conn.execute(
            "INSERT INTO documents (doc_id, title, title_length) VALUES (?, ?, ?)",
            ("doc1", "Test", 3),
        )
        conn.execute(
            "INSERT INTO postings VALUES (?, ?, ?, ?, ?, ?)",
            ("title", "test", "doc1", 3, 3, positions.tobytes()),
        )
        conn.commit()
        conn.close()

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=1
        )

        postings = segment.get_postings("title", "test", include_positions=True)
        assert len(postings) == 1
        assert postings[0].doc_id == "doc1"
        assert list(postings[0].positions) == [1, 2, 3]


@pytest.mark.unit
def test_sqlite_segment_get_document():
    """Test getting document from SQLite segment."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        # Create segment with data using correct column name
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.execute("INSERT INTO documents (doc_id, title) VALUES (?, ?)", ("doc1", "Test"))
        conn.commit()
        conn.close()

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=1
        )

        doc = segment.get_document("doc1")
        assert doc is not None
        assert doc["title"] == "Test"


@pytest.mark.unit
def test_sqlite_segment_field_lengths():
    """Test getting field length stats from SQLite segment."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        # Create segment with data
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.execute("INSERT INTO documents (doc_id, title, title_length) VALUES (?, ?, ?)", ("doc1", "Doc", 5))
        conn.commit()
        conn.close()

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=1
        )

        stats = segment.get_field_length_stats(["title"])
        assert stats["title"].total_terms == 5
        assert stats["title"].document_count == 1


@pytest.mark.unit
def test_sqlite_segment_writer_build():
    """Test SQLite segment writer build process."""
    schema = Schema(fields=[TextField("title")], unique_field="title", name="test")
    writer = SqliteSegmentWriter(schema)

    writer.add_document({"title": "Test Document"})
    segment_data = writer.build()

    assert segment_data["segment_id"] is not None
    assert "postings" in segment_data
    assert "stored_fields" in segment_data
    assert len(segment_data["stored_fields"]) == 1


@pytest.mark.unit
def test_sqlite_segment_store_save_existing_segment():
    """Test saving when segment already exists."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)
        segment_data = {
            "segment_id": "test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema": {"fields": []},
            "postings": {},
            "stored_fields": {},
            "field_lengths": {},
        }

        # Create existing file
        db_path = store._db_path("test")
        db_path.touch()

        # Should return existing path without overwriting
        result_path = store.save(segment_data)
        assert result_path == db_path


@pytest.mark.unit
def test_sqlite_segment_store_save_with_error():
    """Test save error handling and cleanup."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)
        segment_data = {
            "segment_id": "test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema": {"fields": []},
            "postings": {},
            "stored_fields": {},
            "field_lengths": {},
        }

        # Mock sqlite3.connect to raise error
        with patch("sqlite3.connect", side_effect=sqlite3.Error("Test error")):
            with pytest.raises(RuntimeError, match="Failed to save SQLite segment"):
                store.save(segment_data)


@pytest.mark.unit
def test_sqlite_segment_store_load_nonexistent():
    """Test loading nonexistent segment."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)
        result = store.load("nonexistent")
        assert result is None


@pytest.mark.unit
def test_sqlite_segment_store_create_schema():
    """Test SQLite schema creation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)

        conn = sqlite3.connect(":memory:")
        store._create_schema(conn)

        # Verify tables were created
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]

        assert "metadata" in table_names
        assert "postings" in table_names
        assert "documents" in table_names
        assert "field_lengths" not in table_names


@pytest.mark.unit
def test_sqlite_segment_store_db_path():
    """Test database path generation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)

        path = store._db_path("test_segment")
        assert path.name == "test_segment.db"
        assert path.parent == Path(tmp_dir)


@pytest.mark.unit
def test_sqlite_segment_writer_add_document_duplicate():
    """Test adding duplicate document to writer."""
    schema = Schema(fields=[TextField("title")], unique_field="title", name="test")
    writer = SqliteSegmentWriter(schema)

    writer.add_document({"title": "Test"})

    with pytest.raises(ValueError, match="Duplicate document"):
        writer.add_document({"title": "Test"})


@pytest.mark.unit
def test_sqlite_segment_writer_add_document_missing_unique():
    """Test adding document without unique field."""
    schema = Schema(fields=[TextField("title")], unique_field="title", name="test")
    writer = SqliteSegmentWriter(schema)

    with pytest.raises(ValueError, match="Document missing unique field"):
        writer.add_document({"body": "No title"})


@pytest.mark.unit
def test_sqlite_segment_get_postings_empty():
    """Test getting postings when none exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        # Create empty segment
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.execute(
            "CREATE TABLE postings (field TEXT, term TEXT, doc_id TEXT, tf INTEGER, doc_length INTEGER, positions_blob BLOB)"
        )
        conn.commit()
        conn.close()

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=0
        )

        postings = segment.get_postings("title", "nonexistent")
        assert postings == []


@pytest.mark.unit
def test_sqlite_segment_get_document_missing():
    """Test getting missing document."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        # Create empty segment
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE documents (
                doc_id TEXT PRIMARY KEY,
                url TEXT,
                url_path TEXT,
                title TEXT,
                headings_h1 TEXT,
                headings_h2 TEXT,
                headings TEXT,
                body TEXT,
                path TEXT,
                tags TEXT,
                excerpt TEXT,
                language TEXT,
                timestamp TEXT,
                url_path_length INTEGER,
                title_length INTEGER,
                headings_h1_length INTEGER,
                headings_h2_length INTEGER,
                headings_length INTEGER,
                body_length INTEGER
            )
        """)
        conn.commit()
        conn.close()

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=0
        )

        doc = segment.get_document("nonexistent")
        assert doc is None


@pytest.mark.unit
def test_sqlite_segment_close():
    """Test closing segment connections."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        schema = Schema(fields=[TextField("title")], unique_field="title", name="test")

        segment = SqliteSegment(
            schema=schema, db_path=db_path, segment_id="test", created_at=datetime.now(timezone.utc), doc_count=1
        )

        # Should not raise error
        segment.close()


@pytest.mark.unit
def test_sqlite_segment_store_latest():
    """Test getting latest segment."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SqliteSegmentStore(tmp_dir)

        # No segments yet
        latest = store.latest()
        assert latest is None


@pytest.mark.unit
def test_sqlite_connection_pool_close_all_with_error():
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
def test_sqlite_segment_store_set_max_segments():
    """Test setting max segments."""
    original = SqliteSegmentStore.MAX_SEGMENTS

    SqliteSegmentStore.set_max_segments(10)
    assert SqliteSegmentStore.MAX_SEGMENTS == 10

    SqliteSegmentStore.set_max_segments(None)
    assert SqliteSegmentStore.MAX_SEGMENTS == SqliteSegmentStore.DEFAULT_MAX_SEGMENTS

    # Restore original
    SqliteSegmentStore.MAX_SEGMENTS = original
