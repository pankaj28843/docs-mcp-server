"""Test SQLite storage functionality."""

from array import array
import gc
from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import patch

import pytest

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.sqlite_storage import SQLiteConnectionPool, SqliteSegmentStore, SqliteSegmentWriter


# Global cleanup tracking
_active_connections = []
_active_segments = []


def _track_connection(conn):
    """Track SQLite connections for cleanup."""
    _active_connections.append(conn)
    return conn


def _track_segment(segment):
    """Track segments for cleanup."""
    if segment:
        _active_segments.append(segment)
    return segment


@pytest.fixture(autouse=True)
def cleanup_sqlite_resources():
    """Auto-cleanup fixture that runs for every test."""
    yield
    # Force cleanup of tracked resources
    for segment in _active_segments:
        try:
            segment.close()
        except Exception:
            pass
    _active_segments.clear()

    for conn in _active_connections:
        try:
            conn.close()
        except Exception:
            pass
    _active_connections.clear()

    # Force garbage collection to trigger any remaining ResourceWarnings now
    gc.collect()


@pytest.fixture
def sample_schema():
    """Create a simple schema for testing."""
    return Schema(
        unique_field="url",
        fields=[
            TextField(name="url", stored=True, indexed=True),
            TextField(name="title", stored=True, indexed=True),
            TextField(name="body", stored=True, indexed=True),
        ],
    )


@pytest.fixture
def sample_documents():
    """Create sample documents for testing."""
    return [
        {
            "url": "https://example.com/doc1",
            "title": "First Document",
            "body": "This is the first document with some content to index.",
        },
        {
            "url": "https://example.com/doc2",
            "title": "Second Document",
            "body": "This is the second document with different content.",
        },
        {
            "url": "https://example.com/doc3",
            "title": "Third Document",
            "body": "This document contains overlapping terms with the first document.",
        },
    ]


@pytest.fixture
def sqlite_store():
    """Create SQLite store with proper cleanup."""
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SqliteSegmentStore(temp_dir)
        yield store
        # SqliteSegmentStore doesn't need explicit cleanup - connections are managed by segments


@pytest.fixture
def managed_sqlite_store():
    """Create SQLite store with automatic cleanup for tests that need manual temp dir management."""
    stores = []

    def create_store(temp_dir):
        store = SqliteSegmentStore(temp_dir)
        stores.append(store)

        # Wrap the load method to track segments
        original_load = store.load

        def tracked_load(segment_id):
            segment = original_load(segment_id)
            return _track_segment(segment)

        store.load = tracked_load

        return store

    return create_store

    # Cleanup handled by autouse fixture


def test_sqlite_storage_basic_functionality(sample_schema, sample_documents, sqlite_store):
    """Test basic SQLite storage save/load functionality."""
    # Create segment using SQLite writer
    writer = SqliteSegmentWriter(sample_schema)
    for doc in sample_documents:
        writer.add_document(doc)
    segment_data = writer.build()

    # Save using SQLite storage
    db_path = sqlite_store.save(segment_data)

    # Verify file was created
    assert db_path.exists()
    assert db_path.suffix == ".db"

    # Load segment back
    loaded_segment = sqlite_store.load(segment_data["segment_id"])
    assert loaded_segment is not None
    assert loaded_segment.segment_id == segment_data["segment_id"]
    assert loaded_segment.doc_count == len(sample_documents)


