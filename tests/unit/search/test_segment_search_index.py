from __future__ import annotations

from pathlib import Path

from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.segment_search_index import SegmentSearchIndex
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore, SqliteSegmentWriter


def _build_segment(tmp_path: Path, docs_root: Path, *, body: str, excerpt: str) -> Path:
    doc_path = docs_root / "doc.md"
    doc_path.write_text(body, encoding="utf-8")

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document(
        {
            "url": doc_path.resolve().as_uri(),
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


def test_segment_search_reads_body_from_disk_when_missing_in_db(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    db_path = _build_segment(tmp_path, docs_root, body="Hello search world.", excerpt="Excerpt only.")

    search_index = SegmentSearchIndex(db_path, docs_root=docs_root)
    response = search_index.search("search", max_results=5)

    assert response.results
    assert "search" in response.results[0].snippet.lower()


def test_segment_search_falls_back_to_excerpt_when_file_missing(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    db_path = _build_segment(tmp_path, docs_root, body="Hello search world.", excerpt="Search excerpt fallback.")

    (docs_root / "doc.md").unlink()

    search_index = SegmentSearchIndex(db_path, docs_root=docs_root)
    response = search_index.search("search", max_results=5)

    assert response.results
    assert "excerpt" in response.results[0].snippet.lower()
