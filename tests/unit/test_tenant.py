"""Unit tests for simplified tenant architecture."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.tenant import MockSchedulerService, MockSyncRuntime, TenantApp, create_tenant_app
from docs_mcp_server.utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


@pytest.mark.unit
class TestTenantApp:
    """Test simplified tenant app with direct search index access."""

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
    def tenant_config_with_search_index(self, tmp_path: Path):
        """Create test tenant configuration with search index."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)

        # Create search segments directory and manifest
        search_segments_dir = docs_root / "__search_segments"
        search_segments_dir.mkdir()

        manifest = {"latest_segment_id": "test_segment_123", "segments": ["test_segment_123"]}

        manifest_path = search_segments_dir / "manifest.json"
        with manifest_path.open("w") as f:
            json.dump(manifest, f)

        # Create a dummy database file
        db_path = search_segments_dir / "test_segment_123.db"
        db_path.touch()

        return TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

    def test_tenant_app_creation(self, tenant_config):
        """Test that TenantApp can be created with direct search index."""
        app = TenantApp(tenant_config)
        assert app.codename == "test"
        assert app.docs_name == "Test Docs"
        assert app._search_index is None  # No segments directory exists
        assert isinstance(app.sync_runtime, MockSyncRuntime)

    def test_tenant_app_creation_with_search_index(self, tenant_config_with_search_index):
        """Test TenantApp creation with existing search index."""
        with patch("docs_mcp_server.tenant.SegmentSearchIndex") as mock_index:
            mock_index.return_value = Mock()

            app = TenantApp(tenant_config_with_search_index)
            assert app.codename == "test"
            assert app._search_index is not None
            mock_index.assert_called_once()

    def test_create_search_index_no_segments_dir(self, tenant_config):
        """Test _create_search_index when segments directory doesn't exist."""
        app = TenantApp(tenant_config)
        assert app._search_index is None

    def test_create_search_index_no_manifest(self, tmp_path):
        """Test _create_search_index when manifest doesn't exist."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)

        # Create search segments directory but no manifest
        search_segments_dir = docs_root / "__search_segments"
        search_segments_dir.mkdir()

        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

        app = TenantApp(tenant_config)
        assert app._search_index is None

    def test_create_search_index_no_latest_segment(self, tmp_path):
        """Test _create_search_index when manifest has no latest_segment_id."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)

        # Create search segments directory and empty manifest
        search_segments_dir = docs_root / "__search_segments"
        search_segments_dir.mkdir()

        manifest = {"segments": []}
        manifest_path = search_segments_dir / "manifest.json"
        with manifest_path.open("w") as f:
            json.dump(manifest, f)

        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

        app = TenantApp(tenant_config)
        assert app._search_index is None

    def test_create_search_index_no_database_file(self, tmp_path):
        """Test _create_search_index when database file doesn't exist."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)

        # Create search segments directory and manifest but no database
        search_segments_dir = docs_root / "__search_segments"
        search_segments_dir.mkdir()

        manifest = {"latest_segment_id": "missing_segment"}
        manifest_path = search_segments_dir / "manifest.json"
        with manifest_path.open("w") as f:
            json.dump(manifest, f)

        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

        app = TenantApp(tenant_config)
        assert app._search_index is None

    def test_create_search_index_invalid_manifest(self, tmp_path):
        """Test _create_search_index when manifest is invalid JSON."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)

        # Create search segments directory and invalid manifest
        search_segments_dir = docs_root / "__search_segments"
        search_segments_dir.mkdir()

        manifest_path = search_segments_dir / "manifest.json"
        with manifest_path.open("w") as f:
            f.write("invalid json")

        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

        app = TenantApp(tenant_config)
        assert app._search_index is None

    def test_create_tenant_app_factory(self, tenant_config):
        """Test the factory function."""
        app = create_tenant_app(tenant_config)
        assert isinstance(app, TenantApp)
        assert app.codename == "test"

    @pytest.mark.asyncio
    async def test_initialize_is_noop(self, tenant_config):
        """Test that initialize is a no-op."""
        app = TenantApp(tenant_config)
        await app.initialize()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_closes_search_index(self, tenant_config):
        """Test that shutdown closes the search index."""
        app = TenantApp(tenant_config)

        # Mock the search index
        mock_index = Mock()
        app._search_index = mock_index

        await app.shutdown()
        mock_index.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_search_index(self, tenant_config):
        """Test that shutdown works without search index."""
        app = TenantApp(tenant_config)
        assert app._search_index is None

        await app.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_search_returns_empty_without_index(self, tenant_config):
        """Test that search returns empty response without search index."""
        app = TenantApp(tenant_config)

        result = await app.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert result.error is not None
        assert "No search index available" in result.error
        assert result.query == "test query"

    @pytest.mark.asyncio
    async def test_search_with_index_success(self, tenant_config):
        """Test successful search with search index."""
        app = TenantApp(tenant_config)

        # Mock search index and response
        mock_index = Mock()
        mock_search_response = Mock()
        mock_search_response.results = [
            Mock(
                document_url="http://example.com/doc1",
                document_title="Test Document",
                relevance_score=0.95,
                snippet="Test snippet",
            )
        ]
        mock_index.search.return_value = mock_search_response
        app._search_index = mock_index

        result = await app.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert len(result.results) == 1
        assert result.results[0].url == "http://example.com/doc1"
        assert result.results[0].title == "Test Document"
        assert result.results[0].score == 0.95
        assert result.results[0].snippet == "Test snippet"
        assert result.error is None
        assert result.query == "test query"
        # Note: SearchDocsResponse doesn't have total_results attribute

        mock_index.search.assert_called_once_with("test query", 10)

    @pytest.mark.asyncio
    async def test_search_with_index_exception(self, tenant_config):
        """Test search when index raises exception."""
        app = TenantApp(tenant_config)

        # Mock search index that raises exception
        mock_index = Mock()
        mock_index.search.side_effect = Exception("Search failed")
        app._search_index = mock_index

        result = await app.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert result.error is not None
        assert "Search failed" in result.error
        assert result.query == "test query"

    @pytest.mark.asyncio
    async def test_fetch_returns_error_response(self, tenant_config):
        """Test that fetch returns error response."""
        app = TenantApp(tenant_config)

        result = await app.fetch("test://uri", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.url == "test://uri"
        assert result.title == ""
        assert result.content == ""
        assert result.context_mode == "full"
        assert result.error is not None
        assert "Fetch not implemented" in result.error

    @pytest.mark.asyncio
    async def test_browse_tree_returns_error_response(self, tenant_config):
        """Test that browse_tree returns error response."""
        app = TenantApp(tenant_config)

        result = await app.browse_tree("/path", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.root_path == "/path"
        assert result.depth == 2
        assert result.nodes == []
        assert result.error is not None
        assert "Browse not implemented" in result.error

    def test_get_performance_stats_without_index(self, tenant_config):
        """Test get_performance_stats without search index."""
        app = TenantApp(tenant_config)

        result = app.get_performance_stats()

        assert result["tenant"] == "test"
        assert result["optimization_level"] == "basic"
        assert result["has_search_index"] is False

    def test_get_performance_stats_with_index(self, tenant_config):
        """Test get_performance_stats with search index."""
        app = TenantApp(tenant_config)

        # Mock search index with performance info
        mock_index = Mock()
        mock_index.get_performance_info.return_value = {
            "total_documents": 100,
            "simd_enabled": True,
            "optimization_level": "fully_optimized",
        }
        app._search_index = mock_index

        result = app.get_performance_stats()

        assert result["tenant"] == "test"
        assert result["optimization_level"] == "fully_optimized"  # Updated expectation
        assert result["has_search_index"] is True
        assert result["total_documents"] == 100
        assert result["simd_enabled"] is True

    def test_supports_browse_returns_config_value(self, tenant_config):
        """Test supports_browse returns value from config."""
        app = TenantApp(tenant_config)

        # Test default value
        result = app.supports_browse()
        assert result == tenant_config.supports_browse

    @pytest.mark.asyncio
    async def test_health_returns_status(self, tenant_config):
        """Test health returns status."""
        app = TenantApp(tenant_config)

        result = await app.health()

        assert result["status"] == "healthy"
        assert result["tenant"] == "test"


class TestMockSchedulerService:
    """Test mock scheduler service."""

    def test_init_sets_tenant_codename(self):
        """Test initialization sets tenant codename."""
        service = MockSchedulerService("test_tenant")
        assert service.tenant_codename == "test_tenant"

    @pytest.mark.asyncio
    async def test_get_status_snapshot_returns_mock_data(self):
        """Test get_status_snapshot returns expected mock data."""
        service = MockSchedulerService("test_tenant")

        result = await service.get_status_snapshot()

        assert isinstance(result, dict)
        assert result["scheduler_running"] is False
        assert result["scheduler_initialized"] is False
        assert "stats" in result

        stats = result["stats"]
        assert stats["mode"] == "offline"
        assert stats["refresh_schedule"] is None
        assert stats["storage_doc_count"] == 0
        assert stats["queue_depth"] == 0
        assert stats["metadata_total_urls"] == 0
        assert stats["fallback_attempts"] == 0
        assert stats["fallback_successes"] == 0
        assert stats["fallback_failures"] == 0


class TestMockSyncRuntime:
    """Test mock sync runtime."""

    def test_init_creates_scheduler_service(self):
        """Test initialization creates scheduler service."""
        runtime = MockSyncRuntime("test_tenant")
        assert isinstance(runtime._scheduler_service, MockSchedulerService)
        assert runtime._scheduler_service.tenant_codename == "test_tenant"

    def test_get_scheduler_service_returns_service(self):
        """Test get_scheduler_service returns the scheduler service."""
        runtime = MockSyncRuntime("test_tenant")

        service = runtime.get_scheduler_service()

        assert service is runtime._scheduler_service
        assert isinstance(service, MockSchedulerService)