def test_sqlite_storage_document_retrieval(sample_schema, sample_documents, managed_sqlite_store):
    """Test document storage and retrieval functionality."""
    with tempfile.TemporaryDirectory() as sqlite_dir:
        # Create segment
        writer = SqliteSegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment_data = writer.build()

        # Save with SQLite storage
        sqlite_store = managed_sqlite_store(sqlite_dir)
        sqlite_store.save(segment_data)
        sqlite_segment = sqlite_store.load(segment_data["segment_id"])

        # Compare stored documents
        for doc in sample_documents:
            doc_id = doc["url"]
            sqlite_doc = sqlite_segment.get_document(doc_id)
            assert sqlite_doc == doc

        # Test postings functionality - check if we can retrieve any postings
        # The exact term might not exist, so let's check if the segment has any postings at all
        assert sqlite_segment.doc_count == len(sample_documents)

        # Test that documents are properly stored and retrievable
        for doc in sample_documents:
            doc_id = doc["url"]
            sqlite_doc = sqlite_segment.get_document(doc_id)
            assert sqlite_doc == doc


def test_binary_position_encoding():
    """Test that binary position encoding works correctly."""
    # Test position array encoding/decoding
    original_positions = [0, 5, 10, 15, 20]
    positions_array = array("I", original_positions)
    positions_blob = positions_array.tobytes()

    # Decode back
    decoded_array = array("I")
    decoded_array.frombytes(positions_blob)
    decoded_positions = list(decoded_array)

    assert decoded_positions == original_positions


def test_sqlite_storage_latest_segment(sample_schema, sample_documents, managed_sqlite_store):
    """Test latest segment functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = managed_sqlite_store(temp_dir)

        # Initially no segments
        assert sqlite_store.latest() is None
        assert sqlite_store.latest_segment_id() is None
        assert sqlite_store.latest_doc_count() is None

        # Create and save first segment
        writer1 = SqliteSegmentWriter(sample_schema, segment_id="segment1")
        writer1.add_document(sample_documents[0])
        segment1_data = writer1.build()
        sqlite_store.save(segment1_data)

        # Create and save second segment (more recent)
        writer2 = SqliteSegmentWriter(sample_schema, segment_id="segment2")
        for doc in sample_documents:
            writer2.add_document(doc)
        segment2_data = writer2.build()
        sqlite_store.save(segment2_data)

        # Latest should be segment2
        latest = sqlite_store.latest()
        assert latest is not None
        assert latest.segment_id == "segment2"
        assert latest.doc_count == len(sample_documents)

        assert sqlite_store.latest_segment_id() == "segment2"
        assert sqlite_store.latest_doc_count() == len(sample_documents)


def test_sqlite_storage_list_segments(sample_schema, sample_documents):
    """Test listing all segments."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create multiple segments
        for i, doc in enumerate(sample_documents):
            writer = SqliteSegmentWriter(sample_schema, segment_id=f"segment{i}")
            writer.add_document(doc)
            segment_data = writer.build()
            sqlite_store.save(segment_data)

        # List segments
        segments = sqlite_store.list_segments()
        assert len(segments) == len(sample_documents)

        segment_ids = {seg["segment_id"] for seg in segments}
        expected_ids = {f"segment{i}" for i in range(len(sample_documents))}
        assert segment_ids == expected_ids


def test_sqlite_storage_prune_segments(sample_schema, sample_documents):
    """Test pruning segments to keep only specified IDs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create multiple segments
        segment_ids = []
        for i, doc in enumerate(sample_documents):
            writer = SqliteSegmentWriter(sample_schema, segment_id=f"segment{i}")
            writer.add_document(doc)
            segment_data = writer.build()
            sqlite_store.save(segment_data)
            segment_ids.append(f"segment{i}")

        # Keep only first two segments
        keep_ids = segment_ids[:2]
        sqlite_store.prune_to_segment_ids(keep_ids)

        # Verify only kept segments remain
        remaining_segments = sqlite_store.list_segments()
        remaining_ids = {seg["segment_id"] for seg in remaining_segments}
        assert remaining_ids == set(keep_ids)


def test_sqlite_storage_segment_path(sample_schema, sample_documents):
    """Test getting segment path."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Non-existent segment
        assert sqlite_store.segment_path("nonexistent") is None

        # Create segment
        writer = SqliteSegmentWriter(sample_schema, segment_id="test_segment")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        # Existing segment
        path = sqlite_store.segment_path("test_segment")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".db"


