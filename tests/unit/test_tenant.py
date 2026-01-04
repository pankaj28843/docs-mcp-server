"""Unit tests for tenant factory and services.

Following Cosmic Python Chapter 7: Aggregates
- Test aggregate roots and bounded contexts
- Use dependency injection for testability
- Mock external dependencies
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.tenant import (
    MANIFEST_POLL_INTERVAL_SECONDS,
    MAX_BROWSE_DEPTH,
    TenantApp,
    TenantServices,
)


@pytest.mark.unit
class TestTenantServices:
    """Test tenant services container."""

    @pytest.fixture
    def tenant_config(self, tmp_path: Path):
        """Create test tenant configuration."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)
        return TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

    @pytest.fixture
    def infra_config(self):
        """Create infrastructure configuration."""
        from docs_mcp_server.deployment_config import SharedInfraConfig

        return SharedInfraConfig(allow_index_builds=True)

    @pytest.fixture
    def tenant_services(self, tenant_config, infra_config):
        """Create tenant services instance."""
        # Attach infrastructure to tenant_config (Context Object pattern)
        tenant_config._infrastructure = infra_config
        return TenantServices(tenant_config)

    def test_initialization(self, tenant_services, tenant_config):
        """Test tenant services initialization."""
        assert tenant_services.tenant_config == tenant_config
        assert tenant_services.storage_path.exists()

    def test_creates_tenant_specific_settings(self, tenant_services, tenant_config):
        """Test that tenant-specific values are accessible from config."""
        # Tenant-specific values are directly accessible
        assert tenant_services.tenant_config.docs_name == tenant_config.docs_name
        assert tenant_services.tenant_config.docs_sitemap_url == tenant_config.docs_sitemap_url

    def test_sync_runtime_receives_fallback_settings(self, tenant_config):
        from docs_mcp_server.deployment_config import SharedInfraConfig

        with patch("docs_mcp_server.config.httpx.head", return_value=SimpleNamespace(status_code=200)):
            infra_config = SharedInfraConfig(
                article_extractor_fallback={
                    "enabled": True,
                    "endpoint": "http://10.20.30.1:13005/",
                    "timeout_seconds": 15,
                }
            )
            tenant_config._infrastructure = infra_config

            services = TenantServices(tenant_config)

            scheduler_settings = services.sync_runtime._scheduler_settings
            assert scheduler_settings.fallback_extractor_enabled is True
            assert scheduler_settings.fallback_extractor_endpoint == "http://10.20.30.1:13005/"

    def test_docs_sync_enabled_only_for_online_with_schedule(self, infra_config, tmp_path: Path):
        """Ensure docs_sync_enabled toggles based on source type + schedule."""
        online_config = TenantConfig(
            source_type="online",
            codename="online",
            docs_name="Online Docs",
            docs_sitemap_url="https://example.com/online.xml",
            docs_entry_url="https://example.com/online/",
            refresh_schedule="0 0 * * *",
        )
        online_config._infrastructure = infra_config
        online_services = TenantServices(online_config)
        assert online_services.tenant_config.docs_sync_enabled is True

        fs_root = tmp_path / "fsdocs"
        fs_root.mkdir()
        filesystem_config = TenantConfig(
            source_type="filesystem",
            codename="fsdocs",
            docs_name="FS Docs",
            docs_root_dir=str(fs_root),
            refresh_schedule="0 0 * * *",
        )
        filesystem_config._infrastructure = infra_config
        filesystem_services = TenantServices(filesystem_config)
        assert filesystem_services.tenant_config.docs_sync_enabled is False

    def test_storage_path_is_always_absolute(self, infra_config, tmp_path: Path, monkeypatch):
        """Relative docs_root_dir values should be normalized before use."""

        monkeypatch.chdir(tmp_path)
        relative_root = Path("relative/docs")
        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="rel",
            docs_name="Relative Docs",
            docs_root_dir=str(relative_root),
        )
        tenant_config._infrastructure = infra_config

        services = TenantServices(tenant_config)

        assert services.storage_path.is_absolute()
        assert str(services.storage_path).endswith(str(relative_root))

    @pytest.mark.unit
    def test_cleanup_orphaned_staging_dirs_handles_exceptions(self, tenant_config, infra_config, monkeypatch):
        """Cleanup of orphaned staging dirs should log warnings but not fail initialization."""
        from unittest.mock import Mock

        # Mock cleanup function to raise exception
        mock_cleanup = Mock(side_effect=RuntimeError("cleanup failed"))
        monkeypatch.setattr("docs_mcp_server.tenant.cleanup_orphaned_staging_dirs", mock_cleanup)

        # Should not raise exception during initialization
        tenant_config._infrastructure = infra_config
        services = TenantServices(tenant_config)
        assert services is not None

        # Cleanup should have been called
        mock_cleanup.assert_called_once()

    def test_get_search_service_lazy_initialization(self, tenant_services):
        """Test search service is created lazily."""
        assert tenant_services.index_runtime._search_service is None

        search_service = tenant_services.get_search_service()

        assert search_service is not None
        assert tenant_services.index_runtime._search_service is search_service

    def test_get_search_service_returns_same_instance(self, tenant_services):
        """Test search service returns same instance on multiple calls."""
        search_service1 = tenant_services.get_search_service()
        search_service2 = tenant_services.get_search_service()

        assert search_service1 is search_service2

    def test_invalidate_search_cache_does_not_instantiate_service(self, tenant_services):
        assert tenant_services.index_runtime._search_service is None

        tenant_services.invalidate_search_cache()

        assert tenant_services.index_runtime._search_service is None

    @pytest.mark.asyncio
    async def test_ensure_search_index_lazy_raises_when_builds_disabled(self, tenant_config):
        from docs_mcp_server.deployment_config import SharedInfraConfig

        infra_config = SharedInfraConfig(allow_index_builds=False)
        tenant_config._infrastructure = infra_config
        services = TenantServices(tenant_config)

        with pytest.raises(RuntimeError, match="build indices"):
            await services.ensure_search_index_lazy()

    @pytest.mark.asyncio
    async def test_build_search_index_refuses_when_builds_disabled(self, tenant_config):
        from docs_mcp_server.deployment_config import SharedInfraConfig

        infra_config = SharedInfraConfig(allow_index_builds=False)
        tenant_config._infrastructure = infra_config
        services = TenantServices(tenant_config)

        with pytest.raises(RuntimeError, match="build"):
            await services.build_search_index()

    @pytest.mark.asyncio
    async def test_ensure_index_resident_warms_and_starts_watch(self, tenant_services, monkeypatch):
        ensure_resident = AsyncMock()
        search_service = Mock()
        search_service.ensure_resident = ensure_resident
        monkeypatch.setattr(tenant_services.index_runtime, "get_search_service", Mock(return_value=search_service))
        ensure_lazy = AsyncMock(return_value=True)
        monkeypatch.setattr(tenant_services.index_runtime, "ensure_search_index_lazy", ensure_lazy)

        await tenant_services.ensure_index_resident()

        ensure_lazy.assert_awaited()
        ensure_resident.assert_awaited_once_with(
            tenant_services.storage_path,
            poll_interval=MANIFEST_POLL_INTERVAL_SECONDS,
        )
        assert tenant_services.index_runtime._index_resident is True

    @pytest.mark.asyncio
    async def test_ensure_index_resident_skipped_when_residency_disabled(
        self,
        tenant_config,
        infra_config,
        monkeypatch,
    ) -> None:
        tenant_config._infrastructure = infra_config
        services = TenantServices(tenant_config, enable_residency=False)
        ensure_lazy = AsyncMock()
        monkeypatch.setattr(services.index_runtime, "ensure_search_index_lazy", ensure_lazy)
        get_service = Mock()
        monkeypatch.setattr(services.index_runtime, "get_search_service", get_service)

        await services.ensure_index_resident()

        ensure_lazy.assert_not_called()
        get_service.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_search_index_lazy_schedules_background_refresh(self, tenant_services, monkeypatch):
        """Existing indexes should trigger non-blocking background rebuild on first search."""

        monkeypatch.setattr(tenant_services.index_runtime, "has_search_index", Mock(return_value=True))
        build_mock = AsyncMock(return_value=(1, 0))
        monkeypatch.setattr(tenant_services.index_runtime, "build_search_index", build_mock)

        ready = await tenant_services.ensure_search_index_lazy()

        assert ready is True
        task = tenant_services.index_runtime._background_index_task
        assert task is not None

        # Allow background task to complete and confirm rebuild happened
        await task
        build_mock.assert_awaited()
        assert tenant_services.index_runtime._background_index_completed is True

    def test_get_scheduler_service_lazy_initialization(self, tenant_services):
        """Test scheduler service is created lazily."""
        assert tenant_services.sync_runtime._scheduler_service is None

        scheduler_service = tenant_services.get_scheduler_service()

        assert scheduler_service is not None
        assert tenant_services.sync_runtime._scheduler_service is scheduler_service

    def test_get_scheduler_service_returns_same_instance(self, tenant_services):
        """Test scheduler service returns same instance on multiple calls."""
        scheduler_service1 = tenant_services.get_scheduler_service()
        scheduler_service2 = tenant_services.get_scheduler_service()

        assert scheduler_service1 is scheduler_service2

    def test_get_uow_creates_new_instance(self, tenant_services):
        """Test that get_uow creates a new instance each time."""
        uow1 = tenant_services.get_uow()
        uow2 = tenant_services.get_uow()
        assert uow1 is not uow2

    @pytest.mark.asyncio
    async def test_shutdown_cancels_background_tasks_and_drops_cache(self, tenant_services, monkeypatch):
        tenant_services.index_runtime._background_index_task = asyncio.create_task(asyncio.sleep(10))
        search_service = Mock()
        search_service.stop_resident = AsyncMock()
        tenant_services.index_runtime._search_service = search_service

        await tenant_services.shutdown()

        assert tenant_services.index_runtime._background_index_task is None
        search_service.stop_resident.assert_awaited_once_with(tenant_services.storage_path)
        search_service.invalidate_cache.assert_called_once_with(tenant_services.storage_path)


