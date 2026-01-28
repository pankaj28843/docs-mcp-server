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
    """TenantApp stub that only tracks registered tool names."""

    def __init__(self, tool_names: list[str]) -> None:
        self.tool_names = tool_names


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

        metadata = TenantMetadata.from_config(config)

        assert metadata.codename == "hybrid"
        assert metadata.display_name == "Hybrid Docs"
        assert metadata.source_type == "git"
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
        registry.register(first_config, FakeTenantApp(["search_django"]))

        metadata_first = registry.get_metadata("django")
        metadata_second = registry.get_metadata("django")
        assert metadata_first is metadata_second

        updated_config = make_config(codename="django", docs_name="Django Next")
        registry.register(updated_config, FakeTenantApp(["search_django", "fetch_django"]))

        metadata_updated = registry.get_metadata("django")
        assert metadata_updated is not metadata_first
        assert metadata_updated.display_name == "Django Next"

    def test_lookup_helpers_and_iteration(self) -> None:
        registry = TenantRegistry()
        alpha_config = make_config(codename="alpha", docs_name="Alpha Docs")
        beta_config = make_config(codename="beta", docs_name="Beta Docs")
        alpha_app = FakeTenantApp(["search_alpha"])
        beta_app = FakeTenantApp(["search_beta"])

        registry.register(alpha_config, alpha_app)
        registry.register(beta_config, beta_app)

        assert len(registry) == 2
        assert "alpha" in registry
        assert registry.get_tenant("alpha") is alpha_app
        assert registry.get_tenant("missing") is None
        assert registry.list_codenames() == ["alpha", "beta"]

        tenants = registry.list_tenants()
        assert [metadata.codename for metadata in tenants] == ["alpha", "beta"]
