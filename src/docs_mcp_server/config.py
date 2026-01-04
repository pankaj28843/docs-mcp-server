"""Centralized configuration for docs-mcp-server using Pydantic Settings."""

import json
import os
import random
from typing import ClassVar, Literal

import httpx
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource
from pydantic_settings.sources.types import ForceDecode, NoDecode


def _json_or_raw(value: object) -> object:
    """Decode JSON values but fall back to raw input on errors.

    Env providers expect complex fields (like list[str]) to be encoded as JSON,
    but our configuration still accepts simple comma-separated strings. This
    loader preserves backwards compatibility by returning the raw input when
    JSON decoding fails so downstream validators can normalize the value.
    """

    if not isinstance(value, (str, bytes, bytearray)):
        return value

    text = value.decode() if isinstance(value, (bytes, bytearray)) else value
    try:
        return json.loads(text)
    except ValueError:
        return text


class RawFriendlyEnvSource(EnvSettingsSource):
    """Env source that tolerates comma-separated strings for complex fields."""

    def decode_complex_value(self, field_name, field, value):  # type: ignore[override]
        if field and (
            NoDecode in field.metadata
            or (self.config.get("enable_decoding") is False and ForceDecode not in field.metadata)
        ):
            return value

        return _json_or_raw(value)


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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # We replace env_settings with RawFriendlyEnvSource for backwards compat
        del env_settings  # Silence unused-variable lint without renaming
        return (
            init_settings,
            RawFriendlyEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # At least one of these must be provided (validated in model_validator)
    docs_sitemap_url: list[str] = Field(
        default_factory=list,
        description="List of sitemap URLs (comma-separated env values remain supported)",
    )
    docs_entry_url: list[str] = Field(
        default_factory=list,
        description="List of entry URLs for crawler discovery (comma-separated env values remain supported)",
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
    crawler_min_concurrency: int = Field(
        default=5,
        ge=1,
        description="Minimum concurrent crawler workers when adaptive throttling contracts",
    )
    crawler_max_concurrency: int = Field(
        default=20,
        ge=1,
        description="Maximum concurrent crawler workers when no throttling is detected",
    )
    crawler_lock_ttl_seconds: int = Field(
        default=180,
        ge=60,
        description="TTL for crawler lock leases guarding multi-worker deployments",
    )
    crawler_max_sessions: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Hard ceiling for total crawler sessions inside a single process",
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

    _validated_fallback_endpoints: ClassVar[set[str]] = set()

    # Fallback article extractor
    fallback_extractor_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("fallback_extractor_enabled", "DOCS_FALLBACK_EXTRACTOR_ENABLED"),
        description="Enable HTTP fallback when in-process extraction fails",
    )
    fallback_extractor_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("fallback_extractor_endpoint", "DOCS_FALLBACK_EXTRACTOR_ENDPOINT"),
        description='Endpoint accepting POST {"url": ...} payloads (e.g., http://10.20.30.1:13005/)',
    )
    fallback_extractor_timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=120,
        validation_alias=AliasChoices("fallback_extractor_timeout_seconds", "DOCS_FALLBACK_EXTRACTOR_TIMEOUT_SECONDS"),
        description="Timeout applied to fallback HTTP requests",
    )
    fallback_extractor_batch_size: int = Field(
        default=1,
        ge=1,
        le=8,
        validation_alias=AliasChoices("fallback_extractor_batch_size", "DOCS_FALLBACK_EXTRACTOR_BATCH_SIZE"),
        description="Maximum URLs sent per fallback call (single-url pipeline by default)",
    )
    fallback_extractor_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias=AliasChoices("fallback_extractor_max_retries", "DOCS_FALLBACK_EXTRACTOR_MAX_RETRIES"),
        description="Retry attempts when fallback extraction fails",
    )
    fallback_extractor_api_key_env: str = Field(
        default="",
        validation_alias=AliasChoices("fallback_extractor_api_key_env", "DOCS_FALLBACK_EXTRACTOR_API_KEY_ENV"),
        description="Environment variable name that stores the fallback API token",
    )
    fallback_extractor_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("fallback_extractor_api_key", "DOCS_FALLBACK_EXTRACTOR_API_KEY"),
        description="Resolved fallback API token (derived from env if not provided explicitly)",
    )

    @field_validator("docs_sitemap_url", "docs_entry_url", mode="before")
    @classmethod
    def _normalize_docs_urls(cls, value: object) -> list[str]:
        return _normalize_url_collection(value)

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

        if self.crawler_min_concurrency > self.crawler_max_concurrency:
            raise ValueError("CRAWLER_MIN_CONCURRENCY cannot exceed CRAWLER_MAX_CONCURRENCY")

        if self.crawler_max_concurrency > self.crawler_max_sessions:
            raise ValueError("CRAWLER_MAX_CONCURRENCY cannot exceed CRAWLER_MAX_SESSIONS (hard cap 100)")

        self._validate_fallback_extractor()
        return self

    def _validate_fallback_extractor(self) -> None:
        if not self.fallback_extractor_enabled:
            self.fallback_extractor_api_key = self.fallback_extractor_api_key or None
            return

        endpoint = (self.fallback_extractor_endpoint or "").strip()
        if not endpoint:
            raise ValueError("Fallback extractor enabled but endpoint is not configured")
        self.fallback_extractor_endpoint = endpoint

        resolved_key = (self.fallback_extractor_api_key or "").strip() or None
        env_name = (self.fallback_extractor_api_key_env or "").strip()
        if not resolved_key and env_name:
            resolved_key = os.getenv(env_name)
            if not resolved_key:
                raise ValueError(
                    f"Fallback extractor enabled but environment variable '{env_name}' is not set",
                )

        self.fallback_extractor_api_key = resolved_key

        if endpoint not in self._validated_fallback_endpoints:
            self._warm_fallback_endpoint(endpoint)
            self._validated_fallback_endpoints.add(endpoint)

    def _warm_fallback_endpoint(self, endpoint: str) -> None:
        try:
            response = httpx.head(
                endpoint,
                timeout=min(float(self.fallback_extractor_timeout_seconds), 10.0),
            )
            # Any response indicates the host is reachable; we only care about connection errors
            _ = response.status_code
        except httpx.HTTPError as exc:
            raise ValueError(f"Fallback extractor endpoint '{endpoint}' is not reachable: {exc}") from exc

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
        return list(self.docs_sitemap_url)

    def get_docs_entry_urls(self) -> list[str]:
        """Get list of documentation entry/root URLs (comma-separated).

        This is used for documentation sites that don't have a sitemap
        or have incomplete sitemaps. The crawler will start from these URLs
        and discover all linked pages.

        Returns:
            List of entry URLs, empty if none specified
        """
        return list(self.docs_entry_url)

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


def _normalize_url_collection(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        normalized: list[str] = []
        for item in value:
            if not item:
                continue
            normalized_item = str(item).strip()
            if normalized_item:
                normalized.append(normalized_item)
        return normalized
    normalized_value = str(value).strip()
    return [normalized_value] if normalized_value else []
