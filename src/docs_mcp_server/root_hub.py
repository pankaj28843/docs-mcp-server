"""RootHub - Single entry point for all documentation tenants."""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP

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
        if ctx:
            await ctx.info(f"[root-hub] Listing {len(registry)} tenants")

        tenants = registry.list_tenants()
        return {
            "count": len(tenants),
            "tenants": [
                {
                    "codename": t.codename,
                    "description": f"{t.display_name} - {t.description}",
                }
                for t in tenants
            ],
        }

    @mcp.tool(name="describe_tenant", annotations={"title": "Describe Tenant", "readOnlyHint": True})
    async def describe_tenant(
        codename: Annotated[str, "Tenant codename (e.g., 'django', 'fastapi')"],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get detailed information about a documentation tenant. Returns display name, description, source type, test queries, URL prefixes, and browse support. Use this to understand a tenant's capabilities before searching or fetching."""
        if ctx:
            await ctx.info(f"[root-hub] Describing tenant: {codename}")

        metadata = registry.get_metadata(codename)
        if metadata is None:
            return {
                "error": f"Tenant '{codename}' not found",
                "available_tenants": ", ".join(registry.list_codenames()),
            }

        return metadata.as_dict()


def _register_proxy_tools(mcp: FastMCP, registry: TenantRegistry) -> None:
    @mcp.tool(name="root_search", annotations={"title": "Search Docs", "readOnlyHint": True})
    async def root_search(
        tenant_codename: Annotated[str, "Tenant codename (e.g., 'django', 'fastapi')"],
        query: Annotated[str, "Search query"],
        size: Annotated[int, "Max results (1-100)"] = 10,
        word_match: Annotated[bool, "Whole word matching"] = False,
        include_stats: Annotated[bool, "Include search stats"] = False,
        include_debug: Annotated[bool, "Include match trace debug metadata"] = False,
        ctx: Context | None = None,
    ) -> SearchDocsResponse:
        """Search documentation within a specific tenant. Returns ranked results with URL, title, score, and snippet. Use word_match=true for exact phrase matching. Use include_stats=true for debugging search quality."""
        if ctx:
            await ctx.info(f"[root-hub] root_search → {tenant_codename}: {query}")

        tenant_app = registry.get_tenant(tenant_codename)
        if tenant_app is None:
            return SearchDocsResponse(
                results=[],
                error=_format_missing_tenant_error(registry, tenant_codename),
                query=query,
            )

        return await tenant_app.search(
            query=query,
            size=size,
            word_match=word_match,
            include_stats=include_stats,
            include_debug=include_debug,
        )

    @mcp.tool(name="root_fetch", annotations={"title": "Fetch Doc", "readOnlyHint": True})
    async def root_fetch(
        tenant_codename: Annotated[str, "Tenant codename"],
        uri: Annotated[str, "Document URL"],
        context: Annotated[str | None, "'full' or 'surrounding'"] = None,
        ctx: Context | None = None,
    ) -> FetchDocResponse:
        """Fetch the full content of a documentation page by URL. Returns title and markdown content. Use context='full' for complete document or 'surrounding' for relevant sections only."""
        if ctx:
            await ctx.info(f"[root-hub] root_fetch → {tenant_codename}: {uri}")

        tenant_app = registry.get_tenant(tenant_codename)
        if tenant_app is None:
            return FetchDocResponse(
                url=uri,
                title="",
                content="",
                error=_format_missing_tenant_error(registry, tenant_codename),
            )

        return await tenant_app.fetch(uri, context)

    @mcp.tool(name="root_browse", annotations={"title": "Browse Tree", "readOnlyHint": True})
    async def root_browse(
        tenant_codename: Annotated[str, "Tenant codename"],
        path: Annotated[str, "Relative path (empty for root)"] = "",
        depth: Annotated[int, "Levels to traverse (1-5)"] = 2,
        ctx: Context | None = None,
    ) -> BrowseTreeResponse:
        """Browse the directory structure of filesystem-based documentation tenants. Returns a tree of files and folders with titles and URLs. Only works for tenants with supports_browse=true (filesystem or git sources)."""
        if ctx:
            await ctx.info(f"[root-hub] root_browse → {tenant_codename}: path='{path}', depth={depth}")

        tenant_app = registry.get_tenant(tenant_codename)
        if tenant_app is None:
            return BrowseTreeResponse(
                root_path=path or "/",
                depth=depth,
                nodes=[],
                error=_format_missing_tenant_error(registry, tenant_codename),
            )

        if not registry.is_filesystem_tenant(tenant_codename):
            return BrowseTreeResponse(
                root_path=path or "/",
                depth=depth,
                nodes=[],
                error=f"Tenant '{tenant_codename}' does not support browse",
            )

        return await tenant_app.browse_tree(path=path, depth=depth)
