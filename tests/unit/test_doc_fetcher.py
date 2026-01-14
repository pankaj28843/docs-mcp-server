"""Unit tests covering AsyncDocFetcher fallback behavior."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.utils import doc_fetcher as doc_fetcher_module
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


class _StubGetResponse:
    def __init__(self, status: int, text_data: str) -> None:
        self.status = status
        self._text_data = text_data

    async def text(self) -> str:
        return self._text_data


class _StubGetSession:
    def __init__(self, response: _StubGetResponse) -> None:
        self._response = response

    async def get(self, _url: str):
        return self._response


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
async def test_create_session_sets_headers(settings_factory, monkeypatch):
    settings = settings_factory()
    monkeypatch.setattr(Settings, "get_random_user_agent", lambda _self: "agent")
    fetcher = AsyncDocFetcher(settings)

    fetcher._create_session()

    assert fetcher.session is not None
    await fetcher._close_session()


@pytest.mark.unit
def test_create_session_builds_aiohttp_components(settings_factory, monkeypatch):
    settings = settings_factory()
    monkeypatch.setattr(Settings, "get_random_user_agent", lambda _self: "agent")
    fetcher = AsyncDocFetcher(settings)

    created: dict[str, object] = {}

    def _timeout(**kwargs):
        created["timeout"] = kwargs
        return "timeout"

    def _connector(**kwargs):
        created["connector"] = kwargs
        return "connector"

    aiohttp_stub = types.SimpleNamespace(
        ClientTimeout=_timeout,
        TCPConnector=_connector,
    )
    monkeypatch.setattr(doc_fetcher_module, "aiohttp", aiohttp_stub)
    monkeypatch.setitem(fetcher._build_session_components.__globals__, "aiohttp", aiohttp_stub)

    timeout, connector, headers = fetcher._build_session_components()

    assert timeout == "timeout"
    assert connector == "connector"
    assert created["timeout"]["total"] == fetcher.http_timeout
    assert created["connector"]["limit"] == fetcher.max_concurrent_requests
    assert headers["User-Agent"] == "agent"


@pytest.mark.unit
def test_create_session_assigns_session(settings_factory):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)

    fetcher._create_session()

    assert fetcher.session is not None
    if hasattr(fetcher.session, "close"):
        asyncio.run(fetcher._close_session())
    else:
        fetcher.session = None


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_with_fallback_records_disabled_event(settings_factory, monkeypatch):
    settings = settings_factory(fallback_extractor_enabled=False)
    fetcher = AsyncDocFetcher(settings)

    recorded = []

    class _Span:
        def is_recording(self):
            return True

        def add_event(self, name, _attrs):
            recorded.append(name)

    monkeypatch.setattr("docs_mcp_server.utils.doc_fetcher.trace.get_current_span", lambda: _Span())

    page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

    assert page is None
    assert reason == "fallback_disabled"
    assert "fetch.fallback.disabled" in recorded


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_with_fallback_records_skip_event(settings_factory, monkeypatch):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)

    recorded = []

    class _Span:
        def is_recording(self):
            return True

        def add_event(self, name, _attrs):
            recorded.append(name)

    monkeypatch.setattr("docs_mcp_server.utils.doc_fetcher.trace.get_current_span", lambda: _Span())

    page, reason = await fetcher._fetch_with_fallback("https://example.com/_static/app.js")

    assert page is None
    assert reason == "fallback_skipped_asset"
    assert "fetch.fallback.skipped" in recorded


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_with_fallback_propagates_cancelled(settings_factory):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)

    class _CancelSession:
        async def post(self, *_args, **_kwargs):
            raise asyncio.CancelledError

    fetcher.session = _CancelSession()
    fetcher.fallback_max_retries = 0

    with pytest.raises(asyncio.CancelledError):
        await fetcher._fetch_with_fallback("https://example.com/doc")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_direct_markdown_returns_none_when_candidate_missing(settings_factory):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md"

    assert await fetcher._fetch_direct_markdown("https://example.com/") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_direct_markdown_creates_session(settings_factory, monkeypatch):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md"
    response = _StubGetResponse(status=200, text_data="# Title")
    session = _StubGetSession(response)

    def _create_session():
        fetcher.session = session

    monkeypatch.setattr(fetcher, "_create_session", _create_session)

    page = await fetcher._fetch_direct_markdown("https://example.com/page.html")

    assert page is not None
    assert page.title == "Title"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_direct_markdown_returns_none_for_empty_markdown(settings_factory):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md"
    fetcher.session = _StubGetSession(_StubGetResponse(status=200, text_data=""))

    assert await fetcher._fetch_direct_markdown("https://example.com/page.html") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_direct_markdown_returns_none_for_empty_prepared(settings_factory):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md"
    fetcher.session = _StubGetSession(_StubGetResponse(status=200, text_data="\ufeff"))

    assert await fetcher._fetch_direct_markdown("https://example.com/page.html") is None
