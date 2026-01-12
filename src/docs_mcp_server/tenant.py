"""Tenant runtime primitives - Direct search implementation.

Eliminates pass-through wrappers and connects directly to SegmentSearchIndex
for honest, simplified architecture.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any

import aiohttp
from justhtml import JustHTML

from .deployment_config import TenantConfig
from .search.segment_search_index import SegmentSearchIndex
from .utils.models import BrowseTreeNode, BrowseTreeResponse, FetchDocResponse, SearchDocsResponse, SearchResult


logger = logging.getLogger(__name__)


class MockSchedulerService:
    """Mock scheduler service for simplified tenant implementation."""

    def __init__(self, tenant_codename: str):
        self.tenant_codename = tenant_codename

    async def get_status_snapshot(self) -> dict[str, Any]:
        """Return minimal status snapshot."""
        return {
            "scheduler_running": False,
            "scheduler_initialized": False,
            "stats": {
                "mode": "offline",
                "refresh_schedule": None,
                "scheduler_running": False,
                "scheduler_initialized": False,
                "storage_doc_count": 0,
                "queue_depth": 0,
                "metadata_total_urls": 0,
                "metadata_due_urls": 0,
                "metadata_successful": 0,
                "metadata_pending": 0,
                "metadata_first_seen_at": None,
                "metadata_last_success_at": None,
                "metadata_sample": [],
                "failed_url_count": 0,
                "failure_sample": [],
                "fallback_attempts": 0,
                "fallback_successes": 0,
                "fallback_failures": 0,
            },
        }


class MockSyncRuntime:
    """Mock sync runtime for simplified tenant implementation."""

    def __init__(self, tenant_codename: str):
        self._scheduler_service = MockSchedulerService(tenant_codename)

    def get_scheduler_service(self) -> MockSchedulerService:
        """Return mock scheduler service."""
        return self._scheduler_service


class TenantApp:
    """Simplified tenant app with direct search index access."""

    def __init__(self, tenant_config: TenantConfig):
        self.tenant_config = tenant_config
        self.codename = tenant_config.codename
        self.docs_name = tenant_config.docs_name
        self._search_index = self._create_search_index()
        self.sync_runtime = MockSyncRuntime(tenant_config.codename)

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

            return SegmentSearchIndex(search_db_path)
        except Exception as e:
            logger.error(f"Failed to create search index for {self.codename}: {e}")
            return None

    async def initialize(self) -> None:
        """No-op initialization for documentation search engine."""

    async def shutdown(self) -> None:
        """Shutdown search index."""
        if self._search_index:
            self._search_index.close()

    async def search(self, query: str, size: int, word_match: bool) -> SearchDocsResponse:
        """Search documents directly using segment search index."""
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
        """Fetch document content from URL or file path."""
        try:
            # Handle file:// URLs for filesystem tenants
            if uri.startswith("file://"):
                return await self._fetch_local_file(uri, context)
            return await self._fetch_http_url(uri, context)
        except Exception as e:
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                context_mode=context,
                error=f"Fetch error: {e!s}",
            )

    async def _fetch_local_file(self, file_uri: str, context: str | None) -> FetchDocResponse:
        """Fetch content from local file."""
        # Convert file:// URI to path
        file_path = Path(file_uri.replace("file://", ""))

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

    async def _fetch_http_url(self, uri: str, context: str | None) -> FetchDocResponse:
        """Fetch content from HTTP URL."""
        async with (
            aiohttp.ClientSession() as session,
            session.get(uri, timeout=aiohttp.ClientTimeout(total=10)) as response,
        ):
            if response.status != 200:
                return FetchDocResponse(
                    url=uri,
                    title="",
                    content="",
                    context_mode=context,
                    error=f"HTTP {response.status}: {response.reason}",
                )

            html = await response.text()

            # Parse HTML with justhtml
            doc = JustHTML(html)

            # Get title
            title_elems = doc.query("title")
            title = title_elems[0].to_text().strip() if title_elems else "Untitled"

            # Get main content - try common content selectors
            content_selectors = [
                "main",
                "article",
                ".content",
                "#content",
                ".main-content",
                ".post-content",
                ".entry-content",
            ]

            content = ""
            for selector in content_selectors:
                content_elems = doc.query(selector)
                if content_elems:
                    content = content_elems[0].to_text()
                    break

            # Fallback to body if no content found
            if not content:
                body_elems = doc.query("body")
                content = body_elems[0].to_text() if body_elems else doc.to_text()

            # Clean up content
            content = "\n".join(line.strip() for line in content.split("\n") if line.strip())

            # Handle context modes
            if context == "surrounding" and len(content) > 8000:
                content = content[:8000] + "..."

            return FetchDocResponse(
                url=uri,
                title=title,
                content=content,
                context_mode=context,
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
                # Skip hidden files and common ignore patterns
                if item.name.startswith(".") or item.name in ["__pycache__", "node_modules"]:
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
        return {"status": "healthy", "tenant": self.codename}


def create_tenant_app(tenant_config: TenantConfig) -> TenantApp:
    """Create tenant app with direct search index access."""
    return TenantApp(tenant_config)