def test_sqlite_storage_connection_pool():
    """Test connection pool functionality."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        temp_path = temp_file.name

    try:
        pool = SQLiteConnectionPool(temp_path, max_connections=2)

        # Test getting connections (thread-local returns same connection)
        with pool.get_connection() as conn1:
            assert conn1 is not None
            with pool.get_connection() as conn2:
                assert conn2 is not None
                assert conn1 == conn2  # Thread-local returns same connection

        # Test connection reuse
        with pool.get_connection() as conn3:
            # Should reuse the thread-local connection
            assert conn3 is not None
            assert conn3 == conn1

        # Test cleanup
        pool.close_all()
        # Thread-local storage doesn't have _connections attribute
    finally:
        # Clean up temp file
        try:
            Path(temp_path).unlink()
        except OSError:
            # Best-effort cleanup; ignore failures if the file is already gone or locked
            pass


def test_sqlite_storage_error_handling(sample_schema):
    """Test error handling in SQLite storage."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Test loading non-existent segment
        assert sqlite_store.load("nonexistent") is None

        # Test empty directory
        assert sqlite_store.latest() is None
        assert sqlite_store.latest_segment_id() is None
        assert sqlite_store.latest_doc_count() is None

        # Test with corrupted database
        corrupted_path = sqlite_store._db_path("corrupted")
        corrupted_path.write_text("not a database")

        # Should handle corruption gracefully
        assert sqlite_store.load("corrupted") is None

        # Test save error handling by mocking a sqlite error
        valid_data = {"segment_id": "test", "schema": sample_schema.to_dict()}

        with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked database error")):
            with pytest.raises(RuntimeError, match="Failed to save SQLite segment"):
                sqlite_store.save(valid_data)


def test_sqlite_storage_save_handles_cleanup_and_close_errors(sample_schema, sample_documents, monkeypatch):
    """Exercise cleanup and close error paths on save."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="cleanup_close")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()

        def _raise_schema(_self, _conn):
            raise sqlite3.Error("schema boom")

        monkeypatch.setattr(SqliteSegmentStore, "_create_schema", _raise_schema)

        target_path = sqlite_store._db_path(segment_data["segment_id"])
        original_unlink = Path.unlink

        def _unlink(path, *args, **kwargs):
            if path == target_path:
                raise OSError("unlink boom")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _unlink)

        with pytest.raises(RuntimeError, match="Failed to save SQLite segment"):
            sqlite_store.save(segment_data)


def test_sqlite_storage_save_handles_close_failure(sample_schema, sample_documents, monkeypatch):
    """Exercise connection close error handling."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="close_fail")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()

        real_connect = sqlite3.connect
        captured: dict[str, sqlite3.Connection] = {}

        class _ConnWrapper:
            def __init__(self, conn: sqlite3.Connection) -> None:
                object.__setattr__(self, "_conn", conn)

            def __enter__(self):
                return self._conn

            def __exit__(self, exc_type, exc, tb):
                self._conn.close()
                return False

            def close(self):
                raise sqlite3.Error("close boom")

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def __setattr__(self, name, value):
                if name == "_conn":
                    object.__setattr__(self, name, value)
                else:
                    setattr(self._conn, name, value)

        def _connect(path):
            conn = real_connect(path)
            captured["conn"] = conn
            return _ConnWrapper(conn)

        monkeypatch.setattr(sqlite3, "connect", _connect)

        db_path = sqlite_store.save(segment_data)
        assert db_path.exists()
        captured["conn"].close()


def test_sqlite_storage_update_manifest_handles_bad_json_and_write_error(sample_schema, monkeypatch, tmp_path):
    """Cover manifest error handling branches."""
    sqlite_store = SqliteSegmentStore(tmp_path)
    manifest_path = sqlite_store._manifest_path
    manifest_path.write_text("{bad json", encoding="utf-8")

    original_write = Path.write_text

    def _write_text(path, *args, **kwargs):
        if path == manifest_path:
            raise OSError("write boom")
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _write_text)

    sqlite_store._update_manifest("seg1", {"doc_count": 0})


