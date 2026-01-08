"""Tenant runtime primitives shared by the server and worker processes.

The previous architecture mounted one FastMCP server per tenant. That approach
made the HTTP surface area hard to maintain (hundreds of endpoints) and forced
background work like schedulers and index warmups to live inside the request
serving process.

This module now provides a lightweight `TenantApp` that exposes only the core
behaviors (search, fetch, browse, health) without creating FastMCP servers on
its own. The HTTP server composes these objects into a single root MCP surface,
while the worker process reuses the exact same services to run sync/index jobs.

Key properties:
- Zero FastMCP instances per tenant (only one global server)
- No background tasks in the HTTP lifecycle; workers own schedulers
- Shared dependency injection container (`TenantServices`) retained for tests
- Helper utilities (browse tree builders, snippet extraction) remain available
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path
import re
from typing import Any

from .config import Settings
from .deployment_config import TenantConfig
from .service_layer import services as svc
from .service_layer.filesystem_unit_of_work import (
    FileSystemUnitOfWork,
    cleanup_orphaned_staging_dirs,
)
from .service_layer.search_service import SearchService
from .services.git_sync_scheduler_service import GitSyncSchedulerService
from .services.scheduler_protocol import SyncSchedulerProtocol
from .services.scheduler_service import SchedulerService, SchedulerServiceConfig
from .utils.git_sync import GitRepoSyncer, GitSourceConfig
from .utils.models import (
    BrowseTreeNode,
    BrowseTreeResponse,
    FetchDocResponse,
    SearchDocsResponse,
    SearchResult,
)
from .utils.path_builder import PathBuilder
from .utils.sync_metadata_store import SyncMetadataStore
from .utils.sync_progress_store import SyncProgressStore


logger = logging.getLogger(__name__)

IGNORED_DIRS: set[str] = {"__docs_metadata", "__scheduler_meta", "__sync_progress"}
IGNORED_DIR_PREFIXES: tuple[str, ...] = (".staging",)
HASHED_MARKDOWN_PATTERN = re.compile(r"^[0-9a-f]{64}\.md$")
MAX_BROWSE_DEPTH = 5
MANIFEST_POLL_INTERVAL_SECONDS = 60.0


def _should_skip_entry(entry: Path, storage_root: Path) -> bool:
    if entry.name in IGNORED_DIRS:
        return True
    if entry.name.startswith(IGNORED_DIR_PREFIXES):
        return True
    if entry.name.endswith(".meta.json"):
        return True
    if entry.is_file() and entry.parent == storage_root and HASHED_MARKDOWN_PATTERN.match(entry.name):
        return True
    return False


def _has_visible_children(directory: Path, storage_root: Path) -> bool:
    return any(not _should_skip_entry(child, storage_root) for child in directory.iterdir())


def _load_metadata_for_relative_path(metadata_root: Path, relative_path: Path) -> dict[str, Any] | None:
    if not metadata_root.exists():
        return None

    meta_path = metadata_root / relative_path.with_suffix(".meta.json")
    if not meta_path.exists():
        return None

    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - best effort metadata enrichment
        logger.debug("Failed to read metadata for %s: %s", meta_path, exc)
        return None


def _build_scheduler_settings(tenant_config: TenantConfig, infra_config: Any) -> Settings:
    fallback_config = infra_config.article_extractor_fallback
    return Settings(
        http_timeout=infra_config.http_timeout,
        max_concurrent_requests=infra_config.max_concurrent_requests,
        log_level=infra_config.log_level,
        operation_mode=infra_config.operation_mode,
        crawler_playwright_first=infra_config.crawler_playwright_first,
        docs_name=tenant_config.docs_name,
        docs_sitemap_url=tenant_config.get_docs_sitemap_urls(),
        docs_entry_url=tenant_config.get_docs_entry_urls(),
        markdown_url_suffix=tenant_config.markdown_url_suffix or "",
        preserve_query_strings=tenant_config.preserve_query_strings,
        url_whitelist_prefixes=tenant_config.url_whitelist_prefixes,
        url_blacklist_prefixes=tenant_config.url_blacklist_prefixes,
        docs_sync_enabled=tenant_config.docs_sync_enabled,
        max_crawl_pages=tenant_config.max_crawl_pages,
        enable_crawler=tenant_config.enable_crawler,
        fallback_extractor_enabled=fallback_config.enabled,
        fallback_extractor_endpoint=fallback_config.endpoint or "",
        fallback_extractor_timeout_seconds=fallback_config.timeout_seconds,
        fallback_extractor_batch_size=fallback_config.batch_size,
        fallback_extractor_max_retries=fallback_config.max_retries,
        fallback_extractor_api_key_env=fallback_config.api_key_env or "",
    )


def _build_browse_nodes(
    directory: Path,
    storage_root: Path,
    metadata_root: Path,
    depth: int,
) -> list[BrowseTreeNode]:
    if depth <= 0:
        return []

    nodes: list[BrowseTreeNode] = []
    entries = sorted(directory.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
    for entry in entries:
        if _should_skip_entry(entry, storage_root):
            continue

        try:
            relative = entry.relative_to(storage_root)
        except ValueError:
            continue

        metadata = _load_metadata_for_relative_path(metadata_root, relative)
        node = BrowseTreeNode(
            name=entry.name,
            path=str(relative.as_posix()),
            type="directory" if entry.is_dir() else "file",
            title=metadata.get("title") if metadata else None,
            url=metadata.get("url") if metadata else None,
            has_children=_has_visible_children(entry, storage_root) if entry.is_dir() else None,
            children=None,
        )

        if entry.is_dir() and depth > 1:
            node.children = _build_browse_nodes(entry, storage_root, metadata_root, depth - 1)

        nodes.append(node)

    return nodes


class StorageContext:
    """Manage tenant-specific storage directories and repositories."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config

        if tenant_config.docs_root_dir:
            root_candidate = Path(tenant_config.docs_root_dir).expanduser()
        else:
            root_candidate = Path("/tmp/mcp_data") / tenant_config.codename

        self.storage_path = root_candidate.resolve(strict=False)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        logger.info("[%s] Storage path: %s", tenant_config.codename, self.storage_path)

        self._path_builder = PathBuilder(ignore_query_strings=not tenant_config.preserve_query_strings)
        self._sync_metadata_store = SyncMetadataStore(self.storage_path)
        self._sync_progress_store = SyncProgressStore(self.storage_path)

        self._cleanup_orphaned_staging_dirs()

    def _cleanup_orphaned_staging_dirs(self) -> None:
        try:
            cleaned = cleanup_orphaned_staging_dirs(self.storage_path, max_age_hours=1.0)
            if cleaned > 0:
                logger.info("Cleaned up %s orphaned staging dirs for %s", cleaned, self.tenant_config.codename)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Failed to cleanup staging dirs: %s", exc)

    @property
    def metadata_store(self) -> SyncMetadataStore:
        return self._sync_metadata_store

    @property
    def progress_store(self) -> SyncProgressStore:
        return self._sync_progress_store

    def get_uow(self) -> FileSystemUnitOfWork:
        from docs_mcp_server.utils.url_translator import UrlTranslator

        url_translator = UrlTranslator(tenant_data_dir=self.storage_path)
        allow_missing_metadata = self.tenant_config.source_type == "filesystem"
        return FileSystemUnitOfWork(
            base_dir=self.storage_path,
            url_translator=url_translator,
            path_builder=self._path_builder,
            allow_missing_metadata_for_base=allow_missing_metadata,
        )


