"""Unit tests for deployment configuration.

Following Cosmic Python Chapter 3: Testing with abstractions
- Test domain models in isolation
- Use value objects for configuration
- No external dependencies
"""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import ValidationError
import pytest

from docs_mcp_server.deployment_config import (
    ArticleExtractorFallbackConfig,
    DeploymentConfig,
    LogProfileConfig,
    SharedInfraConfig,
    TenantConfig,
)


pytestmark = pytest.mark.unit


class TestTenantConfig:
    """Test tenant configuration value object."""

    def test_minimal_filesystem_tenant(self):
        """Test creating filesystem tenant with minimal required fields."""
        config = TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir="./mcp-data/test",
        )

        assert config.codename == "test"
        assert config.docs_name == "Test Docs"
        assert config.source_type == "filesystem"
        assert config.docs_root_dir == "./mcp-data/test"

    def test_minimal_online_tenant(self):
        """Test creating online tenant with sitemap URL."""
        config = TenantConfig(
            source_type="online",
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
        )

        assert config.codename == "test"
        assert config.source_type == "online"
        assert config.docs_sitemap_url == ["https://example.com/sitemap.xml"]

    def test_minimal_git_tenant(self):
        """Test creating git-backed tenant with sparse checkout fields."""
        config = TenantConfig(
            source_type="git",
            codename="handbook",
            docs_name="Engineering Handbook",
            git_repo_url="https://github.com/acme/handbook.git",
            git_subpaths=["handbook"],
        )

        assert config.source_type == "git"
        assert config.git_repo_url == "https://github.com/acme/handbook.git"
        assert config.git_subpaths == ["handbook"]
        assert config.git_branch == "main"

    def test_tenant_search_config_defaults(self):
        """Test default search config is attached to tenants."""
        config = TenantConfig(
            source_type="filesystem",
            codename="search",
            docs_name="Search Docs",
            docs_root_dir="./mcp-data/search",
        )

        assert config.search.enabled is True
        assert config.search.engine == "bm25"  # BM25 is the default engine
        assert config.search.analyzer_profile == "default"
        assert config.search.boosts.title == 2.5  # Updated default for better title relevance

    def test_tenant_search_config_accepts_customizations(self):
        """Search config allows opting into new engines and analyzer presets."""
        config = TenantConfig(
            source_type="filesystem",
            codename="bm25",
            docs_name="Search Docs",
            docs_root_dir="./mcp-data/search",
            search={
                "enabled": False,
                "engine": "bm25",
                "analyzer_profile": "code-friendly",
                "boosts": {"title": 3.0, "body": 0.8},
                "snippet": {"max_fragments": 3, "style": "html"},
                "ranking": {"bm25_k1": 1.5, "bm25_b": 0.65, "enable_proximity_bonus": False},
                "suggestions_enabled": True,
            },
        )

        assert config.search.enabled is False
        assert config.search.engine == "bm25"
        assert config.search.analyzer_profile == "code-friendly"
        assert config.search.boosts.title == 3.0
        assert config.search.boosts.body == 0.8
        assert config.search.snippet.max_fragments == 3
        assert config.search.snippet.style == "html"
        assert config.search.ranking.bm25_k1 == 1.5
        assert config.search.ranking.enable_proximity_bonus is False
        assert config.search.suggestions_enabled is True

    def test_tenant_with_refresh_schedule(self):
        """Test tenant config with cron refresh schedule."""
        config = TenantConfig(
            source_type="filesystem",
            codename="django",
            docs_name="Django",
            docs_root_dir="./mcp-data/django",
            refresh_schedule="0 2 * * 1",  # Weekly Monday 2am
        )

        assert config.refresh_schedule == "0 2 * * 1"

    def test_tenant_requires_discovery_method_for_online(self):
        """Test that online tenants require sitemap or entry URL."""
        with pytest.raises(ValidationError, match="either docs_sitemap_url or docs_entry_url"):
            TenantConfig(
                source_type="online",
                codename="test",
                docs_name="Test",
                docs_sitemap_url="",  # No discovery method
                docs_entry_url="",
            )

    def test_filesystem_tenant_requires_docs_root_dir(self):
        """Test that filesystem tenants require docs_root_dir."""
        with pytest.raises(ValidationError, match="must specify docs_root_dir"):
            TenantConfig(
                source_type="filesystem",
                codename="test",
                docs_name="Test",
                docs_root_dir=None,  # Missing required field
            )

    def test_git_tenant_requires_repo_and_subpaths(self):
        """Test that git tenants require repo URL and at least one subpath."""
        with pytest.raises(ValidationError, match="git_repo_url"):
            TenantConfig(
                source_type="git",
                codename="handbook",
                docs_name="Engineering Handbook",
                git_repo_url=None,
                git_subpaths=["docs"],
            )

        with pytest.raises(ValidationError, match="git_subpaths"):
            TenantConfig(
                source_type="git",
                codename="handbook",
                docs_name="Engineering Handbook",
                git_repo_url="https://github.com/acme/handbook.git",
                git_subpaths=[],
            )

    def test_rejects_extra_keys(self):
        """Test that extra keys in tenant config are rejected."""
        with pytest.raises(ValidationError, match="extra"):
            TenantConfig(
                source_type="filesystem",
                codename="test",
                docs_name="Test",
                docs_root_dir="./mcp-data/test",
                invalid_field="should_fail",  # type: ignore
            )


