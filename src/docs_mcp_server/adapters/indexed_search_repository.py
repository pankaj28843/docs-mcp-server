"""Repository backed by SQLite search segments and the BM25 engine."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
import logging
from pathlib import Path
import time
from typing import Any

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.deployment_config import SearchBoostConfig, SearchRankingConfig, SearchSnippetConfig
from docs_mcp_server.domain.search import MatchTrace, SearchQuery, SearchResponse, SearchResult, SearchStats
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.snippet import build_smart_snippet
from docs_mcp_server.search.sqlite_storage import SqliteSegment, SqliteSegmentStore


logger = logging.getLogger(__name__)

_SEGMENTS_SUBDIR = "__search_segments"
_PROXIMITY_BONUS = 0.05


class IndexedSearchRepository(AbstractSearchRepository):
    """Execute searches against SQLite segments without in-process caching."""

    def __init__(
        self,
        *,
        snippet: SearchSnippetConfig,
        ranking: SearchRankingConfig,
        boosts: SearchBoostConfig,
        analyzer_profile: str = "default",
        segments_subdir: str = _SEGMENTS_SUBDIR,
    ) -> None:
        self._snippet = snippet
        self._ranking = ranking
        self._boosts = boosts
        self._segments_subdir = segments_subdir
        self._query_analyzer_name = _resolve_profile_analyzer(analyzer_profile)

    async def search_documents(
        self,
        query: SearchQuery,
        data_dir: Path,
        max_results: int = 20,
        word_match: bool = False,
        include_stats: bool = False,
    ) -> SearchResponse:
        return await asyncio.to_thread(
            self._search_sync,
            query,
            data_dir,
            max_results,
            include_stats,
        )

    def _search_sync(
        self,
        query: SearchQuery,
        data_dir: Path,
        max_results: int,
        include_stats: bool,
    ) -> SearchResponse:
        start = time.perf_counter()
        segments_dir = self._segments_dir(data_dir)
        segment = self._load_segment_from_store(segments_dir)
        if segment is None:
            logger.info("BM25 search skipped: no segment for %s", data_dir)
            return SearchResponse(results=[], stats=None)

        try:
            seed_text = self._compose_seed_text(query)
            field_boosts = self._resolve_field_boosts(segment.schema)
            engine = BM25SearchEngine(
                segment.schema,
                field_boosts=field_boosts,
                k1=self._ranking.bm25_k1,
                b=self._ranking.bm25_b,
            )
            token_context = engine.tokenize_query(seed_text)
            ranked = engine.score(segment, token_context, limit=max(1, max_results))
            highlight_terms = list(token_context.ordered_terms)

            results: list[SearchResult] = []
            for ranked_doc in ranked:
                doc_fields = segment.get_document(ranked_doc.doc_id)
                if not doc_fields:
                    continue
                snippet = _build_snippet(doc_fields, highlight_terms, self._snippet)
                score = ranked_doc.score
                ranking_factors: dict[str, float] = {"bm25": round(score, 6)}
                if self._ranking.enable_proximity_bonus:
                    bonus = self._proximity_bonus(query, doc_fields)
                    if bonus > 0:
                        score += bonus
                        ranking_factors["proximity_bonus"] = round(bonus, 6)
                match_trace = MatchTrace(
                    stage=5,
                    stage_name="bm25_index",
                    query_variant=" ".join(highlight_terms)[:100],
                    match_reason="BM25F ranking via SQLite segments",
                    ripgrep_flags=[],
                    ranking_factors=ranking_factors,
                )
                results.append(
                    SearchResult(
                        document_url=str(doc_fields.get("url") or ranked_doc.doc_id),
                        document_title=str(doc_fields.get("title") or doc_fields.get("path") or ranked_doc.doc_id),
                        snippet=snippet,
                        match_trace=match_trace,
                        relevance_score=score,
                    )
                )

            stats = None
            if include_stats:
                stats = SearchStats(
                    stage=5,
                    files_found=len(results),
                    matches_found=len(results),
                    files_searched=segment.doc_count,
                    search_time=time.perf_counter() - start,
                )
            return SearchResponse(results=results, stats=stats)
        finally:
            segment.close()

    async def warm_cache(self, data_dir: Path) -> None:
        """No-op: caching is disabled."""

    async def reload_cache(self, data_dir: Path) -> bool:
        """No-op: caching is disabled."""
        return False

    def invalidate_cache(self, data_dir: Path | None = None) -> None:
        """No-op: caching is disabled."""

    async def ensure_resident(self, data_dir: Path, *, poll_interval: float | None = None) -> None:
        """No-op: residency is disabled."""

    async def stop_resident(self, data_dir: Path | None = None) -> None:
        """No-op: residency is disabled."""

    def get_cache_metrics(self, data_dir: Path | None = None) -> dict[str, dict[str, float | int]]:
        return {}

    def _segments_dir(self, data_dir: Path) -> Path:
        return data_dir / self._segments_subdir

    def _load_segment_from_store(self, segments_dir: Path) -> SqliteSegment | None:
        store = SqliteSegmentStore(segments_dir)
        return store.latest()

    def _resolve_field_boosts(self, schema: Schema) -> dict[str, float]:
        base: dict[str, float] = {field.name: schema.get_boost(field.name) for field in schema.fields}
        overrides = {
            "title": self._boosts.title,
            "headings_h1": self._boosts.headings_h1,
            "headings_h2": self._boosts.headings_h2,
            "headings": self._boosts.headings,
            "body": self._boosts.body,
            "path": self._boosts.path,
            "url": self._boosts.url,
        }
        for field_name, weight in overrides.items():
            if field_name in base:
                base[field_name] = weight
        return base

    def _compose_seed_text(self, query: SearchQuery) -> str:
        parts: list[str] = []
        if query.original_text:
            parts.append(query.original_text)
            analyzer = get_analyzer(self._query_analyzer_name)
            parts.extend(token.text for token in analyzer(query.original_text) if token.text)
        parts.extend(query.normalized_tokens)
        keywords = query.extracted_keywords
        parts.extend(keywords.acronyms)
        parts.extend(keywords.technical_terms)
        parts.extend(keywords.technical_nouns)
        parts.extend(keywords.verb_forms)
        return " ".join(part for part in parts if part).strip()

    def _proximity_bonus(self, query: SearchQuery, doc_fields: Mapping[str, Any]) -> float:
        original = (query.original_text or "").strip().lower()
        if not original:
            return 0.0
        body = str(doc_fields.get("body") or "").lower()
        if not body:
            return 0.0
        if original in body:
            return _PROXIMITY_BONUS
        return 0.0


def _build_snippet(doc_fields: Mapping[str, Any], terms: Sequence[str], config: SearchSnippetConfig) -> str:
    """Return a sentence-boundary-aware highlighted snippet using smart extraction."""

    candidates = [
        str(doc_fields.get("body") or ""),
        str(doc_fields.get("excerpt") or ""),
        str(doc_fields.get("title") or ""),
    ]
    text = next((candidate for candidate in candidates if candidate), "")
    if not text:
        return ""

    return build_smart_snippet(
        text=text,
        terms=list(terms),
        max_chars=config.fragment_char_limit,
        style=config.style,
    )


def _resolve_profile_analyzer(profile: str) -> str | None:
    lookup = {
        "default": None,
        "aggressive-stem": "aggressive-stem",
        "code-friendly": "code-friendly",
    }
    return lookup.get(profile)