@pytest.mark.unit
class TestTenantApp:
    """Test TenantApp facade."""

    @pytest.fixture
    def tenant_config(self, tmp_path: Path) -> TenantConfig:
        """Create test tenant configuration."""
        docs_root = tmp_path / "mcp-data" / "django"
        docs_root.mkdir(parents=True)
        return TenantConfig(
            source_type="filesystem",
            codename="django",
            docs_name="Django Documentation",
            docs_root_dir=str(docs_root),
        )

    @pytest.fixture
    def online_config(self, tmp_path: Path) -> TenantConfig:
        """Create online tenant configuration."""
        docs_root = tmp_path / "mcp-data" / "online"
        docs_root.mkdir(parents=True)
        return TenantConfig(
            source_type="online",
            codename="online-tenant",
            docs_name="Online Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            docs_root_dir=str(docs_root),
        )

    @pytest.fixture
    def infra_config(self):
        """Create infrastructure configuration."""
        from docs_mcp_server.deployment_config import SharedInfraConfig

        return SharedInfraConfig(allow_index_builds=True)

    @pytest.fixture
    def tenant_app(self, tenant_config: TenantConfig, infra_config) -> TenantApp:
        """Create tenant application instance."""
        tenant_config._infrastructure = infra_config
        return TenantApp(tenant_config)

    # -- Initialization Tests --

    def test_initialization(self, tenant_app: TenantApp, tenant_config: TenantConfig) -> None:
        """Test tenant app initialization."""
        assert tenant_app.tenant_config == tenant_config
        assert tenant_app.codename == tenant_config.codename
        assert tenant_app.docs_name == tenant_config.docs_name
        assert tenant_app.services is not None
        assert tenant_app._initialized is False

    @pytest.mark.asyncio
    async def test_initialize_sets_flag(self, tenant_app: TenantApp, monkeypatch) -> None:
        """Test that initialize() sets the _initialized flag."""
        ensure_resident = AsyncMock()
        tenant_app.index_runtime.ensure_index_resident = ensure_resident  # type: ignore[assignment]
        assert tenant_app._initialized is False
        await tenant_app.initialize()
        assert tenant_app._initialized is True
        ensure_resident.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, tenant_app: TenantApp, monkeypatch) -> None:
        """Test that initialize() is idempotent."""
        ensure_resident = AsyncMock()
        tenant_app.index_runtime.ensure_index_resident = ensure_resident  # type: ignore[assignment]
        await tenant_app.initialize()
        await tenant_app.initialize()  # Should not fail
        assert tenant_app._initialized is True
        ensure_resident.assert_not_called()

    @pytest.mark.asyncio
    async def test_shutdown_delegates_to_services(self, tenant_app: TenantApp, monkeypatch) -> None:
        shutdown_mock = AsyncMock()
        tenant_app.services.shutdown = shutdown_mock  # type: ignore[assignment]

        await tenant_app.shutdown()

        shutdown_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_resident_runs_once(self, tenant_app: TenantApp) -> None:
        async def _mark_ready() -> None:
            tenant_app.index_runtime._index_resident = True

        tenant_app.index_runtime._index_resident = False
        ensure_resident = AsyncMock(side_effect=_mark_ready)
        tenant_app.index_runtime.ensure_index_resident = ensure_resident  # type: ignore[assignment]

        await tenant_app.ensure_resident()
        await tenant_app.ensure_resident()

        ensure_resident.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_resident_serializes_concurrent_calls(self, tenant_app: TenantApp) -> None:
        async def _mark_ready() -> None:
            tenant_app.index_runtime._index_resident = True

        tenant_app.index_runtime._index_resident = False
        ensure_resident = AsyncMock(side_effect=_mark_ready)
        tenant_app.index_runtime.ensure_index_resident = ensure_resident  # type: ignore[assignment]

        await asyncio.gather(*(tenant_app.ensure_resident() for _ in range(3)))

        ensure_resident.assert_awaited_once()

    # -- Health Tests --

    @pytest.mark.asyncio
    async def test_health_returns_healthy_status(self, tenant_app: TenantApp) -> None:
        """Test health() returns healthy status."""
        health = await tenant_app.health()
        assert health["status"] == "healthy"
        assert health["tenant"] == tenant_app.codename
        assert health["name"] == tenant_app.docs_name
        assert "documents" in health
        assert health["source_type"] == "filesystem"

    @pytest.mark.asyncio
    async def test_health_returns_unhealthy_on_error(self, tenant_config: TenantConfig, infra_config) -> None:
        """Test health() returns unhealthy status on error."""
        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)

        # Mock the UoW to raise an exception
        with patch.object(tenant_app.storage, "get_uow") as mock_uow:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("Database error"))
            mock_uow.return_value = mock_ctx

            health = await tenant_app.health()
            assert health["status"] == "unhealthy"
            assert "error" in health
            assert "Database error" in health["error"]

    # -- Supports Browse Tests --

    def test_supports_browse_filesystem_tenant(self, tenant_app: TenantApp) -> None:
        """Test that filesystem tenants support browse."""
        assert tenant_app.supports_browse() is True

    def test_supports_browse_online_tenant(self, online_config: TenantConfig, infra_config) -> None:
        """Test that online tenants don't support browse."""
        online_config._infrastructure = infra_config
        tenant_app = TenantApp(online_config)
        assert tenant_app.supports_browse() is False

    # -- Browse Tree Tests --

    @pytest.mark.asyncio
    async def test_browse_tree_returns_empty_for_missing_path(self, tenant_app: TenantApp) -> None:
        """Test browse_tree() returns empty response for missing path."""
        result = await tenant_app.browse_tree(path="/nonexistent", depth=2)
        assert result.root_path is not None
        assert result.nodes == []

    @pytest.mark.asyncio
    async def test_browse_tree_lists_files(self, tenant_config: TenantConfig, infra_config, tmp_path: Path) -> None:
        """Test browse_tree() lists files in a directory."""
        docs_root = Path(tenant_config.docs_root_dir)
        (docs_root / "file1.md").write_text("# File 1")
        (docs_root / "file2.md").write_text("# File 2")
        (docs_root / "subdir").mkdir()
        (docs_root / "subdir" / "nested.md").write_text("# Nested")

        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)
        result = await tenant_app.browse_tree(path="/", depth=2)

        assert result.root_path is not None
        assert len(result.nodes) >= 2

        # Check we have both files
        names = [node.name for node in result.nodes]
        assert "file1.md" in names
        assert "file2.md" in names

    @pytest.mark.asyncio
    async def test_browse_tree_enforces_max_depth(self, tenant_config: TenantConfig, infra_config) -> None:
        """Test browse_tree() enforces MAX_BROWSE_DEPTH."""
        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)

        # Request depth > MAX_BROWSE_DEPTH should be clamped
        result = await tenant_app.browse_tree(path="/", depth=MAX_BROWSE_DEPTH + 10)

        # Should not raise, just clamp depth
        assert result.root_path is not None

    # -- Fetch Tests --

    @pytest.mark.asyncio
    async def test_fetch_file_url(self, tenant_config: TenantConfig, infra_config) -> None:
        """Test fetch() handles file:// URLs."""
        docs_root = Path(tenant_config.docs_root_dir)
        test_file = docs_root / "test.md"
        test_file.write_text("# Test Content\n\nSome body text.")

        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)
        result = await tenant_app.fetch(f"file://{test_file}", context=None)

        assert result.error is None
        assert result.title == "test.md"
        assert "Test Content" in result.content

    @pytest.mark.asyncio
    async def test_fetch_file_not_found(self, tenant_config: TenantConfig, infra_config) -> None:
        """Test fetch() returns error for missing file."""
        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)
        result = await tenant_app.fetch("file:///nonexistent/path.md", context=None)

        assert result.error is not None
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_fetch_surrounding_context(self, tenant_config: TenantConfig, infra_config) -> None:
        """Test fetch() with surrounding context mode."""
        docs_root = Path(tenant_config.docs_root_dir)
        test_file = docs_root / "test.md"
        test_file.write_text(
            "# Intro\n\n## Target Section\n\nTarget content here.\n\n## Other Section\n\nMore content."
        )

        tenant_config._infrastructure = infra_config
        tenant_app = TenantApp(tenant_config)
        result = await tenant_app.fetch(f"file://{test_file}#Target-Section", context="surrounding")

        assert result.error is None
        assert "Target Section" in result.content

    # -- Search Tests --

    @pytest.mark.asyncio
    async def test_search_returns_response(self, tenant_app: TenantApp, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test search() returns a SearchDocsResponse."""
        # Mock the search service
        mock_search = AsyncMock(return_value=([], None))
        monkeypatch.setattr(
            "docs_mcp_server.tenant.svc.search_documents_filesystem",
            mock_search,
        )
        monkeypatch.setattr(tenant_app.index_runtime, "ensure_search_index_lazy", AsyncMock(return_value=True))
        monkeypatch.setattr(tenant_app, "ensure_resident", AsyncMock())
        monkeypatch.setattr(tenant_app.index_runtime, "get_search_service", Mock())

        result = await tenant_app.search(
            query="test query",
            size=10,
            word_match=False,
            include_stats=False,
        )

        assert result.results is not None
        assert isinstance(result.results, list)

    @pytest.mark.asyncio
    async def test_search_handles_error(self, tenant_app: TenantApp, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test search() handles errors gracefully."""
        monkeypatch.setattr(
            tenant_app.index_runtime,
            "ensure_search_index_lazy",
            AsyncMock(side_effect=RuntimeError("Index error")),
        )

        result = await tenant_app.search(
            query="test query",
            size=10,
            word_match=False,
            include_stats=False,
        )

        assert result.error is not None
        assert "Index error" in result.error

    # -- Extract Surrounding Context Tests (static method) --

    def test_extract_surrounding_context_for_markdown(self) -> None:
        """Markdown headings should be located and trimmed with ellipses."""
        content = "# Intro\n\n## Usage\nThis section explains usage in detail.\n\nNext"
        snippet = TenantApp._extract_surrounding_context(content, "Usage", chars=10)

        assert "## Usage" in snippet
        assert snippet.startswith("# Intro")
        assert snippet.endswith("\n...")

    def test_extract_surrounding_context_handles_custom_anchor(self) -> None:
        """{#anchor} markers should be resolved."""
        content = "Intro\n## Details {#custom-anchor}\nBody text here"
        snippet = TenantApp._extract_surrounding_context(content, "custom-anchor", chars=5)

        assert "{#custom-anchor}" in snippet
        assert snippet.startswith("...\n")

    def test_extract_surrounding_context_handles_html_id(self) -> None:
        """HTML id attributes should be matched."""
        content = '<h2 id="heading-anchor">Heading</h2>\n<p>Data</p>'
        snippet = TenantApp._extract_surrounding_context(content, "heading-anchor", chars=3)

        assert "heading-anchor" in snippet
        assert snippet.endswith("\n...")

    def test_extract_surrounding_context_missing_fragment_returns_full(self) -> None:
        """Missing fragments should return the original content."""
        content = "# Title\nBody copy"
        assert TenantApp._extract_surrounding_context(content, "") == content
        assert TenantApp._extract_surrounding_context(content, "absent") == content

    # -- Tenant Isolation Tests --

    def test_multiple_tenants_are_isolated(self, infra_config, tmp_path: Path) -> None:
        """Test that multiple tenant instances are isolated."""
        root1 = tmp_path / "django"
        root1.mkdir()
        root2 = tmp_path / "fastapi"
        root2.mkdir()

        tenant1_config = TenantConfig(
            source_type="filesystem",
            codename="django",
            docs_name="Django",
            docs_root_dir=str(root1),
        )

        tenant2_config = TenantConfig(
            source_type="filesystem",
            codename="fastapi",
            docs_name="FastAPI",
            docs_root_dir=str(root2),
        )

        tenant1_config._infrastructure = infra_config
        tenant2_config._infrastructure = infra_config
        tenant1 = TenantApp(tenant1_config)
        tenant2 = TenantApp(tenant2_config)

        # Services should be different instances
        assert tenant1.services is not tenant2.services
        assert tenant1.codename != tenant2.codename
        assert tenant1.docs_name != tenant2.docs_name
