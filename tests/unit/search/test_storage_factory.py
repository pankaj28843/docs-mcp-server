"""Test SQLite-only storage factory functionality."""

from pathlib import Path
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
    ]


def test_create_segment_store():
    """Test creating SQLite segment store."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from docs_mcp_server.search.storage_factory import create_segment_store

        store = create_segment_store(Path(temp_dir))
        assert isinstance(store, SqliteSegmentStore)


def test_get_latest_doc_count_empty():
    """Test getting doc count from empty storage."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from docs_mcp_server.search.storage_factory import get_latest_doc_count

        count = get_latest_doc_count(Path(temp_dir))
        assert count is None


def test_get_latest_doc_count_with_data(sample_schema, sample_documents):
    """Test getting doc count from storage with data."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from docs_mcp_server.search.storage_factory import create_segment_store, get_latest_doc_count

        # Create and save segment
        store = create_segment_store(Path(temp_dir))
        writer = SqliteSegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment_data = writer.build()
        store.save(segment_data)

        # Test doc count
        count = get_latest_doc_count(Path(temp_dir))
        assert count == len(sample_documents)


def test_has_search_index_empty():
    """Test checking for search index in empty directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from docs_mcp_server.search.storage_factory import has_search_index

        # Non-existent directory
        assert not has_search_index(Path(temp_dir) / "nonexistent")

        # Empty directory
        assert not has_search_index(Path(temp_dir))


def test_has_search_index_with_data(sample_schema, sample_documents):
    """Test checking for search index with data."""
    with tempfile.TemporaryDirectory() as temp_dir:
        from docs_mcp_server.search.storage_factory import create_segment_store, has_search_index

        # Create and save segment
        store = create_segment_store(Path(temp_dir))
        writer = SqliteSegmentWriter(sample_schema)
        for doc in sample_documents:
            writer.add_document(doc)
        segment_data = writer.build()
        store.save(segment_data)

        # Test index exists
        assert has_search_index(Path(temp_dir))
