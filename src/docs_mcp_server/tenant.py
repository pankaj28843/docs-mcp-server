"""Tenant runtime primitives - Direct search implementation.

Eliminates pass-through wrappers and connects directly to SegmentSearchIndex
for honest, simplified architecture.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import json
import logging
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .deployment_config import TenantConfig
from .search.indexer import TenantIndexer
from .search.indexing_utils import build_indexing_context
from .search.segment_search_index import SegmentSearchIndex
from .service_layer.filesystem_unit_of_work import FileSystemUnitOfWork
from .services.git_sync_scheduler_service import GitSyncSchedulerService
from .services.scheduler_service import SchedulerService, SchedulerServiceConfig
from .utils.git_sync import GitRepoSyncer, GitSourceConfig
from .utils.models import BrowseTreeNode, BrowseTreeResponse, FetchDocResponse, SearchDocsResponse, SearchResult
from .utils.path_builder import PathBuilder
from .utils.sync_metadata_store import SyncMetadataStore
from .utils.sync_progress_store import SyncProgressStore
from .utils.url_translator import UrlTranslator


logger = logging.getLogger(__name__)

INTERNAL_DIRECTORY_NAMES = frozenset(
    {
        "__docs_metadata",
        "__scheduler_meta",
        "__search_segments",
        "__sync_progress",
        "__pycache__",
        "node_modules",
    }
)


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
        self._search_index = self._create_search_index()
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

    def _create_search_index(self) -> SegmentSearchIndex | None:
        """Create search index directly from segment database."""
        data_path = Path(self.tenant_config.docs_root_dir)
        search_segments_dir = data_path / "__search_segments"

        if not search_segments_dir.exists():
            logger.warning(f"No search segments directory for {self.codename}")
            return None

        manifest_path = search_segments_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning(f"No manifest file for {self.codename}")
            return None

        try:
            with manifest_path.open() as f:
                manifest = json.load(f)

            latest_segment_id = manifest.get("latest_segment_id")
            if not latest_segment_id:
                logger.warning(f"No latest segment ID for {self.codename}")
                return None

            search_db_path = search_segments_dir / f"{latest_segment_id}.db"
            if not search_db_path.exists():
                logger.warning(f"Search database not found: {search_db_path}")
                return None

            return SegmentSearchIndex(search_db_path, tenant=self.codename)
        except Exception as e:
            logger.error(f"Failed to create search index for {self.codename}: {e}")
            return None

    def reload_search_index(self) -> bool:
        """Reload search index after sync/indexing completes.

        Returns:
            True if index was successfully loaded, False otherwise.
        """
        old_index = self._search_index
        self._search_index = self._create_search_index()
        if old_index is not None:
            try:
                old_index.close()
            except Exception as e:
                logger.warning(f"[{self.codename}] Failed to close old search index: {e}")
        if self._search_index is not None:
            logger.info(f"[{self.codename}] Search index reloaded successfully")
            return True
        return False

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
        if self._search_index is not None:
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

    async def shutdown(self) -> None:
        """Shutdown search index and sync runtime."""
        if self._search_index:
            self._search_index.close()
        await self.sync_runtime.shutdown()

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Search documents directly using segment search index."""
        if not self._search_index:
            if not self._has_docs():
                return SearchDocsResponse(results=[], query=query)
            await self._ensure_search_index()
        if not self._search_index:
            return SearchDocsResponse(results=[], error=f"No search index available for {self.codename}", query=query)

        search_latency_start_ms = time.perf_counter()

        try:
            # Direct call to segment search index
            search_response = self._search_index.search(query, size)

            # Convert to standardized response format
            document_search_results = [
                SearchResult(
                    url=result.document_url,
                    title=result.document_title,
                    score=result.relevance_score,
                    snippet=result.snippet,
                )
                for result in search_response.results
            ]

            search_latency_ms = (time.perf_counter() - search_latency_start_ms) * 1000
            logger.debug(f"Search completed in {search_latency_ms:.2f}ms for {self.codename}")

            return SearchDocsResponse(
                results=document_search_results, query=query, total_results=len(document_search_results)
            )

        except Exception as e:
            logger.error(f"Search failed for {self.codename}: {e}")
            return SearchDocsResponse(results=[], error=f"Search failed: {e!s}", query=query)

    async def fetch(self, uri: str, context: str | None) -> FetchDocResponse:
        """Fetch document content from local cached/indexed data only.

        Search and fetch always work against indexed and crawled data,
        never making live HTTP requests.
        """
        try:
            # Handle file:// URLs for filesystem/git tenants
            if uri.startswith("file://"):
                return await self._fetch_local_file(uri, context)
            # For HTTP URLs, use cached crawled content
            cached = self._fetch_cached(uri, context)
            if cached is not None:
                return cached
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                context_mode=context,
                error="Document not found in local cache. Run sync to crawl this URL.",
            )
        except Exception as e:
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                context_mode=context,
                error=f"Fetch error: {e!s}",
            )

    def _fetch_cached(self, uri: str, context: str | None) -> FetchDocResponse | None:
        """Fetch from locally cached content (crawled markdown files).

        Supports two storage formats:
        1. Hash-based: {docs_root}/{sha256_hash}.md (UrlTranslator format)
        2. Path-based: {docs_root}/{netloc}/{url_path}.md (crawler format)
        """
        docs_root = Path(self.tenant_config.docs_root_dir)
        doc_fields = None
        candidate_paths: list[Path] = [self._url_translator.get_internal_path_from_public_url(uri)]

        if self._search_index:
            doc_fields = self._search_index.get_document_by_url(uri)
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
                if context == "surrounding" and len(content) > 8000:
                    content = content[:8000] + "..."
                return FetchDocResponse(
                    url=uri,
                    title=title_hint,
                    content=content,
                    context_mode=context,
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
            # Handle context modes
            if context == "surrounding" and len(content) > 8000:
                content = content[:8000] + "..."
            return FetchDocResponse(
                url=uri,
                title=title,
                content=content,
                context_mode=context,
            )
        except Exception:
            return None

    async def _fetch_local_file(self, file_uri: str, context: str | None) -> FetchDocResponse:
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
                context_mode=context,
                error="File not found",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            title = file_path.stem  # Use filename without extension as title

            # Handle context modes
            if context == "surrounding" and len(content) > 8000:
                content = content[:8000] + "..."

            return FetchDocResponse(
                url=file_uri,
                title=title,
                content=content,
                context_mode=context,
            )
        except Exception as e:
            return FetchDocResponse(
                url=file_uri,
                title="",
                content="",
                context_mode=context,
                error=f"Error reading file: {e!s}",
            )

    async def browse_tree(self, path: str, depth: int) -> BrowseTreeResponse:
        """Browse document tree for filesystem tenants."""
        if not self.tenant_config.supports_browse:
            return BrowseTreeResponse(
                root_path=path, depth=depth, nodes=[], error="Browse not supported for this tenant type"
            )

        try:
            # Get the base directory for this tenant
            base_dir = Path(self.tenant_config.docs_root_dir or f"mcp-data/{self.codename}")
            if not base_dir.is_absolute():
                base_dir = Path.cwd() / base_dir

            # Resolve the target directory
            target_dir = base_dir / path if path else base_dir

            if not target_dir.exists() or not target_dir.is_dir():
                return BrowseTreeResponse(root_path=path, depth=depth, nodes=[], error=f"Directory not found: {path}")

            # Build the tree
            nodes = await self._build_directory_tree(target_dir, base_dir, depth)

            return BrowseTreeResponse(root_path=path, depth=depth, nodes=nodes)

        except Exception as e:
            logger.error(f"Browse failed for {self.codename}: {e}")
            return BrowseTreeResponse(root_path=path, depth=depth, nodes=[], error=f"Browse failed: {e!s}")

    async def _build_directory_tree(self, target_dir: Path, base_dir: Path, max_depth: int) -> list[BrowseTreeNode]:
        """Build directory tree recursively."""
        nodes = []

        if max_depth <= 0:
            return nodes

        try:
            # Get all items in directory, sorted
            items = sorted(target_dir.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))

            for item in items:
                # Skip hidden files and common internal directories
                if item.name.startswith(".") or item.name in INTERNAL_DIRECTORY_NAMES:
                    continue

                # Calculate relative path from base
                try:
                    rel_path = item.relative_to(base_dir)
                except ValueError:
                    continue  # Skip items outside base directory

                if item.is_dir():
                    # Directory node
                    children = await self._build_directory_tree(item, base_dir, max_depth - 1) if max_depth > 1 else []
                    nodes.append(
                        BrowseTreeNode(
                            name=item.name,
                            path=str(rel_path),
                            type="directory",
                            url=f"file://{item}",
                            title=item.name,
                            has_children=len(children) > 0 if max_depth > 1 else None,
                            children=children if max_depth > 1 else None,
                        )
                    )
                elif item.suffix.lower() in [".md", ".txt", ".rst", ".html"]:
                    # File node (only include documentation files)
                    nodes.append(
                        BrowseTreeNode(
                            name=item.name,
                            path=str(rel_path),
                            type="file",
                            url=f"file://{item}",
                            title=item.stem,  # Remove extension for title
                            has_children=False,
                            children=None,
                        )
                    )

        except PermissionError:
            logger.warning(f"Permission denied accessing {target_dir}")
        except Exception as e:
            logger.error(f"Error building tree for {target_dir}: {e}")

        return nodes

    def get_performance_stats(self) -> dict:
        """Get performance statistics including optimization status."""
        stats = {
            "tenant": self.codename,
            "optimization_level": "advanced" if self._search_index else "basic",
            "has_search_index": self._search_index is not None,
        }

        if self._search_index:
            # Get detailed performance info from search index
            perf_info = self._search_index.get_performance_info()
            stats.update(perf_info)

        return stats

    def supports_browse(self) -> bool:
        """Determine if this tenant supports browsing the document tree."""
        return self.tenant_config.supports_browse

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
    metadata_store = SyncMetadataStore(base_dir)

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

    progress_store = SyncProgressStore(base_dir)
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