class TestSharedInfraConfig:
    """Test infrastructure configuration value object."""

    def test_minimal_infrastructure_config(self):
        """Test creating infrastructure config with defaults."""
        config = SharedInfraConfig()

        assert config.mcp_port == 8000  # Default
        assert config.max_concurrent_requests == 20  # Default
        assert config.operation_mode == "online"  # Default

    def test_infrastructure_config_custom_values(self):
        """Test infrastructure config with custom values."""
        config = SharedInfraConfig(
            mcp_port=9000,
            max_concurrent_requests=50,
            http_timeout=60,
            search_timeout=20,
            log_level="debug",
            operation_mode="offline",
        )

        assert config.mcp_port == 9000
        assert config.max_concurrent_requests == 50
        assert config.http_timeout == 60
        assert config.search_timeout == 20
        assert config.log_level == "debug"

    def test_rejects_extra_keys(self):
        """Test that extra keys in infrastructure config are rejected."""
        with pytest.raises(ValidationError, match="extra"):
            SharedInfraConfig(
                invalid_field="should_fail",  # type: ignore
            )

    def test_article_extractor_fallback_defaults(self):
        """Fallback config should be attached with safe defaults."""
        config = SharedInfraConfig()

        assert config.article_extractor_fallback.enabled is False
        assert config.article_extractor_fallback.endpoint is None

    def test_article_extractor_fallback_customization(self):
        """Fallback config accepts endpoint + retry overrides."""
        config = SharedInfraConfig(
            article_extractor_fallback={
                "enabled": True,
                "endpoint": "http://10.20.30.1:13005/",
                "timeout_seconds": 15,
                "max_retries": 3,
            }
        )

        assert config.article_extractor_fallback.enabled is True
        assert config.article_extractor_fallback.endpoint == "http://10.20.30.1:13005/"
        assert config.article_extractor_fallback.max_retries == 3


class TestArticleExtractorFallbackConfig:
    """Direct tests for the fallback config validator."""

    def test_requires_endpoint_when_enabled(self):
        with pytest.raises(ValidationError, match="endpoint must be set"):
            ArticleExtractorFallbackConfig(enabled=True, endpoint=None)