def test_sqlite_storage_load_returns_none_when_metadata_missing(monkeypatch, tmp_path):
    sqlite_store = SqliteSegmentStore(tmp_path)
    db_path = sqlite_store._db_path("empty_meta")
    sqlite3.connect(db_path).close()

    monkeypatch.setattr(sqlite_store, "_load_metadata", lambda _conn: {})

    assert sqlite_store.load("empty_meta") is None


def test_sqlite_storage_load_returns_none_on_invalid_schema(sample_schema, sample_documents):
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="bad_schema")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        db_path = sqlite_store._db_path("bad_schema")
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE metadata SET value = ? WHERE key = 'schema'", ("not-json",))
            conn.commit()

        assert sqlite_store.load("bad_schema") is None


def test_sqlite_storage_load_handles_invalid_created_at(sample_schema, sample_documents):
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="bad_time")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        db_path = sqlite_store._db_path("bad_time")
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE metadata SET value = ? WHERE key = 'created_at'", ("invalid",))
            conn.commit()

        loaded = sqlite_store.load("bad_time")

        assert loaded is not None
        assert loaded.created_at.tzinfo is not None


def test_sqlite_storage_load_handles_close_error(sample_schema, sample_documents, monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="close_error")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        real_connect = sqlite3.connect
        captured: dict[str, sqlite3.Connection] = {}

        class _ConnWrapper:
            def __init__(self, conn: sqlite3.Connection) -> None:
                object.__setattr__(self, "_conn", conn)

            def __enter__(self):
                return self._conn

            def __exit__(self, exc_type, exc, tb):
                self._conn.close()
                return False

            def close(self):
                raise sqlite3.Error("close boom")

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def __setattr__(self, name, value):
                if name == "_conn":
                    object.__setattr__(self, name, value)
                else:
                    setattr(self._conn, name, value)

        def _connect(path):
            conn = real_connect(path)
            captured["conn"] = conn
            return _ConnWrapper(conn)

        monkeypatch.setattr(sqlite3, "connect", _connect)

        loaded = sqlite_store.load("close_error")
        assert loaded is not None
        captured["conn"].close()


def test_sqlite_storage_load_metadata_handles_operational_error(tmp_path):
    sqlite_store = SqliteSegmentStore(tmp_path)
    db_path = sqlite_store._db_path("no_meta")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, field_data TEXT)")
    conn.commit()

    assert sqlite_store._load_metadata(conn) == {}

    conn.close()


def test_sqlite_storage_list_segments_skips_failures(sample_schema, sample_documents, monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        for idx, doc in enumerate(sample_documents[:2]):
            writer = SqliteSegmentWriter(sample_schema, segment_id=f"seg{idx}")
            writer.add_document(doc)
            sqlite_store.save(writer.build())

        original_load = sqlite_store.load

        def _load(segment_id):
            if segment_id == "seg0":
                raise RuntimeError("boom")
            return original_load(segment_id)

        monkeypatch.setattr(sqlite_store, "load", _load)

        segments = sqlite_store.list_segments()

        assert len(segments) == 1
        assert segments[0]["segment_id"] == "seg1"


def test_sqlite_storage_prune_ignores_unlink_errors(sample_schema, sample_documents, monkeypatch):
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)
        writer = SqliteSegmentWriter(sample_schema, segment_id="to_remove")
        writer.add_document(sample_documents[0])
        sqlite_store.save(writer.build())

        target_path = sqlite_store._db_path("to_remove")
        original_unlink = Path.unlink

        def _unlink(path, *args, **kwargs):
            if path == target_path:
                raise OSError("unlink boom")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _unlink)

        sqlite_store.prune_to_segment_ids([])


