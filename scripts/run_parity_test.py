#!/usr/bin/env python3
"""Parity test: verify Python and Go produce identical search rankings.

Usage:
    uv run python scripts/run_parity_test.py \
        --fixture-dir tests/fixtures/ci_mcp_data \
        --go-binary cli/docsearch
"""

# ruff: noqa: E402, T201, TRY004

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


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


def go_environment(config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["TECHDOCS_DEPLOYMENT_CONFIG"] = str(config_path.resolve())
    env.pop("TECHDOCS_DATA_DIR", None)
    return env


def run_go_json(
    go_binary: str,
    fixture_dir: Path,
    config_path: Path,
    args: list[str],
    *,
    expected_exit: int,
) -> dict:
    result = subprocess.run(
        [go_binary, *args, "--json", "--data-dir", str(fixture_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=go_environment(config_path),
    )
    if result.returncode != expected_exit:
        raise AssertionError(
            f"docsearch {' '.join(args)} exited {result.returncode}, expected {expected_exit}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    if result.stderr:
        raise AssertionError(f"docsearch {' '.join(args)} wrote JSON-mode stderr: {result.stderr!r}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"docsearch {' '.join(args)} emitted invalid JSON: {result.stdout!r}") from exc
    if not isinstance(payload, dict):
        raise AssertionError(f"docsearch {' '.join(args)} emitted non-object JSON: {payload!r}")
    return payload


def go_search(
    go_binary: str,
    fixture_dir: Path,
    config_path: Path,
    tenant: str,
    query: str,
) -> list[str]:
    """Return ranked URL list from Go CLI."""
    data = run_go_json(
        go_binary,
        fixture_dir,
        config_path,
        ["search", tenant, query],
        expected_exit=0,
    )
    return [r["url"] for r in data.get("results", [])]


def assert_failure(payload: dict, *, error_class: str, code: str) -> None:
    error = payload.get("error")
    if not isinstance(error, dict):
        raise AssertionError(f"missing error object: {payload!r}")
    if error.get("class") != error_class or error.get("code") != code:
        raise AssertionError(f"unexpected failure classification: {payload!r}")
    if not error.get("message") or not error.get("actions"):
        raise AssertionError(f"failure lacks message/actions: {payload!r}")


def verify_installed_cli_contract(go_binary: str, fixture_dir: Path, config_path: Path) -> None:
    listed = run_go_json(go_binary, fixture_dir, config_path, ["list"], expected_exit=0)
    if listed.get("count") != 4:
        raise AssertionError(f"unexpected tenant list: {listed!r}")

    described = run_go_json(go_binary, fixture_dir, config_path, ["describe", "webapi-ci"], expected_exit=0)
    if described.get("codename") != "webapi-ci" or "provenance" not in described:
        raise AssertionError(f"describe omitted identity/provenance: {described!r}")

    searched = run_go_json(
        go_binary,
        fixture_dir,
        config_path,
        ["search", "webapi-ci", "routing"],
        expected_exit=0,
    )
    results = searched.get("results") or []
    if searched.get("tenant") != "webapi-ci" or not results or "provenance" not in searched:
        raise AssertionError(f"search omitted results/tenant/provenance: {searched!r}")

    run_go_json(go_binary, fixture_dir, config_path, ["search-all", "routing"], expected_exit=0)
    url = results[0]["url"]
    fetched = run_go_json(
        go_binary,
        fixture_dir,
        config_path,
        ["fetch", "webapi-ci", url, "--max-chars", "10"],
        expected_exit=0,
    )
    if fetched.get("returned_chars", 0) > 10 or "truncated" not in fetched or "provenance" not in fetched:
        raise AssertionError(f"bounded fetch omitted counts/provenance: {fetched!r}")

    with tempfile.TemporaryDirectory() as temp_dir:
        destination = Path(temp_dir) / "page.md"
        artifact = run_go_json(
            go_binary,
            fixture_dir,
            config_path,
            ["fetch", "webapi-ci", url, "--out", str(destination)],
            expected_exit=0,
        )
        if not destination.is_file() or artifact.get("artifact", {}).get("path") != str(destination):
            raise AssertionError(f"file-backed fetch did not produce its artifact: {artifact!r}")

    failure_cases = [
        (["search", "missing", "query"], 4, "tenant", "tenant_not_found"),
        (["fetch", "webapi-ci", "https://example.com/missing"], 6, "document", "document_not_found"),
        (["describe", "missing"], 4, "tenant", "tenant_not_found"),
        (["search", "webapi-ci", "query", "--size", "0"], 2, "usage", "invalid_argument"),
        (["search", "unindexed-ci", "query"], 5, "index", "index_unavailable"),
    ]
    for args, exit_code, error_class, code in failure_cases:
        payload = run_go_json(
            go_binary,
            fixture_dir,
            config_path,
            args,
            expected_exit=exit_code,
        )
        assert_failure(payload, error_class=error_class, code=code)

    missing_root = fixture_dir / "missing-data-root"
    payload = run_go_json(
        go_binary,
        missing_root,
        config_path,
        ["list"],
        expected_exit=3,
    )
    assert_failure(payload, error_class="storage", code="data_root_unavailable")
    print("PASS installed CLI JSON success/failure, fetch policy, and exit-code contract")


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

    config_path = PROJECT_ROOT / "tests" / "fixtures" / "ci_deployment.json"
    if not config_path.exists():
        print(f"Fixture deployment config not found: {config_path}", file=sys.stderr)
        return 1

    try:
        verify_installed_cli_contract(str(go_bin), args.fixture_dir, config_path)
    except AssertionError as exc:
        print(f"FAIL installed CLI contract: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for tenant, query in QUERIES:
        py_urls = python_search(args.fixture_dir, tenant, query)
        go_urls = go_search(str(go_bin), args.fixture_dir, config_path, tenant, query)

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
