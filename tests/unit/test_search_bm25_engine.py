"""Unit tests for the lightweight BM25 search helpers."""

from __future__ import annotations

from array import array
from types import MappingProxyType

import pytest

from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.bm25_engine import BM25SearchEngine, QueryTokens
from docs_mcp_server.search.schema import KeywordField, Schema, TextField, create_default_schema
from docs_mcp_server.search.storage import IndexSegment, Posting, SegmentWriter


pytestmark = pytest.mark.unit


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


def test_tokenize_query_returns_empty_for_blank_input() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema)

    tokens = engine.tokenize_query("   ")

    assert tokens.is_empty()


def test_tokenize_query_skips_fields_without_terms() -> None:
    schema = Schema(fields=[KeywordField("url"), TextField("body", analyzer_name="path")], unique_field="url")
    engine = BM25SearchEngine(schema, enable_synonyms=False)

    tokens = engine.tokenize_query("/")

    assert tokens.is_empty()


def test_score_returns_empty_when_query_tokens_empty() -> None:
    schema = create_default_schema()
    segment = SegmentWriter(schema).build()
    engine = BM25SearchEngine(schema, enable_synonyms=False)

    ranked = engine.score(segment, QueryTokens.empty(), limit=5)

    assert ranked == []


def test_score_skips_fields_with_no_tokens() -> None:
    schema = create_default_schema()
    segment = SegmentWriter(schema).build()
    engine = BM25SearchEngine(schema, enable_synonyms=False)
    tokens = QueryTokens(MappingProxyType({"body": ()}), (), 0, "")

    ranked = engine.score(segment, tokens, limit=5)

    assert ranked == []


def test_score_skips_fields_without_postings() -> None:
    schema = create_default_schema()
    segment = IndexSegment(
        schema=schema,
        postings={"body": {}},
        stored_fields={"doc-1": {"url": "https://example.com"}},
        field_lengths={"body": {"doc-1": 3}},
    )
    engine = BM25SearchEngine(schema, enable_synonyms=False)
    tokens = QueryTokens(MappingProxyType({"body": ("alpha",)}), ("alpha",), 1, "alpha")

    ranked = engine.score(segment, tokens, limit=5)

    assert ranked == []


def test_score_ignores_zero_weight_postings() -> None:
    schema = create_default_schema()
    segment = IndexSegment(
        schema=schema,
        postings={"body": {"alpha": [Posting(doc_id="doc-1", positions=array("I"))]}},
        stored_fields={"doc-1": {"url": "https://example.com"}},
        field_lengths={"body": {"doc-1": 0}},
    )
    engine = BM25SearchEngine(schema, enable_synonyms=False)
    tokens = QueryTokens(MappingProxyType({"body": ("alpha",)}), ("alpha",), 1, "alpha")

    ranked = engine.score(segment, tokens, limit=5)

    assert ranked == []


def test_apply_phrase_bonus_noops_without_body_field() -> None:
    schema = Schema(fields=[KeywordField("url"), TextField("title")], unique_field="url")
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=True)
    segment = IndexSegment(schema=schema, postings={}, stored_fields={}, field_lengths={})
    doc_scores = {"doc-1": 1.0}

    engine._apply_phrase_bonus(doc_scores, segment, "alpha beta")  # pylint: disable=protected-access

    assert doc_scores["doc-1"] == 1.0


def test_apply_phrase_bonus_noops_without_postings() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=True)
    segment = IndexSegment(
        schema=schema,
        postings={"body": {}},
        stored_fields={"doc-1": {"url": "https://example.com"}},
        field_lengths={"body": {"doc-1": 2}},
    )
    doc_scores = {"doc-1": 1.0}

    engine._apply_phrase_bonus(doc_scores, segment, "alpha beta")  # pylint: disable=protected-access

    assert doc_scores["doc-1"] == 1.0


def test_apply_phrase_bonus_skips_infinite_span() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=True)
    segment = IndexSegment(
        schema=schema,
        postings={
            "body": {
                "alpha": [Posting(doc_id="doc-1", positions=array("I"))],
                "beta": [Posting(doc_id="doc-1", positions=array("I"))],
            }
        },
        stored_fields={"doc-1": {"url": "https://example.com"}},
        field_lengths={"body": {"doc-1": 2}},
    )
    doc_scores = {"doc-1": 1.0}

    engine._apply_phrase_bonus(doc_scores, segment, "alpha beta")  # pylint: disable=protected-access

    assert doc_scores["doc-1"] == 1.0


