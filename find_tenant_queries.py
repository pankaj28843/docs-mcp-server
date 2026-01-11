#!/usr/bin/env python3
"""Derive high-signal test queries for each tenant from SQLite search segments.

The script inspects `mcp-data/<tenant>/__search_segments/` to locate
the latest SQLite segment, walks the stored documents, and extracts
titles, headings, and bullet links to seed three query buckets:

- natural: question-style prompts ("How to ...", "What is ...")
- phrases: direct titles/headings for phrase matching
- words: high-frequency keywords from titles/headings

Run with `--update` to rewrite deployment.json with the generated queries.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable
import json
from pathlib import Path
import re
import sys


STOPWORDS = {
    "and",
    "with",
    "your",
    "from",
    "that",
    "this",
    "using",
    "into",
    "when",
    "will",
    "have",
    "each",
    "such",
    "more",
    "most",
    "many",
    "over",
    "them",
    "they",
    "their",
    "within",
    "ours",
    "been",
    "than",
    "where",
    "what",
    "how",
}
NATURAL_PREFIXES = (
    "how",
    "what",
    "when",
    "where",
    "why",
    "using",
    "building",
    "creating",
    "configuring",
    "working",
)
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_\-/]{2,}")


def _load_latest_segment_docs(docs_root: Path) -> list[dict]:
    """Load documents from SQLite segment."""
    search_dir = docs_root / "__search_segments"
    if not search_dir.exists():
        return []

    # Import SQLite storage
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore

    try:
        store = SqliteSegmentStore(search_dir)
        segment = store.latest()
        if not segment:
            return []

        docs = []
        stored_fields = segment.stored_fields
        for doc_id, fields in stored_fields.items():
            if isinstance(fields, dict):
                docs.append(fields)
        
        return docs
    except Exception:
        return []


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        marker = normalized.lower()
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(normalized)
    return ordered


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.findall(text):
        token = match.lower()
        if len(token) < 4 or token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _fallback_queries(codename: str) -> dict[str, list[str]]:
    base = codename.replace("-", " ")
    natural = [f"{base} getting started", f"{base} configuration guide", f"{base} troubleshooting"]
    phrases = [f"{base} quickstart", f"{base} reference", f"{base} API overview"]
    words = [codename, "configuration", "guide"]
    return {"natural": natural, "phrases": phrases, "words": words}


def derive_queries(codename: str, docs_root: Path) -> dict[str, list[str]]:
    docs = _load_latest_segment_docs(docs_root)
    if not docs:
        return _fallback_queries(codename)

    phrase_candidates: list[str] = []
    natural_candidates: list[str] = []
    bullet_candidates: list[str] = []
    token_counter: Counter[str] = Counter()

    for doc in docs:
        title = (doc.get("title") or "").strip()
        if title:
            normalized_title = " ".join(title.split())
            phrase_candidates.append(normalized_title)
            token_counter.update(_tokenize(normalized_title))
            if normalized_title.lower().startswith(NATURAL_PREFIXES) or normalized_title.endswith("?"):
                natural_candidates.append(normalized_title)

        body = doc.get("body") or ""
        if not body:
            continue

        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip("¶").strip()
            if not line:
                continue
            if line.startswith(("##", "###")):
                heading = line.lstrip("# ").strip()
                if heading:
                    phrase_candidates.append(heading)
                    token_counter.update(_tokenize(heading))
                    if heading.lower().startswith(NATURAL_PREFIXES) or heading.endswith("?"):
                        natural_candidates.append(heading)
                continue
            if line.startswith(("*", "-", "•")) and "[" in line and "]" in line:
                text = line.split("]", 1)[0]
                text = text.split("[", 1)[-1].strip()
                if text:
                    bullet_candidates.append(text)
                    phrase_candidates.append(text)
                    token_counter.update(_tokenize(text))

    natural_pool = bullet_candidates + natural_candidates
    natural = _dedupe([q for q in natural_pool if len(q.split()) >= 2])[:4]
    phrases = _dedupe(phrase_candidates)[:6]
    words = [token for token, _ in token_counter.most_common(6)]

    fallback = _fallback_queries(codename)
    if len(natural) < 3:
        natural.extend([item for item in fallback["natural"] if item not in natural])
        natural = natural[:3]
    if len(phrases) < 3:
        phrases.extend([item for item in fallback["phrases"] if item not in phrases])
        phrases = phrases[:3]
    if len(words) < 3:
        for item in fallback["words"]:
            if item not in words:
                words.append(item)
            if len(words) >= 3:
                break

    return {
        "natural": natural,
        "phrases": phrases,
        "words": words,
    }


def _load_config(path: Path) -> dict:
    with path.open() as fh:
        return json.load(fh)


def _write_config(path: Path, config: dict):
    path.write_text(json.dumps(config, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate per-tenant test queries from manifests")
    parser.add_argument(
        "--tenants",
        nargs="+",
        help="Limit processing to specific tenant codenames",
    )
    parser.add_argument(
        "--config",
        default="deployment.json",
        help="Path to deployment config (default: deployment.json)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite deployment.json with the generated test_queries",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = _load_config(config_path)
    targets = set(args.tenants or [])
    limit_to_subset = bool(targets)

    tenant_queries: dict[str, dict[str, list[str]]] = {}

    print("Deriving test queries from manifest/index data...\n")
    for tenant_config in config.get("tenants", []):
        codename = tenant_config.get("codename")
        if not codename:
            continue
        if limit_to_subset and codename not in targets:
            continue

        docs_root = Path(tenant_config.get("docs_root_dir", f"./mcp-data/{codename}"))
        if not docs_root.exists():
            print(f"⚠️ {codename}: docs root {docs_root} missing, skipping")
            continue

        queries = derive_queries(codename, docs_root)
        tenant_queries[codename] = queries
        print(
            f"📂 {codename}: natural={queries['natural'][:3]}, phrases={queries['phrases'][:3]}, words={queries['words'][:3]}"
        )

    if not tenant_queries:
        print("No tenant queries generated")
        return 1

    if args.update:
        updated = False
        for tenant_config in config.get("tenants", []):
            codename = tenant_config.get("codename")
            if codename in tenant_queries:
                tenant_config["test_queries"] = tenant_queries[codename]
                updated = True
        if updated:
            _write_config(config_path, config)
            print(f"\n✅ Updated {config_path} with manifest-derived queries")
        else:
            print("\n⚠️ No matching tenants to update in deployment config")

    else:
        print("\nGenerated tenant query blocks (add to deployment.json):\n")
        for codename, queries in tenant_queries.items():
            print(f'  "{codename}": {json.dumps(queries, indent=2)},')

    return 0


if __name__ == "__main__":
    sys.exit(main())
