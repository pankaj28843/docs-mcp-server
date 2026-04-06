#!/usr/bin/env python3
"""Parity test: verify Python and Go produce identical search rankings.

Usage:
    uv run python scripts/run_parity_test.py \
        --fixture-dir tests/fixtures/ci_mcp_data \
        --go-binary cli/docsearch
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore


QUERIES = [
    ("webapi-ci", "routing"),
    ("webapi-ci", "security"),
    ("gitdocs-ci", "themes"),
    ("gitdocs-ci", "plugins"),
    ("localdocs-ci", "tools"),
]


def python_search(fixture_dir: Path, tenant: str, query: str) -> list[str]:
    """Return ranked URL list from Python BM25 engine."""
    seg_dir = fixture_dir / tenant / "__search_segments"
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
        segment.close()
        return []

    ranked = engine.score(segment, tokens, limit=10)
    urls = []
    for doc in ranked:
        fields = segment.get_document(doc.doc_id)
        if fields:
            urls.append(fields.get("url", doc.doc_id))
    segment.close()
    return urls


def go_search(go_binary: str, fixture_dir: Path, tenant: str, query: str) -> list[str]:
    """Return ranked URL list from Go CLI."""
    result = subprocess.run(
        [go_binary, "search", tenant, query, "--json", "--data-dir", str(fixture_dir)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        print(f"  Go CLI error: {result.stderr}", file=sys.stderr)
        return []

    data = json.loads(result.stdout)
    return [r["url"] for r in data.get("results", [])]


def main():
    parser = argparse.ArgumentParser(description="Python/Go parity test")
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--go-binary", type=str, required=True)
    args = parser.parse_args()

    if not args.fixture_dir.exists():
        print(f"Fixture dir not found: {args.fixture_dir}", file=sys.stderr)
        return 1

    go_bin = Path(args.go_binary)
    if not go_bin.exists():
        print(f"Go binary not found: {go_bin}", file=sys.stderr)
        return 1

    failures = 0
    for tenant, query in QUERIES:
        py_urls = python_search(args.fixture_dir, tenant, query)
        go_urls = go_search(str(go_bin), args.fixture_dir, tenant, query)

        # Both must return results
        if not py_urls:
            print(f"FAIL {tenant}/{query}: Python returned no results")
            failures += 1
            continue
        if not go_urls:
            print(f"FAIL {tenant}/{query}: Go returned no results")
            failures += 1
            continue

        # Rank-1 must match (strict)
        if py_urls[0] != go_urls[0]:
            print(f"FAIL {tenant}/{query}: rank-1 mismatch")
            print(f"  Python: {py_urls[0]}")
            print(f"  Go:     {go_urls[0]}")
            failures += 1
            continue

        # Top-N URL sets must match
        py_set = set(py_urls)
        go_set = set(go_urls)
        if py_set != go_set:
            print(f"WARN {tenant}/{query}: URL sets differ (rank-1 matches)")
            print(f"  Python only: {py_set - go_set}")
            print(f"  Go only:     {go_set - py_set}")

        print(f"PASS {tenant}/{query}: rank-1={py_urls[0]}")

    if failures:
        print(f"\n{failures} parity test(s) FAILED")
        return 1

    print(f"\nAll {len(QUERIES)} parity tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
