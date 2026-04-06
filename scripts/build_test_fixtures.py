#!/usr/bin/env python3
"""Build deterministic test fixtures for CI parity tests.

Generates pre-built SQLite segment databases and golden search results
from sample_data.py content. Run manually when fixtures need updating:

    uv run python scripts/build_test_fixtures.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "integration_tests"))

from sample_data import (
    FILESYSTEM_DOCS,
    GIT_DOCS,
    ONLINE_DOCS,
    create_filesystem_tenant,
    create_git_tenant,
    create_online_tenant,
)

from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore, SqliteSegmentWriter

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "ci_mcp_data"
GOLDEN_DIR = PROJECT_ROOT / "tests" / "fixtures" / "golden"
SEGMENT_ID = "ci_fixture_001"
CREATED_AT = "2026-01-01T00:00:00+00:00"


def _extract_title(content: str) -> str:
    for line in content.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_headings(content: str) -> tuple[str, str, str]:
    h1, h2, other = [], [], []
    for line in content.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            h1.append(line[2:].strip())
        elif line.startswith("## ") and not line.startswith("### "):
            h2.append(line[3:].strip())
        elif line.startswith("### "):
            other.append(line[4:].strip())
    return " ".join(h1), " ".join(h2), " ".join(other)


def build_segment(docs: list[dict], tenant_dir: Path) -> None:
    """Index documents into a SQLite segment database."""
    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema, segment_id=SEGMENT_ID)
    writer.created_at = datetime.fromisoformat(CREATED_AT)

    for doc in docs:
        content = doc["content"]
        title = doc.get("title") or _extract_title(content)
        url = doc.get("url", f"file://{doc['filename']}")
        h1, h2, headings = _extract_headings(content)

        document = {
            "url": url,
            "url_path": url.split("//", 1)[-1] if "//" in url else doc["filename"],
            "title": title,
            "headings_h1": h1,
            "headings_h2": h2,
            "headings": headings,
            "body": content,
            "path": doc["filename"],
            "excerpt": content[:200],
        }
        writer.add_document(document)

    segment_data = writer.build()
    seg_dir = tenant_dir / "__search_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    store = SqliteSegmentStore(str(seg_dir))
    store.save(segment_data)
    print(f"  Built segment: {seg_dir / (SEGMENT_ID + '.db')} ({segment_data['doc_count']} docs)")


def run_golden_search(tenant_name: str, query: str) -> list[dict]:
    """Run BM25 search with features disabled to match Go CLI behavior."""
    seg_dir = FIXTURE_DIR / tenant_name / "__search_segments"
    store = SqliteSegmentStore(str(seg_dir))
    segment = store.latest()
    if segment is None:
        return []

    engine = BM25SearchEngine(
        segment.schema,
        enable_synonyms=False,
        enable_fuzzy=False,
        enable_phrase_bonus=False,
    )
    tokens = engine.tokenize_query(query)
    if tokens.is_empty():
        return []

    ranked = engine.score(segment, tokens, limit=10)
    results = []
    for rank, doc in enumerate(ranked, 1):
        fields = segment.get_document(doc.doc_id)
        results.append({
            "url": fields.get("url", doc.doc_id) if fields else doc.doc_id,
            "title": fields.get("title", "") if fields else "",
            "rank": rank,
            "score": round(doc.score, 6),
        })
    segment.close()
    return results


def save_golden(tenant: str, query: str, results: list[dict]) -> None:
    slug = f"search_{tenant.replace('-', '_')}_{query.replace(' ', '_')}.json"
    path = GOLDEN_DIR / slug
    data = {
        "tenant": tenant,
        "query": query,
        "results": results,
        "generated_by": "python",
        "generated_at": CREATED_AT,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    urls = [r["url"] for r in results[:3]]
    print(f"  Golden: {slug} ({len(results)} results, top: {urls})")


def main():
    # Clean and recreate
    import shutil

    if FIXTURE_DIR.exists():
        shutil.rmtree(FIXTURE_DIR)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    # Build tenant directories with markdown content
    print("Building tenant content...")
    create_online_tenant(FIXTURE_DIR / "webapi-ci")
    create_git_tenant(FIXTURE_DIR / "gitdocs-ci")
    create_filesystem_tenant(FIXTURE_DIR / "localdocs-ci")

    # Build search indexes
    print("\nBuilding search indexes...")
    build_segment(ONLINE_DOCS, FIXTURE_DIR / "webapi-ci")
    build_segment(
        [{"filename": f"docs/{d['filename']}", "content": d["content"]} for d in GIT_DOCS],
        FIXTURE_DIR / "gitdocs-ci",
    )
    build_segment(FILESYSTEM_DOCS, FIXTURE_DIR / "localdocs-ci")

    # Generate golden search results
    print("\nGenerating golden search results...")
    golden_queries = [
        ("webapi-ci", "routing"),
        ("webapi-ci", "security"),
        ("gitdocs-ci", "themes"),
        ("gitdocs-ci", "plugins"),
        ("localdocs-ci", "tools"),
    ]

    for tenant, query in golden_queries:
        results = run_golden_search(tenant, query)
        save_golden(tenant, query, results)

    print(f"\nFixtures written to {FIXTURE_DIR}")
    print(f"Golden results written to {GOLDEN_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
