"""Cache service for documentation with a filesystem backend."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import logging
import math
from urllib.parse import urlparse

from ..config import Settings
from ..domain.model import Document
from ..service_layer.filesystem_unit_of_work import AbstractUnitOfWork
from ..services.semantic_cache_matcher import SemanticCacheMatcher
from ..utils.doc_fetcher import AsyncDocFetcher, DocFetchError
from ..utils.models import DocPage


logger = logging.getLogger(__name__)


class CacheService:
    """Service for caching documentation with a filesystem backend.

    This class provides a testable, injectable service for documentation caching,
    following FastMCP and FastAPI dependency injection patterns.
    """

    def __init__(
        self,
        settings: Settings,
        uow_factory: Callable[[], AbstractUnitOfWork],
        embedding_provider: Callable[[str], list[float]] | None = None,
    ):
        """Initialize cache service.

        Args:
            settings: Settings instance with all configuration
            uow_factory: Factory function to create a Unit of Work
        """
        self.settings = settings
        self.uow_factory = uow_factory
        self.min_fetch_interval_hours = settings.min_fetch_interval_hours
        self.offline_mode = settings.is_offline_mode()
        self.semantic_cache_enabled = settings.semantic_cache_enabled
        self.semantic_cache_candidate_limit = settings.semantic_cache_candidate_limit
        self._embedding_provider = embedding_provider or self._default_embedding_provider
        self._fetcher: AsyncDocFetcher | None = None
        self._semantic_candidate_cache: list[Document] = []
        self._semantic_candidate_cache_loaded = False
        self._semantic_candidate_cache_lock = asyncio.Lock()

        # Initialize semantic cache matcher
        self._semantic_matcher = SemanticCacheMatcher(
            embedding_provider=self._embedding_provider,
            similarity_threshold=settings.semantic_cache_similarity_threshold,
            return_limit=settings.semantic_cache_return_limit,
        )

    async def ensure_ready(self) -> None:
        """Ensure cache is ready (fetcher initialized)."""
        if self._fetcher is None:
            self._fetcher = AsyncDocFetcher(settings=self.settings)
            await self._fetcher.__aenter__()
            logger.info("Document fetcher initialized")

    async def close(self) -> None:
        """Close resources."""
        if self._fetcher is not None:
            await self._fetcher.__aexit__(None, None, None)
            self._fetcher = None

    def _default_embedding_provider(self, text: str) -> list[float]:
        """Generate a lightweight embedding vector for semantic cache lookups."""

        buckets = 16
        vector = [0.0] * buckets
        normalized = text.lower().strip()
        if not normalized:
            normalized = "unknown"

        for index, char in enumerate(normalized):
            if not char.isalnum():
                continue
            bucket = index % buckets
            vector[bucket] += float(ord(char))

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _normalize_url_for_semantic(self, url: str) -> str:
        """Normalize a URL into a semantic-friendly slug."""

        parsed = urlparse(url)
        slug = parsed.path.replace("-", " ").replace("_", " ").strip().lower()
        if parsed.fragment:
            slug = f"{slug} #{parsed.fragment.lower()}".strip()
        return slug or url.lower()

    def _build_doc_page(
        self,
        document: Document,
        *,
        content: str,
        extraction_method: str | None = None,
    ) -> DocPage:
        payload = {
            "url": str(document.url.value),
            "title": document.title,
            "content": content,
            "readability_content": None,
        }
        if extraction_method is not None:
            payload["extraction_method"] = extraction_method
        return DocPage(**payload)

    def _document_to_page(self, document: Document) -> DocPage:
        """Convert a cached Document into a DocPage instance."""

        content = document.content.text or document.content.markdown
        return self._build_doc_page(
            document,
            content=content,
            extraction_method="semantic_cache",
        )

    async def _get_document(self, url: str) -> Document | None:
        async with self.uow_factory() as uow:
            return await uow.documents.get(url)

    async def get_cached_document(self, url: str) -> DocPage | None:
        """Get document from cache if available and fresh.

        Args:
            url: Document URL

        Returns:
            DocPage if cached and fresh, None otherwise
        """
        doc = await self._get_document(url)
        if not doc:
            return None

        # Check freshness
        if doc.metadata.last_fetched_at:
            now = datetime.now(timezone.utc)
            age_hours = (now - doc.metadata.last_fetched_at).total_seconds() / 3600
            if age_hours < self.min_fetch_interval_hours:
                logger.debug(f"Cache hit for {url}")
                return self._build_doc_page(doc, content=doc.content.text)
        return None

    async def get_stale_cached_document(self, url: str) -> DocPage | None:
        """Get document from cache even if stale (for offline mode).

        Args:
            url: Document URL

        Returns:
            DocPage if cached (regardless of age), None otherwise
        """
        doc = await self._get_document(url)
        if not doc:
            return None

        logger.warning(f"Using stale cache for {url} (offline mode)")
        return self._build_doc_page(doc, content=doc.content.text)

    async def fetch_and_cache(self, url: str) -> tuple[DocPage | None, str | None]:
        """Fetch document from source and cache it.

        Args:
            url: Document URL to fetch

        Returns:
            Tuple of (DocPage if successful, failure reason string when None)
        """
        if not self._fetcher:
            await self.ensure_ready()

        # Type narrowing: after ensure_ready(), fetcher is guaranteed to be initialized
        assert self._fetcher is not None, "Fetcher should be initialized after ensure_ready()"

        failure_reason: str | None = None

        try:
            page = await self._fetcher.fetch_page(url)
        except DocFetchError as exc:
            failure_reason = self._format_fetch_failure(exc)
            logger.warning("Fetcher could not extract %s: %s", url, failure_reason)
            page = None
        except Exception as e:
            failure_reason = f"unexpected_error:{e.__class__.__name__}"
            logger.error(f"Error fetching {url}: {e}", exc_info=True)
            page = None

        if page:
            cached, cache_error = await self._cache_document(page)
            if cached:
                return page, None

            failure_reason = cache_error or "cache_store_failed"
            logger.warning("Cache write failed for %s: %s", url, failure_reason)

        if not page:
            logger.warning(f"Failed to fetch {url}")
            failure_reason = failure_reason or "page_fetch_failed"

        await self._mark_document_failure(url)
        return None, failure_reason

    async def _cache_document(self, page: DocPage) -> tuple[bool, str | None]:
        """Cache a document to the filesystem repository.

        Args:
            page: Document page to cache

        Returns:
            Tuple of (success flag, failure reason when False)
        """
        from ..service_layer import services

        try:
            async with self.uow_factory() as uow:
                stored = await services.store_document(
                    url=page.url,
                    title=page.title,
                    markdown=page.readability_content.processed_markdown if page.readability_content else page.content,
                    text=page.readability_content.extracted_content if page.readability_content else page.content,
                    excerpt=page.readability_content.excerpt if page.readability_content else None,
                    uow=uow,
                )
            await self._record_semantic_candidate(str(stored.url.value), stored.title)
            return True, None
        except Exception as e:
            logger.error(f"Failed to cache document {page.url}: {e}", exc_info=True)
            return False, f"cache_store_failed:{e.__class__.__name__}"

    async def _mark_document_failure(self, url: str) -> None:
        """Record a failed fetch or cache attempt in persistent metadata."""

        async with self.uow_factory() as uow:
            from ..service_layer import services

            await services.mark_document_failed(url, uow)

    async def _get_semantic_cache_hits(self, url: str, limit: int | None = None) -> tuple[list[DocPage], bool]:
        """Return semantically similar cached documents for a requested URL."""

        if not self.semantic_cache_enabled:
            return [], False

        normalized_query = self._normalize_url_for_semantic(url)
        query_vector = self._embedding_provider(normalized_query)
        documents = await self._get_semantic_candidates()

        # Delegate to semantic matcher
        scored, confident = self._semantic_matcher.find_similar(
            query_url=url,
            query_embedding=query_vector,
            candidate_documents=documents,
            url_normalizer=self._normalize_url_for_semantic,
            limit=limit,
        )

        # Convert matched documents to pages
        hits = [self._document_to_page(doc) for _, doc in scored]
        return hits, confident

    async def _get_semantic_candidates(self) -> list[Document]:
        async with self._semantic_candidate_cache_lock:
            if self._semantic_candidate_cache_loaded:
                return list(self._semantic_candidate_cache)

            async with self.uow_factory() as uow:
                documents = await uow.documents.list(limit=self.semantic_cache_candidate_limit)

            self._semantic_candidate_cache = documents
            self._semantic_candidate_cache_loaded = True
            return list(documents)

    async def _record_semantic_candidate(self, url: str, title: str) -> None:
        if not self.semantic_cache_enabled or not self._semantic_candidate_cache_loaded:
            return
        if not title or not title.strip():
            logger.debug("Skipping semantic candidate with empty title: %s", url)
            return

        try:
            candidate = Document.create(url=url, title=title, markdown=title, text=title)
        except ValueError as exc:
            logger.debug("Skipping semantic candidate for %s: %s", url, exc)
            return

        async with self._semantic_candidate_cache_lock:
            updated: list[Document] = [candidate]
            for existing in self._semantic_candidate_cache:
                if str(existing.url.value) == url:
                    continue
                updated.append(existing)
                if len(updated) >= self.semantic_cache_candidate_limit:
                    break
            self._semantic_candidate_cache = updated

    async def _get_semantic_cache_hit(self, url: str) -> DocPage | None:
        """Return the most relevant semantic cache hit when confident."""

        hits, confident = await self._get_semantic_cache_hits(url, limit=1)
        if hits and confident:
            return hits[0]
        return None

    async def check_and_fetch_page(
        self,
        url: str,
        *,
        use_semantic_cache: bool = True,
    ) -> tuple[DocPage | None, bool, str | None]:
        """Universal page fetching with cache check.

        This is the primary method for getting documentation pages.
        Implements the caching strategy with proper TTL enforcement.

        Args:
            url: URL to fetch
            use_semantic_cache: When False, force a network fetch instead of
                relying on semantic cache heuristics. Used by schedulers when
                force-syncing a tenant so fresh content is guaranteed.

        Returns:
            Tuple of (DocPage if available, cache hit flag, failure reason when None)
        """
        # Try fresh cache first
        cached = await self.get_cached_document(url)
        if cached:
            return cached, True, None

        # Check offline mode with stale cache
        if self.offline_mode:
            stale = await self.get_stale_cached_document(url)
            if stale:
                return stale, True, None

            if self.semantic_cache_enabled and use_semantic_cache:
                semantic_hit = await self._get_semantic_cache_hit(url)
                if semantic_hit:
                    return semantic_hit, True, None
            logger.warning(f"Cannot fetch {url} - offline mode and no cache")
            return None, False, "offline_no_cache"

        if self.semantic_cache_enabled and use_semantic_cache:
            semantic_hit = await self._get_semantic_cache_hit(url)
            if semantic_hit:
                logger.info(f"Semantic cache hit for {url}")
                return semantic_hit, True, None

        # Fetch from source
        await self.ensure_ready()
        logger.info(f"Fetching {url}")
        page, failure_reason = await self.fetch_and_cache(url)
        return page, False, failure_reason

    async def get_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        async with self.uow_factory() as uow:
            count = await uow.documents.count()
            return {"documents": count}

    def get_fetcher_stats(self) -> dict[str, int]:
        """Expose fetcher metrics (fallback attempts/success/failure)."""

        if not self._fetcher:
            return {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}
        return self._fetcher.get_fallback_metrics()

    def _format_fetch_failure(self, exc: DocFetchError) -> str:
        reason = exc.reason or "doc_fetch_error"
        detail = (exc.detail or "").strip()
        if detail:
            trimmed = detail if len(detail) <= 240 else f"{detail[:237]}..."
            return f"{reason}:{trimmed}"
        return reason
