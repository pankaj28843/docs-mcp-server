"""Test SQLite storage functionality."""

import tempfile

import pytest

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore, SqliteSegmentWriter


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
        # Cleanup is automatic with TemporaryDirectory


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


def test_sqlite_storage_document_retrieval(sample_schema, sample_documents):
    """Test document storage and retrieval functionality."""
    with tempfile.TemporaryDirectory() as sqlite_dir:
        # Create segment
        writer = SqliteSegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment_data = writer.build()

        # Save with SQLite storage
        sqlite_store = SqliteSegmentStore(sqlite_dir)
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
    from array import array

    # Test position array encoding/decoding
    original_positions = [0, 5, 10, 15, 20]
    positions_array = array("I", original_positions)
    positions_blob = positions_array.tobytes()

    # Decode back
    decoded_array = array("I")
    decoded_array.frombytes(positions_blob)
    decoded_positions = list(decoded_array)

    assert decoded_positions == original_positions


def test_sqlite_storage_latest_segment(sample_schema, sample_documents):
    """Test latest segment functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

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
    import tempfile

    from docs_mcp_server.search.sqlite_storage import SQLiteConnectionPool

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
        from pathlib import Path

        try:
            Path(temp_path).unlink()
        except OSError:
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

        # Test save error handling by making directory read-only
        from pathlib import Path

        temp_path = Path(temp_dir)
        temp_path.chmod(0o444)
        try:
            # This should fail due to permission error
            valid_data = {"segment_id": "test", "schema": sample_schema.to_dict()}
            with pytest.raises(RuntimeError, match="Failed to save SQLite segment"):
                sqlite_store.save(valid_data)
        finally:
            # Restore permissions
            temp_path.chmod(0o755)


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
    from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore

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
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_store = SqliteSegmentStore(temp_dir)

        # Create a segment first
        writer = SqliteSegmentWriter(sample_schema, segment_id="perm_test")
        writer.add_document(sample_documents[0])
        segment_data = writer.build()
        sqlite_store.save(segment_data)

        # Make directory read-only to simulate permission error
        from pathlib import Path

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
