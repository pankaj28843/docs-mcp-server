"""Unit tests for RootHub discovery and proxy helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self
from unittest.mock import MagicMock, patch

import pytest

from docs_mcp_server import root_hub
from docs_mcp_server.domain.model import URL, Content, Document
from docs_mcp_server.registry import TenantMetadata


class ToolCaptureMCP:
    """Minimal FastMCP stub that records registered tools."""

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}

    def tool(
        self, name: str, annotations: dict[str, Any] | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[name] = {"func": func, "annotations": annotations or {}}
            return func

        return decorator


class RecordingContext:
    """Simple ctx.info recorder used by FastMCP tools."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def info(self, message: str) -> None:
        self.messages.append(message)


@dataclass
class FakeTenantApp:
    """Tenant stub exposing only the attributes RootHub touches."""

    codename: str = "test-tenant"
    docs_name: str = "Test Tenant"
    fetch_default_mode: str = "full"
    fetch_surrounding_chars: int = 120
    services: Any = None
    _search_results: list[Any] | None = None
    _fetch_result: Any | None = None
    _browse_result: Any | None = None
    _enable_browse_tools: bool = False

    def __post_init__(self) -> None:
        if self.services is None:
            self.services = make_service_stub()

    def supports_browse(self) -> bool:
        return self._enable_browse_tools

    async def search(
        self,
        query: str,
        size: int = 10,
        word_match: bool = False,
        include_stats: bool = False,
        include_debug: bool = False,
    ) -> Any:
        """Return configured search results."""
        from docs_mcp_server.utils.models import SearchDocsResponse

        if self._search_results is not None:
            return SearchDocsResponse(results=self._search_results, stats=None)
        return SearchDocsResponse(results=[], stats=None)

    async def fetch(self, uri: str, context: str | None = None) -> Any:
        """Return configured fetch result."""
        from docs_mcp_server.utils.models import FetchDocResponse

        if self._fetch_result is not None:
            return self._fetch_result
        return FetchDocResponse(url=uri, title="Test", content="Test content")

    async def browse_tree(self, path: str = "/", depth: int = 2) -> Any:
        """Return configured browse result."""
        from docs_mcp_server.utils.models import BrowseTreeResponse

        if self._browse_result is not None:
            return self._browse_result
        return BrowseTreeResponse(
            root_path=path or "/",
            depth=depth,
            nodes=[],
        )

    def _extract_surrounding_context(self, content: str, fragment: str, chars: int) -> str:
        return f"{fragment}:{chars}:{content[:8]}"


class FakeRegistry:
    """Lightweight registry covering the interface RootHub requires."""

    def __init__(
        self,
        tenants: dict[str, Any] | None = None,
        metadata: dict[str, TenantMetadata] | None = None,
        filesystem: set[str] | None = None,
    ) -> None:
        self._tenants = tenants or {}
        self._metadata = metadata or {}
        self._filesystem = filesystem or set()

    def list_tenants(self) -> list[TenantMetadata]:
        return list(self._metadata.values())

    def get_metadata(self, codename: str) -> TenantMetadata | None:
        return self._metadata.get(codename)

    def list_codenames(self) -> list[str]:
        return list(self._tenants.keys())

    def get_tenant(self, codename: str) -> Any | None:
        return self._tenants.get(codename)

    def is_filesystem_tenant(self, codename: str) -> bool:
        return codename in self._filesystem

    def __len__(self) -> int:  # pragma: no cover - trivial passthrough
        return len(self._tenants)