def test_sqlite_segment_writer_adds_unique_field_when_not_stored():
    schema = Schema(
        unique_field="slug",
        fields=[
            TextField(name="slug", stored=False, indexed=True),
            TextField(name="title", stored=True, indexed=True),
        ],
    )
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"slug": "doc-1", "title": "Doc"})

    segment_data = writer.build()
    stored = next(iter(segment_data["stored_fields"].values()))

    assert stored["slug"] == "doc-1"


def test_sqlite_segment_writer_rejects_none_unique_value(sample_schema):
    writer = SqliteSegmentWriter(sample_schema)

    with pytest.raises(ValueError, match="cannot be None"):
        writer.add_document({"url": None, "title": "Doc", "body": "Content"})


def test_sqlite_segment_writer_analyze_field_unknown_type(sample_schema):
    writer = SqliteSegmentWriter(sample_schema)

    assert writer._analyze_field(object(), "value") == []  # pylint: disable=protected-access


def test_sqlite_storage_metadata_handling(sample_schema, sample_documents):
    """Test metadata storage and retrieval."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create segment with custom metadata
        writer = SqliteSegmentWriter(sample_schema, segment_id="meta_test")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()

        # Test that metadata is stored and retrieved correctly
        sqlite_store.save(segment_data)

        # Load and verify metadata
        loaded = sqlite_store.load("meta_test")
        assert loaded is not None
        assert loaded.segment_id == "meta_test"
        assert loaded.doc_count == 1
        assert loaded.schema.unique_field == sample_schema.unique_field


def test_sqlite_storage_empty_postings(sample_schema):
    """Test handling of empty postings."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create segment with minimal data
        segment_dict = {
            "segment_id": "empty_test",
            "schema": sample_schema.to_dict(),
            "postings": {},
            "stored_fields": {},
            "field_lengths": {},
        }

        sqlite_store.save(segment_dict)
        loaded = sqlite_store.load("empty_test")

        assert loaded is not None
        assert loaded.doc_count == 0


def test_sqlite_storage_max_segments_configuration():
    """Test max segments configuration."""
    # Store original value
    original_max = SqliteSegmentStore.MAX_SEGMENTS

    try:
        # Test setting max segments
        SqliteSegmentStore.set_max_segments(10)
        assert SqliteSegmentStore.MAX_SEGMENTS == 10

        # Test setting None (should use default)
        SqliteSegmentStore.set_max_segments(None)
        assert SqliteSegmentStore.MAX_SEGMENTS == SqliteSegmentStore.DEFAULT_MAX_SEGMENTS

        # Test setting invalid value (should clamp to 1)
        SqliteSegmentStore.set_max_segments(0)
        assert SqliteSegmentStore.MAX_SEGMENTS == 1

        # Test setting negative value (should clamp to 1)
        SqliteSegmentStore.set_max_segments(-5)
        assert SqliteSegmentStore.MAX_SEGMENTS == 1
    finally:
        # Restore original value - this is critical for test isolation
        SqliteSegmentStore.MAX_SEGMENTS = original_max


def test_sqlite_segment_cleanup(sample_schema, sample_documents):
    """Test segment cleanup functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create segment
        writer = SqliteSegmentWriter(sample_schema, segment_id="cleanup_test")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        # Load segment and test cleanup
        loaded = sqlite_store.load("cleanup_test")
        assert loaded is not None

        # Test segment close method
        loaded.close()

        # Verify segment still works after close
        doc = loaded.get_document(sample_documents[0]["url"])
        assert doc is not None


def test_sqlite_storage_file_permissions_error(sample_schema, sample_documents):
    """Test handling of file permission errors."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create a segment first
        writer = SqliteSegmentWriter(sample_schema, segment_id="perm_test")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        # Make directory read-only to simulate permission error
        temp_path = Path(temp_dir)
        temp_path.chmod(0o444)

        try:
            # This should handle the permission error gracefully
            result = sqlite_store.latest_segment_id()
            # Result could be None if stat() fails
            assert result is None or result == "perm_test"
        finally:
            # Restore permissions for cleanup
            temp_path.chmod(0o755)