class IndexRuntime:
    """Own search index verification, residency, and cache management."""

    def __init__(
        self,
        tenant_config: TenantConfig,
        storage: StorageContext,
        *,
        allow_index_builds: bool,
        enable_residency: bool,
    ):
        self.tenant_config = tenant_config
        self._storage = storage
        self._allow_index_builds = allow_index_builds
        self._enable_residency = enable_residency
        self._shutting_down = False

        self._search_service: SearchService | None = None
        self._background_index_task: asyncio.Task | None = None
        self._background_index_completed = False
        self._index_verified = False
        self._index_resident = False

        if not self._allow_index_builds:
            logger.info(
                "[%s] Index building disabled for server runtime; external workers must rebuild segments",
                self.tenant_config.codename,
            )

    def _residency_enabled(self) -> bool:
        return self._enable_residency and not self._shutting_down

    def _index_build_disabled_error(self) -> RuntimeError:
        return RuntimeError(
            f"[{self.tenant_config.codename}] Search index building is disabled in this runtime; "
            "run docs_mcp_server.worker (or your external builder) to rebuild indices."
        )

    def _missing_index_error(self) -> RuntimeError:
        return RuntimeError(
            f"[{self.tenant_config.codename}] Search index missing; build indices please "
            "before serving MCP search traffic."
        )

    def get_search_service(self) -> SearchService:
        if self._search_service is None:
            from docs_mcp_server.adapters.indexed_search_repository import IndexedSearchRepository

            search_config = self.tenant_config.search
            repository = IndexedSearchRepository(
                snippet=search_config.snippet,
                ranking=search_config.ranking,
                boosts=search_config.boosts,
                analyzer_profile=search_config.analyzer_profile,
            )
            self._search_service = SearchService(
                search_repository=repository,
            )
        return self._search_service

    def invalidate_search_cache(self) -> None:
        if self._search_service is None:
            return
        self._search_service.invalidate_cache(self._storage.storage_path)

    def has_search_index(self) -> bool:
        from docs_mcp_server.search.storage import JsonSegmentStore

        segments_dir = self._storage.storage_path / "__search_segments"
        if not segments_dir.exists():
            return False
        store = JsonSegmentStore(segments_dir)
        return store.latest() is not None

    async def build_search_index(self, *, limit: int | None = None) -> tuple[int, int]:
        if not self._allow_index_builds:
            raise self._index_build_disabled_error()

        from docs_mcp_server.search.indexer import TenantIndexer, TenantIndexingContext

        logger.info("[%s] Building search index", self.tenant_config.codename)

        context = TenantIndexingContext(
            codename=self.tenant_config.codename,
            docs_root=self._storage.storage_path,
            segments_dir=self._storage.storage_path / "__search_segments",
            source_type=self.tenant_config.source_type,
            url_whitelist_prefixes=tuple(self.tenant_config.get_url_whitelist_prefixes()),
            url_blacklist_prefixes=tuple(self.tenant_config.get_url_blacklist_prefixes()),
        )

        indexer = TenantIndexer(context)
        result = await asyncio.to_thread(indexer.build_segment, limit=limit)

        if result.errors:
            for error in result.errors[:5]:
                logger.warning("[%s] Index error: %s", self.tenant_config.codename, error)

        self.invalidate_search_cache()
        self._background_index_completed = True

        return (result.documents_indexed, result.documents_skipped)

    async def ensure_search_index_lazy(self) -> None:
        if getattr(self, "_index_verified", False):
            if self._allow_index_builds:
                self._schedule_background_index_refresh()
            return

        if self.has_search_index():
            self._index_verified = True
            if self._allow_index_builds:
                self._schedule_background_index_refresh()
            return

        if not self._allow_index_builds:
            raise self._missing_index_error()

        logger.info("[%s] Building search index lazily", self.tenant_config.codename)
        try:
            await self.build_search_index()
            self._index_verified = True
        except Exception as exc:
            logger.error("[%s] Failed to build index lazily: %s", self.tenant_config.codename, exc)
            return

    def _schedule_background_index_refresh(self) -> None:
        if not self._allow_index_builds:
            return
        if not self._residency_enabled():
            return
        if self._background_index_completed:
            return
        if self._background_index_task and not self._background_index_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        logger.debug("[%s] Scheduling background index refresh", self.tenant_config.codename)
        self._background_index_task = loop.create_task(self._run_background_index_refresh())
        self._background_index_task.add_done_callback(self._handle_background_index_refresh_done)

    async def _run_background_index_refresh(self) -> tuple[int, int]:
        logger.info("[%s] Background index refresh started", self.tenant_config.codename)
        return await self.build_search_index()

    def _handle_background_index_refresh_done(self, task: asyncio.Task) -> None:
        self._background_index_task = None
        try:
            indexed, skipped = task.result()
            self._background_index_completed = True
            self._index_verified = True
            logger.info(
                "[%s] Background index refresh complete (%s indexed, %s skipped)",
                self.tenant_config.codename,
                indexed,
                skipped,
            )
        except asyncio.CancelledError:
            logger.debug("[%s] Background index refresh cancelled", self.tenant_config.codename)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("[%s] Background index refresh failed: %s", self.tenant_config.codename, exc)

    async def ensure_index_resident(self) -> None:
        if not self._residency_enabled():
            logger.debug("[%s] Residency disabled; skipping index warmup", self.tenant_config.codename)
            return
        if self._index_resident:
            return

        await self.ensure_search_index_lazy()
        search_service = self.get_search_service()
        try:
            await search_service.ensure_resident(
                self._storage.storage_path,
                poll_interval=MANIFEST_POLL_INTERVAL_SECONDS,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("[%s] Failed to ensure index residency: %s", self.tenant_config.codename, exc)
            return

        logger.info("[%s] Resident search index warmed", self.tenant_config.codename)
        self._index_resident = True

    def is_index_resident(self) -> bool:
        return self._index_resident

    def is_index_verified(self) -> bool:
        return self._index_verified

    async def on_sync_complete(self) -> None:
        if not self._allow_index_builds:
            logger.info(
                "[%s] Sync complete; index rebuild skipped (server runtime forbids in-process builds)",
                self.tenant_config.codename,
            )
            return

        logger.info("[%s] Sync complete, rebuilding index", self.tenant_config.codename)
        self._index_verified = False
        self._background_index_completed = False
        if self._background_index_task and not self._background_index_task.done():
            self._background_index_task.cancel()
            self._background_index_task = None
        try:
            indexed, skipped = await self.build_search_index()
            self._index_verified = True
            self._background_index_completed = True
            logger.info(
                "[%s] Index rebuilt (%s indexed, %s skipped)",
                self.tenant_config.codename,
                indexed,
                skipped,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("[%s] Failed to rebuild index: %s", self.tenant_config.codename, exc)

    async def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True

        await self._cancel_task(self._background_index_task)
        self._background_index_task = None

        self._index_resident = False

        if self._search_service is not None:
            await self._search_service.stop_resident(self._storage.storage_path)
        self.invalidate_search_cache()

    async def _cancel_task(self, task: asyncio.Task | None) -> None:
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


class SyncRuntime:
    """Coordinate crawler/git schedulers and sync metadata."""

    def __init__(
        self,
        tenant_config: TenantConfig,
        storage: StorageContext,
        index_runtime: IndexRuntime,
        *,
        infra_config: Any,
    ):
        if tenant_config._infrastructure is None:
            raise RuntimeError(
                f"Tenant '{tenant_config.codename}' missing infrastructure reference. "
                "Ensure DeploymentConfig.attach_infrastructure_to_tenants() ran."
            )

        self.tenant_config = tenant_config
        self._storage = storage
        self._index_runtime = index_runtime
        self._git_syncer: GitRepoSyncer | None = None
        self._scheduler_service: SchedulerService | None = None
        self._git_sync_scheduler_service: GitSyncSchedulerService | None = None
        self._scheduler_settings = _build_scheduler_settings(tenant_config, infra_config)

    def _ensure_git_syncer(self) -> GitRepoSyncer | None:
        if self.tenant_config.source_type != "git":
            return None

        if self._git_syncer is None:
            git_base = Path("/tmp/git-tenants") / self.tenant_config.codename
            repo_path = git_base / "repo"
            export_path = self._storage.storage_path

            git_config = GitSourceConfig(
                repo_url=self.tenant_config.git_repo_url or "",
                branch=self.tenant_config.git_branch or "main",
                subpaths=self.tenant_config.git_subpaths or [],
                strip_prefix=self.tenant_config.git_strip_prefix,
                auth_token_env=self.tenant_config.git_auth_token_env,
                shallow_clone=True,
            )

            self._git_syncer = GitRepoSyncer(
                config=git_config,
                repo_path=repo_path,
                export_path=export_path,
            )

        return self._git_syncer

    def _ensure_git_sync_scheduler(self) -> GitSyncSchedulerService | None:
        if self.tenant_config.source_type != "git":
            return None

        if self._git_sync_scheduler_service is None:
            git_syncer = self._ensure_git_syncer()
            if git_syncer is None:
                return None

            self._git_sync_scheduler_service = GitSyncSchedulerService(
                git_syncer=git_syncer,
                metadata_store=self._storage.metadata_store,
                refresh_schedule=self.tenant_config.refresh_schedule,
            )

        return self._git_sync_scheduler_service

    def get_scheduler_service(self) -> SyncSchedulerProtocol:
        if self.tenant_config.source_type == "git":
            git_scheduler = self._ensure_git_sync_scheduler()
            if git_scheduler is not None:
                return git_scheduler

        if self._scheduler_service is None:
            config = SchedulerServiceConfig(
                sitemap_urls=self.tenant_config.get_docs_sitemap_urls(),
                entry_urls=self.tenant_config.get_docs_entry_urls(),
                refresh_schedule=self.tenant_config.refresh_schedule,
                enabled=self.tenant_config.docs_sync_enabled,
            )

            self._scheduler_service = SchedulerService(
                settings=self._scheduler_settings,
                uow_factory=self._storage.get_uow,
                metadata_store=self._storage.metadata_store,
                progress_store=self._storage.progress_store,
                tenant_codename=self.tenant_config.codename,
                config=config,
                on_sync_complete=self._index_runtime.on_sync_complete,
            )
        return self._scheduler_service


class TenantServices:
    """Service container per tenant composed of focused runtimes."""

    def __init__(
        self,
        tenant_config: TenantConfig,
        *,
        enable_residency: bool = True,
    ):
        if tenant_config._infrastructure is None:
            raise RuntimeError(
                f"Tenant '{tenant_config.codename}' missing infrastructure reference. "
                "Ensure DeploymentConfig.attach_infrastructure_to_tenants() ran."
            )

        infra_config = tenant_config._infrastructure
        allow_index_builds = (
            tenant_config.allow_index_builds
            if tenant_config.allow_index_builds is not None
            else infra_config.allow_index_builds
        )

        self.tenant_config = tenant_config
        self.storage = StorageContext(tenant_config)
        self.index_runtime = IndexRuntime(
            tenant_config,
            self.storage,
            allow_index_builds=allow_index_builds,
            enable_residency=enable_residency,
        )
        self.sync_runtime = SyncRuntime(
            tenant_config,
            self.storage,
            self.index_runtime,
            infra_config=infra_config,
        )

    async def shutdown(self) -> None:
        await self.index_runtime.shutdown()


class TenantApp:
    """Thin facade over `TenantServices` for the new server/worker runtime."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename
        self.docs_name = tenant_config.docs_name

        self._services = TenantServices(tenant_config)
        self.storage = self._services.storage
        self.index_runtime = self._services.index_runtime
        self.sync_runtime = self._services.sync_runtime
        self._initialized = False
        self._residency_lock = asyncio.Lock()
        self._shutting_down = False
        self._lazy_residency_logged = False

    async def initialize(self) -> None:
        """Mark tenant as initialized without performing storage verification.

        Storage verification is deferred to first actual usage (search/fetch)
        to achieve fast startup times (<5 seconds for all tenants).
        """
        if self._initialized:
            return
        self._initialized = True
        logger.debug("[%s] Tenant initialized (lazy storage verification)", self.codename)

    async def ensure_resident(self) -> None:
        if self._shutting_down:
            logger.debug("[%s] Skipping residency while shutting down", self.codename)
            return
        if self.index_runtime.is_index_resident():
            return

        async with self._residency_lock:
            if self.index_runtime.is_index_resident():
                return
            if not self._lazy_residency_logged:
                logger.info("[%s] Lazy index residency warmup triggered", self.codename)
                self._lazy_residency_logged = True
            await self.index_runtime.ensure_index_resident()

    async def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._lazy_residency_logged = False
        await self._services.shutdown()

    async def health(self) -> dict[str, Any]:
        try:
            async with self.storage.get_uow() as uow:
                doc_count = await uow.documents.count()
            return {
                "status": "healthy",
                "tenant": self.codename,
                "name": self.docs_name,
                "documents": doc_count,
                "source_type": self.tenant_config.source_type,
            }
        except Exception as exc:
            logger.error("[%s] Health check failed: %s", self.codename, exc, exc_info=True)
            return {
                "status": "unhealthy",
                "tenant": self.codename,
                "name": self.docs_name,
                "error": str(exc),
            }

    def supports_browse(self) -> bool:
        return self.tenant_config.source_type == "filesystem"

    async def browse_tree(self, path: str = "/", depth: int = 2) -> BrowseTreeResponse:
        depth = max(1, min(depth, MAX_BROWSE_DEPTH))

        storage_root = self.storage.storage_path
        metadata_root = storage_root / "__docs_metadata"

        if path in {"", "/"}:
            target_dir = storage_root
            breadcrumb = "/"
        else:
            normalized = path.lstrip("/")
            target_dir = storage_root / normalized
            breadcrumb = normalized

        if not target_dir.exists() or not target_dir.is_dir():
            return BrowseTreeResponse(
                root_path=path or "/",
                depth=depth,
                nodes=[],
            )

        nodes = _build_browse_nodes(target_dir, storage_root, metadata_root, depth)

        return BrowseTreeResponse(root_path=breadcrumb or "/", depth=depth, nodes=nodes)

    @staticmethod
    def _extract_surrounding_context(content: str, fragment: str, chars: int = 500) -> str:
        if not fragment:
            return content

        patterns = [
            rf"#+\s*{re.escape(fragment)}",
            rf"\{{#\s*{re.escape(fragment)}\}}",
            rf'id=["\']{re.escape(fragment)}["\']',
            re.escape(fragment),
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                start = max(0, match.start() - chars)
                end = min(len(content), match.end() + chars)

                if start > 0:
                    newline_pos = content.rfind("\n", start - 50, start)
                    if newline_pos != -1:
                        start = newline_pos + 1

                if end < len(content):
                    newline_pos = content.find("\n", end, end + 50)
                    if newline_pos != -1:
                        end = newline_pos

                context = content[start:end]
                if start > 0:
                    context = "...\n" + context
                if end < len(content):
                    context = context + "\n..."

                return context

        return content

    def _resolve_fetch_context_mode(self, context: str | None) -> str:
        return context or self.tenant_config.fetch_default_mode

    def _apply_fetch_context(self, content: str, fragment: str, context: str | None) -> str:
        if context == "surrounding" and fragment:
            return TenantApp._extract_surrounding_context(
                content,
                fragment,
                chars=self.tenant_config.fetch_surrounding_chars,
            )
        return content

    def _fetch_file_uri(
        self,
        uri_without_fragment: str,
        fragment: str,
        context: str | None,
    ) -> FetchDocResponse:
        from urllib.parse import unquote, urlparse

        parsed = urlparse(uri_without_fragment)
        file_path = Path(unquote(parsed.path))
        resolved_path = self._resolve_fetch_file_path(file_path)

        if resolved_path is None:
            return FetchDocResponse(
                url=uri_without_fragment,
                title="",
                content="",
                error=f"File not found: {file_path}",
            )

        content = resolved_path.read_text(encoding="utf-8")
        content = self._apply_fetch_context(content, fragment, context)
        return FetchDocResponse(
            url=uri_without_fragment,
            title=resolved_path.name,
            content=content,
            context_mode=self._resolve_fetch_context_mode(context),
        )

    async def _fetch_repo_doc(
        self,
        uri_without_fragment: str,
        fragment: str,
        context: str | None,
    ) -> FetchDocResponse:
        async with self.storage.get_uow() as uow:
            doc = await svc.fetch_document(uri_without_fragment, uow)

        if doc is None:
            return FetchDocResponse(
                url=uri_without_fragment,
                title="",
                content="",
                error="Document not found in repository",
            )

        content = doc.content.markdown  # type: ignore[attr-defined]
        content = self._apply_fetch_context(content, fragment, context)
        return FetchDocResponse(
            url=doc.url.value,  # type: ignore[attr-defined]
            title=doc.title,
            content=content,
            context_mode=self._resolve_fetch_context_mode(context),
        )

    async def fetch(self, uri: str, context: str | None) -> FetchDocResponse:
        from urllib.parse import urldefrag

        uri_without_fragment, fragment = urldefrag(uri)

        try:
            if uri_without_fragment.startswith("file://"):
                return self._fetch_file_uri(uri_without_fragment, fragment, context)

            return await self._fetch_repo_doc(uri_without_fragment, fragment, context)

        except Exception as exc:
            logger.error("[%s] Fetch error: %s", self.codename, exc, exc_info=True)
            return FetchDocResponse(
                url=uri_without_fragment,
                title="",
                content="",
                error=f"Failed to fetch document: {exc!s}",
            )

    def _resolve_fetch_file_path(self, requested_path: Path) -> Path | None:
        """Return a filesystem path that exists for the requested file URI."""

        if requested_path.exists() and requested_path.is_file():
            return requested_path

        storage_root = self.storage.storage_path

        parts = requested_path.parts
        if self.codename in parts:
            suffix_parts = parts[parts.index(self.codename) + 1 :]
            candidate = storage_root.joinpath(*suffix_parts) if suffix_parts else storage_root
            if candidate.exists() and candidate.is_file():
                logger.debug("[%s] Rebased fetch path from %s to %s", self.codename, requested_path, candidate)
                return candidate

        fallback = storage_root / requested_path.name
        if fallback.exists() and fallback.is_file():
            logger.debug("[%s] Fallback fetch path from %s to %s", self.codename, requested_path, fallback)
            return fallback

        return None

    async def search(
        self,
        query: str,
        size: int,
        word_match: bool,
        include_stats: bool,
    ) -> SearchDocsResponse:
        try:
            await self.ensure_resident()
            search_service = self.index_runtime.get_search_service()

            documents, stats = await svc.search_documents_filesystem(
                query=query,
                search_service=search_service,
                data_dir=self.storage.storage_path,
                limit=size,
                word_match=word_match,
                include_stats=include_stats,
                tenant_codename=self.codename,
            )

            results = [
                SearchResult(
                    url=str(doc.url.value),
                    title=doc.title,
                    score=doc.score or 0.0,
                    snippet=doc.snippet or "",
                    match_stage=doc.match_stage,
                    match_stage_name=doc.match_stage_name,
                    match_query_variant=doc.match_query_variant,
                    match_reason=doc.match_reason,
                    match_ripgrep_flags=doc.match_ripgrep_flags,
                )
                for doc in documents
            ]

            return SearchDocsResponse(results=results, stats=stats)

        except Exception as exc:
            logger.error("[%s] Search error: %s", self.codename, exc, exc_info=True)
            return SearchDocsResponse(results=[], error=f"Search failed: {exc!s}", query=query)


def create_tenant_app(
    tenant_config: TenantConfig,
) -> TenantApp:
    return TenantApp(tenant_config)