class DummyAsyncUoW:
    """Async context manager stub used by service helpers."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False


def make_service_stub(**overrides: Any) -> SimpleNamespace:
    """Create a service namespace with the methods RootHub expects."""

    async def _ensure_search_index_lazy() -> None:
        return None

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    base: dict[str, Any] = {
        "storage_path": Path("/tmp"),
        "ensure_search_index_lazy": _ensure_search_index_lazy,
        "get_search_service": lambda: MagicMock(name="search-service"),
        "get_uow": lambda: DummyAsyncUoW(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def tenant_metadata() -> TenantMetadata:
    return TenantMetadata(
        codename="django",
        display_name="Django",
        description="Official Django docs",
        source_type="filesystem",
        test_queries=["orm", "views"],
        url_prefixes=["https://docs.djangoproject.com"],
        supports_browse=True,
    )


@pytest.mark.unit
class TestRootHubTools:
    """Covers discovery and proxy helpers without spinning up FastMCP."""

    @pytest.mark.asyncio
    async def test_list_tenants_reports_registry_size(self, tenant_metadata: TenantMetadata) -> None:
        registry = FakeRegistry(tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        ctx = RecordingContext()
        result = await mcp.tools["list_tenants"]["func"](ctx=ctx)

        assert result["count"] == 1
        assert result["tenants"][0]["codename"] == "django"
        assert ctx.messages == ["[root-hub] Listing 1 tenants"]

    @pytest.mark.asyncio
    async def test_list_tenants_handles_empty_registry(self) -> None:
        registry = FakeRegistry()
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        result = await mcp.tools["list_tenants"]["func"](ctx=None)

        assert result["count"] == 0
        assert result["tenants"] == []

    @pytest.mark.asyncio
    async def test_describe_tenant_excludes_tool_list(self, tenant_metadata: TenantMetadata) -> None:
        registry = FakeRegistry(tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        ctx = RecordingContext()
        result = await mcp.tools["describe_tenant"]["func"](codename="django", ctx=ctx)

        assert result["codename"] == "django"
        assert "tools" not in result
        assert ctx.messages == ["[root-hub] Describing tenant: django"]

    @pytest.mark.asyncio
    async def test_describe_tenant_handles_missing_entry(self, tenant_metadata: TenantMetadata) -> None:
        registry = FakeRegistry(tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        result = await mcp.tools["describe_tenant"]["func"](codename="missing", ctx=None)

        assert result["error"] == "Tenant 'missing' not found"
        assert result["available_tenants"] == "django"

    @pytest.mark.asyncio
    async def test_root_search_returns_error_for_unknown_tenant(self, tenant_metadata: TenantMetadata) -> None:
        registry = FakeRegistry(tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_search"]["func"](tenant_codename="unknown", query="install")

        assert response.results == []
        assert response.error.startswith("Tenant 'unknown' not found")
        assert response.query == "install"

    @pytest.mark.asyncio
    async def test_root_fetch_reads_local_file_with_context(
        self, tmp_path: Path, tenant_metadata: TenantMetadata
    ) -> None:
        """Verify root_fetch passes through context mode to tenant_app.fetch()."""
        from docs_mcp_server.utils.models import FetchDocResponse

        # Configure FakeTenantApp with expected response
        expected_response = FetchDocResponse(
            url="file:///tmp/doc.md",
            title="doc.md",
            content="section-1:120:# Demo",
            context_mode="surrounding",
        )
        tenant = FakeTenantApp(_fetch_result=expected_response)
        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_fetch"]["func"](
            tenant_codename="django",
            uri="file:///tmp/doc.md#section-1",
            context=None,
        )

        assert response.url == "file:///tmp/doc.md"
        assert response.title == "doc.md"
        assert response.context_mode == "surrounding"
        assert response.content.startswith("section-1:120:")

    @pytest.mark.asyncio
    async def test_root_browse_rejects_non_filesystem_tenant(self, tenant_metadata: TenantMetadata) -> None:
        registry = FakeRegistry(
            tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata}, filesystem=set()
        )
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_browse"]["func"](tenant_codename="django", path="", depth=2)

        # Matches the actual error message from root_hub.py
        assert response.error == "Tenant 'django' does not support browse"
        assert response.nodes == []

    @pytest.mark.asyncio
    async def test_root_browse_lists_directory(self, tenant_metadata: TenantMetadata) -> None:
        """Verify root_browse passes through to tenant_app.browse_tree()."""
        from docs_mcp_server.utils.models import BrowseTreeNode, BrowseTreeResponse

        # Configure FakeTenantApp with expected browse result
        expected_response = BrowseTreeResponse(
            root_path="/",
            depth=3,
            nodes=[
                BrowseTreeNode(
                    name="root",
                    path="/",
                    type="directory",
                    has_children=False,
                )
            ],
        )
        tenant = FakeTenantApp(_browse_result=expected_response, _enable_browse_tools=True)
        registry = FakeRegistry(
            tenants={"django": tenant},
            metadata={"django": tenant_metadata},
            filesystem={"django"},
        )
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_browse"]["func"](tenant_codename="django", path="", depth=3)

        assert response.error is None
        assert response.nodes[0].name == "root"
        assert response.nodes[0].path == "/"
        assert response.nodes[0].type == "directory"
        assert response.root_path == "/"
        assert response.depth == 3

    @pytest.mark.asyncio
    async def test_root_browse_rejects_path_traversal(self, tenant_metadata: TenantMetadata) -> None:
        """Verify root_browse returns error for path traversal attempts."""
        from docs_mcp_server.utils.models import BrowseTreeResponse

        # Configure FakeTenantApp to return an error for path traversal
        error_response = BrowseTreeResponse(
            root_path="../escape",
            depth=2,
            nodes=[],
            error="Path '../escape' escapes the tenant storage root",
        )
        tenant = FakeTenantApp(_browse_result=error_response, _enable_browse_tools=True)
        registry = FakeRegistry(
            tenants={"django": tenant},
            metadata={"django": tenant_metadata},
            filesystem={"django"},
        )
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_browse"]["func"](tenant_codename="django", path="../escape")

        assert response.error is not None
        assert "escapes the tenant storage root" in response.error
        assert response.nodes == []

    @pytest.mark.asyncio
    async def test_root_browse_reports_missing_target(self, tenant_metadata: TenantMetadata) -> None:
        """Verify root_browse returns error for missing paths."""
        from docs_mcp_server.utils.models import BrowseTreeResponse

        # Configure FakeTenantApp to return a "not found" error
        error_response = BrowseTreeResponse(
            root_path="missing/path",
            depth=2,
            nodes=[],
            error="Path 'missing/path' not found",
        )
        tenant = FakeTenantApp(_browse_result=error_response, _enable_browse_tools=True)
        registry = FakeRegistry(
            tenants={"django": tenant},
            metadata={"django": tenant_metadata},
            filesystem={"django"},
        )
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_browse"]["func"](tenant_codename="django", path="missing/path")

        assert "not found" in response.error
        assert response.nodes == []

    @pytest.mark.asyncio
    async def test_root_browse_rejects_file_targets(self, tenant_metadata: TenantMetadata) -> None:
        """Verify root_browse returns error when targeting a file."""
        from docs_mcp_server.utils.models import BrowseTreeResponse

        # Configure FakeTenantApp to return a "not a directory" error
        error_response = BrowseTreeResponse(
            root_path="file.md",
            depth=2,
            nodes=[],
            error="Path 'file.md' is not a directory",
        )
        tenant = FakeTenantApp(_browse_result=error_response, _enable_browse_tools=True)
        registry = FakeRegistry(
            tenants={"django": tenant},
            metadata={"django": tenant_metadata},
            filesystem={"django"},
        )
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_browse"]["func"](tenant_codename="django", path="file.md")

        assert "is not a directory" in response.error
        assert response.nodes == []

    @pytest.mark.asyncio
    async def test_root_search_converts_documents_and_stats(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        """Verify root_search passes through to tenant_app.search()."""
        from docs_mcp_server.utils.models import (
            SearchDocsResponse,
            SearchResult,
            SearchStats as ResponseSearchStats,
        )

        # Configure FakeTenantApp with expected search result
        expected_result = SearchResult(
            url="https://example.com/doc",
            title="Doc",
            score=0.42,
            snippet="snippet",
        )
        expected_stats = ResponseSearchStats(
            stage=2,
            files_found=1,
            matches=1,
            files_searched=1,
            search_time=0.1,
            timed_out=False,
            progress={},  # Required field
        )
        # Configure the FakeTenantApp to return a full SearchDocsResponse
        tenant = FakeTenantApp()

        # Override the search method to return our configured response
        async def configured_search(**kwargs):
            return SearchDocsResponse(results=[expected_result], stats=expected_stats)

        tenant.search = configured_search  # type: ignore[method-assign]

        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_search"]["func"](tenant_codename="django", query="install", include_stats=True)

        assert response.error is None
        assert response.results[0].url == "https://example.com/doc"
        assert response.results[0].score == 0.42
        assert response.stats is not None
        assert response.stats.stage == 2

    @pytest.mark.asyncio
    async def test_root_search_reports_service_errors(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        """Verify root_search handles errors from tenant_app.search()."""
        from docs_mcp_server.utils.models import SearchDocsResponse

        # Configure the FakeTenantApp to return an error response
        tenant = FakeTenantApp()

        async def error_search(**kwargs):
            return SearchDocsResponse(results=[], error="search boom")

        tenant.search = error_search  # type: ignore[method-assign]

        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_search"]["func"](tenant_codename="django", query="install")

        assert response.error is not None
        assert "search boom" in response.error

    @pytest.mark.asyncio
    async def test_root_search_passes_include_debug_flag(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        from docs_mcp_server.utils.models import SearchDocsResponse

        recorded_kwargs: dict[str, Any] = {}

        tenant = FakeTenantApp()

        async def recording_search(**kwargs):
            recorded_kwargs.update(kwargs)
            return SearchDocsResponse(results=[], stats=None)

        tenant.search = recording_search  # type: ignore[method-assign]

        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        await mcp.tools["root_search"]["func"](
            tenant_codename="django",
            query="install",
            include_debug=True,
        )

        assert recorded_kwargs.get("include_debug") is True

    @pytest.mark.asyncio
    async def test_root_fetch_uses_repository_result(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        """Verify root_fetch passes through to tenant_app.fetch()."""
        from docs_mcp_server.utils.models import FetchDocResponse

        # Configure FakeTenantApp with expected fetch result
        expected_response = FetchDocResponse(
            url="https://example.com/doc",
            title="Doc",
            content="# Section\ncontent around Section",
            context_mode="surrounding",
        )
        tenant = FakeTenantApp(_fetch_result=expected_response)

        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_fetch"]["func"](
            tenant_codename="django",
            uri="https://example.com/doc#Section",
            context="surrounding",
        )

        assert response.error is None
        assert response.title == "Doc"
        assert "Section" in response.content

    @pytest.mark.asyncio
    async def test_root_fetch_reports_errors(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        from docs_mcp_server.utils.models import FetchDocResponse

        # Configure FakeTenantApp with an error response
        error_response = FetchDocResponse(
            url="https://example.com/doc",
            title="",
            content="",
            error="fetch boom",
        )
        tenant = FakeTenantApp(_fetch_result=error_response)

        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_fetch"]["func"](tenant_codename="django", uri="https://example.com/doc")

        assert response.error is not None
        assert "fetch boom" in response.error

    @pytest.mark.asyncio
    async def test_root_fetch_reports_missing_file(
        self,
        tmp_path: Path,
        tenant_metadata: TenantMetadata,
    ) -> None:
        from docs_mcp_server.utils.models import FetchDocResponse

        missing_uri = (tmp_path / "missing.md").as_uri()

        # Configure FakeTenantApp with a file not found error
        error_response = FetchDocResponse(
            url=missing_uri,
            title="",
            content="",
            error="File not found: /tmp/missing.md",
        )
        tenant = FakeTenantApp(_fetch_result=error_response)
        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        response = await mcp.tools["root_fetch"]["func"](tenant_codename="django", uri=missing_uri)

        assert response.error is not None
        assert "File not found" in response.error


@pytest.mark.unit
class TestRootHubLifespan:
    """Tests for RootHub lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_root_hub_creates_fastmcp(self, tenant_metadata):
        """Verify create_root_hub creates a FastMCP instance."""
        registry = FakeRegistry(tenants={"django": FakeTenantApp()}, metadata={"django": tenant_metadata})

        # Patch FastMCP to avoid annotation introspection issues
        with patch("docs_mcp_server.root_hub.FastMCP") as mock_fastmcp:
            mock_fastmcp.return_value = MagicMock()

            mcp = root_hub.create_root_hub(registry)

            # Should create a FastMCP instance (mocked)
            assert mcp is not None
            # Verify FastMCP was called with correct name
            mock_fastmcp.assert_called_once()
            call_kwargs = mock_fastmcp.call_args.kwargs
            assert call_kwargs["name"] == "Docs Root Hub"


