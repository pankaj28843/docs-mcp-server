"""SQLite-only storage for high-performance search indexing."""

from pathlib import Path

from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore


def create_segment_store(segments_dir: Path, **kwargs) -> SqliteSegmentStore:
    """Create SQLite segment store."""
    return SqliteSegmentStore(segments_dir)


def get_latest_doc_count(segments_dir: Path, **kwargs) -> int | None:
    """Get latest document count from SQLite storage."""
    store = create_segment_store(segments_dir)
    return store.latest_doc_count()


def has_search_index(segments_dir: Path, **kwargs) -> bool:
    """Check if search index exists in SQLite storage."""
    if not segments_dir.exists():
        return False
    store = create_segment_store(segments_dir)
    return store.latest_segment_id() is not None
