"""Unit tests for DocumentationSearchEngine - Deep Module Implementation."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.documentation_search_engine import DocumentationSearchEngine, create_documentation_search_engine
from docs_mcp_server.domain.search import MatchTrace, SearchResult
from docs_mcp_server.utils.models import BrowseTreeResponse, FetchDocResponse, SearchDocsResponse


@pytest.mark.unit
class TestDocumentationSearchEngine:
    """Test DocumentationSearchEngine deep module implementation."""

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
    def search_engine(self, tenant_config):
        """Create DocumentationSearchEngine instance."""
        return DocumentationSearchEngine(tenant_config)

    def test_initialization(self, tenant_config):
        """Test DocumentationSearchEngine initialization."""
        engine = DocumentationSearchEngine(tenant_config)

        assert engine.codename == "test"
        assert engine.docs_name == "Test Docs"
        assert engine._config == tenant_config
        assert engine._data_path.name == "test"
        assert engine._optimization_level == "none"  # No search index available

    def test_factory_function(self, tenant_config):
        """Test factory function for creating documentation search engines."""
        engine = create_documentation_search_engine(tenant_config)

        assert isinstance(engine, DocumentationSearchEngine)
        assert engine.codename == "test"

    @patch("docs_mcp_server.documentation_search_engine.OptimizedDocumentIndex")
    def test_create_optimized_document_index_success(self, mock_index_class, tenant_config, tmp_path):
        """Test successful creation of optimized document index."""
        # Create search database file in the correct location
        data_path = tmp_path / "mcp-data" / "test" / "__search_segments"
        data_path.mkdir(parents=True, exist_ok=True)

        # Create manifest with latest_segment_id
        manifest_path = data_path / "manifest.json"
        manifest_path.write_text('{"latest_segment_id": "test_segment"}')

        # Create the corresponding database file
        db_path = data_path / "test_segment.db"
        db_path.touch()

        mock_index = Mock()
        mock_index_class.return_value = mock_index

        engine = DocumentationSearchEngine(tenant_config)

        # The engine should have created an index
        assert engine._document_index is not None
        assert engine._optimization_level == "basic"

    def test_create_optimized_document_index_missing_db(self, tenant_config):
        """Test handling of missing search database."""
        engine = DocumentationSearchEngine(tenant_config)

        # No search database exists, so no index should be created
        assert engine._document_index is None
        assert engine._optimization_level == "none"

    @patch("docs_mcp_server.documentation_search_engine.OptimizedDocumentIndex")
    def test_create_optimized_document_index_exception(self, mock_index_class, tenant_config, tmp_path):
        """Test handling of exception during index creation."""
        # Create search database file in the correct location
        data_path = tmp_path / "data" / "test" / "__search_segments"
        search_db_path = data_path / "search.db"
        search_db_path.parent.mkdir(parents=True, exist_ok=True)
        search_db_path.touch()

        mock_index_class.side_effect = Exception("Index creation failed")

        # Patch the Path constructor to return our test path
        with patch("docs_mcp_server.documentation_search_engine.Path") as mock_path:
            mock_path.return_value = data_path.parent
            engine = DocumentationSearchEngine(tenant_config)

            # Exception should be handled gracefully
            assert engine._document_index is None
            assert engine._optimization_level == "none"

    def test_search_documents_no_index(self, search_engine):
        """Test search when no index is available."""
        result = search_engine.search_documents("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert result.error == "No search index available for test"
        assert result.query == "test query"

    @patch("docs_mcp_server.documentation_search_engine.time.perf_counter")
    @patch("docs_mcp_server.documentation_search_engine.get_metrics_collector")
    @patch("docs_mcp_server.documentation_search_engine.record_search_metrics")
    def test_search_documents_with_index_success(
        self, mock_record_metrics, mock_get_collector, mock_perf_counter, search_engine
    ):
        """Test successful search with index."""
        # Mock timing
        mock_perf_counter.side_effect = [0.0, 0.1]  # 100ms search

        # Mock metrics collector
        mock_collector = Mock()
        mock_get_collector.return_value = mock_collector

        # Mock document index
        mock_index = Mock()

        # Create a proper result object that will pass validation
        mock_result = SearchResult(
            document_url="http://test.com/doc1",
            document_title="Doc 1",
            relevance_score=0.9,
            snippet="Test snippet",
            match_trace=MatchTrace(
                stage=1, stage_name="basic_search", query_variant="test", match_reason="keyword_match"
            ),
        )

        mock_search_response = Mock()
        mock_search_response.results = [mock_result]

        mock_index.search.return_value = mock_search_response
        search_engine._document_index = mock_index
        search_engine._optimization_level = "basic"

        result = search_engine.search_documents("test query", 10, False)

        # Verify search was called
        mock_index.search.assert_called_once_with("test query", 10)

        # Verify result structure
        assert isinstance(result, SearchDocsResponse)
        assert len(result.results) == 1
        assert result.results[0].url == "http://test.com/doc1"
        assert result.results[0].title == "Doc 1"
        assert result.results[0].score == 0.9
        assert result.results[0].snippet == "Test snippet"
        assert result.query == "test query"
        assert len(result.results) == 1

        # Verify metrics were recorded
        mock_record_metrics.assert_called_once_with(100.0, memory_mb=0.0, result_count=1, query_tokens=2)

    def test_search_documents_with_index_exception(self, search_engine):
        """Test search when index raises exception."""
        # Mock document index that raises exception
        mock_index = Mock()
        mock_index.search.side_effect = Exception("Search failed")
        search_engine._document_index = mock_index

        result = search_engine.search_documents("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert "Search failed: Search failed" in result.error
        assert result.query == "test query"

    def test_fetch_document_content_with_fetch_support(self, search_engine):
        """Test fetch when index supports content fetching."""
        # Mock document index with fetch_content method
        mock_index = Mock()
        mock_content = {"title": "Test Document", "content": "Test content"}
        mock_index.fetch_content.return_value = mock_content
        search_engine._document_index = mock_index

        result = search_engine.fetch_document_content("http://test.com/doc#fragment", "full")

        # Verify fragment was removed from URI
        mock_index.fetch_content.assert_called_once_with("http://test.com/doc", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.title == "Test Document"
        assert result.content == "Test content"
        assert result.url == "http://test.com/doc#fragment"

    def test_fetch_document_content_fallback(self, search_engine):
        """Test fetch fallback when index doesn't support fetching."""
        # Mock document index without fetch_content method
        mock_index = Mock()
        del mock_index.fetch_content  # Remove the method
        search_engine._document_index = mock_index

        result = search_engine.fetch_document_content("http://test.com/doc", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.title == "Document"
        assert "Content retrieval not available" in result.content
        assert result.url == "http://test.com/doc"

    def test_fetch_document_content_exception(self, search_engine):
        """Test fetch when exception occurs."""
        # Mock document index that raises exception
        mock_index = Mock()
        mock_index.fetch_content.side_effect = Exception("Fetch failed")
        search_engine._document_index = mock_index

        result = search_engine.fetch_document_content("http://test.com/doc", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.title == "Error"
        assert "Failed to fetch document: Fetch failed" in result.content
        assert result.url == "http://test.com/doc"

    def test_browse_document_tree_not_supported(self, tmp_path):
        """Test browse when not supported by configuration."""
        # Create online tenant config (doesn't support browsing)
        tenant_config = TenantConfig(
            source_type="online",
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url=["https://example.com/sitemap.xml"],
            docs_root_dir=str(tmp_path),  # Add required field
        )
        search_engine = DocumentationSearchEngine(tenant_config)

        result = search_engine.browse_document_tree("/path", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.nodes == []
        assert "Browsing not supported" in result.error

    def test_browse_document_tree_with_support(self, search_engine):
        """Test browse when index supports tree browsing."""
        # Mock document index with browse_tree method
        mock_index = Mock()
        mock_tree = [
            {"name": "file1.md", "path": "/path/file1.md", "type": "file"},
            {"name": "file2.md", "path": "/path/file2.md", "type": "file"},
        ]
        mock_index.browse_tree.return_value = mock_tree
        search_engine._document_index = mock_index

        result = search_engine.browse_document_tree("/path", 2)

        mock_index.browse_tree.assert_called_once_with("/path", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert len(result.nodes) == 2
        assert result.nodes[0].name == "file1.md"
        assert result.nodes[0].path == "/path/file1.md"
        assert result.nodes[0].type == "file"
        assert result.nodes[1].name == "file2.md"
        assert result.nodes[1].path == "/path/file2.md"
        assert result.nodes[1].type == "file"
        assert result.error is None

    def test_browse_document_tree_no_implementation(self, search_engine):
        """Test browse when index doesn't support browsing."""
        # Mock document index without browse_tree method
        mock_index = Mock()
        del mock_index.browse_tree  # Remove the method
        search_engine._document_index = mock_index

        result = search_engine.browse_document_tree("/path", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.nodes == []
        assert "Tree browsing not implemented" in result.error

    def test_browse_document_tree_exception(self, search_engine):
        """Test browse when exception occurs."""
        # Mock document index that raises exception
        mock_index = Mock()
        mock_index.browse_tree.side_effect = Exception("Browse failed")
        search_engine._document_index = mock_index

        result = search_engine.browse_document_tree("/path", 2)

        assert isinstance(result, BrowseTreeResponse)
        assert result.nodes == []
        assert "Browse failed: Browse failed" in result.error

    def test_get_performance_metrics_no_index(self, search_engine):
        """Test performance metrics when no index is available."""
        result = search_engine.get_performance_metrics()

        expected = {
            "codename": "test",
            "optimization_level": "none",
            "index_available": False,
            "supports_browse": True,
        }
        assert result == expected

    def test_get_performance_metrics_with_index(self, search_engine):
        """Test performance metrics when index is available."""
        # Mock document index with get_metrics method
        mock_index = Mock()
        mock_metrics = {"documents_indexed": 100, "index_size_mb": 5.2}
        mock_index.get_metrics.return_value = mock_metrics
        search_engine._document_index = mock_index
        search_engine._optimization_level = "basic"

        result = search_engine.get_performance_metrics()

        expected = {
            "codename": "test",
            "optimization_level": "basic",
            "index_available": True,
            "supports_browse": True,
            "documents_indexed": 100,
            "index_size_mb": 5.2,
        }
        assert result == expected

    def test_get_performance_metrics_index_no_metrics(self, search_engine):
        """Test performance metrics when index doesn't support metrics."""
        # Mock document index without get_metrics method
        mock_index = Mock()
        del mock_index.get_metrics  # Remove the method
        search_engine._document_index = mock_index
        search_engine._optimization_level = "basic"

        result = search_engine.get_performance_metrics()

        expected = {
            "codename": "test",
            "optimization_level": "basic",
            "index_available": True,
            "supports_browse": True,
        }
        assert result == expected

    def test_close_with_index(self, search_engine):
        """Test close when index supports closing."""
        # Mock document index with close method
        mock_index = Mock()
        search_engine._document_index = mock_index

        search_engine.close()

        mock_index.close.assert_called_once()

    def test_close_no_index(self, search_engine):
        """Test close when no index is available."""
        # Should not raise exception
        search_engine.close()

    def test_close_index_no_close_method(self, search_engine):
        """Test close when index doesn't support closing."""
        # Mock document index without close method
        mock_index = Mock()
        del mock_index.close  # Remove the method
        search_engine._document_index = mock_index

        # Should not raise exception
        search_engine.close()

    def test_detect_optimization_level_no_index(self, search_engine):
        """Test optimization level detection when no index."""
        assert search_engine._detect_optimization_level() == "none"

    def test_detect_optimization_level_with_index(self, search_engine):
        """Test optimization level detection with index."""
        mock_index = Mock()
        search_engine._document_index = mock_index

        assert search_engine._detect_optimization_level() == "basic"

    def test_fetch_content_fallback_method(self, search_engine):
        """Test the fallback content retrieval method."""
        result = search_engine._fetch_content_fallback("http://test.com/doc", "full")

        assert isinstance(result, FetchDocResponse)
        assert result.title == "Document"
        assert "Content retrieval not available" in result.content
        assert result.url == "http://test.com/doc"