class TestDeploymentConfig:
    """Test complete deployment configuration aggregate."""

    def test_minimal_deployment_config(self):
        """Test creating deployment config with minimal setup."""
        config = DeploymentConfig(
            infrastructure=SharedInfraConfig(),
            tenants=[
                TenantConfig(
                    source_type="filesystem",
                    codename="test",
                    docs_name="Test Docs",
                    docs_root_dir="./mcp-data/test",
                )
            ],
        )

        assert len(config.tenants) == 1
        assert config.tenants[0].codename == "test"

    def test_deployment_config_multiple_tenants(self):
        """Test deployment config with multiple tenants."""
        config = DeploymentConfig(
            infrastructure=SharedInfraConfig(),
            tenants=[
                TenantConfig(
                    source_type="filesystem",
                    codename="django",
                    docs_name="Django",
                    docs_root_dir="./mcp-data/django",
                ),
                TenantConfig(
                    source_type="filesystem",
                    codename="fastapi",
                    docs_name="FastAPI",
                    docs_root_dir="./mcp-data/fastapi",
                ),
            ],
        )

        assert len(config.tenants) == 2
        assert config.tenants[0].codename == "django"
        assert config.tenants[1].codename == "fastapi"

    def test_deployment_config_from_dict(self):
        """Test creating deployment config from dictionary."""
        config_dict = {
            "infrastructure": {
                "mcp_port": 8000,
            },
            "tenants": [
                {
                    "source_type": "filesystem",
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_root_dir": "./mcp-data/test",
                }
            ],
        }

        config = DeploymentConfig(**config_dict)

        assert len(config.tenants) == 1
        assert config.infrastructure.mcp_port == 8000

    def test_deployment_config_from_json_file(self):
        """Test loading deployment config from JSON file."""
        config_data = {
            "infrastructure": {},
            "tenants": [
                {
                    "source_type": "filesystem",
                    "codename": "test",
                    "docs_name": "Test Docs",
                    "docs_root_dir": "./mcp-data/test",
                }
            ],
        }

        # Create temporary JSON file
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            config = DeploymentConfig.from_json_file(temp_path)

            assert len(config.tenants) == 1
            assert config.tenants[0].codename == "test"
        finally:
            temp_path.unlink()

    def test_deployment_config_file_not_found(self):
        """Test error handling when config file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            DeploymentConfig.from_json_file(Path("/nonexistent/config.json"))

    def test_deployment_config_invalid_json(self):
        """Test error handling for invalid JSON."""
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            temp_path = Path(f.name)

        try:
            with pytest.raises(json.JSONDecodeError):
                DeploymentConfig.from_json_file(temp_path)
        finally:
            temp_path.unlink()

    def test_deployment_config_empty_tenants(self):
        """Test that deployment config requires at least one tenant."""
        with pytest.raises(ValidationError, match="tenants"):
            DeploymentConfig(infrastructure=SharedInfraConfig(), tenants=[])

    def test_deployment_config_duplicate_codenames(self):
        """Test handling of duplicate tenant codenames."""
        with pytest.raises(ValidationError, match="Duplicate tenant codenames"):
            DeploymentConfig(
                infrastructure=SharedInfraConfig(),
                tenants=[
                    TenantConfig(
                        source_type="filesystem",
                        codename="test",
                        docs_name="Test Docs 1",
                        docs_root_dir="./mcp-data/test1",
                    ),
                    TenantConfig(
                        source_type="filesystem",
                        codename="test",  # Duplicate
                        docs_name="Test Docs 2",
                        docs_root_dir="./mcp-data/test2",
                    ),
                ],
            )

    def test_get_tenant_by_codename(self):
        """Test retrieving tenant by codename."""
        config = DeploymentConfig(
            infrastructure=SharedInfraConfig(),
            tenants=[
                TenantConfig(
                    source_type="filesystem",
                    codename="django",
                    docs_name="Django",
                    docs_root_dir="./mcp-data/django",
                ),
            ],
        )

        tenant = config.get_tenant("django")
        assert tenant is not None
        assert tenant.codename == "django"

        assert config.get_tenant("missing") is None

    def test_list_codenames(self):
        """Test listing all tenant codenames."""
        config = DeploymentConfig(
            infrastructure=SharedInfraConfig(),
            tenants=[
                TenantConfig(
                    source_type="filesystem",
                    codename="django",
                    docs_name="Django",
                    docs_root_dir="./mcp-data/django",
                ),
                TenantConfig(
                    source_type="filesystem",
                    codename="fastapi",
                    docs_name="FastAPI",
                    docs_root_dir="./mcp-data/fastapi",
                ),
            ],
        )

        codenames = config.list_codenames()
        assert codenames == ["django", "fastapi"]


class TestLogProfileConfig:
    """Test log profile configuration value object."""

    def test_minimal_log_profile_defaults(self):
        """Test creating log profile with defaults."""
        config = LogProfileConfig()

        assert config.level == "info"
        assert config.json_output is True
        assert config.trace_categories == []
        assert config.trace_level == "debug"
        assert config.logger_levels == {}
        assert config.access_log is False

    def test_log_profile_custom_values(self):
        """Test log profile with custom values."""
        config = LogProfileConfig(
            level="debug",
            json_output=False,
            trace_categories=["docs_mcp_server", "uvicorn"],
            trace_level="info",
            logger_levels={"uvicorn.access": "warning", "fastmcp": "debug"},
            access_log=True,
        )

        assert config.level == "debug"
        assert config.json_output is False
        assert config.trace_categories == ["docs_mcp_server", "uvicorn"]
        assert config.trace_level == "info"
        assert config.logger_levels == {"uvicorn.access": "warning", "fastmcp": "debug"}
        assert config.access_log is True

    def test_log_profile_rejects_invalid_level(self):
        """Test that invalid log levels are rejected."""
        with pytest.raises(ValidationError, match="pattern"):
            LogProfileConfig(level="verbose")

    def test_log_profile_rejects_invalid_trace_level(self):
        """Test that invalid trace_level is rejected."""
        with pytest.raises(ValidationError, match="pattern"):
            LogProfileConfig(trace_level="trace")

    def test_log_profile_validates_logger_levels_values(self):
        """Test that logger_levels dict values are validated."""
        with pytest.raises(ValidationError, match="Invalid log level"):
            LogProfileConfig(logger_levels={"mylogger": "verbose"})

    def test_log_profile_validates_multiple_invalid_logger_levels(self):
        """Test that multiple invalid logger_levels are reported."""
        with pytest.raises(ValidationError, match="mylogger=trace"):
            LogProfileConfig(logger_levels={"mylogger": "trace", "other": "debug"})

    def test_log_profile_accepts_all_valid_levels(self):
        """Test that all valid log levels are accepted."""
        for level in ["debug", "info", "warning", "error", "critical"]:
            config = LogProfileConfig(level=level, trace_level=level)
            assert config.level == level
            assert config.trace_level == level

    def test_log_profile_accepts_valid_logger_levels(self):
        """Test that valid logger_levels values pass validation."""
        config = LogProfileConfig(
            logger_levels={
                "debug_logger": "debug",
                "info_logger": "info",
                "warning_logger": "warning",
                "error_logger": "error",
                "critical_logger": "critical",
            }
        )
        assert len(config.logger_levels) == 5

    def test_log_profile_rejects_extra_keys(self):
        """Test that extra keys are rejected."""
        with pytest.raises(ValidationError, match="extra"):
            LogProfileConfig(
                level="info",
                unknown_field="should_fail",  # type: ignore
            )


class TestSharedInfraConfigLogProfiles:
    """Test log profile integration with SharedInfraConfig."""

    def test_log_profiles_default_has_default_profile(self):
        """Test that log_profiles defaults to a 'default' profile."""
        config = SharedInfraConfig()
        assert "default" in config.log_profiles
        assert config.log_profiles["default"].level == "info"

    def test_log_profiles_custom_profiles(self):
        """Test adding custom log profiles (must include referenced profile)."""
        config = SharedInfraConfig(
            log_profile="production",
            log_profiles={
                "production": {"level": "warning", "json_output": True},
                "debug": {"level": "debug", "json_output": False, "access_log": True},
            },
        )

        assert "production" in config.log_profiles
        assert config.log_profiles["production"].level == "warning"
        assert config.log_profiles["debug"].access_log is True

    def test_get_active_log_profile_default(self):
        """Test getting active profile when using default."""
        config = SharedInfraConfig()
        profile = config.get_active_log_profile()

        assert profile.level == "info"
        assert profile.json_output is True

    def test_get_active_log_profile_named(self):
        """Test getting active profile by name."""
        config = SharedInfraConfig(
            log_profile="custom",
            log_profiles={
                "custom": {"level": "debug", "access_log": True},
            },
        )
        profile = config.get_active_log_profile()

        assert profile.level == "debug"
        assert profile.access_log is True

    def test_validate_log_profile_exists(self):
        """Test that referenced log_profile must exist in log_profiles."""
        with pytest.raises(ValidationError, match="not found in log_profiles"):
            SharedInfraConfig(
                log_profile="missing",
                log_profiles={"other": {"level": "info"}},
            )
