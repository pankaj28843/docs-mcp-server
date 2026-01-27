"""RootHub - Single entry point for all documentation tenants."""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from opentelemetry.trace import SpanKind

from docs_mcp_server.observability import REQUEST_COUNT, REQUEST_LATENCY, track_latency
from docs_mcp_server.observability.tracing import create_span
from docs_mcp_server.registry import TenantMetadata, TenantRegistry
from docs_mcp_server.search.fuzzy import levenshtein_distance
from docs_mcp_server.utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


logger = logging.getLogger(__name__)


def _format_missing_tenant_error(registry: TenantRegistry, codename: str) -> str:
    available = ", ".join(registry.list_codenames())
    return f"Tenant '{codename}' not found. Available: {available}"


def _score_tenant_match(metadata: TenantMetadata, query: str) -> float:
    """Score how well a tenant matches a search query.

    Uses a combination of exact matching and fuzzy (Levenshtein) distance
    to score tenant metadata fields against the query.

    Returns:
        Score from 0.0 to 1.0, higher is better match.
    """
    query_lower = query.lower()
    query_terms = query_lower.split()

    # Collect all searchable text from tenant metadata
    searchable_fields: list[tuple[str, float]] = [
        (metadata.codename.lower(), 3.0),  # Codename gets highest weight
        (metadata.display_name.lower(), 2.5),
        (metadata.description.lower(), 1.5),
        (metadata.source_type.lower(), 0.5),
    ]

    # Add URL prefixes and test queries
    searchable_fields.extend((url.lower(), 1.0) for url in metadata.url_prefixes)
    searchable_fields.extend((tq.lower(), 1.0) for tq in metadata.test_queries)

    best_score = 0.0

    for field_text, weight in searchable_fields:
        # Exact substring match (strongest signal)
        if query_lower in field_text:
            # Full query matches exactly
            score = 1.0 * weight
            best_score = max(best_score, score)
            continue

        # Check if field text contains query as whole word
        if any(query_lower == word for word in field_text.split()):
            score = 0.95 * weight
            best_score = max(best_score, score)
            continue

        # Term-by-term matching for multi-word queries
        term_scores = []
        for term in query_terms:
            if term in field_text:
                term_scores.append(0.8)
            else:
                # Fuzzy match against words in field
                field_words = field_text.replace("-", " ").replace("_", " ").split()
                best_fuzzy = 0.0
                for word in field_words:
                    if len(term) >= 3 and len(word) >= 3:
                        distance = levenshtein_distance(term, word, max_distance=2)
                        if distance <= 2:
                            # Convert distance to score: 0 dist = 0.7, 1 dist = 0.5, 2 dist = 0.3
                            fuzzy_score = max(0.0, 0.7 - (distance * 0.2))
                            best_fuzzy = max(best_fuzzy, fuzzy_score)
                term_scores.append(best_fuzzy)

        if term_scores:
            avg_term_score = sum(term_scores) / len(term_scores)
            score = avg_term_score * weight
            best_score = max(best_score, score)

    return min(best_score, 1.0)  # Cap at 1.0


def create_root_hub(registry: TenantRegistry) -> FastMCP:
    """Create the root MCP server that proxies to every tenant."""

    instructions = (
        f"Docs Hub exposing {len(registry)} documentation sources. "
        "List tenants, pick a codename, then call root_search/root_fetch/root_browse."
    )

    mcp = FastMCP(
        name="Docs Root Hub",
        instructions=instructions,
        mask_error_details=True,
    )

    _register_discovery_tools(mcp, registry)
    _register_proxy_tools(mcp, registry)
    return mcp


