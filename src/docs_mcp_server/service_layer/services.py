"""Service layer - Use case orchestration.

Following Cosmic Python Chapter 4: Service Layer
- Orchestrates business use cases
- Works with domain model through repositories
- Uses Unit of Work for transaction management
"""

import logging
from pathlib import Path

from docs_mcp_server.domain import Document
from docs_mcp_server.service_layer.filesystem_unit_of_work import AbstractUnitOfWork
from docs_mcp_server.service_layer.search_service import SearchService
from docs_mcp_server.utils.models import SearchStats


logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 50


def _build_guardrail_stats(*, warning: str, matches: int = 0, error: str | None = None) -> SearchStats:
    """Create synthetic SearchStats payloads for guardrail fallbacks."""

    return SearchStats(
        stage=0,
        files_found=matches,
        matches=matches,
        files_searched=0,
        search_time=0.0,
        timed_out=False,
        progress={},
        warning=warning,
        error=error,
    )


async def fetch_document(
    url: str,
    uow: AbstractUnitOfWork,
) -> Document | None:
    """Fetch and store a document.

    Service layer use case:
    1. Check if document exists
    2. Return if found
    3. Otherwise return None (caller should fetch from source)

    Args:
        url: Document URL
        uow: Unit of Work for transaction management

    Returns:
        Document if found, None otherwise
    """
    async with uow:
        document = await uow.documents.get(url)
        return document


async def search_documents_filesystem(
    query: str,
    search_service: SearchService,  # Updated to use new SearchService
    uow: AbstractUnitOfWork,  # Kept for interface compatibility but not used for search
    data_dir: Path,  # NEW: Explicit data directory parameter
    limit: int = 10,
    word_match: bool = False,  # NEW: Enable whole word matching
    include_stats: bool = False,  # NEW: Include search statistics
    tenant_codename: str | None = None,
) -> tuple[list[Document], SearchStats | None]:
    """Search for documents using modern multi-stage search.

    OPTIMIZATION: Search results contain all needed data (URL, title, snippet, score).
    No filesystem I/O is performed - we directly construct Document objects from
    search results for maximum performance.

    Args:
        query: Natural language search query
        search_service: SearchService instance (new multi-stage implementation)
        uow: Unit of Work (kept for interface compatibility, not used for search)
        data_dir: Directory containing markdown files to search
        limit: Maximum results
        word_match: Enable whole word matching (passed to ripgrep as -w flag)
        include_stats: Include search performance statistics
        tenant_codename: Optional tenant identifier for cache instrumentation context

    Returns:
        A tuple containing a list of matching Documents and search statistics.
    """
    if not query or not query.strip():
        return [], None

    normalized_limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    # Execute new multi-stage search with guardrails for failures
    try:
        search_response = await search_service.search(
            raw_query=query,
            data_dir=data_dir,
            max_results=normalized_limit,
            word_match=word_match,
            include_stats=include_stats,
            tenant_context=tenant_codename,
        )
    except Exception as exc:
        logger.exception("Search service failed for query '%s'", query)
        fallback_stats = _build_guardrail_stats(
            warning="Search service error; returning empty result set",
            matches=0,
            error=str(exc),
        )
        return [], fallback_stats

    # OPTIMIZATION: Construct documents directly from search results
    # No filesystem I/O - search results already contain all needed data
    from docs_mcp_server.domain.model import (
        URL,
        Content,
        Document,
        DocumentMetadata,
    )

    managed_docs = []
    for result in search_response.results:
        # Create transient document from search result data
        doc = Document(
            url=URL(result.document_url),
            title=result.document_title,
            content=Content(markdown=result.snippet, text=result.snippet),
            metadata=DocumentMetadata(),
        )
        doc.score = result.relevance_score
        doc.snippet = result.snippet
        # Copy match trace metadata
        doc.match_stage = result.match_trace.stage
        doc.match_stage_name = result.match_trace.stage_name
        doc.match_query_variant = result.match_trace.query_variant
        doc.match_reason = result.match_trace.match_reason
        doc.match_ripgrep_flags = result.match_trace.ripgrep_flags
        managed_docs.append(doc)

    # Convert domain SearchStats to utils SearchStats if present
    stats = None
    if search_response.stats:
        stats = SearchStats(
            stage=search_response.stats.stage,
            files_found=search_response.stats.files_found,
            matches=search_response.stats.matches_found,
            files_searched=search_response.stats.files_searched,
            search_time=search_response.stats.search_time,
            timed_out=False,
            progress={},
            warning=search_response.stats.warning,
            error=None,
        )
    elif include_stats:
        stats = _build_guardrail_stats(
            warning="Search telemetry missing; synthesized fallback metrics",
            matches=len(managed_docs),
        )

    return managed_docs, stats


async def store_document(
    url: str,
    title: str,
    markdown: str,
    text: str,
    excerpt: str | None,
    uow: AbstractUnitOfWork,
) -> Document:
    """Store or update a document.

    Service layer use case:
    1. Get existing document or create new
    2. Update content
    3. Mark as successfully fetched
    4. Commit transaction

    Args:
        url: Document URL
        title: Document title
        markdown: Markdown content
        text: Plain text content
        excerpt: Optional excerpt
        uow: Unit of Work for transaction management

    Returns:
        Stored Document
    """
    async with uow:
        # Try to get existing document
        document = await uow.documents.get(url)

        if document:
            # Update existing document
            document.update_content(markdown=markdown, text=text, excerpt=excerpt or "")
            document.title = title
        else:
            # Create new document
            document = Document.create(
                url=url,
                title=title,
                markdown=markdown,
                text=text,
                excerpt=excerpt or "",
            )

        # Mark as successfully fetched
        document.metadata.mark_success()

        # Store in repository
        await uow.documents.add(document)

        # Commit transaction
        await uow.commit()

        return document


async def mark_document_failed(
    url: str,
    uow: AbstractUnitOfWork,
) -> None:
    """Mark a document fetch as failed.

    Service layer use case:
    1. Get document
    2. Mark as failed (increments retry count)
    3. Commit transaction

    Args:
        url: Document URL
        uow: Unit of Work for transaction management
    """
    async with uow:
        document = await uow.documents.get(url)

        if document:
            document.mark_fetch_failed()
            await uow.documents.add(document)
            await uow.commit()
