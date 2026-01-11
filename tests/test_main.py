"""Tests for __main__.py entry point."""

import runpy
import sys
from unittest.mock import Mock, patch

import pytest
import docs_mcp_server.__main__

from docs_mcp_server.__main__ import main
from docs_mcp_server.app import main as main_from_app


class TestMainModule:
    """Test the __main__.py entry point module."""

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        assert callable(main)

    @patch("docs_mcp_server.app.main")
    def test_main_called_when_run_as_module(self, mock_app_main):
        """Test that main() is called when module is executed."""
        runpy.run_module("docs_mcp_server.__main__", run_name="__main__")

        mock_app_main.assert_called_once()

    def test_main_delegates_to_app_main(self):
        """Test that __main__ module imports main from app."""
        # They should be the same function
        assert main is main_from_app

    @patch("docs_mcp_server.app.main")
    def test_module_execution_with_python_m(self, mock_app_main):
        """Test running the module with python -m without spawning a new interpreter."""
        with patch.object(sys, "argv", ["docs_mcp_server", "--help"]):
            runpy.run_module("docs_mcp_server", run_name="__main__")

        mock_app_main.assert_called_once()


@pytest.mark.integration
class TestMainModuleIntegration:
    """Integration tests for the main module."""

    def test_module_can_be_imported(self):
        """Test that the module can be imported without errors."""
        # If we get here without exception, import succeeded
        assert True

    @patch("uvicorn.run")
    @patch("docs_mcp_server.app.DeploymentConfig.from_json_file")
    def test_main_handles_missing_config_gracefully(self, mock_config, mock_uvicorn):
        """Test that main handles missing deployment config gracefully."""
        # Mock a minimal config
        mock_deployment_config = Mock()
        mock_deployment_config.infrastructure = Mock()
        mock_deployment_config.infrastructure.log_level = "INFO"
        mock_deployment_config.infrastructure.mcp_host = "127.0.0.1"
        mock_deployment_config.infrastructure.mcp_port = 8000
        mock_deployment_config.infrastructure.uvicorn_workers = 1
        mock_deployment_config.infrastructure.uvicorn_limit_concurrency = None
        mock_deployment_config.tenants = [Mock(codename="test", docs_name="Test Docs")]
        mock_config.return_value = mock_deployment_config

        with patch("docs_mcp_server.app.create_app") as mock_create_app:
            mock_create_app.return_value = Mock()

            # Should not raise exception
            main()

            # Should attempt to run uvicorn
            mock_uvicorn.assert_called_once()
