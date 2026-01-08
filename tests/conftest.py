"""Shared test fixtures and configuration."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# Complete test environment that overrides ALL possible config values
TEST_ENV = {
    # Required values
    "DOCS_NAME": "Test Docs",
    "DOCS_SITEMAP_URL": "https://example.com/sitemap.xml",
    # Core operational settings
    "HTTP_TIMEOUT": "30",
    "MAX_CONCURRENT_REQUESTS": "5",
    "REQUEST_DELAY_MS": "100",
    "OPERATION_MODE": "online",
    "LOG_LEVEL": "info",
    "MIN_FETCH_INTERVAL_HOURS": "24",
    "SNIPPET_LENGTH": "2000",
    "TOKEN_CANDIDATE_CAP": "25",
    "MIN_COVERAGE_RATIO": "0.5",
    # Scoring weights
    "EXACT_PHRASE_WEIGHT": "10.0",
    "EXACT_PHRASE_TITLE_WEIGHT": "15.0",
    "ALL_TOKENS_WEIGHT": "5.0",
    "PARTIAL_TOKENS_WEIGHT": "1.0",
    "TOKEN_FREQUENCY_BONUS": "0.1",
    "TITLE_MATCH_BONUS": "2.0",
    # Sync settings
    "DOCS_SYNC_ENABLED": "false",  # Disable sync in tests
    "DEFAULT_SYNC_INTERVAL_DAYS": "7",
    "MAX_SYNC_INTERVAL_DAYS": "30",
    # Crawler settings
    "MAX_CRAWL_PAGES": "1000",
    "ENABLE_CRAWLER": "false",
    # Server settings
    "MCP_HOST": "127.0.0.1",
    "MCP_PORT": "15005",
    "CONTAINER": "false",
    "DOCS_MCP_PRELOAD": "false",
    "UVICORN_WORKERS": "1",
    "UVICORN_LIMIT_CONCURRENCY": "100",
    "UVICORN_KEEP_ALIVE": "5",
    # URL filtering
    "URL_WHITELIST_PREFIXES": "",
    "URL_BLACKLIST_PREFIXES": "",
    # Proxy settings - ensure they're cleared for tests
    "http_proxy": "",
    "https_proxy": "",
    "all_proxy": "",
    "no_proxy": "",
}


# Set environment variables immediately when conftest.py is loaded
for key, value in TEST_ENV.items():
    os.environ[key] = value

# Now we can safely import config-dependent modules
from docs_mcp_server.utils.models import DocPage, ReadabilityContent, SearchResult


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Clean environment variables before each test and set test defaults."""
    # Set test environment variables
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def stub_doc_fetcher_session(monkeypatch):
    """Prevent real aiohttp sessions in tests unless explicitly stubbed."""
    from types import SimpleNamespace

    from docs_mcp_server.utils import doc_fetcher

    async def _session_used(*_args, **_kwargs):
        raise RuntimeError("test must stub AsyncDocFetcher.session explicitly")

    def _fake_create_session(self):
        self.session = SimpleNamespace(
            get=AsyncMock(side_effect=_session_used),
            post=AsyncMock(side_effect=_session_used),
            close=AsyncMock(),
        )

    monkeypatch.setattr(doc_fetcher.AsyncDocFetcher, "_create_session", _fake_create_session)


@pytest.fixture
def mock_doc_fetcher():
    """Mock AsyncDocFetcher."""
    mock = AsyncMock()
    mock.__aenter__.return_value = mock
    mock.__aexit__.return_value = None

    # Mock successful fetch_page response
    readability_content = ReadabilityContent(
        raw_html="<html><body><h1>Test</h1></body></html>",
        extracted_content="Test content",
        processed_markdown="# Test\n\nContent",
        excerpt="Test excerpt",
        score=0.8,
        success=True,
        extraction_method="readability",
    )

    mock_doc = DocPage(
        url="https://example.com/test",
        title="Test Document",
        content="# Test\n\nContent",
        readability_content=readability_content,
    )

    mock.fetch_page.return_value = mock_doc
    return mock


@pytest.fixture
def sample_search_results():
    """Sample search results for testing."""
    return [
        SearchResult(
            url="https://example.com/doc1",
            title="First Document",
            score=0.95,
            snippet="This is the first document content",
        ),
        SearchResult(
            url="https://example.com/doc2",
            title="Second Document",
            score=0.85,
            snippet="This is the second document content",
        ),
    ]


@pytest.fixture
def sample_doc_page():
    """Sample DocPage for testing."""
    readability_content = ReadabilityContent(
        raw_html="<html><body><h1>Sample</h1><p>Content</p></body></html>",
        extracted_content="Sample\n\nContent",
        processed_markdown="# Sample\n\nContent",
        excerpt="Sample content excerpt",
        score=0.9,
        success=True,
        extraction_method="readability",
    )

    return DocPage(
        url="https://example.com/sample",
        title="Sample Document",
        content="# Sample\n\nContent",
        readability_content=readability_content,
    )


@pytest.fixture
def mock_sync_status():
    """Mock sync status data."""
    return {"sync_enabled": True, "last_sync": datetime.now(timezone.utc).isoformat()}


@pytest.fixture
def mock_health_data():
    """Mock health check data."""
    return {
        "status": "healthy",
        "cache": {"total_documents": 100, "index_size_bytes": 1048576},
        "tools": {"search_test_docs_docs": "available", "fetch_test_docs_doc": "available"},
    }


@pytest.fixture
def mock_mcp_tools():
    """Mock MCP tools response."""
    return {
        "tools": [
            {"name": "search_test_docs_docs", "description": "Search Test Docs documentation"},
            {"name": "fetch_test_docs_doc", "description": "Fetch a specific Test Docs document"},
        ]
    }


@pytest.fixture
def mock_cache_stats():
    """Mock cache statistics."""
    return {"total_documents": 150, "index_size_bytes": 2097152, "last_updated": datetime.now(timezone.utc).isoformat()}


@pytest.fixture
def mock_cache_service():
    """Mock CacheService for testing."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    mock.ttl_days = 30
    mock.min_fetch_interval_hours = 24.0
    return mock


@pytest.fixture
def mock_search_service():
    """Mock SearchService for testing."""
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.token_candidate_cap = 100
    mock.snippet_length = 200
    return mock


@pytest.fixture
def mock_scheduler_service():
    """Mock SchedulerService for testing."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    mock.sync_enabled = True
    return mock


@pytest.fixture
def test_settings():
    """Fixture that returns Settings with explicit parameters for type checking.

    While Settings() works fine in tests due to environment variables set in conftest.py,
    Pylance needs explicit parameters for static type checking.
    """
    from docs_mcp_server.config import Settings

    return Settings(
        docs_name="Test Docs",
        docs_sitemap_url="https://example.com/sitemap.xml",
    )
