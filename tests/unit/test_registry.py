"""Unit tests for docs_mcp_server.registry."""

from __future__ import annotations

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.registry import TenantMetadata, TenantRegistry


class FakeToolManager:
    """Minimal tool manager that exposes the _tools dict."""

    def __init__(self, tool_names: list[str]) -> None:
        self._tools = {name: object() for name in tool_names}


class FakeMCP:
    """MCP stub exposing the tool manager."""

    def __init__(self, tool_names: list[str]) -> None:
        self._tool_manager = FakeToolManager(tool_names)


class FakeTenantApp:
    """TenantApp stub that only tracks registered tool names and supports_browse flag."""

    def __init__(self, tool_names: list[str], supports_browse: bool = False) -> None:
        self.tool_names = tool_names
        self._supports_browse = supports_browse

    def supports_browse(self) -> bool:
        return self._supports_browse


def make_config(**overrides: object) -> TenantConfig:
    """Helper to create valid TenantConfig instances for tests."""

    base: dict[str, object] = {
        "source_type": "online",
        "codename": "demo",
        "docs_name": "Demo Docs",
        "docs_sitemap_url": "https://docs.example.com/sitemap.xml",
        "docs_entry_url": "https://docs.example.com/start",
        "url_whitelist_prefixes": "https://docs.example.com/start",
        "test_queries": {
            "natural": ["how to get started"],
            "phrases": ['"install"'],
            "words": ["install", "configure"],
        },
    }
    base.update(overrides)
    return TenantConfig.model_validate(base)


@pytest.mark.unit
class TestTenantMetadata:
    def test_from_config_builds_description_and_queries(self) -> None:
        config = make_config(
            source_type="git",
            codename="hybrid",
            docs_name="Hybrid Docs",
            git_repo_url="https://github.com/example/hybrid-docs.git",
            git_subpaths=["docs"],
            url_whitelist_prefixes=(
                "https://alpha.example.com/en/latest/tutorials/,"
                "https://beta.example.com/en/stable/how-to/,"
                "https://gamma.example.com/en/reference/,"
                "https://delta.example.com/en/guides/"
            ),
            docs_entry_url="https://beta.example.com/intro,https://epsilon.example.com/start",
            docs_sitemap_url="https://zeta.example.com/sitemap.xml",
            test_queries={
                "natural": ["how to deploy"],
                "phrases": ['"QuerySet"'],
                "words": ["deployment", "auth"],
            },
        )
        tenant_app = FakeTenantApp(["search_hybrid", "fetch_hybrid"], supports_browse=True)

        metadata = TenantMetadata.from_config(config, tenant_app)

        assert metadata.codename == "hybrid"
        assert metadata.display_name == "Hybrid Docs"
        assert metadata.source_type == "git"
        assert metadata.supports_browse is True
        assert metadata.test_queries == ["how to deploy", '"QuerySet"', "deployment", "auth"]
        assert metadata.url_prefixes == [
            "https://alpha.example.com/en/latest/tutorials/",
            "https://beta.example.com/en/stable/how-to/",
            "https://gamma.example.com/en/reference/",
            "https://delta.example.com/en/guides/",
        ]
        assert "covering tutorials, how to, reference, ..." in metadata.description
        assert "(alpha.example.com, beta.example.com, ...)" in metadata.description


@pytest.mark.unit
class TestTenantRegistry:
    def test_register_and_metadata_cache_invalidation(self) -> None:
        registry = TenantRegistry()
        first_config = make_config(codename="django", docs_name="Django Docs")
        registry.register(first_config, FakeTenantApp(["search_django"], supports_browse=False))

        metadata_first = registry.get_metadata("django")
        metadata_second = registry.get_metadata("django")
        assert metadata_first is metadata_second
        assert metadata_first.supports_browse is False

        updated_config = make_config(codename="django", docs_name="Django Next")
        registry.register(updated_config, FakeTenantApp(["search_django", "fetch_django"], supports_browse=True))

        metadata_updated = registry.get_metadata("django")
        assert metadata_updated is not metadata_first
        assert metadata_updated.display_name == "Django Next"
        assert metadata_updated.supports_browse is True

    def test_lookup_helpers_and_iteration(self) -> None:
        registry = TenantRegistry()
        alpha_config = make_config(codename="alpha", docs_name="Alpha Docs")
        beta_config = make_config(codename="beta", docs_name="Beta Docs")
        alpha_app = FakeTenantApp(["search_alpha"], supports_browse=False)
        beta_app = FakeTenantApp(["search_beta"], supports_browse=True)

        registry.register(alpha_config, alpha_app)
        registry.register(beta_config, beta_app)

        assert len(registry) == 2
        assert "alpha" in registry
        assert registry.get_tenant("alpha") is alpha_app
        assert registry.get_tenant("missing") is None
        assert registry.list_codenames() == ["alpha", "beta"]

        tenants = registry.list_tenants()
        assert [metadata.codename for metadata in tenants] == ["alpha", "beta"]

    def test_is_filesystem_tenant_detection(self) -> None:
        registry = TenantRegistry()
        filesystem_config = make_config(
            source_type="filesystem",
            codename="fs",
            docs_root_dir="/tmp/fs-docs",
            docs_sitemap_url="",
            docs_entry_url="",
        )
        git_config = make_config(
            source_type="git",
            codename="gitty",
            git_repo_url="https://github.com/example/repo.git",
            git_subpaths=["docs"],
        )
        online_config = make_config(codename="web")

        registry.register(filesystem_config, FakeTenantApp([], supports_browse=True))
        registry.register(git_config, FakeTenantApp([], supports_browse=True))
        registry.register(online_config, FakeTenantApp([], supports_browse=False))

        assert registry.is_filesystem_tenant("fs") is True
        assert registry.is_filesystem_tenant("gitty") is True
        assert registry.is_filesystem_tenant("web") is False
        assert registry.is_filesystem_tenant("missing") is False
