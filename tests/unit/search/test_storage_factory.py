"""Test storage factory functionality."""

from pathlib import Path
import tempfile

import pytest

from docs_mcp_server.search.schema import Schema, TextField
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore
from docs_mcp_server.search.storage import JsonSegmentStore
from docs_mcp_server.search.storage_factory import UnifiedSegmentStore


class TestUnifiedSegmentStore:
    """Test unified segment store factory."""

    @pytest.fixture
    def schema(self):
        """Create test schema."""
        return Schema(
            fields=[
                TextField(name="url", stored=True),
                TextField(name="title", stored=True),
                TextField(name="body", stored=False),
            ]
        )

    def test_create_json_store_by_default(self, schema):
        """Test that JSON store is created by default."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = UnifiedSegmentStore(Path(temp_dir))
            assert isinstance(store._store, JsonSegmentStore)

    def test_create_sqlite_store_when_requested(self, schema):
        """Test that SQLite store is created when requested."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = UnifiedSegmentStore(Path(temp_dir), use_sqlite=True)
            assert isinstance(store._store, SqliteSegmentStore)

    def test_create_json_store_when_sqlite_disabled(self, schema):
        """Test that JSON store is created when SQLite is explicitly disabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = UnifiedSegmentStore(Path(temp_dir), use_sqlite=False)
            assert isinstance(store._store, JsonSegmentStore)

    def test_factory_passes_parameters_correctly(self, schema):
        """Test that factory passes parameters to underlying stores correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test JSON store
            json_store = UnifiedSegmentStore(Path(temp_dir))
            assert json_store._store.directory == Path(temp_dir)

            # Test SQLite store
            sqlite_store = UnifiedSegmentStore(Path(temp_dir), use_sqlite=True)
            assert sqlite_store._store.directory == Path(temp_dir)

    def test_both_stores_have_same_interface(self, schema):
        """Test that both stores expose the same interface through the factory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            json_store = UnifiedSegmentStore(Path(temp_dir))
            sqlite_store = UnifiedSegmentStore(Path(temp_dir), use_sqlite=True)

            # Both should have the same methods
            for method_name in ["save", "load", "latest", "latest_segment_id", "latest_doc_count", "segment_path"]:
                assert hasattr(json_store, method_name)
                assert hasattr(sqlite_store, method_name)
                assert callable(getattr(json_store, method_name))
                assert callable(getattr(sqlite_store, method_name))
