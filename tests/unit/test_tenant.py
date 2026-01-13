"""Unit tests for simplified tenant architecture."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.services.scheduler_service import SchedulerService
from docs_mcp_server.tenant import TenantApp, TenantSyncRuntime, create_tenant_app
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
        assert isinstance(app.sync_runtime, TenantSyncRuntime)
        assert isinstance(app.sync_runtime.get_scheduler_service(), SchedulerService)

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
        assert "Fetch error" in result.error

    @pytest.mark.asyncio
    async def test_browse_tree_returns_error_response(self, tenant_config):
        """Test that browse_tree returns error response for non-existent path."""
        app = TenantApp(tenant_config)

        result = await app.browse_tree("/nonexistent", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.root_path == "/nonexistent"
        assert result.depth == 2
        assert result.nodes == []
        assert result.error is not None
        assert "Directory not found" in result.error

    @pytest.mark.asyncio
    async def test_browse_tree_success(self, tenant_config):
        """Test successful browse_tree operation."""
        app = TenantApp(tenant_config)

        # Create some test files and directories
        docs_root = Path(tenant_config.docs_root_dir)
        (docs_root / "subdir").mkdir()
        (docs_root / "test.md").write_text("# Test")
        (docs_root / "subdir" / "nested.md").write_text("# Nested")

        result = await app.browse_tree("", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.root_path == ""
        assert result.depth == 2
        assert result.error is None
        assert len(result.nodes) > 0

        # Check that we have both files and directories
        node_names = [node.name for node in result.nodes]
        assert "subdir" in node_names
        assert "test.md" in node_names

    @pytest.mark.asyncio
    async def test_browse_tree_non_filesystem_tenant(self, tmp_path):
        """Test browse_tree with non-filesystem tenant."""
        config = TenantConfig(
            source_type="online",
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_root_dir=str(tmp_path / "test"),  # Provide a root dir to avoid None
        )
        app = TenantApp(config)

        result = await app.browse_tree("", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.error is not None
        assert "Browse not supported" in result.error

    @pytest.mark.asyncio
    async def test_fetch_local_file_success(self, tenant_config):
        """Test successful local file fetch."""
        app = TenantApp(tenant_config)

        # Create a test file
        docs_root = Path(tenant_config.docs_root_dir)
        test_file = docs_root / "test.md"
        test_content = "# Test Content\n\nThis is a test file."
        test_file.write_text(test_content)

        result = await app.fetch(f"file://{test_file}", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.error is None
        assert result.title == "test"
        assert result.content == test_content
        assert result.context_mode == "full"

    @pytest.mark.asyncio
    async def test_fetch_local_file_not_found(self, tenant_config):
        """Test local file fetch with non-existent file."""
        app = TenantApp(tenant_config)

        result = await app.fetch("file:///nonexistent/file.md", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.error is not None
        assert "File not found" in result.error

    @pytest.mark.asyncio
    async def test_fetch_local_file_surrounding_context(self, tenant_config):
        """Test local file fetch with surrounding context."""
        app = TenantApp(tenant_config)

        # Create a large test file
        docs_root = Path(tenant_config.docs_root_dir)
        test_file = docs_root / "large.md"
        test_content = "# Large Content\n\n" + "This is a very long line. " * 500
        test_file.write_text(test_content)

        result = await app.fetch(f"file://{test_file}", "surrounding")

        assert isinstance(result, FetchDocResponse)
        assert result.error is None
        assert result.title == "large"
        assert len(result.content) <= 8003  # 8000 + "..."
        assert result.content.endswith("...")

    @pytest.mark.asyncio
    async def test_fetch_http_url_success(self, tenant_config):
        """Test successful HTTP URL fetch."""
        app = TenantApp(tenant_config)

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = Mock()
            mock_response.status = 200

            # Create an async mock for text()
            async def mock_text():
                return "<html><title>Test</title><body><main>Content</main></body></html>"

            mock_response.text = mock_text
            mock_get.return_value.__aenter__.return_value = mock_response

            result = await app.fetch("https://example.com/test", "full")

            assert isinstance(result, FetchDocResponse)
            assert result.error is None
            assert result.title == "Test"
            assert "Content" in result.content

    @pytest.mark.asyncio
    async def test_fetch_http_url_error(self, tenant_config):
        """Test HTTP URL fetch with error."""
        app = TenantApp(tenant_config)

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = Mock()
            mock_response.status = 404
            mock_response.reason = "Not Found"
            mock_get.return_value.__aenter__.return_value = mock_response

            result = await app.fetch("https://example.com/notfound", "full")

            assert isinstance(result, FetchDocResponse)
            assert result.error is not None
            assert "HTTP 404" in result.error

    @pytest.mark.asyncio
    async def test_fetch_exception_handling(self, tenant_config):
        """Test fetch with exception handling."""
        app = TenantApp(tenant_config)

        with patch("aiohttp.ClientSession.get", side_effect=Exception("Network error")):
            result = await app.fetch("https://example.com/test", "full")

            assert isinstance(result, FetchDocResponse)
            assert result.error is not None
            assert "Fetch error" in result.error

    @pytest.mark.asyncio
    async def test_build_directory_tree_with_depth(self, tenant_config):
        """Test _build_directory_tree with different depths."""
        app = TenantApp(tenant_config)

        # Create nested directory structure
        docs_root = Path(tenant_config.docs_root_dir)
        (docs_root / "level1").mkdir()
        (docs_root / "level1" / "level2").mkdir()
        (docs_root / "level1" / "level2" / "deep.md").write_text("# Deep")
        (docs_root / "level1" / "file.md").write_text("# File")

        # Test depth 1
        nodes = await app._build_directory_tree(docs_root, docs_root, 1)
        assert len(nodes) == 1
        assert nodes[0].name == "level1"
        assert nodes[0].children is None  # No children at depth 1

        # Test depth 2
        nodes = await app._build_directory_tree(docs_root, docs_root, 2)
        assert len(nodes) == 1
        assert nodes[0].name == "level1"
        assert nodes[0].children is not None
        assert len(nodes[0].children) == 2  # level2 dir and file.md

    @pytest.mark.asyncio
    async def test_build_directory_tree_filters_hidden_files(self, tenant_config):
        """Test that _build_directory_tree filters hidden files and directories."""
        app = TenantApp(tenant_config)

        docs_root = Path(tenant_config.docs_root_dir)
        (docs_root / ".hidden").mkdir()
        (docs_root / "__pycache__").mkdir()
        (docs_root / "visible.md").write_text("# Visible")
        (docs_root / ".hidden_file.md").write_text("# Hidden")

        nodes = await app._build_directory_tree(docs_root, docs_root, 2)

        node_names = [node.name for node in nodes]
        assert "visible.md" in node_names
        assert ".hidden" not in node_names
        assert "__pycache__" not in node_names
        assert ".hidden_file.md" not in node_names

    @pytest.mark.asyncio
    async def test_build_directory_tree_file_types(self, tenant_config):
        """Test that _build_directory_tree only includes documentation files."""
        app = TenantApp(tenant_config)

        docs_root = Path(tenant_config.docs_root_dir)
        (docs_root / "doc.md").write_text("# Doc")
        (docs_root / "text.txt").write_text("Text")
        (docs_root / "readme.rst").write_text("RST")
        (docs_root / "page.html").write_text("<html></html>")
        (docs_root / "script.py").write_text("print('hello')")
        (docs_root / "binary.jpg").write_bytes(b"fake image")

        nodes = await app._build_directory_tree(docs_root, docs_root, 1)

        node_names = [node.name for node in nodes]
        assert "doc.md" in node_names
        assert "text.txt" in node_names
        assert "readme.rst" in node_names
        assert "page.html" in node_names
        assert "script.py" not in node_names
        assert "binary.jpg" not in node_names

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


class TestTenantSyncRuntime:
    """Test tenant sync runtime."""

    def test_init_creates_scheduler_service(self, tmp_path: Path):
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)
        tenant_config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )
        runtime = TenantSyncRuntime(tenant_config)
        assert isinstance(runtime.get_scheduler_service(), SchedulerService)
