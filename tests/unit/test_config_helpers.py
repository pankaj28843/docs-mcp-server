from __future__ import annotations

import pytest

import docs_mcp_server.config as config_module
from docs_mcp_server.utils.url_matching import url_matches_prefix


@pytest.mark.unit
def test_json_or_raw_handles_invalid_json() -> None:
    assert config_module._json_or_raw("not-json") == "not-json"
    assert config_module._json_or_raw("[1,2]") == [1, 2]


@pytest.mark.unit
def test_normalize_url_collection_accepts_string_and_iterables() -> None:
    assert config_module._normalize_url_collection("https://a, https://b") == ["https://a", "https://b"]
    assert config_module._normalize_url_collection(["https://a", "", None, " https://b "]) == ["https://a", "https://b"]
    assert config_module._normalize_url_collection(123) == ["123"]


@pytest.mark.unit
def test_settings_requires_urls_when_sync_enabled() -> None:
    with pytest.raises(ValueError, match="DOCS_SITEMAP_URL or DOCS_ENTRY_URL"):
        config_module.Settings(docs_name="Docs", docs_sync_enabled=True, docs_sitemap_url=[], docs_entry_url=[])


@pytest.mark.unit
def test_settings_resolves_fallback_extractor_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_TOKEN", "token-123")

    class DummyResponse:
        status_code = 200

    def fake_head(endpoint: str, timeout: float):
        return DummyResponse()

    monkeypatch.setattr(config_module.httpx, "head", fake_head)
    config_module.Settings._validated_fallback_endpoints = set()

    settings = config_module.Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        fallback_extractor_enabled=True,
        fallback_extractor_endpoint="https://fallback.local",
        fallback_extractor_api_key_env="FALLBACK_TOKEN",
    )

    assert settings.fallback_extractor_api_key == "token-123"


@pytest.mark.unit
def test_should_process_url_respects_whitelist_and_blacklist() -> None:
    settings = config_module.Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        url_whitelist_prefixes="https://allowed",
        url_blacklist_prefixes="https://allowed/private",
    )

    assert settings.should_process_url("https://allowed/docs") is True
    assert settings.should_process_url("https://blocked") is False
    assert settings.should_process_url("https://allowed/private/secret") is False


@pytest.mark.unit
def test_should_process_url_keeps_theme_prefixes_at_path_boundaries() -> None:
    settings = config_module.Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://developer.android.com/sitemap.xml"],
        url_whitelist_prefixes="https://developer.android.com/ndk/",
        url_blacklist_prefixes="https://developer.android.com/ndk/reference/",
    )

    assert settings.should_process_url("https://developer.android.com/ndk?hl=en") is True
    assert settings.should_process_url("https://developer.android.com/ndk/guides/build.md.txt") is True
    assert settings.should_process_url("https://developer.android.com/ndk.md.txt") is True
    assert settings.should_process_url("https://developer.android.com/ndk-for-games") is False
    assert settings.should_process_url("https://developer.android.com/ndk/reference/group/audio.md.txt") is False
    assert settings.should_process_url("https://developer.android.com/ndk/reference-tools") is True


@pytest.mark.unit
def test_get_random_user_agent_returns_from_pool() -> None:
    settings = config_module.Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    assert settings.get_random_user_agent() in settings.USER_AGENTS


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "prefix", "expected"),
    [
        ("https://developer.android.com/ndk/reference", "https://developer.android.com/ndk/", True),
        ("https://developer.android.com/ndk/reference", "https://other.example/ndk/", False),
        ("http://developer.android.com/ndk/reference", "https://developer.android.com/ndk/", False),
        ("https://developer.android.com/ndk", "https://developer.android.com", True),
        ("allowed/docs", "allowed", True),
        ("", "allowed", False),
        ("allowed", "", False),
    ],
)
def test_url_matches_prefix_handles_url_and_legacy_rules(url: str, prefix: str, expected: bool) -> None:
    assert url_matches_prefix(url, prefix) is expected
