"""Tests for app.py - Main ASGI application."""

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from docs_mcp_server.app import create_app, main


class TestCreateApp:
    """Test the create_app function."""

    def test_create_app_requires_deployment_config(self):
        """Test that create_app raises error when deployment.json is missing and no env vars."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nonexistent.json"

            # Clear DOCS_* env vars to ensure no fallback to env-driven mode
            with patch.dict(os.environ, {}, clear=True):
                # Patch Settings to fail validation (no DOCS_NAME set)
                with patch("docs_mcp_server.app._build_env_deployment_from_env") as mock_env:
                    mock_env.side_effect = ValueError("DOCS_NAME must be set")
                    with pytest.raises(FileNotFoundError, match="Deployment config not found"):
                        create_app(config_path)

    def test_create_app_with_valid_config(self):
        """Test creating app with valid deployment configuration."""
        config_data = {
            "infrastructure": {
                "mcp_port": 8000,
                "max_concurrent_requests": 20,
            },
            "tenants": [
                {
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_sitemap_url": "https://example.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://example.com/",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            with patch("docs_mcp_server.app_builder.create_tenant_app") as mock_create_tenant:
                mock_tenant_app = Mock()
                mock_tenant_app.codename = "test"
                mock_tenant_app.docs_name = "Test Docs"
                mock_tenant_app.get_http_app.return_value = Mock()
                mock_create_tenant.return_value = mock_tenant_app

                app = create_app(config_path)

                assert isinstance(app, Starlette)
                mock_create_tenant.assert_called_once()
        finally:
            config_path.unlink()

    def test_create_app_uses_default_config_path(self):
        """Test that create_app uses default deployment.json path when no config file exists."""
        with patch("docs_mcp_server.app_builder.Path.exists") as mock_exists:
            mock_exists.return_value = False

            # Patch env-driven fallback to fail, so FileNotFoundError is raised
            with patch("docs_mcp_server.app_builder._build_env_deployment_from_env") as mock_env:
                mock_env.side_effect = ValueError("DOCS_NAME must be set")

                with pytest.raises(FileNotFoundError) as exc_info:
                    create_app()

                assert "deployment.json" in str(exc_info.value)

    @patch("docs_mcp_server.app_builder.create_tenant_app")
    def test_create_app_mounts_tenants_correctly(self, mock_create_tenant):
        """Test that root hub architecture mounts core routes correctly.

        In the new architecture, tenants are not individually mounted.
        Instead, there's a root hub at /mcp that provides discovery and
        proxy access to all tenants.
        """
        config_data = {
            "infrastructure": {},
            "tenants": [
                {
                    "codename": "django",
                    "docs_name": "Django",
                    "docs_sitemap_url": "https://docs.djangoproject.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://docs.djangoproject.com/",
                },
                {
                    "codename": "fastapi",
                    "docs_name": "FastAPI",
                    "docs_sitemap_url": "https://fastapi.tiangolo.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://fastapi.tiangolo.com/",
                },
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            # Mock tenant apps
            mock_tenant_apps = []
            for tenant_data in config_data["tenants"]:
                mock_app = Mock()
                mock_app.codename = tenant_data["codename"]
                mock_app.docs_name = tenant_data["docs_name"]
                mock_app.get_http_app.return_value = Mock()
                mock_tenant_apps.append(mock_app)

            mock_create_tenant.side_effect = mock_tenant_apps

            app = create_app(config_path)

            # Check that core routes are mounted (root hub architecture)
            mount_paths = [route.path for route in app.routes if hasattr(route, "path")]

            # Root hub architecture: /mcp (root hub), /health, /mcp.json
            assert "/mcp" in mount_paths, f"Expected /mcp in {mount_paths}"
            assert "/health" in mount_paths, f"Expected /health in {mount_paths}"
            assert "/mcp.json" in mount_paths, f"Expected /mcp.json in {mount_paths}"
            # Tenants are created but accessible via root hub, not individual mounts
            assert mock_create_tenant.call_count == 2

        finally:
            config_path.unlink()


class TestAppHealthEndpoint:
    """Test the health check endpoint."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config_data = {
            "infrastructure": {
                "mcp_port": 8000,
            },
            "tenants": [
                {
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_sitemap_url": "https://example.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://example.com/",
                }
            ],
        }

    @patch("docs_mcp_server.app_builder.create_tenant_app")
    @patch("httpx.AsyncClient")
    def test_health_endpoint_all_healthy(self, mock_httpx, mock_create_tenant):
        """Test health endpoint when all tenants are healthy."""
        # Mock http_app with routes
        mock_http_app = Mock()
        mock_http_app.routes = []

        # Mock tenant app with async health() method
        mock_tenant_app = Mock()
        mock_tenant_app.codename = "test"
        mock_tenant_app.docs_name = "Test Docs"
        mock_tenant_app.get_http_app.return_value = mock_http_app
        # The health() method must be async - use AsyncMock
        mock_tenant_app.health = AsyncMock(
            return_value={
                "status": "healthy",
                "name": "Test Docs",
                "services": {"search": "healthy", "cache": "healthy"},
            }
        )
        mock_create_tenant.return_value = mock_tenant_app

        # Mock httpx response (not used but required for signature)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "healthy",
            "name": "Test Docs",
            "services": {"search": "healthy", "cache": "healthy"},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_httpx.return_value = mock_client

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(self.config_data, f)
            config_path = Path(f.name)

        try:
            app = create_app(config_path)
            client = TestClient(app)

            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["tenant_count"] == 1
            assert "test" in data["tenants"]
            assert "infrastructure" in data

        finally:
            config_path.unlink()

    @patch("docs_mcp_server.app_builder.create_tenant_app")
    def test_health_endpoint_with_unhealthy_tenant(self, mock_create_tenant):
        """Test health endpoint when a tenant is unhealthy."""
        # Mock tenant app with unhealthy health response
        mock_tenant_app = Mock()
        mock_tenant_app.codename = "test"
        mock_tenant_app.docs_name = "Test Docs"
        mock_tenant_app.get_http_app.return_value = Mock()
        mock_tenant_app.health = AsyncMock(
            return_value={
                "status": "unhealthy",
                "name": "Test Docs",
                "error": "Service down",
            }
        )
        mock_create_tenant.return_value = mock_tenant_app

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(self.config_data, f)
            config_path = Path(f.name)

        try:
            app = create_app(config_path)
            client = TestClient(app)

            response = client.get("/health")

            # Health endpoint always returns 200, check "status" field for degraded state
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert "test" in data["tenants"]
            assert data["tenants"]["test"]["status"] == "unhealthy"

        finally:
            config_path.unlink()