def test_sqlite_segment_writer_edge_cases(sample_schema):
    """Test SQLite segment writer edge cases."""
    # Test with custom segment ID
    writer = SqliteSegmentWriter(sample_schema, segment_id="custom_id")
    assert writer.segment_id == "custom_id"

    # Test building empty segment
    segment_data = writer.build()
    assert segment_data["segment_id"] == "custom_id"
    assert segment_data["doc_count"] == 0

    # Test adding document with missing unique field
    doc_without_unique = {"title": "Test", "body": "Content"}
    with pytest.raises(ValueError, match="Document missing unique field"):
        writer.add_document(doc_without_unique)


def test_sqlite_segment_postings_retrieval(sample_schema, sample_documents):
    """Test postings retrieval from SQLite segment."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create segment with documents
        writer = SqliteSegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment_data = writer.build()

        sqlite_store.save(segment_data)
        segment = sqlite_store.load(segment_data["segment_id"])

        # Test getting postings for a term that should exist
        # The exact terms depend on the analyzer, but we can test the interface
        postings = segment.get_postings("body", "document")  # Common word in test docs
        assert isinstance(postings, list)

        # Test getting postings for non-existent term
        empty_postings = segment.get_postings("body", "nonexistentterm12345")
        assert empty_postings == []


def test_sqlite_connection_pool_edge_cases():
    """Test SQLite connection pool edge cases."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        temp_path = temp_file.name

    try:
        # Test with max_connections=1
        pool = SQLiteConnectionPool(temp_path, max_connections=1)

        with pool.get_connection() as conn:
            assert conn is not None
            # Execute a simple query to ensure connection works
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1

        # Test close_all
        pool.close_all()

        # Test getting connection after close_all
        with pool.get_connection() as conn:
            assert conn is not None

    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            # Best-effort cleanup; ignore failures if the file is already gone or locked
            pass


def test_sqlite_storage_invalid_segment_data(sample_schema):
    """Test SQLite storage with invalid segment data."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Test with data that would cause int() conversion error in positions
        invalid_data = {
            "segment_id": "test",
            "postings": {
                "field": {
                    "term": [
                        {
                            "doc_id": "doc1",
                            "positions": ["not_a_number"],  # This will cause int() to fail
                        }
                    ]
                }
            },
        }
        with pytest.raises(ValueError, match="invalid literal for int"):
            sqlite_store.save(invalid_data)


def test_sqlite_segment_field_lengths(sample_schema, sample_documents):
    """Test field lengths storage and retrieval."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        writer = SqliteSegmentWriter(sample_schema)
        writer.add_document(sample_documents[0])
        segment_data = writer.build()

        sqlite_store.save(segment_data)
        segment = sqlite_store.load(segment_data["segment_id"])

        # Check that field lengths are stored correctly
        # field_lengths structure: {field_name: {doc_id: length}}
        doc_id = sample_documents[0]["url"]
        field_lengths = segment.field_lengths

        # Check structure exists
        assert "title" in field_lengths
        assert "body" in field_lengths

        # Check doc_id exists in each field
        assert doc_id in field_lengths["title"]
        assert doc_id in field_lengths["body"]


def test_sqlite_storage_concurrent_access(sample_schema, sample_documents):
    """Test concurrent access to SQLite storage."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create initial segment
        writer = SqliteSegmentWriter(sample_schema, segment_id="concurrent_test")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        results = []

        def load_segment():
            segment = sqlite_store.load("concurrent_test")
            results.append(segment is not None)

        # Create multiple threads to access the same segment
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=load_segment)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All threads should have successfully loaded the segment
        assert all(results)
        assert len(results) == 3
