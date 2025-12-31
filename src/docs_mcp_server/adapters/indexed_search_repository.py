"""Repository backed by JSON search segments and the BM25 engine."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.deployment_config import SearchBoostConfig, SearchRankingConfig, SearchSnippetConfig
from docs_mcp_server.domain.search import MatchTrace, SearchQuery, SearchResponse, SearchResult, SearchStats
from docs_mcp_server.search.analyzers import get_analyzer
from docs_mcp_server.search.bm25_engine import BM25SearchEngine
from docs_mcp_server.search.schema import Schema
from docs_mcp_server.search.snippet import build_smart_snippet
from docs_mcp_server.search.storage import IndexSegment, JsonSegmentStore


logger = logging.getLogger(__name__)

_SEGMENTS_SUBDIR = "__search_segments"
_PROXIMITY_BONUS = 0.05


@dataclass
class SegmentCacheMetrics:
    """Lightweight counters for cache instrumentation."""

    hits: int = 0
    misses: int = 0
    loads: int = 0
    last_load_seconds: float = 0.0
    last_loaded_at: float = 0.0
    last_hit_at: float = 0.0
    last_miss_at: float = 0.0

    def snapshot(self) -> dict[str, float | int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "loads": self.loads,
            "last_load_seconds": round(self.last_load_seconds, 4),
            "last_loaded_at": round(self.last_loaded_at, 6),
            "last_hit_at": round(self.last_hit_at, 6),
            "last_miss_at": round(self.last_miss_at, 6),
        }


@dataclass
class _ResidentSession:
    """Tracks manifest polling state for a resident tenant cache."""

    data_dir: Path
    poll_interval: float
    pointer: str | None = None
    next_check_at: float = field(default_factory=time.monotonic)


class IndexedSearchRepository(AbstractSearchRepository):
    """Execute searches against previously built JSONL segments."""

    def __init__(
        self,
        *,
        snippet: SearchSnippetConfig,
        ranking: SearchRankingConfig,
        boosts: SearchBoostConfig,
        analyzer_profile: str = "default",
        segments_subdir: str = _SEGMENTS_SUBDIR,
        manifest_poll_interval: float = 60.0,
        min_manifest_poll_interval: float = 0.01,
    ) -> None:
        self._snippet = snippet
        self._ranking = ranking
        self._boosts = boosts
        self._segments_subdir = segments_subdir
        self._query_analyzer_name = _resolve_profile_analyzer(analyzer_profile)
        self._segments: dict[str, IndexSegment] = {}
        self._segment_locks: dict[str, threading.Lock] = {}
        self._segment_metrics: dict[str, SegmentCacheMetrics] = {}
        self._resident_sessions: dict[str, _ResidentSession] = {}
        self._segments_lock = threading.Lock()
        self._min_poll_interval = max(0.001, min_manifest_poll_interval)
        self._default_poll_interval = max(self._min_poll_interval, manifest_poll_interval)
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()
        self._monitor_wakeup = threading.Event()

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
        segment = self._get_cached_segment(data_dir)
        if segment is None:
            logger.info("BM25 search skipped: no segment for %s", data_dir)
            return SearchResponse(results=[], stats=None)

        seed_text = self._compose_seed_text(query)
        engine = BM25SearchEngine(
            segment.schema,
            field_boosts=self._resolve_field_boosts(segment.schema),
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
                match_reason="BM25F ranking via JSON segments",
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

    async def warm_cache(self, data_dir: Path) -> None:
        """Load the latest segment on a worker thread so future searches stay warm."""

        await asyncio.to_thread(self._get_cached_segment, data_dir)

    async def reload_cache(self, data_dir: Path) -> bool:
        """Force a reload from disk when manifest pointers change."""

        return await asyncio.to_thread(self._reload_segment, data_dir)

    def invalidate_cache(self, data_dir: Path | None = None) -> None:
        """Drop cached segments so the next search reloads from disk."""

        if data_dir is None:
            with self._segments_lock:
                self._segments.clear()
                self._segment_metrics.clear()
                self._segment_locks.clear()
            return

        key = self._cache_key(self._segments_dir(data_dir))
        lock = self._get_or_create_lock(key)
        with lock:
            self._segments.pop(key, None)
        with self._segments_lock:
            self._segment_metrics.pop(key, None)
            self._segment_locks.pop(key, None)

    async def ensure_resident(self, data_dir: Path, *, poll_interval: float | None = None) -> None:
        """Warm the cache and start a manifest watcher."""

        reloaded = await self.reload_cache(data_dir)
        if not reloaded:
            await self.warm_cache(data_dir)
        segments_dir = self._segments_dir(data_dir)
        requested_interval = poll_interval if poll_interval is not None else self._default_poll_interval
        interval = max(self._min_poll_interval, requested_interval)
        key = self._cache_key(segments_dir)

        pointer = await asyncio.to_thread(self._read_manifest_pointer, segments_dir)
        now = time.monotonic()

        with self._segments_lock:
            session = self._resident_sessions.get(key)
            if session is not None:
                session.poll_interval = interval
                if pointer:
                    session.pointer = pointer
                session.next_check_at = now
            else:
                session = _ResidentSession(
                    data_dir=data_dir,
                    poll_interval=interval,
                    pointer=pointer,
                    next_check_at=now,
                )
                self._resident_sessions[key] = session
            self._start_monitor_thread_locked()
            self._monitor_wakeup.set()

        logger.info("Tracking manifest for %s (interval %.1fs)", key, interval)

    async def stop_resident(self, data_dir: Path | None = None) -> None:
        """Cancel manifest watchers and stop polling for the provided directory."""

        removed_keys: list[str] = []
        should_stop = False
        with self._segments_lock:
            if data_dir is None:
                if self._resident_sessions:
                    removed_keys = list(self._resident_sessions.keys())
                self._resident_sessions.clear()
            else:
                key = self._cache_key(self._segments_dir(data_dir))
                if key in self._resident_sessions:
                    self._resident_sessions.pop(key, None)
                    removed_keys.append(key)
            should_stop = not self._resident_sessions

        for key in removed_keys:
            logger.info("Stopped manifest tracking for %s", key)

        if should_stop:
            self._stop_monitor_thread()

    def _segments_dir(self, data_dir: Path) -> Path:
        return data_dir / self._segments_subdir

    def _get_cached_segment(self, data_dir: Path) -> IndexSegment | None:
        segments_dir = self._segments_dir(data_dir)
        if not segments_dir.exists():
            return None
        key = self._cache_key(segments_dir)
        lock = self._get_or_create_lock(key)
        metrics = self._get_or_create_metrics(key)
        with lock:
            cached = self._segments.get(key)
            if cached is not None:
                self._record_cache_hit(metrics)
                return cached
            self._record_cache_miss(metrics)

        load_started = time.perf_counter()
        segment = self._load_segment_from_store(segments_dir)
        load_duration = time.perf_counter() - load_started

        with lock:
            if segment is not None:
                self._segments[key] = segment
                self._record_cache_load(metrics, load_duration)
            else:
                self._segments.pop(key, None)

        if segment is not None:
            logger.info(
                "Loaded search segment %s (loads=%d hits=%d misses=%d, %.2fs)",
                key,
                metrics.loads,
                metrics.hits,
                metrics.misses,
                load_duration,
            )
        return segment

    def _reload_segment(self, data_dir: Path) -> bool:
        segments_dir = self._segments_dir(data_dir)
        if not segments_dir.exists():
            self.invalidate_cache(data_dir)
            return False
        key = self._cache_key(segments_dir)
        lock = self._get_or_create_lock(key)
        metrics = self._get_or_create_metrics(key)
        load_started = time.perf_counter()
        segment = self._load_segment_from_store(segments_dir)
        load_duration = time.perf_counter() - load_started

        with lock:
            if segment is None:
                self._segments.pop(key, None)
            else:
                self._segments[key] = segment
                self._record_cache_load(metrics, load_duration)

        if segment is None:
            logger.warning("Failed to reload search segment for %s (manifest missing)", key)
            return False

        logger.info(
            "Reloaded search segment %s (loads=%d hits=%d misses=%d, %.2fs)",
            key,
            metrics.loads,
            metrics.hits,
            metrics.misses,
            load_duration,
        )
        return True

    def _load_segment_from_store(self, segments_dir: Path) -> IndexSegment | None:
        store = JsonSegmentStore(segments_dir)
        return store.latest()

    def _cache_key(self, path: Path) -> str:
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _get_or_create_lock(self, key: str) -> threading.Lock:
        with self._segments_lock:
            lock = self._segment_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._segment_locks[key] = lock
            return lock

    def _get_or_create_metrics(self, key: str) -> SegmentCacheMetrics:
        with self._segments_lock:
            metrics = self._segment_metrics.get(key)
            if metrics is None:
                metrics = SegmentCacheMetrics()
                self._segment_metrics[key] = metrics
            return metrics

    def _record_cache_hit(self, metrics: SegmentCacheMetrics) -> None:
        metrics.hits += 1
        metrics.last_hit_at = time.perf_counter()

    def _record_cache_miss(self, metrics: SegmentCacheMetrics) -> None:
        metrics.misses += 1
        metrics.last_miss_at = time.perf_counter()

    def _record_cache_load(self, metrics: SegmentCacheMetrics, load_duration: float) -> None:
        metrics.loads += 1
        metrics.last_load_seconds = load_duration
        metrics.last_loaded_at = time.perf_counter()

    def get_cache_metrics(self, data_dir: Path | None = None) -> dict[str, dict[str, float | int]]:
        if data_dir is not None:
            key = self._cache_key(self._segments_dir(data_dir))
            with self._segments_lock:
                metrics = self._segment_metrics.get(key)
            return {key: metrics.snapshot()} if metrics else {}

        with self._segments_lock:
            snapshot = {key: metrics.snapshot() for key, metrics in self._segment_metrics.items()}
        return snapshot

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

    def _start_monitor_thread_locked(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()
        self._monitor_wakeup.clear()
        thread = threading.Thread(target=self._manifest_monitor_loop, name="manifest-monitor", daemon=True)
        self._monitor_thread = thread
        thread.start()

    def _stop_monitor_thread(self) -> None:
        thread: threading.Thread | None
        with self._segments_lock:
            thread = self._monitor_thread
            if thread is None:
                return
            self._monitor_thread = None
            self._monitor_stop.set()
            self._monitor_wakeup.set()
        if thread is not None:
            thread.join(timeout=5.0)
        self._monitor_stop = threading.Event()
        self._monitor_wakeup = threading.Event()
        logger.info("Manifest monitor thread stopped")

    def _manifest_monitor_loop(self) -> None:
        logger.info("Manifest monitor thread started")
        try:
            while not self._monitor_stop.is_set():
                now = time.monotonic()
                due: list[tuple[str, _ResidentSession]] = []
                next_due: float | None = None

                with self._segments_lock:
                    items = list(self._resident_sessions.items())

                for key, session in items:
                    if session.next_check_at <= now:
                        due.append((key, session))
                    elif next_due is None or session.next_check_at < next_due:
                        next_due = session.next_check_at

                if due:
                    for key, session in due:
                        self._check_manifest_session(key, session)
                    continue

                if self._monitor_stop.is_set():
                    break

                wait_timeout = 5.0 if next_due is None else max(0.05, min(5.0, next_due - now))

                if self._monitor_wakeup.wait(timeout=wait_timeout):
                    self._monitor_wakeup.clear()
                    continue
        finally:
            logger.info("Manifest monitor thread exiting")

    def _check_manifest_session(self, cache_key: str, session: _ResidentSession) -> None:
        if self._monitor_stop.is_set():
            return
        segments_dir = self._segments_dir(session.data_dir)
        try:
            pointer = self._read_manifest_pointer(segments_dir)
            with self._segments_lock:
                current = self._resident_sessions.get(cache_key)
            if current is not session:
                return
            if pointer and pointer != session.pointer:
                logger.info("Manifest pointer changed for %s", cache_key)
                reloaded = self._reload_segment(session.data_dir)
                if reloaded:
                    with self._segments_lock:
                        current = self._resident_sessions.get(cache_key)
                        if current is session:
                            session.pointer = pointer
                else:
                    logger.warning("Manifest reload failed for %s; keeping previous segment", cache_key)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Manifest monitor error for %s: %s", cache_key, exc)
        finally:
            with self._segments_lock:
                current = self._resident_sessions.get(cache_key)
                if current is session:
                    next_interval = max(self._min_poll_interval, session.poll_interval)
                    session.next_check_at = time.monotonic() + next_interval

    def _read_manifest_pointer(self, segments_dir: Path) -> str | None:
        manifest_path = segments_dir / JsonSegmentStore.MANIFEST_FILENAME
        if not manifest_path.exists():
            return None
        try:
            raw_manifest = manifest_path.read_bytes()
        except OSError:
            return None
        try:
            payload = json.loads(raw_manifest)
        except json.JSONDecodeError:
            return None
        latest_id = payload.get("latest_segment_id")
        if not latest_id:
            return None
        digest = hashlib.sha256(raw_manifest).hexdigest()
        return f"{latest_id}:{digest}"


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