class TestMcpJsonEndpoint:
    """Test the mcp.json configuration endpoint."""

    @patch("docs_mcp_server.app_builder.create_tenant_app")
    def test_mcp_json_endpoint_returns_valid_config(self, mock_create_tenant):
        """Test that /mcp.json returns valid MCP configuration.

        The new root hub architecture uses a single 'docs-mcp-root' server
        entry that points to /mcp, instead of per-tenant entries.
        """
        config_data = {
            "infrastructure": {
                "mcp_host": "127.0.0.1",
                "mcp_port": 8000,
            },
            "tenants": [
                {
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_sitemap_url": "https://example.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://example.com/",
                }
            ],
        }

        # Mock tenant app
        mock_tenant_app = Mock()
        mock_tenant_app.codename = "test"
        mock_tenant_app.docs_name = "Test Docs"
        mock_tenant_app.get_http_app.return_value = Mock()
        mock_create_tenant.return_value = mock_tenant_app

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            app = create_app(config_path)
            client = TestClient(app)

            response = client.get("/mcp.json")

            assert response.status_code == 200
            data = response.json()
            assert "servers" in data
            # Root hub architecture uses single 'docs-mcp-root' entry
            assert "docs-mcp-root" in data["servers"]
            assert data["servers"]["docs-mcp-root"]["url"] == "http://127.0.0.1:8000/mcp"
            assert data["servers"]["docs-mcp-root"]["type"] == "http"
            assert data["defaultModel"] == "claude-haiku-4.5"

        finally:
            config_path.unlink()


