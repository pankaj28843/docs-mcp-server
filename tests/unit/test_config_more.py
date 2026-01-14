"""Additional unit tests for config edge cases."""

import httpx
from pydantic_settings.sources.types import NoDecode
import pytest

from docs_mcp_server.config import RawFriendlyEnvSource, Settings, _json_or_raw, _normalize_url_collection


@pytest.mark.unit
def test_json_or_raw_returns_non_string_values():
    payload = {"a": 1}
    assert _json_or_raw(payload) is payload


@pytest.mark.unit
def test_raw_friendly_env_source_skips_decode_when_no_decode():
    source = RawFriendlyEnvSource(Settings)
    field = type("Field", (), {"metadata": [NoDecode]})
    value = source.decode_complex_value("field", field, "raw")
    assert value == "raw"


@pytest.mark.unit
def test_settings_validation_rejects_invalid_concurrency():
    with pytest.raises(ValueError, match="CRAWLER_MIN_CONCURRENCY"):
        Settings(
            docs_name="Test",
            docs_sync_enabled=False,
            crawler_min_concurrency=10,
            crawler_max_concurrency=5,
        )


@pytest.mark.unit
def test_settings_validation_rejects_concurrency_over_sessions():
    with pytest.raises(ValueError, match="CRAWLER_MAX_CONCURRENCY"):
        Settings(
            docs_name="Test",
            docs_sync_enabled=False,
            crawler_max_concurrency=99,
            crawler_max_sessions=10,
        )


@pytest.mark.unit
def test_settings_fallback_extractor_requires_endpoint():
    with pytest.raises(ValueError, match="endpoint is not configured"):
        Settings(
            docs_name="Test",
            docs_sync_enabled=False,
            fallback_extractor_enabled=True,
            fallback_extractor_endpoint="",
        )


@pytest.mark.unit
def test_settings_warm_fallback_endpoint_reports_unreachable(monkeypatch):
    Settings._validated_fallback_endpoints.clear()

    def _raise(*_args, **_kwargs):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "head", _raise)

    with pytest.raises(ValueError, match="not reachable"):
        Settings(
            docs_name="Test",
            docs_sync_enabled=False,
            fallback_extractor_enabled=True,
            fallback_extractor_endpoint="http://example.com",
        )


@pytest.mark.unit
def test_should_process_url_rejects_empty():
    settings = Settings(docs_name="Test", docs_sync_enabled=False)
    assert settings.should_process_url("") is False


@pytest.mark.unit
def test_normalize_url_collection_none_returns_empty():
    assert _normalize_url_collection(None) == []
