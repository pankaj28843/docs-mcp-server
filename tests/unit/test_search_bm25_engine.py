"""Unit tests for the lightweight BM25 search helpers."""

from __future__ import annotations

from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.storage import SegmentWriter


def _body_base_terms(query: str, schema) -> list[str]:
    body_field = next((field for field in schema.text_fields if field.name == "body"), None)
    if body_field is None:
        return []
    analyzer = get_analyzer(body_field.analyzer_name)
    seen: set[str] = set()
    terms: list[str] = []
    for token in analyzer(query):
        if not token.text or token.text in seen:
            continue
        seen.add(token.text)
        terms.append(token.text)
    return terms


def test_tokenize_query_returns_ordered_tokens_without_duplicates() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False)

    query = "Graph auth integration"
    tokens = engine.tokenize_query(query)

    assert not tokens.is_empty()
    expected_base_terms = _body_base_terms(query, schema)
    assert tokens.base_term_count == len(expected_base_terms)
    assert list(tokens.ordered_terms[: len(expected_base_terms)]) == expected_base_terms
    assert len(tokens.ordered_terms) == len(set(tokens.ordered_terms)), "terms should be unique per query"


def test_tokenize_query_appends_synonyms_after_base_terms() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema)

    tokens = engine.tokenize_query("auth")
    body_terms = tokens.per_field.get("body")
    assert body_terms is not None
    # Base term should remain first, with stable synonym ordering afterwards
    assert body_terms[0] == "auth"
    assert list(body_terms[1:]) == ["authentication", "authorization"]
    assert tokens.base_term_count == 1


def test_score_supports_fuzzy_matches_for_base_terms() -> None:
    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/hooks",
            "title": "Webhook handling",
            "headings": "Webhooks",
            "body": "Use webhooks to receive events without polling.",
            "path": "hooks.md",
            "tags": ["webhooks"],
            "excerpt": "Receive events via webhooks",
            "timestamp": 1700000000,
        }
    )
    segment = writer.build()

    engine = BM25SearchEngine(schema, enable_synonyms=False)
    tokens = engine.tokenize_query("webhookz")

    ranked = engine.score(segment, tokens, limit=5)
    assert ranked, "Fuzzy match should produce a ranked document"
    assert ranked[0].score > 0
