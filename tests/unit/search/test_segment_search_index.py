from __future__ import annotations

from pathlib import Path

from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.segment_search_index import SegmentSearchIndex
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore, SqliteSegmentWriter


def _build_segment(tmp_path: Path, *, body: str, excerpt: str) -> Path:
    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document(
        {
            "url": "file:///doc.md",
            "url_path": "/doc.md",
            "title": "Doc",
            "headings_h1": "Doc",
            "headings_h2": "",
            "headings": "",
            "body": body,
            "path": "doc.md",
            "tags": [],
            "excerpt": excerpt,
            "language": "en",
            "timestamp": 0,
        }
    )

    segment_data = writer.build()
    store = SqliteSegmentStore(tmp_path)
    return store.save(segment_data)


def test_segment_search_uses_body_from_db(tmp_path: Path) -> None:
    db_path = _build_segment(tmp_path, body="Hello search world.", excerpt="Excerpt only.")

    search_index = SegmentSearchIndex(db_path)
    response = search_index.search("search", max_results=5)

    assert response.results
    assert "search" in response.results[0].snippet.lower()
