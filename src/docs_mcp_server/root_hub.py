"""RootHub - Single entry point for all documentation tenants."""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from opentelemetry.trace import SpanKind

from docs_mcp_server.observability.tracing import create_span
from docs_mcp_server.registry import TenantRegistry
from docs_mcp_server.utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


logger = logging.getLogger(__name__)


def _format_missing_tenant_error(registry: TenantRegistry, codename: str) -> str:
    available = ", ".join(registry.list_codenames())
    return f"Tenant '{codename}' not found. Available: {available}"


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
    @mcp.tool(name="list_tenants", annotations={"title": "List Docs", "readOnlyHint": True})
    async def list_tenants(ctx: Context | None = None) -> dict[str, Any]:
        """List all available documentation sources (tenants). Returns count and array of tenants with codename and description. Use this to discover what documentation is available before searching."""
        with create_span("mcp.tool.list_tenants", kind=SpanKind.INTERNAL) as span:
            span.set_attribute("mcp.tool.name", "list_tenants")
            tenants = registry.list_tenants()
            span.set_attribute("tenant.count", len(tenants))
            logger.info(f"list_tenants called - returning {len(tenants)} tenants")
            return {
                "count": len(tenants),
                "tenants": [
                    {"codename": t.codename, "description": f"{t.display_name} - {t.description}"} for t in tenants
                ],
            }

    @mcp.tool(name="describe_tenant", annotations={"title": "Describe Tenant", "readOnlyHint": True})
    async def describe_tenant(
        codename: Annotated[str, "Tenant codename (e.g., 'django', 'fastapi')"],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get detailed information about a documentation tenant. Returns display name, description, source type, test queries, URL prefixes, and browse support. Use this to understand a tenant's capabilities before searching or fetching."""
        with create_span(
            "mcp.tool.describe_tenant", kind=SpanKind.INTERNAL, attributes={"tenant.codename": codename}
        ) as span:
            metadata = registry.get_metadata(codename)
            if metadata is None:
                span.set_attribute("error", True)
                logger.warning(f"describe_tenant called with unknown tenant: {codename}")
                return {
                    "error": f"Tenant '{codename}' not found",
                    "available_tenants": ", ".join(registry.list_codenames()),
                }
            logger.info(f"describe_tenant called - tenant={codename}, source_type={metadata.source_type}")
            return metadata.as_dict()


def _register_proxy_tools(mcp: FastMCP, registry: TenantRegistry) -> None:
    @mcp.tool(name="root_search", annotations={"title": "Search Docs", "readOnlyHint": True})
    async def root_search(
        tenant_codename: Annotated[str, "Tenant codename (e.g., 'django', 'fastapi')"],
        query: Annotated[str, "Search query"],
        size: Annotated[int, "Max results (1-100)"] = 10,
        word_match: Annotated[bool, "Whole word matching"] = False,
        ctx: Context | None = None,
    ) -> SearchDocsResponse:
        """Search documentation within a specific tenant. Returns ranked results with URL, title, score, and snippet. Use word_match=true for exact phrase matching."""
        with create_span(
            "mcp.tool.root_search",
            kind=SpanKind.INTERNAL,
            attributes={"tenant.codename": tenant_codename, "search.query": query[:100]},
        ) as span:
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning(f"root_search called with unknown tenant: {tenant_codename}")
                return SearchDocsResponse(
                    results=[], error=_format_missing_tenant_error(registry, tenant_codename), query=query
                )
            logger.info(
                f"root_search called - tenant={tenant_codename}, query='{query[:50]}', size={size}, word_match={word_match}"
            )
            result = await tenant_app.search(query=query, size=size, word_match=word_match)
            span.set_attribute("search.result_count", len(result.results))
            logger.info(f"root_search completed - tenant={tenant_codename}, results={len(result.results)}")
            return result

    @mcp.tool(name="root_fetch", annotations={"title": "Fetch Doc", "readOnlyHint": True})
    async def root_fetch(
        tenant_codename: Annotated[str, "Tenant codename"],
        uri: Annotated[str, "Document URL"],
        context: Annotated[str | None, "'full' or 'surrounding'"] = None,
        ctx: Context | None = None,
    ) -> FetchDocResponse:
        """Fetch the full content of a documentation page by URL. Returns title and markdown content. Use context='full' for complete document or 'surrounding' for relevant sections only."""
        with create_span(
            "mcp.tool.root_fetch",
            kind=SpanKind.INTERNAL,
            attributes={"tenant.codename": tenant_codename, "fetch.uri": uri[:200]},
        ) as span:
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning(f"root_fetch called with unknown tenant: {tenant_codename}")
                return FetchDocResponse(
                    url=uri, title="", content="", error=_format_missing_tenant_error(registry, tenant_codename)
                )
            logger.info(f"root_fetch called - tenant={tenant_codename}, uri='{uri[:80]}', context={context}")
            result = await tenant_app.fetch(uri, context)
            logger.info(f"root_fetch completed - tenant={tenant_codename}, content_length={len(result.content)}")
            return result

    @mcp.tool(name="root_browse", annotations={"title": "Browse Tree", "readOnlyHint": True})
    async def root_browse(
        tenant_codename: Annotated[str, "Tenant codename"],
        path: Annotated[str, "Relative path (empty for root)"] = "",
        depth: Annotated[int, "Levels to traverse (1-5)"] = 2,
        ctx: Context | None = None,
    ) -> BrowseTreeResponse:
        """Browse the directory structure of filesystem-based documentation tenants. Returns a tree of files and folders with titles and URLs. Only works for tenants with supports_browse=true (filesystem or git sources)."""
        with create_span(
            "mcp.tool.root_browse",
            kind=SpanKind.INTERNAL,
            attributes={"tenant.codename": tenant_codename, "browse.path": path, "browse.depth": depth},
        ) as span:
            tenant_app = registry.get_tenant(tenant_codename)
            if tenant_app is None:
                span.set_attribute("error", True)
                logger.warning(f"root_browse called with unknown tenant: {tenant_codename}")
                return BrowseTreeResponse(
                    root_path=path or "/",
                    depth=depth,
                    nodes=[],
                    error=_format_missing_tenant_error(registry, tenant_codename),
                )
            if not registry.is_filesystem_tenant(tenant_codename):
                span.set_attribute("error", True)
                logger.warning(f"root_browse called on non-filesystem tenant: {tenant_codename}")
                return BrowseTreeResponse(
                    root_path=path or "/",
                    depth=depth,
                    nodes=[],
                    error=f"Tenant '{tenant_codename}' does not support browse",
                )
            logger.info(f"root_browse called - tenant={tenant_codename}, path='{path}', depth={depth}")
            result = await tenant_app.browse_tree(path=path, depth=depth)
            logger.info(f"root_browse completed - tenant={tenant_codename}, nodes={len(result.nodes)}")
            return result