@pytest.mark.unit
class TestRootHubLogging:
    """Tests for logging in RootHub tools."""

    @pytest.mark.asyncio
    async def test_list_tenants_logs_info(self, tenant_metadata):
        # Provide both metadata (for list_tenants) and tenants (for __len__)
        registry = FakeRegistry(metadata={"django": tenant_metadata}, tenants={"django": FakeTenantApp()})
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        list_tenants = mcp.tools["list_tenants"]["func"]
        ctx = RecordingContext()

        await list_tenants(ctx=ctx)
        assert "[root-hub] Listing 1 tenants" in ctx.messages

    @pytest.mark.asyncio
    async def test_describe_tenant_logs_info(self, tenant_metadata):
        registry = FakeRegistry(metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_discovery_tools(mcp, registry)

        describe_tenant = mcp.tools["describe_tenant"]["func"]
        ctx = RecordingContext()

        await describe_tenant("django", ctx=ctx)
        assert "[root-hub] Describing tenant: django" in ctx.messages

    @pytest.mark.asyncio
    async def test_root_search_logs_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tenant_metadata: TenantMetadata,
    ) -> None:
        tenant = FakeTenantApp()
        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        async def fake_search_documents(**kwargs: Any):
            return [], None

        monkeypatch.setattr(
            "docs_mcp_server.service_layer.services.search_documents_filesystem",
            fake_search_documents,
        )

        root_search = mcp.tools["root_search"]["func"]
        ctx = RecordingContext()

        await root_search("django", "query", ctx=ctx)
        assert "[root-hub] root_search → django: query" in ctx.messages

    @pytest.mark.asyncio
    async def test_root_fetch_logs_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tenant_metadata: TenantMetadata,
    ) -> None:
        tenant = FakeTenantApp()
        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        async def fake_fetch_document(uri, uow):
            return Document(url=URL("http://example.com"), title="title", content=Content(text="content"))

        monkeypatch.setattr("docs_mcp_server.service_layer.services.fetch_document", fake_fetch_document)

        root_fetch = mcp.tools["root_fetch"]["func"]
        ctx = RecordingContext()

        await root_fetch("django", "http://example.com", ctx=ctx)
        assert "[root-hub] root_fetch → django: http://example.com" in ctx.messages

    @pytest.mark.asyncio
    async def test_root_browse_logs_info(
        self,
        tenant_metadata: TenantMetadata,
    ) -> None:
        tenant = FakeTenantApp()
        registry = FakeRegistry(tenants={"django": tenant}, metadata={"django": tenant_metadata}, filesystem={"django"})
        mcp = ToolCaptureMCP()
        root_hub._register_proxy_tools(mcp, registry)

        root_browse = mcp.tools["root_browse"]["func"]
        ctx = RecordingContext()

        await root_browse("django", ctx=ctx)
        assert "[root-hub] root_browse → django: path='', depth=2" in ctx.messages