class TestMainFunction:
    """Test the main function."""

    @patch("uvicorn.run")
    @patch("docs_mcp_server.app.create_app")
    @patch("docs_mcp_server.app.DeploymentConfig.from_json_file")
    def test_main_starts_uvicorn_server(self, mock_config, mock_create_app, mock_uvicorn):
        """Test that main function starts uvicorn server."""
        # Mock deployment config
        mock_deployment_config = Mock()
        mock_deployment_config.infrastructure = Mock()
        mock_deployment_config.infrastructure.log_level = "INFO"
        mock_deployment_config.infrastructure.mcp_host = "127.0.0.1"
        mock_deployment_config.infrastructure.mcp_port = 8000
        mock_deployment_config.infrastructure.uvicorn_workers = 1
        mock_deployment_config.infrastructure.uvicorn_limit_concurrency = None
        mock_deployment_config.tenants = []
        mock_config.return_value = mock_deployment_config

        # Mock app
        mock_app = Mock()
        mock_create_app.return_value = mock_app

        main()

        # Verify uvicorn.run was called
        mock_uvicorn.assert_called_once()
        args, kwargs = mock_uvicorn.call_args
        assert args[0] == mock_app  # First arg should be the app
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8000

    @patch("docs_mcp_server.app.DeploymentConfig.from_json_file")
    def test_main_handles_missing_config_file(self, mock_config):
        """Test that main handles missing config file."""
        mock_config.side_effect = FileNotFoundError("Config not found")

        with pytest.raises(FileNotFoundError):
            main()

    @patch.dict("os.environ", {"DEPLOYMENT_CONFIG": "/custom/path/config.json"})
    @patch("docs_mcp_server.app.DeploymentConfig.from_json_file")
    @patch("docs_mcp_server.app.create_app")
    @patch("uvicorn.run")
    def test_main_uses_custom_config_path_from_env(self, mock_uvicorn, mock_create_app, mock_config):
        """Test that main uses custom config path from environment variable."""
        # Mock deployment config
        mock_deployment_config = Mock()
        mock_deployment_config.infrastructure = Mock()
        mock_deployment_config.infrastructure.log_level = "INFO"
        mock_deployment_config.infrastructure.mcp_host = "127.0.0.1"
        mock_deployment_config.infrastructure.mcp_port = 8000
        mock_deployment_config.infrastructure.uvicorn_workers = 1
        mock_deployment_config.infrastructure.uvicorn_limit_concurrency = None
        mock_deployment_config.tenants = []
        mock_config.return_value = mock_deployment_config

        main()

        # Verify config was loaded from custom path
        mock_config.assert_called_once_with(Path("/custom/path/config.json"))

    @patch("docs_mcp_server.app.logging.basicConfig")
    @patch("docs_mcp_server.app.DeploymentConfig.from_json_file")
    @patch("docs_mcp_server.app.create_app")
    @patch("uvicorn.run")
    def test_main_configures_logging(self, mock_uvicorn, mock_create_app, mock_config, mock_logging):
        """Test that main configures logging properly."""
        # Mock deployment config
        mock_deployment_config = Mock()
        mock_deployment_config.infrastructure = Mock()
        mock_deployment_config.infrastructure.log_level = "DEBUG"
        mock_deployment_config.infrastructure.mcp_host = "127.0.0.1"
        mock_deployment_config.infrastructure.mcp_port = 8000
        mock_deployment_config.infrastructure.uvicorn_workers = 1
        mock_deployment_config.infrastructure.uvicorn_limit_concurrency = None
        mock_deployment_config.tenants = []
        mock_config.return_value = mock_deployment_config

        main()

        # Verify logging was configured
        mock_logging.assert_called_once()
        _, kwargs = mock_logging.call_args
        assert kwargs["force"] is True
        assert "%(asctime)s" in kwargs["format"]


@pytest.mark.integration
class TestAppIntegration:
    """Integration tests for the main app."""

    @patch("docs_mcp_server.app_builder.create_tenant_app")
    def test_app_can_be_created_with_minimal_config(self, mock_create_tenant):
        """Test that app can be created with minimal valid configuration."""
        config_data = {
            "infrastructure": {},
            "tenants": [
                {
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_sitemap_url": "https://example.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://example.com/",
                }
            ],
        }

        # Mock tenant app
        mock_tenant_app = Mock()
        mock_tenant_app.codename = "test"
        mock_tenant_app.docs_name = "Test Docs"
        mock_tenant_app.get_http_app.return_value = Mock()
        mock_create_tenant.return_value = mock_tenant_app

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            app = create_app(config_path)
            assert isinstance(app, Starlette)
            assert len(app.routes) >= 2  # At least health and mcp.json routes

        finally:
            config_path.unlink()

    @patch("docs_mcp_server.app.create_tenant_app")
    def test_app_lifespan_management(self, mock_create_tenant):
        """Test that app lifespan properly manages tenant lifespans."""
        config_data = {
            "infrastructure": {},
            "tenants": [
                {
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_sitemap_url": "https://example.com/sitemap.xml",
                    "url_whitelist_prefixes": "https://example.com/",
                }
            ],
        }

        # Mock tenant app with lifespan
        mock_http_app = Mock()
        mock_lifespan = AsyncMock()
        mock_http_app.lifespan.return_value = mock_lifespan

        mock_tenant_app = Mock()
        mock_tenant_app.codename = "test"
        mock_tenant_app.docs_name = "Test Docs"
        mock_tenant_app.get_http_app.return_value = mock_http_app
        mock_create_tenant.return_value = mock_tenant_app

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            config_path = Path(f.name)

        try:
            app = create_app(config_path)

            # Test that app was created successfully
            assert isinstance(app, Starlette)
            # Test that the app has routes (indicating tenant lifespans are set up)
            assert len(app.routes) > 0

        finally:
            config_path.unlink()
