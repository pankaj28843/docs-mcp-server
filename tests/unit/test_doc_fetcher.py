"""Unit tests covering AsyncDocFetcher fallback behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
import types
from unittest.mock import AsyncMock

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.utils import doc_fetcher as doc_fetcher_module
from docs_mcp_server.utils.doc_fetcher import AsyncDocFetcher, DocFetchError
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_preserves_document_sections_and_highlighted_code(settings_factory):
    source = """<html><head><title>Routing guide</title></head><body>
    <nav>Site navigation</nav><main><article>
    <h1>Routing guide</h1><p>Choose a model for each request.</p>
    <h2>Results</h2><table><thead><tr><th>Model</th><th>Cost</th></tr></thead>
    <tbody><tr><td>Small</td><td>27%</td></tr></tbody></table>
    <h2>Quick start</h2><pre class="language-yaml"><code><span>models:</span><br><span>  - name: small</span><br><span>    enabled: true</span></code></pre>
    <h2>Explore</h2><a href="/setup">Setup instructions</a>
    <h2>Release posts</h2><p>Read the feature history.</p>
    <pre><code>curl example.test \\\n  --header 'Accept: application/json'</code></pre>
    </article></main><footer>Site footer</footer></body></html>"""
    fetcher = AsyncDocFetcher(settings_factory())
    fetcher.session = _StubGetSession(_StubGetResponse(200, source))

    page = await fetcher.fetch_page("https://example.test/guide")

    assert page is not None
    for heading in ("Routing guide", "Results", "Quick start", "Explore", "Release posts"):
        assert heading in page.content
    assert "Choose a model for each request." in page.content
    assert "<th>Model</th><th>Cost</th>" in page.content
    assert "<td>Small</td><td>27%</td>" in page.content
    assert "[Setup instructions](https://example.test/setup)" in page.content
    assert "models:\n  - name: small\n    enabled: true" in page.content
    assert "curl example.test \\\n  --header 'Accept: application/json'" in page.content
    assert "Site navigation" not in page.content
    assert "Site footer" not in page.content


@pytest.mark.unit
def test_markdown_normalization_preserves_semantic_whitespace(settings_factory):
    fetcher = AsyncDocFetcher(settings_factory())
    source = (
        "```yaml\nmodels:\n  - name: small\n    value: 'a    b'\n\n\n```\n\n    indented code\n\n- item\n  - child\n"
    )
    assert fetcher._clean_markdown(source) == source.rstrip("\n")
    assert fetcher._prepare_direct_markdown(source) == source


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_article_survives_static_and_rendered_fetch(settings_factory):
    source = (Path(__file__).parents[1] / "fixtures/litellm_auto_router.html").read_text()
    url = "https://docs.litellm.ai/docs/auto_router/"
    for rendered in (False, True):
        browser = types.SimpleNamespace(
            fetch=AsyncMock(return_value=types.SimpleNamespace(html=source, status_code=200))
        )
        fetcher = AsyncDocFetcher(settings_factory(), browser_runtime=browser)
        fetcher.session = _StubGetSession(_StubGetResponse(200, "<html></html>" if rendered else source))

        page = await fetcher.fetch_page(url)

        assert page is not None
        assert page.url == url
        assert page.title == "Auto Router | liteLLM"
        for heading in ("Results", "Quick start", "Explore", "Release posts"):
            assert f"## {heading}" in page.content
        assert "272,876 production requests" in page.content
        assert "https://docs.litellm.ai/docs/auto_router/setup" in page.content
        assert "model_list:\n  - model_name: claude-haiku-4-5\n    litellm_params:" in page.content
        assert "          SIMPLE:    claude-haiku-4-5" in page.content
        assert '\n  -H "Authorization: Bearer $LITELLM_API_KEY"' in page.content
        assert page.content.count("```") == 4
        assert browser.fetch.await_count == int(rendered)


class _ProxyGetSession:
    def __init__(self, responses: dict[str | None, _StubGetResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str | None]] = []

    async def get(self, url: str, **kwargs):
        proxy = kwargs.get("proxy")
        self.calls.append((url, proxy))
        return self._responses[proxy]


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
    fetcher = AsyncDocFetcher(settings, browser_runtime=object())
    fetcher.session = object()

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
async def test_fetch_page_stops_after_markdown_proxy_pool_blocked(settings_factory):
    settings = settings_factory(article_proxies="http://bad:1")
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md.txt"
    fetcher.session = _ProxyGetSession(
        {
            "http://bad:1": _StubGetResponse(status=429, text_data="google.com/sorry unusual traffic"),
        }
    )

    fetcher._apply_rate_limit = AsyncMock()
    fetcher._fetch_static_html_and_extract = AsyncMock(side_effect=AssertionError("static fetch should not run"))
    fetcher._fetch_and_extract = AsyncMock(side_effect=AssertionError("browser should not run"))
    fetcher._fetch_with_fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))

    with pytest.raises(DocFetchError) as exc_info:
        await fetcher.fetch_page("https://example.com/page")

    assert exc_info.value.reason == "fetch_blocked"
    assert fetcher.session.calls == [("https://example.com/page.md.txt", "http://bad:1")]
    fetcher._fetch_static_html_and_extract.assert_not_awaited()
    fetcher._fetch_and_extract.assert_not_awaited()
    fetcher._fetch_with_fallback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_page_stops_after_static_proxy_pool_blocked(settings_factory):
    settings = settings_factory(article_proxies="http://bad:1")
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = _ProxyGetSession(
        {
            "http://bad:1": _StubGetResponse(status=429, text_data="google.com/sorry unusual traffic"),
        }
    )

    fetcher._apply_rate_limit = AsyncMock()
    fetcher._fetch_and_extract = AsyncMock(side_effect=AssertionError("browser should not run"))
    fetcher._fetch_with_fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))

    with pytest.raises(DocFetchError) as exc_info:
        await fetcher.fetch_page("https://example.com/page")

    assert exc_info.value.reason == "fetch_blocked"
    assert fetcher.session.calls == [("https://example.com/page", "http://bad:1")]
    fetcher._fetch_and_extract.assert_not_awaited()
    fetcher._fetch_with_fallback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_page_exhausts_all_static_proxies_before_blocking(settings_factory):
    proxies = [f"http://bad:{port}" for port in (18086, 18085, 8888, 8085)]
    settings = settings_factory(article_proxies=",".join(proxies))
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = _ProxyGetSession(
        {proxy: _StubGetResponse(status=429, text_data="google.com/sorry unusual traffic") for proxy in proxies}
    )

    fetcher._apply_rate_limit = AsyncMock()
    fetcher._fetch_and_extract = AsyncMock(side_effect=AssertionError("browser should not run"))
    fetcher._fetch_with_fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))

    with pytest.raises(DocFetchError) as exc_info:
        await fetcher.fetch_page("https://example.com/page")

    assert exc_info.value.reason == "fetch_blocked"
    assert fetcher.session.calls == [("https://example.com/page", proxy) for proxy in proxies]
    fetcher._fetch_and_extract.assert_not_awaited()
    fetcher._fetch_with_fallback.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_static_fetch_follows_same_origin_meta_refresh(settings_factory):
    fetcher = AsyncDocFetcher(settings_factory())
    fetcher.session = object()
    fetcher._fetch_text_with_proxy_pool = AsyncMock(
        side_effect=[
            (200, '<meta http-equiv="refresh" content="0;url=classes.html">'),
            (200, f"<html><title>Support Test APIs</title><body>{'documentation ' * 160}</body></html>"),
        ]
    )

    page = await fetcher._fetch_static_html_and_extract("https://example.com/reference/test/")

    assert page is not None
    assert page.url == "https://example.com/reference/test/"
    assert page.title == "Support Test APIs"
    assert fetcher._fetch_text_with_proxy_pool.await_args_list[1].args == (
        "https://example.com/reference/test/classes.html",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_page_stops_after_browser_proxy_pool_blocked(settings_factory):
    settings = settings_factory(article_proxies="http://bad:1")
    fetcher = AsyncDocFetcher(settings, browser_runtime=object())
    fetcher.session = object()

    fetcher._apply_rate_limit = AsyncMock()
    fetcher._fetch_direct_markdown = AsyncMock(return_value=None)
    fetcher._fetch_static_html_and_extract = AsyncMock(return_value=None)
    fetcher._fetch_and_extract = AsyncMock(
        side_effect=doc_fetcher_module.FetchBlockedError("All configured proxies were blocked")
    )
    fetcher._fetch_with_fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))

    with pytest.raises(DocFetchError) as exc_info:
        await fetcher.fetch_page("https://example.com/page")

    assert exc_info.value.reason == "fetch_blocked"
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
@pytest.mark.parametrize(
    ("title", "markdown"),
    [
        ("Verify you are human", "# Verify you are human\nEnable JavaScript and cookies to continue."),
        ("404 | Page Not Found | Firebase", "### 404\n\nSorry, we couldn't find that page."),
    ],
)
async def test_fetch_with_fallback_rejects_non_document_pages(settings_factory, title, markdown):
    settings = settings_factory()
    fetcher = AsyncDocFetcher(settings)
    fetcher.session = _StubSession([_StubResponse(200, {"markdown": markdown, "title": title, "excerpt": markdown})])
    fetcher.fallback_max_retries = 0

    page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

    assert page is None
    assert reason == "fallback returned empty payload"
    assert fetcher.get_fallback_metrics() == {
        "fallback_attempts": 1,
        "fallback_successes": 0,
        "fallback_failures": 1,
    }


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_direct_markdown_rotates_blocked_proxy(settings_factory):
    settings = settings_factory(article_proxies="http://bad:1,http://good:2")
    fetcher = AsyncDocFetcher(settings)
    fetcher.markdown_url_suffix = ".md.txt"
    fetcher.session = _ProxyGetSession(
        {
            "http://bad:1": _StubGetResponse(status=429, text_data="google.com/sorry unusual traffic"),
            "http://good:2": _StubGetResponse(status=200, text_data="# Title\n\nBody\n"),
        }
    )

    page = await fetcher._fetch_direct_markdown("https://example.com/page")

    assert page is not None
    assert page.title == "Title"
    assert fetcher.session.calls == [
        ("https://example.com/page.md.txt", "http://bad:1"),
        ("https://example.com/page.md.txt", "http://good:2"),
    ]
    assert fetcher._proxy_candidates()[0] == "http://good:2"
