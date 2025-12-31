"""Centralized configuration for docs-mcp-server using Pydantic Settings."""

import random
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strictly typed configuration loaded from environment variables.

    All environment variables are validated at startup with proper types.
    This replaces the venvalid-based configuration system with Pydantic's
    more strict and feature-rich validation system.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        validate_default=True,
        extra="ignore",  # Ignore extra env vars not defined in model
    )

    # At least one of these must be provided (validated in model_validator)
    docs_sitemap_url: str = Field(default="", description="Comma-separated sitemap URLs for documentation discovery")
    docs_entry_url: str = Field(
        default="", description="Comma-separated entry URLs for crawler-based documentation discovery"
    )

    markdown_url_suffix: str = Field(
        default="",
        description="Suffix appended to discovered URLs when a raw Markdown mirror is available (e.g., '.md')",
    )

    preserve_query_strings: bool = Field(
        default=True,
        description="Keep query parameters in canonical filesystem paths so variant URLs stay isolated",
    )

    # HTTP/Request settings
    http_timeout: int = Field(default=30, ge=1, description="HTTP request timeout in seconds")
    max_concurrent_requests: int = Field(default=10, ge=1, description="Maximum concurrent HTTP requests")
    request_delay_ms: int = Field(default=100, ge=0, description="Delay between requests in milliseconds")

    # Content settings
    snippet_length: int = Field(default=2000, ge=100, description="Maximum snippet length for search results")

    # Sync settings
    docs_sync_enabled: bool = Field(default=True, description="Enable background synchronization")
    min_fetch_interval_hours: int = Field(default=24, ge=1, description="Minimum hours between fetches")
    default_sync_interval_days: int = Field(default=7, ge=1, description="Default sync interval in days")
    max_sync_interval_days: int = Field(default=30, ge=1, description="Maximum sync interval in days")
    semantic_cache_enabled: bool = Field(
        default=True,
        description="Enable semantic similarity fallback for cache hits to reduce redundant fetches",
    )
    semantic_cache_similarity_threshold: float = Field(
        default=0.82,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity required before serving a semantic cache result",
    )
    semantic_cache_candidate_limit: int = Field(
        default=200,
        ge=1,
        description="Maximum number of cached documents to scan when looking for semantic hits",
    )
    semantic_cache_return_limit: int = Field(
        default=3,
        ge=1,
        description="Maximum number of semantic cache hits returned for downstream inspection",
    )

    # Crawler settings
    max_crawl_pages: int = Field(default=1000, ge=1, description="Maximum pages to crawl")
    enable_crawler: bool = Field(default=False, description="Enable link crawler for discovery")
    crawler_playwright_first: bool = Field(
        default=True, description="Use Playwright as primary crawler method (bypasses bot protection)"
    )

    # Server settings
    mcp_host: str = Field(default="127.0.0.1", description="MCP server host")
    mcp_port: int = Field(default=15005, ge=1, le=65535, description="MCP server port")
    uvicorn_workers: int = Field(default=1, ge=1, description="Number of Uvicorn workers")
    uvicorn_limit_concurrency: int = Field(default=100, ge=1, description="Uvicorn concurrency limit")

    # Documentation naming
    docs_name: str = Field(default="Django REST Framework", description="Documentation name")

    # Operation mode
    operation_mode: Literal["online", "offline"] = Field(
        default="online", description="Operation mode: online (with sync) or offline (cache only)"
    )

    # Logging
    log_level: str = Field(default="info", description="Logging level")

    # URL filtering
    url_whitelist_prefixes: str = Field(default="", description="Comma-separated URL prefixes to include")
    url_blacklist_prefixes: str = Field(default="", description="Comma-separated URL prefixes to exclude")

    # Security
    mask_error_details: bool = Field(
        default=True, description="Mask internal error details in responses (security best practice)"
    )

    # Class constant for user agents
    USER_AGENTS: list[str] = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.6 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:142.0) Gecko/20100101 Firefox/142.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:143.0) Gecko/20100101 Firefox/143.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ]

    @model_validator(mode="after")
    def _check_docs_url(self) -> "Settings":
        # For tenants with automatic sync enabled, require at least one URL source
        # This validation only applies when sync is actually enabled
        if self.docs_sync_enabled:
            if not self.docs_sitemap_url and not self.docs_entry_url:
                raise ValueError(
                    "At least one of DOCS_SITEMAP_URL or DOCS_ENTRY_URL must be set for sync-enabled tenants. "
                    "Use DOCS_SITEMAP_URL for sitemap.xml files, or DOCS_ENTRY_URL for documentation root pages "
                    "(e.g., index.html or entry point). Multiple URLs can be specified as comma-separated values."
                )
        return self

    def get_random_user_agent(self) -> str:
        """Get a random User-Agent from the pool."""
        return random.choice(self.USER_AGENTS)

    def is_offline_mode(self) -> bool:
        """Check if running in offline mode.

        Returns:
            True if mode is "offline", False if "online"
        """
        return self.operation_mode == "offline"

    def get_url_whitelist_prefixes(self) -> list[str]:
        """Get list of URL prefixes to whitelist (only include these)."""
        if not self.url_whitelist_prefixes:
            return []
        return [prefix.strip() for prefix in self.url_whitelist_prefixes.split(",") if prefix.strip()]

    def get_url_blacklist_prefixes(self) -> list[str]:
        """Get list of URL prefixes to blacklist (exclude these)."""
        if not self.url_blacklist_prefixes:
            return []
        return [prefix.strip() for prefix in self.url_blacklist_prefixes.split(",") if prefix.strip()]

    def get_docs_sitemap_urls(self) -> list[str]:
        """Get list of documentation sitemap URLs (comma-separated).

        Returns:
            List of sitemap URLs, empty if none specified
        """
        if not self.docs_sitemap_url:
            return []
        return [url.strip() for url in self.docs_sitemap_url.split(",") if url.strip()]

    def get_docs_entry_urls(self) -> list[str]:
        """Get list of documentation entry/root URLs (comma-separated).

        This is used for documentation sites that don't have a sitemap
        or have incomplete sitemaps. The crawler will start from these URLs
        and discover all linked pages.

        Returns:
            List of entry URLs, empty if none specified
        """
        if not self.docs_entry_url:
            return []
        return [url.strip() for url in self.docs_entry_url.split(",") if url.strip()]

    def should_process_url(self, url: str) -> bool:
        """Check if a URL should be processed based on whitelist/blacklist.

        Args:
            url: URL to check

        Returns:
            True if URL should be processed, False otherwise

        Logic:
            1. If whitelist is defined, URL must match at least one whitelist prefix
            2. If blacklist is defined, URL must not match any blacklist prefix
            3. If both defined, whitelist is checked first, then blacklist
            4. If neither defined, all URLs are allowed
        """
        # Skip None or empty URLs
        if not url:
            return False

        whitelist = self.get_url_whitelist_prefixes()
        blacklist = self.get_url_blacklist_prefixes()

        # If whitelist is defined, URL must match at least one prefix
        if whitelist and not any(url.startswith(prefix) for prefix in whitelist):
            return False

        # If blacklist is defined, URL must not match any prefix
        if blacklist and any(url.startswith(prefix) for prefix in blacklist):
            return False

        return True
