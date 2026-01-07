"""Unit tests for the config module."""

import os
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
import pytest

from docs_mcp_server.config import Settings


pytestmark = pytest.mark.unit


class TestConfig:
    """Test configuration loading and validation."""

    def test_config_defaults_are_applied(self):
        """Test that default values are properly applied."""
        # Test that values exist and are converted to proper types
        settings = Settings()  # type: ignore[call-arg]
        assert settings.http_timeout is not None
        assert isinstance(settings.max_concurrent_requests, int)
        assert isinstance(settings.snippet_length, int)

    def test_operation_mode_detection(self):
        """Test operation mode detection."""
        settings = Settings()  # type: ignore[call-arg]
        # Should be "online" from conftest.py
        assert settings.is_offline_mode() is False

    def test_sitemap_urls_parsing(self):
        """Test sitemap URL parsing."""
        settings = Settings()  # type: ignore[call-arg]
        # Should have sitemap URL from conftest.py
        sitemap_urls = settings.get_docs_sitemap_urls()
        assert isinstance(sitemap_urls, list)
        assert len(sitemap_urls) == 1
        assert sitemap_urls[0] == "https://example.com/sitemap.xml"

    @patch.dict(os.environ, {"DOCS_ENTRY_URL": "https://example.com/docs,https://example.com/api"}, clear=False)
    def test_entry_urls_parsing_multiple(self):
        """Test entry URL parsing with multiple URLs."""
        settings = Settings()  # type: ignore[call-arg]
        entry_urls = settings.get_docs_entry_urls()
        assert isinstance(entry_urls, list)
        assert len(entry_urls) == 2
        assert "https://example.com/docs" in entry_urls
        assert "https://example.com/api" in entry_urls

    def test_config_attribute_access(self):
        """Test that config supports modern attribute access."""
        settings = Settings()  # type: ignore[call-arg]
        # Test attribute access (modern Pydantic style)
        assert hasattr(settings, "log_level")
        assert hasattr(settings, "http_timeout")

    def test_user_agents_list(self):
        """Test that user agents list is available."""
        settings = Settings()  # type: ignore[call-arg]
        user_agents = settings.USER_AGENTS
        assert isinstance(user_agents, list)
        assert len(user_agents) > 0
        assert all(isinstance(ua, str) for ua in user_agents)
        assert all("Mozilla" in ua for ua in user_agents)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_env_vars_raise_error(self):
        """Test that missing required environment variables raise ValidationError.

        The required validation is for DOCS_SITEMAP_URL or DOCS_ENTRY_URL.
        """
        with pytest.raises(ValidationError, match="DOCS_SITEMAP_URL or DOCS_ENTRY_URL"):
            Settings()  # type: ignore[call-arg]

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_discovery_urls_raises_error(self):
        """Test that missing discovery URLs raises ValidationError."""
        # Need at least one of sitemap or entry URL
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    @patch("docs_mcp_server.config.httpx.head")
    def test_fallback_env_resolution(self, mock_head):
        """Fallback config should resolve API keys from env vars."""
        mock_head.return_value = SimpleNamespace(status_code=200)
        env = {
            "DOCS_FALLBACK_EXTRACTOR_ENABLED": "true",
            "DOCS_FALLBACK_EXTRACTOR_ENDPOINT": "http://10.20.30.1:13005/",
            "DOCS_FALLBACK_EXTRACTOR_API_KEY_ENV": "REMOTE_TOKEN",
            "REMOTE_TOKEN": "secret-token",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()  # type: ignore[call-arg]

        assert settings.fallback_extractor_enabled is True
        assert settings.fallback_extractor_api_key == "secret-token"

    @patch("docs_mcp_server.config.httpx.head")
    def test_fallback_missing_env_does_not_raise(self, mock_head):
        mock_head.return_value = SimpleNamespace(status_code=200)
        env = {
            "DOCS_FALLBACK_EXTRACTOR_ENABLED": "true",
            "DOCS_FALLBACK_EXTRACTOR_ENDPOINT": "http://10.20.30.1:13005/",
            "DOCS_FALLBACK_EXTRACTOR_API_KEY_ENV": "UNSET_TOKEN",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings()  # type: ignore[call-arg]

        assert settings.fallback_extractor_api_key is None
