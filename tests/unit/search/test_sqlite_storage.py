"""Test SQLite storage compatibility with JSON storage."""

import tempfile

import pytest

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore
from docs_mcp_server.search.storage import JsonSegmentStore, SegmentWriter


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


def test_sqlite_storage_basic_functionality(sample_schema, sample_documents):
    """Test basic SQLite storage save/load functionality."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create segment using existing SegmentWriter
        writer = SegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment = writer.build()

        # Save using SQLite storage
        sqlite_store = SqliteSegmentStore(temp_dir)
        db_path = sqlite_store.save(segment.to_dict())

        # Verify file was created
        assert db_path.exists()
        assert db_path.suffix == ".db"

        # Load segment back
        loaded_segment = sqlite_store.load(segment.segment_id)
        assert loaded_segment is not None
        assert loaded_segment.segment_id == segment.segment_id
        assert loaded_segment.doc_count == len(sample_documents)


def test_sqlite_json_storage_compatibility(sample_schema, sample_documents):
    """Test that SQLite storage produces identical search results to JSON storage."""
    with tempfile.TemporaryDirectory() as json_dir, tempfile.TemporaryDirectory() as sqlite_dir:
        # Create segment
        writer = SegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment = writer.build()

        # Save with JSON storage
        json_store = JsonSegmentStore(json_dir)
        json_store.save(segment)
        json_segment = json_store.load(segment.segment_id)

        # Save with SQLite storage
        sqlite_store = SqliteSegmentStore(sqlite_dir)
        sqlite_store.save(segment.to_dict())
        sqlite_segment = sqlite_store.load(segment.segment_id)

        # Compare document counts
        assert json_segment.doc_count == sqlite_segment.doc_count

        # Compare stored documents
        for doc in sample_documents:
            doc_id = doc["url"]
            json_doc = json_segment.get_document(doc_id)
            sqlite_doc = sqlite_segment.get_document(doc_id)
            assert json_doc == sqlite_doc

        # Compare postings for each field/term combination
        for field_name in ["title", "body"]:
            # Get all terms from JSON segment
            json_terms = set()
            if field_name in segment.postings:
                json_terms = set(segment.postings[field_name].keys())

            for term in json_terms:
                json_postings = json_segment.get_postings(field_name, term)
                sqlite_postings = sqlite_segment.get_postings(field_name, term)

                # Sort by doc_id for comparison
                json_postings.sort(key=lambda p: p.doc_id)
                sqlite_postings.sort(key=lambda p: p.doc_id)

                assert len(json_postings) == len(sqlite_postings)

                for json_posting, sqlite_posting in zip(json_postings, sqlite_postings, strict=True):
                    assert json_posting.doc_id == sqlite_posting.doc_id
                    assert json_posting.frequency == sqlite_posting.frequency
                    assert list(json_posting.positions) == list(sqlite_posting.positions)


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
        writer1 = SegmentWriter(sample_schema, segment_id="segment1")
        writer1.add_document(sample_documents[0])
        segment1 = writer1.build()
        sqlite_store.save(segment1.to_dict())

        # Create and save second segment (more recent)
        writer2 = SegmentWriter(sample_schema, segment_id="segment2")
        for doc in sample_documents:
            writer2.add_document(doc)
        segment2 = writer2.build()
        sqlite_store.save(segment2.to_dict())

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
            writer = SegmentWriter(sample_schema, segment_id=f"segment{i}")
            writer.add_document(doc)
            segment = writer.build()
            sqlite_store.save(segment.to_dict())

        # List segments
        segments = sqlite_store.list_segments()
        assert len(segments) == len(sample_documents)

        segment_ids = {seg["segment_id"] for seg in segments}
        expected_ids = {f"segment{i}" for i in range(len(sample_documents))}
        assert segment_ids == expected_ids
