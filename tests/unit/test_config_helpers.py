from __future__ import annotations

import pytest

import docs_mcp_server.config as config_module
from docs_mcp_server.config import Settings, _json_or_raw, _normalize_url_collection


@pytest.mark.unit
def test_json_or_raw_handles_invalid_json() -> None:
    assert _json_or_raw("not-json") == "not-json"
    assert _json_or_raw("[1,2]") == [1, 2]


@pytest.mark.unit
def test_normalize_url_collection_accepts_string_and_iterables() -> None:
    assert _normalize_url_collection("https://a, https://b") == ["https://a", "https://b"]
    assert _normalize_url_collection(["https://a", "", None, " https://b "]) == ["https://a", "https://b"]
    assert _normalize_url_collection(123) == ["123"]


@pytest.mark.unit
def test_settings_requires_urls_when_sync_enabled() -> None:
    with pytest.raises(ValueError, match="DOCS_SITEMAP_URL or DOCS_ENTRY_URL"):
        Settings(docs_name="Docs", docs_sync_enabled=True, docs_sitemap_url=[], docs_entry_url=[])


@pytest.mark.unit
def test_settings_resolves_fallback_extractor_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_TOKEN", "token-123")

    class DummyResponse:
        status_code = 200

    def fake_head(endpoint: str, timeout: float):
        return DummyResponse()

    monkeypatch.setattr(config_module.httpx, "head", fake_head)
    config_module.Settings._validated_fallback_endpoints = set()

    settings = Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        fallback_extractor_enabled=True,
        fallback_extractor_endpoint="https://fallback.local",
        fallback_extractor_api_key_env="FALLBACK_TOKEN",
    )

    assert settings.fallback_extractor_api_key == "token-123"


@pytest.mark.unit
def test_should_process_url_respects_whitelist_and_blacklist() -> None:
    settings = Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        url_whitelist_prefixes="https://allowed",
        url_blacklist_prefixes="https://allowed/private",
    )

    assert settings.should_process_url("https://allowed/docs") is True
    assert settings.should_process_url("https://blocked") is False
    assert settings.should_process_url("https://allowed/private/secret") is False


@pytest.mark.unit
def test_get_random_user_agent_returns_from_pool() -> None:
    settings = Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    assert settings.get_random_user_agent() in settings.USER_AGENTS
