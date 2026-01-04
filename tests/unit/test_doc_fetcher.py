"""Unit tests covering AsyncDocFetcher fallback behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.utils.doc_fetcher import AsyncDocFetcher
from docs_mcp_server.utils.models import DocPage


class _StubResponse:
    """Minimal aiohttp response lookalike for fallback tests."""

    def __init__(self, status: int, json_data: dict | None = None, text_data: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self) -> dict:
        return self._json_data

    async def text(self) -> str:
        return self._text_data


class _StubSession:
    """Async session that replays predefined responses."""

    def __init__(self, responses: list[_StubResponse | Exception]):
        self._responses = list(responses)
        self.post_calls: list[tuple[str, dict]] = []

    async def post(self, endpoint: str, *, json: dict, headers: dict, timeout):
        self.post_calls.append((endpoint, json))
        if not self._responses:
            raise RuntimeError("stub session exhausted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def settings_factory(monkeypatch):
    """Provide helper to build Settings instances without network warmups."""

    monkeypatch.setattr(Settings, "_warm_fallback_endpoint", lambda self, endpoint: None)

    def _factory(**overrides) -> Settings:
        base = {
            "docs_name": "Example",
            "docs_sitemap_url": "",
            "docs_entry_url": "",
            "docs_sync_enabled": False,
            "fallback_extractor_enabled": True,
            "fallback_extractor_endpoint": "http://fallback:13005/",
        }
        base.update(overrides)
        return Settings(**base)

    return _factory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_page_returns_primary_result_without_fallback(settings_factory):
    """Primary extraction short-circuits fallback when it succeeds."""

    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = object()
    fetcher.playwright_fetcher = object()

    primary_page = DocPage(url="https://example.com/page", title="Primary", content="Body")

    fetcher._apply_rate_limit = AsyncMock()
    fetcher._fetch_direct_markdown = AsyncMock(return_value=None)
    fetcher._fetch_and_extract = AsyncMock(return_value=primary_page)
    fetcher._fetch_with_fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))

    result = await fetcher.fetch_page(primary_page.url)

    assert result == primary_page
    fetcher._fetch_with_fallback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_with_fallback_returns_doc_page(settings_factory):
    """Fallback HTTP endpoint payload converts into DocPage instances."""

    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = _StubSession(
        [
            _StubResponse(
                200,
                {
                    "markdown": "# From fallback\nBody",
                    "title": "From fallback",
                    "excerpt": "Body",
                },
            )
        ]
    )

    page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

    assert page is not None
    assert page.title == "From fallback"
    assert reason is None
    metrics = fetcher.get_fallback_metrics()
    assert metrics["fallback_attempts"] == 1
    assert metrics["fallback_successes"] == 1
    assert metrics["fallback_failures"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_with_fallback_reports_failure_reason(settings_factory):
    """Fallback failures bubble status details for scheduler telemetry."""

    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = _StubSession([_StubResponse(500, text_data="bad request")])
    fetcher.fallback_max_retries = 0

    page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

    assert page is None
    assert reason is not None and "status=500" in reason
    metrics = fetcher.get_fallback_metrics()
    assert metrics["fallback_attempts"] == 1
    assert metrics["fallback_successes"] == 0
    assert metrics["fallback_failures"] == 1
