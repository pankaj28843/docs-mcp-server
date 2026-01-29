"""Tenant runtime primitives - Direct search implementation.

Eliminates pass-through wrappers and connects directly to SegmentSearchIndex
for honest, simplified architecture.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager, suppress
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .deployment_config import TenantConfig
from .search.indexer import TenantIndexer
from .search.indexing_utils import build_indexing_context
from .search.segment_search_index import SegmentSearchIndex
from .search.sqlite_storage import SqliteSegmentStore
from .service_layer.filesystem_unit_of_work import FileSystemUnitOfWork
from .services.git_sync_scheduler_service import GitSyncSchedulerService
from .services.scheduler_service import SchedulerService, SchedulerServiceConfig
from .utils.crawl_state_store import CrawlStateStore
from .utils.git_sync import GitRepoSyncer, GitSourceConfig
from .utils.models import FetchDocResponse, SearchDocsResponse, SearchResult
from .utils.path_builder import PathBuilder
from .utils.url_translator import UrlTranslator


logger = logging.getLogger(__name__)

INTERNAL_DIRECTORY_NAMES = frozenset(
    {
        "__docs_metadata",
        "__search_segments",
        "__crawl_state",
        "__pycache__",
        "node_modules",
    }
)

_MANIFEST_POLL_INTERVAL_S = 2.0


class TenantSyncRuntime:
    """Runtime wrapper for tenant sync scheduling."""

    def __init__(
        self, tenant_config: TenantConfig, on_sync_complete: Callable[[], Coroutine[Any, Any, None]] | None = None
    ):
        self._tenant_config = tenant_config
        self._on_sync_complete = on_sync_complete
        self._scheduler_service = _build_scheduler_service(tenant_config, on_sync_complete)
        self._autostart = _should_autostart_scheduler(tenant_config)

    def get_scheduler_service(self):
        """Return scheduler service for sync endpoints."""
        return self._scheduler_service

    async def initialize(self) -> None:
        """Initialize scheduler if auto-start is enabled."""
        if self._autostart:
            await self._scheduler_service.initialize()

    async def shutdown(self) -> None:
        """Shutdown scheduler if supported."""
        stop_method = getattr(self._scheduler_service, "stop", None)
        if callable(stop_method):
            await stop_method()


class TenantApp:
    """Simplified tenant app with direct search index access."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename
        self.docs_name = tenant_config.docs_name
        self._search_lock = threading.Lock()
        self._active_searches = 0
        self._retired_indexes: list[SegmentSearchIndex] = []
        self._search_index = self._create_search_index()
        self._manifest_poll_interval = _MANIFEST_POLL_INTERVAL_S
        self._manifest_watch_task: asyncio.Task | None = None
        self._manifest_stop_event = asyncio.Event()
        self._url_translator = UrlTranslator(Path(tenant_config.docs_root_dir))
        self._docs_present: bool | None = None
        # Pass callback for git tenants to reload index after sync
        on_sync_complete = self._make_post_sync_callback() if tenant_config.source_type == "git" else None
        self.sync_runtime = TenantSyncRuntime(tenant_config, on_sync_complete)

    def _make_post_sync_callback(self) -> Callable[[], Coroutine[Any, Any, None]]:
        """Create a callback to rebuild index and reload search after git sync."""

        async def _on_sync_complete() -> None:
            logger.info(f"[{self.codename}] Post-sync: rebuilding search index")
            try:
                indexing_context = build_indexing_context(self.tenant_config)
                indexer = TenantIndexer(indexing_context)
                result = indexer.build_segment(persist=True)
                logger.info(f"[{self.codename}] Indexed {result.documents_indexed} documents")
                self.reload_search_index()
            except Exception as e:
                logger.error(f"[{self.codename}] Post-sync indexing failed: {e}")

        return _on_sync_complete

    def _segments_dir(self) -> Path:
        return Path(self.tenant_config.docs_root_dir) / "__search_segments"

    def _manifest_path(self) -> Path:
        return self._segments_dir() / "manifest.json"

    def _read_manifest_latest_segment_id(self, manifest_path: Path, *, log_missing: bool) -> str | None:
        if not manifest_path.exists():
            if log_missing:
                logger.warning("No manifest file for %s", self.codename)
            else:
                logger.debug("No manifest file for %s", self.codename)
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            if log_missing:
                logger.warning("Failed to read manifest for %s: %s", self.codename, exc)
            else:
                logger.debug("Failed to read manifest for %s: %s", self.codename, exc)
            return None

        latest_segment_id = manifest.get("latest_segment_id")
        if not isinstance(latest_segment_id, str) or not latest_segment_id.strip():
            if log_missing:
                logger.warning("No latest segment ID for %s", self.codename)
            else:
                logger.debug("No latest segment ID for %s", self.codename)
            return None
        return latest_segment_id

    def _segment_ready(self, segments_dir: Path, segment_id: str) -> bool:
        store = SqliteSegmentStore(segments_dir)
        segment = store.load(segment_id)
        if segment is None:
            return False
        segment.close()
        return True

    def _current_segment_id(self) -> str | None:
        with self._search_lock:
            if self._search_index is None:
                return None
            return self._search_index.db_path.stem

    def _close_index(self, index: SegmentSearchIndex) -> None:
        try:
            index.close()
        except Exception as exc:
            logger.warning("[%s] Failed to close search index: %s", self.codename, exc)

    def _swap_search_index(self, new_index: SegmentSearchIndex) -> None:
        old_index: SegmentSearchIndex | None = None
        close_now = False
        with self._search_lock:
            old_index = self._search_index
            self._search_index = new_index
            if old_index is not None:
                if self._active_searches > 0:
                    self._retired_indexes.append(old_index)
                else:
                    close_now = True
        if close_now and old_index is not None:
            self._close_index(old_index)

    def _close_search_indexes(self) -> None:
        current: SegmentSearchIndex | None = None
        retired: list[SegmentSearchIndex] = []
        with self._search_lock:
            current = self._search_index
            self._search_index = None
            retired = list(self._retired_indexes)
            self._retired_indexes = []
            self._active_searches = 0
        if current is not None:
            self._close_index(current)
        for old in retired:
            self._close_index(old)

    @contextmanager
    def _lease_search_index(self) -> Iterator[SegmentSearchIndex | None]:
        index: SegmentSearchIndex | None = None
        with self._search_lock:
            index = self._search_index
            if index is not None:
                self._active_searches += 1
        try:
            yield index
        finally:
            if index is not None:
                retired: list[SegmentSearchIndex] = []
                with self._search_lock:
                    self._active_searches -= 1
                    assert self._active_searches >= 0, "Active searches went negative - lease/release mismatch"
                    if self._active_searches == 0 and self._retired_indexes:
                        retired = self._retired_indexes
                        self._retired_indexes = []
                for old in retired:
                    self._close_index(old)

    def _create_search_index(
        self,
        *,
        segment_id: str | None = None,
        log_missing: bool = True,
    ) -> SegmentSearchIndex | None:
        """Create search index directly from segment database."""
        search_segments_dir = self._segments_dir()

        if not search_segments_dir.exists():
            if log_missing:
                logger.warning("No search segments directory for %s", self.codename)
            else:
                logger.debug("No search segments directory for %s", self.codename)
            return None

        manifest_path = self._manifest_path()
        if segment_id is None:
            segment_id = self._read_manifest_latest_segment_id(manifest_path, log_missing=log_missing)
        if not segment_id:
            return None

        search_db_path = search_segments_dir / f"{segment_id}.db"
        if not search_db_path.exists():
            if log_missing:
                logger.warning("Search database not found: %s", search_db_path)
            else:
                logger.debug("Search database not found: %s", search_db_path)
            return None

        if not self._segment_ready(search_segments_dir, segment_id):
            if log_missing:
                logger.warning("Search segment not ready for %s: %s", self.codename, segment_id)
            else:
                logger.debug("Search segment not ready for %s: %s", self.codename, segment_id)
            return None

        try:
            return SegmentSearchIndex(search_db_path, tenant=self.codename)
        except Exception as exc:
            logger.error("Failed to create search index for %s: %s", self.codename, exc)
            return None

    def _maybe_reload_from_manifest(self, *, log_missing: bool) -> bool:
        manifest_path = self._manifest_path()
        latest_segment_id = self._read_manifest_latest_segment_id(manifest_path, log_missing=log_missing)
        if not latest_segment_id:
            return False
        if latest_segment_id == self._current_segment_id():
            return False
        new_index = self._create_search_index(segment_id=latest_segment_id, log_missing=log_missing)
        if new_index is None:
            return False
        self._swap_search_index(new_index)
        logger.info("[%s] Search index updated to segment %s", self.codename, latest_segment_id)
        return True

    def _start_manifest_watch(self) -> None:
        if self._manifest_watch_task and not self._manifest_watch_task.done():
            return
        self._manifest_stop_event.clear()
        self._manifest_watch_task = asyncio.create_task(self._watch_manifest(), name=f"{self.codename}-manifest-watch")

    async def _stop_manifest_watch(self) -> None:
        if self._manifest_watch_task is None:
            return
        self._manifest_stop_event.set()
        self._manifest_watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._manifest_watch_task
        self._manifest_watch_task = None

    async def _watch_manifest(self) -> None:
        while not self._manifest_stop_event.is_set():
            self._maybe_reload_from_manifest(log_missing=False)
            try:
                await asyncio.wait_for(self._manifest_stop_event.wait(), timeout=self._manifest_poll_interval)
            except asyncio.TimeoutError:
                continue

    def reload_search_index(self) -> bool:
        """Reload search index after sync/indexing completes.

        Returns:
            True if index was successfully loaded, False otherwise.
        """
        latest_segment_id = self._read_manifest_latest_segment_id(self._manifest_path(), log_missing=True)
        if not latest_segment_id:
            return False

        if latest_segment_id == self._current_segment_id():
            logger.info("[%s] Search index already at latest segment %s", self.codename, latest_segment_id)
            return True

        new_index = self._create_search_index(segment_id=latest_segment_id, log_missing=True)
        if new_index is None:
            return False
        self._swap_search_index(new_index)
        logger.info("[%s] Search index reloaded successfully", self.codename)
        return True

    def _allow_index_builds(self) -> bool:
        if self.tenant_config.allow_index_builds is not None:
            return bool(self.tenant_config.allow_index_builds)
        infra = self.tenant_config._infrastructure
        return bool(infra.allow_index_builds) if infra is not None else False

    def _has_docs(self) -> bool:
        if self._docs_present is not None:
            return self._docs_present
        docs_root = Path(self.tenant_config.docs_root_dir)
        if not docs_root.exists():
            self._docs_present = False
            return False
        for candidate in docs_root.glob("*.md"):
            if candidate.is_file():
                self._docs_present = True
                return True
        for candidate in docs_root.rglob("*.md"):
            try:
                rel = candidate.relative_to(docs_root)
            except ValueError:
                continue
            if any(part in INTERNAL_DIRECTORY_NAMES for part in rel.parts):
                continue
            self._docs_present = True
            return True
        self._docs_present = False
        return False

    async def _ensure_search_index(self) -> bool:
        if self._current_segment_id() is not None:
            return True
        if not self._allow_index_builds():
            return False

        docs_root = Path(self.tenant_config.docs_root_dir)
        if not docs_root.exists():
            return False

        logger.info("[%s] Building search index on-demand", self.codename)

        def _build_index() -> int:
            indexing_context = build_indexing_context(self.tenant_config)
            indexer = TenantIndexer(indexing_context)
            result = indexer.build_segment(persist=True)
            return result.documents_indexed

        documents_indexed = await asyncio.to_thread(_build_index)
        if documents_indexed <= 0:
            logger.warning("[%s] No documents indexed during on-demand build", self.codename)
            return False
        self._docs_present = True
        return self.reload_search_index()

    async def initialize(self) -> None:
        """Initialize sync runtime if configured."""
        await self.sync_runtime.initialize()
        self._start_manifest_watch()

    async def shutdown(self) -> None:
        """Shutdown search index and sync runtime."""
        await self._stop_manifest_watch()
        self._close_search_indexes()
        await self.sync_runtime.shutdown()

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Search documents directly using segment search index."""
        if self._current_segment_id() is None:
            if not self._has_docs():
                return SearchDocsResponse(results=[], query=query)
            await self._ensure_search_index()
        with self._lease_search_index() as search_index:
            if search_index is None:
                return SearchDocsResponse(
                    results=[], error=f"No search index available for {self.codename}", query=query
                )

            search_latency_start_ms = time.perf_counter()

            try:
                # Direct call to segment search index
                search_response = search_index.search(query, size)

                # Convert to standardized response format
                document_search_results = [
                    SearchResult(
                        url=result.document_url,
                        title=result.document_title,
                        snippet=result.snippet,
                    )
                    for result in search_response.results
                ]

                search_latency_ms = (time.perf_counter() - search_latency_start_ms) * 1000
                logger.debug(f"Search completed in {search_latency_ms:.2f}ms for {self.codename}")

                return SearchDocsResponse(results=document_search_results)

            except Exception as e:
                logger.error(f"Search failed for {self.codename}: {e}")
                return SearchDocsResponse(results=[], error=f"Search failed: {e!s}", query=query)

    async def fetch(self, uri: str) -> FetchDocResponse:
        """Fetch document content from local cached/indexed data only.

        Search and fetch always work against indexed and crawled data,
        never making live HTTP requests.
        """
        try:
            # Handle file:// URLs for filesystem/git tenants
            if uri.startswith("file://"):
                return await self._fetch_local_file(uri)
            # For HTTP URLs, use cached crawled content
            cached = self._fetch_cached(uri)
            if cached is not None:
                return cached
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                error="Document not found in local cache. Run sync to crawl this URL.",
            )
        except Exception as e:
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                error=f"Fetch error: {e!s}",
            )

    def _fetch_cached(self, uri: str) -> FetchDocResponse | None:
        """Fetch from locally cached content (crawled markdown files).

        Supports two storage formats:
        1. Hash-based: {docs_root}/{sha256_hash}.md (UrlTranslator format)
        2. Path-based: {docs_root}/{netloc}/{url_path}.md (crawler format)
        """
        docs_root = Path(self.tenant_config.docs_root_dir)
        doc_fields = None
        candidate_paths: list[Path] = [self._url_translator.get_internal_path_from_public_url(uri)]

        with self._lease_search_index() as search_index:
            if search_index:
                doc_fields = search_index.get_document_by_url(uri)
                path_hint = doc_fields.get("path") if doc_fields else None
                if path_hint:
                    hinted_path = Path(path_hint)
                    if not hinted_path.is_absolute():
                        hinted_path = docs_root / hinted_path
                    candidate_paths.append(hinted_path)

        parsed = urlparse(uri)
        if parsed.netloc:
            url_path = parsed.path.strip("/")
            candidate_paths.append(docs_root / parsed.netloc / f"{url_path}.md")

        cached_path = next((path for path in candidate_paths if path.exists()), None)
        if cached_path is None:
            if doc_fields and doc_fields.get("body"):
                content = str(doc_fields.get("body") or "")
                title_hint = str(doc_fields.get("title") or "")
                if not title_hint and doc_fields.get("path"):
                    title_hint = Path(str(doc_fields["path"])).stem
                return FetchDocResponse(
                    url=uri,
                    title=title_hint,
                    content=content,
                )
            return None

        try:
            content = cached_path.read_text(encoding="utf-8")
            # Extract title from first markdown heading or filename
            title = cached_path.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            return FetchDocResponse(
                url=uri,
                title=title,
                content=content,
            )
        except Exception:
            return None

    async def _fetch_local_file(self, file_uri: str) -> FetchDocResponse:
        """Fetch content from local file.

        Handles path translation when the indexed path differs from the current
        docs_root (e.g., index created on host but fetched in Docker container).
        """
        # Convert file:// URI to path
        uri_path = file_uri.replace("file://", "")
        file_path = Path(uri_path)

        # If file doesn't exist at indexed path, try translating to current docs_root
        if not file_path.exists():
            docs_root = Path(self.tenant_config.docs_root_dir).resolve()
            codename = self.codename
            # Match codename as a path component and use the last occurrence
            uri_path_obj = Path(uri_path)
            parts = list(uri_path_obj.parts)
            if codename in parts:
                # Use the last occurrence of the codename component
                last_index = len(parts) - 1 - list(reversed(parts)).index(codename)
                if last_index + 1 < len(parts):
                    relative_part = Path(*parts[last_index + 1 :])
                    translated_path = (docs_root / relative_part).resolve()
                    # Ensure translated path stays within docs_root to prevent path traversal
                    if translated_path == docs_root or docs_root in translated_path.parents:
                        if translated_path.exists():
                            file_path = translated_path

        if not file_path.exists():
            return FetchDocResponse(
                url=file_uri,
                title="",
                content="",
                error="File not found",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            title = file_path.stem  # Use filename without extension as title

            return FetchDocResponse(
                url=file_uri,
                title=title,
                content=content,
            )
        except Exception as e:
            return FetchDocResponse(
                url=file_uri,
                title="",
                content="",
                error=f"Error reading file: {e!s}",
            )

    def get_performance_stats(self) -> dict:
        """Get performance statistics including optimization status."""
        stats = {
            "tenant": self.codename,
            "optimization_level": "advanced" if self._search_index else "basic",
            "has_search_index": self._search_index is not None,
        }

        with self._lease_search_index() as search_index:
            if search_index:
                # Get detailed performance info from search index
                perf_info = search_index.get_performance_info()
                stats.update(perf_info)

        return stats

    def get_index_status(self) -> dict:
        """Return index status summary for status endpoints."""
        latest_segment_id = self._read_manifest_latest_segment_id(self._manifest_path(), log_missing=False)
        current_segment_id = self._current_segment_id()
        stats = {
            "tenant": self.codename,
            "has_search_index": self._search_index is not None,
            "current_segment_id": current_segment_id,
            "latest_segment_id": latest_segment_id,
            "segment_ready": bool(latest_segment_id and self._segment_ready(self._segments_dir(), latest_segment_id)),
        }
        stats.update(self.get_performance_stats())
        return stats

    async def health(self) -> dict:
        """Return health status."""
        return {
            "status": "healthy",
            "tenant": self.codename,
            "source_type": self.tenant_config.source_type,
        }


def create_tenant_app(tenant_config: TenantConfig) -> TenantApp:
    """Create tenant app with direct search index access."""
    return TenantApp(tenant_config)


def _should_autostart_scheduler(tenant_config: TenantConfig) -> bool:
    """Determine if scheduler should auto-start based on tenant config."""
    if tenant_config.source_type == "git":
        return tenant_config.refresh_schedule is not None
    if tenant_config.source_type != "online":
        return False
    return tenant_config.refresh_schedule is not None


def _resolve_docs_root(tenant_config: TenantConfig) -> Path:
    docs_root = tenant_config.docs_root_dir or f"mcp-data/{tenant_config.codename}"
    root_path = Path(docs_root).expanduser()
    if not root_path.is_absolute():
        root_path = Path.cwd() / root_path
    return root_path


def _build_settings(tenant_config: TenantConfig) -> Settings:
    infra = tenant_config._infrastructure
    payload: dict[str, Any] = {
        "docs_name": tenant_config.docs_name,
        "docs_sitemap_url": tenant_config.get_docs_sitemap_urls(),
        "docs_entry_url": tenant_config.get_docs_entry_urls(),
        "url_whitelist_prefixes": tenant_config.url_whitelist_prefixes,
        "url_blacklist_prefixes": tenant_config.url_blacklist_prefixes,
        "markdown_url_suffix": tenant_config.markdown_url_suffix or "",
        "preserve_query_strings": tenant_config.preserve_query_strings,
        "max_crawl_pages": tenant_config.max_crawl_pages,
        "enable_crawler": tenant_config.enable_crawler,
        "docs_sync_enabled": tenant_config.source_type == "online"
        and (infra.operation_mode == "online" if infra else True),
    }

    if infra is not None:
        payload.update(
            {
                "http_timeout": infra.http_timeout,
                "max_concurrent_requests": infra.max_concurrent_requests,
                "operation_mode": infra.operation_mode,
                "crawler_playwright_first": infra.crawler_playwright_first,
                "log_level": infra.log_level,
            }
        )
        fallback = infra.article_extractor_fallback
        payload.update(
            {
                "fallback_extractor_enabled": fallback.enabled,
                "fallback_extractor_endpoint": fallback.endpoint or "",
                "fallback_extractor_timeout_seconds": fallback.timeout_seconds,
                "fallback_extractor_batch_size": fallback.batch_size,
                "fallback_extractor_max_retries": fallback.max_retries,
                "fallback_extractor_api_key_env": fallback.api_key_env or "",
            }
        )

    return Settings.model_validate(payload)


def _build_scheduler_service(
    tenant_config: TenantConfig, on_sync_complete: Callable[[], Coroutine[Any, Any, None]] | None = None
):
    base_dir = _resolve_docs_root(tenant_config)
    metadata_store = CrawlStateStore(base_dir)

    infra = tenant_config._infrastructure
    operation_mode = infra.operation_mode if infra else "online"

    if tenant_config.source_type == "git":
        if not tenant_config.git_repo_url or not tenant_config.git_subpaths:
            raise ValueError(f"Git tenant '{tenant_config.codename}' missing repo details")
        repo_path = base_dir / ".git_repo"
        git_config = GitSourceConfig(
            repo_url=tenant_config.git_repo_url,
            branch=tenant_config.git_branch,
            subpaths=tenant_config.git_subpaths,
            strip_prefix=tenant_config.git_strip_prefix,
            auth_token_env=tenant_config.git_auth_token_env,
        )
        git_syncer = GitRepoSyncer(
            config=git_config,
            repo_path=repo_path,
            export_path=base_dir,
        )

        return GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule=tenant_config.refresh_schedule,
            enabled=operation_mode == "online",
            on_sync_complete=on_sync_complete,
        )

    settings = _build_settings(tenant_config)
    path_builder = PathBuilder(ignore_query_strings=not tenant_config.preserve_query_strings)
    url_translator = UrlTranslator(base_dir)

    def uow_factory() -> FileSystemUnitOfWork:
        return FileSystemUnitOfWork(
            base_dir=base_dir,
            url_translator=url_translator,
            path_builder=path_builder,
        )

    progress_store = metadata_store
    scheduler_config = SchedulerServiceConfig(
        sitemap_urls=tenant_config.get_docs_sitemap_urls(),
        entry_urls=tenant_config.get_docs_entry_urls(),
        refresh_schedule=tenant_config.refresh_schedule,
        enabled=operation_mode == "online" and tenant_config.source_type == "online",
    )
    return SchedulerService(
        settings=settings,
        uow_factory=uow_factory,
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename=tenant_config.codename,
        config=scheduler_config,
    )