def test_apply_phrase_bonus_skips_wide_scatter() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=True)
    segment = IndexSegment(
        schema=schema,
        postings={
            "body": {
                "alpha": [Posting(doc_id="doc-1", positions=array("I", [1]))],
                "beta": [Posting(doc_id="doc-1", positions=array("I", [10]))],
            }
        },
        stored_fields={"doc-1": {"url": "https://example.com"}},
        field_lengths={"body": {"doc-1": 2}},
    )
    doc_scores = {"doc-1": 1.0}

    engine._apply_phrase_bonus(doc_scores, segment, "alpha beta")  # pylint: disable=protected-access

    assert doc_scores["doc-1"] == 1.0


def test_resolve_postings_tracks_empty_vocabulary() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_fuzzy=True)
    fuzzy_cache: dict[tuple[str, str], tuple[str, int] | None] = {}
    vocabulary_cache: dict[str, list[str]] = {}

    postings, discount = engine._resolve_postings(  # pylint: disable=protected-access
        term="alpha",
        field_name="body",
        postings_by_term={},
        is_base_term=True,
        fuzzy_cache=fuzzy_cache,
        vocabulary_cache=vocabulary_cache,
    )

    assert postings is None
    assert discount == 1.0
    assert fuzzy_cache[("alpha", "body")] is None


def test_resolve_postings_handles_missing_fuzzy_match() -> None:
    schema = create_default_schema()
    engine = BM25SearchEngine(schema, enable_synonyms=False, enable_fuzzy=True)
    postings_by_term = {"tast": []}
    fuzzy_cache: dict[tuple[str, str], tuple[str, int] | None] = {}
    vocabulary_cache: dict[str, list[str]] = {}

    postings, discount = engine._resolve_postings(  # pylint: disable=protected-access
        term="test",
        field_name="body",
        postings_by_term=postings_by_term,
        is_base_term=True,
        fuzzy_cache=fuzzy_cache,
        vocabulary_cache=vocabulary_cache,
    )

    assert postings is None
    assert discount == 1.0
    assert fuzzy_cache[("test", "body")] is None


def test_score_applies_language_boost_for_english_docs() -> None:
    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/en",
            "title": "Webhooks",
            "headings": "Webhooks",
            "body": "Webhooks receive events.",
            "path": "en.md",
            "language": "en",
        }
    )
    writer.add_document(
        {
            "url": "https://example.com/fr",
            "title": "Webhooks",
            "headings": "Webhooks",
            "body": "Webhooks receive events.",
            "path": "fr.md",
            "language": "fr",
        }
    )
    segment = writer.build()
    engine = BM25SearchEngine(schema, enable_synonyms=False)

    tokens = engine.tokenize_query("webhooks")
    ranked = engine.score(segment, tokens, limit=5)

    assert ranked[0].doc_id.endswith("/en")
    assert ranked[0].score > ranked[1].score


def test_score_applies_phrase_bonus_for_adjacent_terms() -> None:
    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/adjacent",
            "title": "Alpha Beta",
            "headings": "Alpha Beta",
            "body": "alpha beta gamma",
            "path": "adjacent.md",
        }
    )
    writer.add_document(
        {
            "url": "https://example.com/scattered",
            "title": "Alpha Beta",
            "headings": "Alpha Beta",
            "body": "alpha gamma delta beta",
            "path": "scattered.md",
        }
    )
    segment = writer.build()
    tokens = BM25SearchEngine(schema, enable_synonyms=False).tokenize_query("alpha beta")

    with_bonus = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=True)
    without_bonus = BM25SearchEngine(schema, enable_synonyms=False, enable_phrase_bonus=False)

    ranked_bonus = with_bonus.score(segment, tokens, limit=10)
    ranked_plain = without_bonus.score(segment, tokens, limit=10)

    score_bonus = {entry.doc_id: entry.score for entry in ranked_bonus}
    score_plain = {entry.doc_id: entry.score for entry in ranked_plain}

    assert score_bonus["https://example.com/adjacent"] > score_plain["https://example.com/adjacent"]
    assert score_bonus["https://example.com/scattered"] >= score_plain["https://example.com/scattered"]
