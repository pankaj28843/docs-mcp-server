"""Lightweight BM25/BM25F search helpers for indexed tenants."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import heapq
from types import MappingProxyType

from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.fuzzy import find_fuzzy_matches
from docs_mcp_server.search.models import Posting
from docs_mcp_server.search.phrase import get_min_span
from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.sqlite_storage import SqliteSegment
from docs_mcp_server.search.stats import FieldLengthStats, bm25, calculate_idf
from docs_mcp_server.search.synonyms import expand_query_terms


# Fuzzy match scores are discounted to prefer exact matches
_FUZZY_DISCOUNT = 0.8


@dataclass(frozen=True)
class RankedDocument:
    """Represents a scored document produced by the BM25 engine."""

    doc_id: str
    score: float


@dataclass(frozen=True)
class QueryTokens:
    """Immutable snapshot of query terms aligned with index fields."""

    per_field: Mapping[str, tuple[str, ...]]
    ordered_terms: tuple[str, ...]
    base_term_count: int
    seed_text: str

    @classmethod
    def empty(cls) -> QueryTokens:
        return cls(MappingProxyType({}), (), 0, "")

    def is_empty(self) -> bool:
        return not self.per_field


class BM25SearchEngine:
    """Compute BM25/BM25F scores for documents stored in an index segment."""

    def __init__(
        self,
        schema: Schema,
        *,
        field_boosts: Mapping[str, float] | None = None,
        k1: float = 1.2,
        b: float = 0.75,
        enable_synonyms: bool = True,
        enable_phrase_bonus: bool = False,
        enable_fuzzy: bool = False,
    ) -> None:
        self.schema = schema
        self.field_boosts = dict(field_boosts or {})
        self.k1 = k1
        self.b = b
        self.enable_synonyms = enable_synonyms
        self.enable_phrase_bonus = enable_phrase_bonus
        self.enable_fuzzy = enable_fuzzy

    def tokenize_query(self, seed_text: str) -> QueryTokens:
        """Return aligned query tokens plus metadata for scoring helpers."""

        normalized_seed = seed_text.strip()
        if not normalized_seed:
            return QueryTokens.empty()

        per_field: dict[str, tuple[str, ...]] = {}
        ordered_terms: list[str] = []
        ordered_seen: set[str] = set()
        base_term_count = 0

        for field in self.schema.text_fields:
            analyzer = get_analyzer(field.analyzer_name)
            seen_in_field: set[str] = set()
            base_terms: list[str] = []
            for token in analyzer(normalized_seed):
                if not token.text or token.text in seen_in_field:
                    continue
                seen_in_field.add(token.text)
                base_terms.append(token.text)

            if field.name == "body" and not base_term_count:
                base_term_count = len(base_terms)

            terms = list(base_terms)
            if self.enable_synonyms and base_terms:
                expanded = expand_query_terms(base_terms)
                for syn in sorted(expanded):
                    if syn in seen_in_field:
                        continue
                    seen_in_field.add(syn)
                    terms.append(syn)

            if not terms:
                continue

            per_field[field.name] = tuple(terms)
            for term in terms:
                if term in ordered_seen:
                    continue
                ordered_seen.add(term)
                ordered_terms.append(term)

        if not per_field:
            return QueryTokens.empty()

        return QueryTokens(
            MappingProxyType(per_field),
            tuple(ordered_terms),
            base_term_count,
            normalized_seed,
        )

    def _resolve_postings(
        self,
        *,
        term: str,
        field_name: str,
        postings: list[Posting] | None,
        is_base_term: bool,
        segment: SqliteSegment,
    ) -> tuple[list[Posting] | None, float]:
        if postings or not (self.enable_fuzzy and is_base_term):
            return postings, 1.0

        vocabulary = segment.get_terms(field_name)
        if not vocabulary:
            return None, 1.0

        fuzzy_matches = find_fuzzy_matches(term, vocabulary)
        if not fuzzy_matches:
            return None, 1.0

        fuzzy_term, _distance = fuzzy_matches[0]
        matched = segment.get_postings(field_name, fuzzy_term, include_positions=self.enable_phrase_bonus)
        return (matched, _FUZZY_DISCOUNT) if matched else (None, 1.0)

    def _apply_phrase_bonus(self, doc_scores: dict[str, float], segment: SqliteSegment, query_text: str) -> None:
        """Apply phrase proximity bonus for multi-word queries.

        Documents where query terms appear adjacent get up to 50% boost.
        Uses precomputed positions from the inverted index instead of
        re-analyzing document text for O(1) lookup per term.
        """
        body_field = next((f for f in self.schema.text_fields if f.name == "body"), None)
        if not body_field:
            return

        analyzer = get_analyzer(body_field.analyzer_name)
        query_tokens = [t.text for t in analyzer(query_text) if t.text]
        if len(query_tokens) < 2:
            return

        term_postings: dict[str, list[Posting]] = {}
        for token in query_tokens:
            postings = segment.get_postings("body", token, include_positions=True)
            if postings:
                term_postings[token] = postings

        if len(term_postings) < len(query_tokens):
            return

        positions_by_doc: dict[str, dict[str, list[int]]] = {}
        for token, postings in term_postings.items():
            for posting in postings:
                if not posting.positions:
                    continue
                positions_by_doc.setdefault(posting.doc_id, {})[token] = list(posting.positions)

        for doc_id in doc_scores:
            term_positions = positions_by_doc.get(doc_id)
            if not term_positions or len(term_positions) < len(query_tokens):
                continue

            span = get_min_span(term_positions)
            if span == float("inf"):
                continue

            term_count = len(query_tokens)
            max_bonus = 1.5

            # Perfect phrase: span equals term count (terms are adjacent)
            if span <= term_count:
                doc_scores[doc_id] *= max_bonus
                continue

            # Decaying bonus based on scatter
            scatter_ratio = span / term_count
            if scatter_ratio >= 3.0:
                continue

            bonus = max_bonus - (scatter_ratio - 1.0) * (max_bonus - 1.0) / 2.0
            doc_scores[doc_id] *= max(1.0, bonus)

    def score(
        self,
        segment: SqliteSegment,
        query_tokens: QueryTokens,
        *,
        limit: int,
        field_length_stats: Mapping[str, FieldLengthStats] | None = None,
    ) -> list[RankedDocument]:
        """Return ranked results for a tokenized query."""

        if query_tokens.is_empty():
            return []

        if field_length_stats is None:
            field_length_stats = segment.get_field_length_stats(list(query_tokens.per_field.keys()))
        doc_scores: dict[str, float] = defaultdict(float)
        total_docs = max(segment.doc_count, 1)

        for field_name, tokens in query_tokens.per_field.items():
            if not tokens:
                continue
            stats = field_length_stats.get(field_name)
            if stats is None:
                continue

            avg_length = max(stats.average_length, 1e-9)
            field_boost = self.field_boosts.get(field_name, 1.0)

            for term_idx, term in enumerate(tokens):
                postings = segment.get_postings(field_name, term, include_positions=self.enable_phrase_bonus)
                postings, discount = self._resolve_postings(
                    term=term,
                    field_name=field_name,
                    postings=postings,
                    is_base_term=term_idx < query_tokens.base_term_count,
                    segment=segment,
                )
                if not postings:
                    continue

                idf = calculate_idf(len(postings), total_docs)
                for posting in postings:
                    doc_length = posting.doc_length or posting.frequency
                    weight = bm25(posting.frequency, doc_length, avg_length, k1=self.k1, b=self.b)
                    if weight <= 0:
                        continue
                    doc_scores[posting.doc_id] += idf * weight * field_boost * discount

        if self.enable_phrase_bonus and query_tokens.seed_text:
            self._apply_phrase_bonus(doc_scores, segment, query_tokens.seed_text)

        if limit <= 0:
            return []
        if limit < len(doc_scores):
            top_items = heapq.nlargest(limit, doc_scores.items(), key=lambda item: item[1])
            return [RankedDocument(doc_id=doc_id, score=score) for doc_id, score in top_items]

        ranked = sorted(
            (RankedDocument(doc_id=doc_id, score=score) for doc_id, score in doc_scores.items()),
            key=lambda entry: entry.score,
            reverse=True,
        )
        return ranked