def _register_discovery_tools(mcp: FastMCP, registry: TenantRegistry) -> None:
    @mcp.tool(name="list_tenants", annotations={"title": "List All Docs", "readOnlyHint": True})
    async def list_tenants(ctx: Context | None = None) -> dict[str, Any]:
        """List ALL available documentation sources (tenants).

        Returns count and array of tenants with codename and description.

        NOTE: Prefer find_tenant over list_tenants to save context window.
        Only use list_tenants when you need to browse ALL available sources
        or when find_tenant returns no matches for your topic.

        Returns:
            {
                "count": 101,
                "tenants": [
                    {"codename": "django", "description": "Django - Official Django docs"},
                    {"codename": "react", "description": "React - Official React docs"},
                    ...
                ]
            }
        """
        tool_name = "list_tenants"
        with (
            track_latency(REQUEST_LATENCY, tenant="root", tool=tool_name),
            create_span("mcp.tool.list_tenants", kind=SpanKind.INTERNAL) as span,
        ):
            span.set_attribute("mcp.tool.name", tool_name)
            tenants = registry.list_tenants()
            span.set_attribute("tenant.count", len(tenants))
            logger.info("list_tenants called - returning %d tenants", len(tenants))
            REQUEST_COUNT.labels(tenant="root", tool=tool_name, status="ok").inc()
            return {
                "count": len(tenants),
                "tenants": [
                    {"codename": t.codename, "description": f"{t.display_name} - {t.description}"} for t in tenants
                ],
            }

    @mcp.tool(name="find_tenant", annotations={"title": "Find Docs", "readOnlyHint": True})
    async def find_tenant(
        query: Annotated[str, "Topic to find (e.g., 'django', 'react', 'aws', 'machine learning')"],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Find documentation tenants matching a topic using fuzzy search.

        RECOMMENDED: Use this FIRST to locate relevant docs before searching.
        Saves context window by returning only matching tenants (not all 100+).

        Searches across tenant codenames, display names, descriptions, URLs,
        and test queries. Supports typo tolerance (e.g., 'djano' finds 'django').

        WORKFLOW:
        1. find_tenant("topic") → get matching tenant codenames
        2. root_search(codename, "query") → search within that tenant
        3. root_fetch(codename, url) → read full page content

        If find_tenant returns no matches, fall back to list_tenants.

        Examples:
            find_tenant("django")     → finds django, drf tenants
            find_tenant("react")      → finds react, react-native tenants
            find_tenant("aws")        → finds aws-eks, aws-bedrock tenants
            find_tenant("ml")         → finds transformers, pytorch tenants

        Returns:
            {
                "query": "django",
                "count": 2,
                "tenants": [
                    {"codename": "django", "description": "...", "match_score": 1.0},
                    {"codename": "drf", "description": "...", "match_score": 0.7}
                ]
            }
        """
        tool_name = "find_tenant"
        with (
            track_latency(REQUEST_LATENCY, tenant="root", tool=tool_name),
            create_span(
                "mcp.tool.find_tenant",
                kind=SpanKind.INTERNAL,
                attributes={"search.query": query[:100], "mcp.tool.name": tool_name},
            ) as span,
        ):
            all_tenants = registry.list_tenants()

            # Score and rank tenants
            scored_tenants: list[tuple[TenantMetadata, float]] = []
            for tenant in all_tenants:
                score = _score_tenant_match(tenant, query)
                if score > 0.1:  # Minimum threshold
                    scored_tenants.append((tenant, score))

            # Sort by score descending
            scored_tenants.sort(key=lambda x: x[1], reverse=True)

            # Take top 10 results
            top_results = scored_tenants[:10]

            span.set_attribute("search.result_count", len(top_results))
            logger.info(
                "find_tenant called - query='%s', matches=%d",
                query[:50],
                len(top_results),
            )
            REQUEST_COUNT.labels(tenant="root", tool=tool_name, status="ok").inc()

            return {
                "query": query,
                "count": len(top_results),
                "tenants": [
                    {
                        "codename": t.codename,
                        "description": f"{t.display_name} - {t.description}",
                        "match_score": round(score, 2),
                    }
                    for t, score in top_results
                ],
            }

    @mcp.tool(name="describe_tenant", annotations={"title": "Describe Tenant", "readOnlyHint": True})
    async def describe_tenant(
        codename: Annotated[str, "Tenant codename (e.g., 'django', 'fastapi')"],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get detailed information about a specific documentation tenant.

        Returns display name, description, source type, test queries,
        URL prefixes, and browse support. Use this to understand a tenant's
        capabilities and get example queries before searching.

        Args:
            codename: Exact tenant codename (use list_tenants or find_tenant to discover)

        Returns:
            {
                "codename": "django",
                "display_name": "Django",
                "description": "Official Django docs",
                "source_type": "online",
                "test_queries": ["models", "views", "forms"],
                "url_prefixes": ["https://docs.djangoproject.com/"],
                "supports_browse": false
            }
        """
        tool_name = "describe_tenant"
        with (
            track_latency(REQUEST_LATENCY, tenant=codename, tool=tool_name),
            create_span(
                "mcp.tool.describe_tenant",
                kind=SpanKind.INTERNAL,
                attributes={"tenant.codename": codename, "mcp.tool.name": tool_name},
            ) as span,
        ):
            metadata = registry.get_metadata(codename)
            if metadata is None:
                span.set_attribute("error", True)
                logger.warning("describe_tenant called with unknown tenant: %s", codename)
                REQUEST_COUNT.labels(tenant=codename, tool=tool_name, status="error").inc()
                return {
                    "error": f"Tenant '{codename}' not found",
                    "available_tenants": ", ".join(registry.list_codenames()),
                }
            logger.info("describe_tenant called - tenant=%s, source_type=%s", codename, metadata.source_type)
            REQUEST_COUNT.labels(tenant=codename, tool=tool_name, status="ok").inc()
            return metadata.as_dict()


def _register_proxy_tools(mcp: FastMCP, registry: TenantRegistry) -> None:
    @mcp.tool(name="root_search", annotations={"title": "Search Docs", "readOnlyHint": True})
    async def root_search(
        tenant_codename: Annotated[str, "Exact tenant codename (e.g., 'django', 'fastapi', 'react')"],
        query: Annotated[str, "Search query - use specific terms, not vague descriptions"],
        size: Annotated[int, "Number of results to return (default: 10, max: 100)"] = 10,
        word_match: Annotated[bool, "Enable whole-word matching for exact phrases"] = False,
        ctx: Context | None = None,
    ) -> SearchDocsResponse:
        """Search documentation within a specific tenant.

        Returns ranked results with URL, title, and highlighted snippet.
        Use word_match=true for exact phrase matching.

        IMPORTANT: The tenant_codename must exactly match a codename from
        list_tenants or find_tenant (e.g., 'django', 'fastapi', 'react').

        Examples:
            root_search("django", "select_related prefetch_related")
            root_search("react", "useEffect cleanup")
            root_search("fastapi", "dependency injection", word_match=true)

        Returns:
            {
                "results": [
                    {"url": "https://...", "title": "QuerySet API", "snippet": "..."},
                    ...
                ],
                "error": null
            }
        """
        tool_name = "root_search"
        with (
            track_latency(REQUEST_LATENCY, tenant=tenant_codename, tool=tool_name),
            create_span(
                "mcp.tool.root_search",
                kind=SpanKind.INTERNAL,
                attributes={
                    "tenant.codename": tenant_codename,
                    "search.query": query[:100],
                    "mcp.tool.name": tool_name,
                },
            ) as span,
        ):
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning("root_search called with unknown tenant: %s", tenant_codename)
                REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="error").inc()
                return SearchDocsResponse(
                    results=[], error=_format_missing_tenant_error(registry, tenant_codename), query=query
                )
            logger.info(
                "root_search called - tenant=%s, query='%s', size=%d, word_match=%s",
                tenant_codename,
                query[:50],
                size,
                word_match,
            )
            result = await tenant_app.search(query=query, size=size, word_match=word_match)
            span.set_attribute("search.result_count", len(result.results))
            logger.info("root_search completed - tenant=%s, results=%d", tenant_codename, len(result.results))
            REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="ok").inc()
            return result

    @mcp.tool(name="root_fetch", annotations={"title": "Fetch Doc Page", "readOnlyHint": True})
    async def root_fetch(
        tenant_codename: Annotated[str, "Tenant codename (same as used in search)"],
        uri: Annotated[str, "Full URL of the documentation page to fetch"],
        ctx: Context | None = None,
    ) -> FetchDocResponse:
        """Fetch the full content of a documentation page by URL.

        Use this after root_search to read the actual documentation content.
        The uri should be a URL from search results.

        Returns the page title and full markdown content.

        Example:
            root_fetch("django", "https://docs.djangoproject.com/en/5.2/topics/db/queries/")

        Returns:
            {
                "url": "https://...",
                "title": "Making queries",
                "content": "# Making queries\\n\\nOnce you've created...",
                "error": null
            }
        """
        tool_name = "root_fetch"
        with (
            track_latency(REQUEST_LATENCY, tenant=tenant_codename, tool=tool_name),
            create_span(
                "mcp.tool.root_fetch",
                kind=SpanKind.INTERNAL,
                attributes={
                    "tenant.codename": tenant_codename,
                    "fetch.uri": uri[:200],
                    "mcp.tool.name": tool_name,
                },
            ) as span,
        ):
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning("root_fetch called with unknown tenant: %s", tenant_codename)
                REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="error").inc()
                return FetchDocResponse(
                    url=uri, title="", content="", error=_format_missing_tenant_error(registry, tenant_codename)
                )
            logger.info(
                "root_fetch called - tenant=%s, uri='%s'",
                tenant_codename,
                uri[:80],
            )
            result = await tenant_app.fetch(uri)
            logger.info("root_fetch completed - tenant=%s, content_length=%d", tenant_codename, len(result.content))
            REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="ok").inc()
            return result

    @mcp.tool(name="root_browse", annotations={"title": "Browse Doc Tree", "readOnlyHint": True})
    async def root_browse(
        tenant_codename: Annotated[str, "Tenant codename"],
        path: Annotated[str, "Relative path within the docs (empty string for root)"] = "",
        depth: Annotated[int, "Directory levels to traverse (1-5, default: 2)"] = 2,
        ctx: Context | None = None,
    ) -> BrowseTreeResponse:
        """Browse the directory structure of filesystem-based documentation.

        Returns a tree of files and folders with titles and URLs.
        Only works for tenants with supports_browse=true (filesystem or git sources).

        Use describe_tenant first to check if a tenant supports browsing.

        Example:
            root_browse("cosmicpython", path="", depth=2)

        Returns:
            {
                "root_path": "/",
                "depth": 2,
                "nodes": [
                    {"name": "chapter_01.md", "type": "file", "title": "Domain Modeling"},
                    {"name": "appendix", "type": "directory", "children": [...]}
                ],
                "error": null
            }
        """
        tool_name = "root_browse"
        with (
            track_latency(REQUEST_LATENCY, tenant=tenant_codename, tool=tool_name),
            create_span(
                "mcp.tool.root_browse",
                kind=SpanKind.INTERNAL,
                attributes={
                    "tenant.codename": tenant_codename,
                    "browse.path": path,
                    "browse.depth": depth,
                    "mcp.tool.name": tool_name,
                },
            ) as span,
        ):
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning("root_browse called with unknown tenant: %s", tenant_codename)
                REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="error").inc()
                return BrowseTreeResponse(
                    root_path=path or "/",
                    depth=depth,
                    nodes=[],
                    error=_format_missing_tenant_error(registry, tenant_codename),
                )
            if not registry.is_filesystem_tenant(tenant_codename):
                span.set_attribute("error", True)
                logger.warning("root_browse called on non-filesystem tenant: %s", tenant_codename)
                REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="error").inc()
                return BrowseTreeResponse(
                    root_path=path or "/",
                    depth=depth,
                    nodes=[],
                    error=f"Tenant '{tenant_codename}' does not support browse (only filesystem/git tenants do)",
                )
            logger.info("root_browse called - tenant=%s, path='%s', depth=%d", tenant_codename, path, depth)
            result = await tenant_app.browse_tree(path=path, depth=depth)
            logger.info("root_browse completed - tenant=%s, nodes=%d", tenant_codename, len(result.nodes))
            REQUEST_COUNT.labels(tenant=tenant_codename, tool=tool_name, status="ok").inc()
            return result
