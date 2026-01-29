"""Multi-tenant deployment configuration using Pydantic.

This module defines the schema for deploying multiple documentation sets
in a single container with isolated services per tenant.

Architecture:
- Each tenant (doc set) gets its own route prefix: /<codename>/mcp
- Services are cached per tenant for performance
- Configuration validates at startup (fail fast)

Following patterns from Cosmic Python + Pydantic best practices.
"""

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from cron_converter import Cron
from pydantic import BaseModel, Field, field_validator, model_validator


def _split_csv(raw_value: str | None) -> list[str]:
    """Split comma-separated config strings into trimmed entries."""

    if not raw_value:
        return []
    return [entry.strip() for entry in raw_value.split(",") if entry.strip()]


def _normalize_url_collection(value: object) -> list[str]:
    """Normalize strings or iterables into a trimmed list of URLs."""

    if value is None or value == "":
        return []

    if isinstance(value, str):
        return _split_csv(value)

    if isinstance(value, (list, tuple, set)):
        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            stripped = str(item).strip()
            if stripped:
                normalized.append(stripped)
        return normalized

    raise TypeError("Expected string, list, tuple, or set when parsing URL collections")


class SearchRankingConfig(BaseModel):
    """Ranking parameters exposed to tenants while keeping safe defaults."""

    model_config = {"extra": "forbid"}

    bm25_k1: Annotated[
        float,
        Field(
            ge=0.5,
            le=3.0,
            description="BM25/BM25F saturation parameter (see Whoosh docs)",
            examples=[1.2],
        ),
    ] = 1.2

    bm25_b: Annotated[
        float,
        Field(
            ge=0.1,
            le=1.0,
            description="BM25/BM25F length normalization parameter",
            examples=[0.75],
        ),
    ] = 0.75


class SearchSnippetConfig(BaseModel):
    """Snippet/highlight preferences per tenant."""

    model_config = {"extra": "forbid"}

    style: Annotated[
        Literal["plain", "html"],
        Field(
            description="Snippet formatter style. HTML emits <mark> tags; plain uses ASCII brackets.",
        ),
    ] = "plain"

    fragment_char_limit: Annotated[
        int,
        Field(
            ge=80,
            le=2000,
            description="Maximum characters per highlighted fragment",
        ),
    ] = 240

    max_fragments: Annotated[
        int,
        Field(
            ge=1,
            le=5,
            description="Maximum number of fragments per result",
        ),
    ] = 2

    surrounding_context_chars: Annotated[
        int,
        Field(
            ge=40,
            le=800,
            description="Characters of additional context to keep around each fragment",
        ),
    ] = 120


class SearchBoostConfig(BaseModel):
    """Field-level boost settings for BM25F scoring."""

    model_config = {"extra": "forbid"}

    title: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Relative boost applied to title field tokens",
        ),
    ] = 2.5

    headings_h1: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for H1 headings (highest prominence)",
        ),
    ] = 2.5

    headings_h2: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for H2 headings (section level)",
        ),
    ] = 2.0

    headings: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for H3+ headings (subsections)",
        ),
    ] = 1.5

    body: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Base weight for document body",
        ),
    ] = 1.0

    code: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for fenced code blocks or inline code",
        ),
    ] = 1.2

    path: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for path/slug level matches",
        ),
    ] = 1.5

    url: Annotated[
        float,
        Field(
            ge=0.0,
            le=5.0,
            description="Boost for URL path segment matches",
        ),
    ] = 1.5


class SearchConfig(BaseModel):
    """Search configuration surfaced through deployment.json."""

    model_config = {"extra": "forbid"}

    enabled: Annotated[
        bool,
        Field(
            description="Master switch for tenant search. Defaults to True to preserve current behavior.",
        ),
    ] = True

    engine: Annotated[
        Literal["bm25"],
        Field(
            description="Search backend to use. BM25-indexed search is the only supported engine.",
        ),
    ] = "bm25"

    analyzer_profile: Annotated[
        Literal["default", "aggressive-stem", "code-friendly"],
        Field(
            description="High-level analyzer preset controlling tokenization, stopwords, and stemming",
        ),
    ] = "default"

    boosts: Annotated[
        SearchBoostConfig,
        Field(description="Field-level boost configuration for BM25F when engine='bm25'"),
    ] = Field(default_factory=SearchBoostConfig)

    snippet: Annotated[
        SearchSnippetConfig,
        Field(description="Snippet/highlight preferences"),
    ] = Field(default_factory=SearchSnippetConfig)

    ranking: Annotated[
        SearchRankingConfig,
        Field(description="Ranking details for analytical tuning"),
    ] = Field(default_factory=SearchRankingConfig)

    suggestions_enabled: Annotated[
        bool,
        Field(
            description="Enable spelling-based suggestion hooks (Did you mean ...). No dictionaries shipped yet, but flag is plumbed.",
        ),
    ] = False

    cache_pin_seconds: Annotated[
        float,
        Field(
            ge=0.0,
            le=3600.0,
            description="Experimental warm-cache pin duration to keep BM25 segments in memory after warmup",
        ),
    ] = 0.0


class ArticleExtractorFallbackConfig(BaseModel):
    """Configuration for the optional external article extractor fallback."""

    model_config = {"extra": "forbid"}

    enabled: Annotated[
        bool,
        Field(
            description="Enable HTTP fallback when local Playwright + article_extractor fails",
        ),
    ] = False

    endpoint: Annotated[
        str | None,
        Field(
            description='HTTP endpoint that accepts POST {"url": ...} payloads (e.g., http://10.20.30.1:13005/)',
        ),
    ] = None

    api_key_env: Annotated[
        str | None,
        Field(
            description="Optional environment variable name that stores the bearer token for the fallback service",
            pattern=r"^[A-Z_][A-Z0-9_]*$",
        ),
    ] = None

    timeout_seconds: Annotated[
        int,
        Field(
            ge=1,
            le=120,
            description="Request timeout applied to fallback extraction calls",
        ),
    ] = 20

    batch_size: Annotated[
        int,
        Field(
            ge=1,
            le=8,
            description="Maximum URLs included per fallback request (current pipeline uses 1)",
        ),
    ] = 1

    max_retries: Annotated[
        int,
        Field(
            ge=0,
            le=5,
            description="Number of retry attempts when fallback extraction fails",
        ),
    ] = 2

    @model_validator(mode="after")
    def validate_endpoint_when_enabled(self) -> "ArticleExtractorFallbackConfig":
        if self.enabled and not (self.endpoint and self.endpoint.strip()):
            raise ValueError("article_extractor_fallback.endpoint must be set when fallback is enabled")
        return self


class TenantConfig(BaseModel):
    """Configuration for a single documentation tenant.

    Each tenant is isolated with:
    - Unique codename for routing (e.g., 'django', 'drf')
    - Independent URL filtering
    - Own sync schedule
    # Tenant source type is now implicitly 'filesystem' for storage,
    # but 'online' tenants will sync from web sources.
    """

    model_config = {"extra": "forbid"}  # Reject any extra keys not in schema

    source_type: Annotated[
        str,
        Field(
            description="Source of documentation ('online' for crawler-based, 'filesystem' for prebuilt trees, 'git' for sparse checkout repositories)",
            pattern=r"^(online|filesystem|git)$",
        ),
    ] = "online"

    docs_root_dir: Annotated[
        str | None,
        Field(
            description="Root directory for filesystem-based tenants",
        ),
    ] = None

    git_repo_url: Annotated[
        str | None,
        Field(
            description="Git repository URL for git-backed tenants (HTTPS preferred)",
            examples=["https://github.com/awslabs/aidlc-workflows.git"],
        ),
    ] = None

    git_branch: Annotated[
        str,
        Field(
            description="Branch, tag, or commit-ish to checkout for git-backed tenants",
        ),
    ] = "main"

    git_subpaths: Annotated[
        list[str] | None,
        Field(
            min_length=1,
            description="List of relative paths to include via sparse checkout (e.g., docs/, handbook/rules)",
        ),
    ] = None

    git_strip_prefix: Annotated[
        str | None,
        Field(
            description="Optional leading path segment to strip when copying files into tenant storage",
            examples=["handbook"],
        ),
    ] = None

    git_auth_token_env: Annotated[
        str | None,
        Field(
            description="Environment variable name that stores a PAT/token for private repositories",
            pattern=r"^[A-Z_][A-Z0-9_]*$",
        ),
    ] = None

    git_sync_interval_minutes: Annotated[
        int | None,
        Field(
            ge=5,
            le=1440,
            description="Optional override for git sync cadence (minutes) when scheduler operates in interval mode",
        ),
    ] = None

    codename: Annotated[
        str,
        Field(
            description="Short identifier for routing (e.g., 'django', 'drf')",
            pattern=r"^[a-z][a-z0-9_-]*$",
            min_length=2,
            max_length=64,
        ),
    ]

    docs_name: Annotated[
        str,
        Field(
            description="Human-readable name for the documentation",
            examples=["Django", "Django REST Framework", "FastAPI"],
            min_length=1,
            max_length=200,
        ),
    ]

    # At least one discovery method required
    docs_sitemap_url: Annotated[
        list[str],
        Field(
            description="List of sitemap URLs (strings also accepted and split on commas)",
            examples=[["https://docs.djangoproject.com/sitemap-en.xml"]],
        ),
    ] = Field(default_factory=list)

    docs_entry_url: Annotated[
        list[str],
        Field(
            description="List of crawler entry URLs (comma-separated strings remain supported)",
            examples=[["https://fastapi.tiangolo.com/"]],
        ),
    ] = Field(default_factory=list)

    # URL filtering
    url_whitelist_prefixes: Annotated[
        str,
        Field(
            description="Comma-separated URL prefixes to include",
            examples=["https://docs.djangoproject.com/en/5.2/"],
        ),
    ] = ""

    url_blacklist_prefixes: Annotated[
        str,
        Field(
            description="Comma-separated URL prefixes to exclude",
            examples=["https://docs.djangoproject.com/en/5.2/releases/"],
        ),
    ] = ""

    markdown_url_suffix: Annotated[
        str | None,
        Field(
            description="Optional suffix appended to discovered URLs for direct Markdown mirrors (e.g., '.md')",
            examples=[".md"],
        ),
    ] = None

    preserve_query_strings: Annotated[
        bool,
        Field(
            description="When true, canonical filesystem paths keep query params so variant URLs coexist",
        ),
    ] = True

    # Sync configuration (cron-based only, no backward compatibility)
    refresh_schedule: Annotated[
        str | None,
        Field(
            description="Cron schedule for automatic refresh (e.g., '0 2 * * 1' for weekly Monday 2am). If None, only manual sync via endpoint. This is the ONLY way to configure automatic refresh.",
            examples=["0 2 * * 1", "0 0 * * *", "0 */6 * * *"],
        ),
    ] = None

    max_crawl_pages: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum pages to crawl per sync",
        ),
    ] = 10000

    enable_crawler: Annotated[
        bool,
        Field(
            description="Enable link crawler for discovery",
        ),
    ] = False

    # Context configuration
    snippet_surrounding_chars: Annotated[
        int,
        Field(
            ge=200,
            le=3000,
            description="Number of characters to include before/after match in search snippets",
        ),
    ] = 1000

    search: Annotated[
        SearchConfig,
        Field(
            description="Search configuration (always enabled, no per-tenant tuning)",
        ),
    ] = Field(default_factory=lambda: SearchConfig())

    allow_index_builds: Annotated[
        bool | None,
        Field(
            description="Override infrastructure-level index building toggle for this tenant",
        ),
    ] = None

    # Test queries for validation (used by debug_multi_tenant.py)
    test_queries: Annotated[
        dict[str, list[str]] | None,
        Field(
            description="Test queries for automated testing: natural (phrases), phrases (exact), words (keywords)",
            examples=[
                {
                    "natural": ["how to configure logging", "setup authentication"],
                    "phrases": ["models.Model", "settings.py"],
                    "words": ["models", "views", "templates"],
                }
            ],
        ),
    ] = None

    # Hidden infrastructure reference (set by DeploymentConfig validator)
    _infrastructure: "SharedInfraConfig | None" = None

    # --- derived helpers -------------------------------------------------

    def get_url_whitelist_prefixes(self) -> list[str]:
        """Return normalized whitelist prefixes for this tenant."""

        return _split_csv(self.url_whitelist_prefixes)

    def get_url_blacklist_prefixes(self) -> list[str]:
        """Return normalized blacklist prefixes for this tenant."""

        return _split_csv(self.url_blacklist_prefixes)

    def get_docs_sitemap_urls(self) -> list[str]:
        """Return normalized sitemap URLs for this tenant."""

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

    @property
    def docs_sync_enabled(self) -> bool:
        """Determine if background sync should be enabled for this tenant.

        Only online tenants with a refresh schedule should enable background sync.
        """
        return self.source_type == "online" and self.refresh_schedule is not None

    @model_validator(mode="after")
    def validate_discovery_urls(self) -> "TenantConfig":
        """Ensure required fields exist for each source type."""
        if self.source_type == "filesystem":
            if not self.docs_root_dir:
                raise ValueError(f"Filesystem tenant '{self.codename}' must specify docs_root_dir")
        elif self.source_type == "git":
            if not self.git_repo_url:
                raise ValueError(f"Git tenant '{self.codename}' must specify git_repo_url")
            if not self.git_subpaths:
                raise ValueError(f"Git tenant '{self.codename}' must provide at least one git_subpaths entry")
        elif not self.docs_sitemap_url and not self.docs_entry_url:
            # Online tenants must have at least one discovery method
            raise ValueError(f"Tenant '{self.codename}' must specify either docs_sitemap_url or docs_entry_url")
        return self

    @field_validator("docs_sitemap_url", mode="before")
    @classmethod
    def _normalize_sitemap_urls(cls, value: object) -> list[str]:
        return _normalize_url_collection(value)

    @field_validator("docs_entry_url", mode="before")
    @classmethod
    def _normalize_entry_urls(cls, value: object) -> list[str]:
        return _normalize_url_collection(value)

    @model_validator(mode="after")
    def validate_refresh_schedule(self) -> "TenantConfig":
        """Validate cron schedule syntax if provided."""
        if self.refresh_schedule:
            try:
                # Validate cron syntax by parsing it
                Cron(self.refresh_schedule)
            except Exception as e:
                raise ValueError(
                    f"Invalid cron schedule '{self.refresh_schedule}' for tenant '{self.codename}': {e}"
                ) from e
        return self


class LogProfileConfig(BaseModel):
    """Configuration for a named logging profile.

    Profiles allow switching between production-optimized (quiet) and
    debug-focused (verbose) logging without code changes.
    """

    model_config = {"extra": "forbid"}

    level: Annotated[
        str,
        Field(
            pattern=r"^(debug|info|warning|error|critical)$",
            description="Root log level for this profile",
        ),
    ] = "info"

    json_output: Annotated[
        bool,
        Field(
            description="Emit structured JSON logs (recommended for production)",
        ),
    ] = True

    trace_categories: Annotated[
        list[str],
        Field(
            description="Logger names to set at trace_level for deep debugging",
            examples=[["docs_mcp_server", "uvicorn.error", "fastmcp"]],
        ),
    ] = Field(default_factory=list)

    trace_level: Annotated[
        str,
        Field(
            pattern=r"^(debug|info|warning|error|critical)$",
            description="Level applied to trace_categories loggers",
        ),
    ] = "debug"

    logger_levels: Annotated[
        dict[str, str],
        Field(
            description="Per-logger level overrides (logger name -> level)",
            examples=[{"uvicorn.access": "warning", "fastmcp": "debug"}],
        ),
    ] = Field(default_factory=dict)

    @field_validator("logger_levels")
    @classmethod
    def validate_logger_levels(cls, value: dict[str, str]) -> dict[str, str]:
        """Validate that all logger_levels values use supported log levels."""
        allowed_levels = {"debug", "info", "warning", "error", "critical"}
        invalid = {name: level for name, level in value.items() if level not in allowed_levels}
        if invalid:
            details = ", ".join(f"{name}={level}" for name, level in invalid.items())
            raise ValueError(
                f"Invalid log level(s) in logger_levels; allowed levels are {sorted(allowed_levels)}; got: {details}"
            )
        return value

    access_log: Annotated[
        bool,
        Field(
            description="Enable uvicorn access logging",
        ),
    ] = False


class ObservabilityCollectorConfig(BaseModel):
    """Configuration for OTLP trace export."""

    model_config = {"extra": "forbid"}

    enabled: Annotated[
        bool,
        Field(
            description="Enable OTLP trace export to an external collector",
        ),
    ] = False

    otlp_protocol: Annotated[
        Literal["http", "grpc"],
        Field(
            description="OTLP transport protocol",
        ),
    ] = "grpc"

    collector_endpoint: Annotated[
        str,
        Field(
            description="OTLP collector endpoint (HTTP uses /v1/traces)",
            examples=["http://localhost:4317", "http://localhost:4318/v1/traces"],
        ),
    ] = "http://localhost:4317"

    headers: Annotated[
        dict[str, str],
        Field(
            description="Optional headers to include with OTLP requests",
        ),
    ] = Field(default_factory=dict)

    timeout_seconds: Annotated[
        int,
        Field(
            ge=1,
            le=60,
            description="OTLP exporter timeout in seconds",
        ),
    ] = 10

    grpc_insecure: Annotated[
        bool,
        Field(
            description="Allow insecure gRPC (plaintext) connections",
        ),
    ] = True

    resource_attributes: Annotated[
        dict[str, str],
        Field(
            description="Additional OpenTelemetry resource attributes for trace export",
        ),
    ] = Field(default_factory=dict)


class SharedInfraConfig(BaseModel):
    """Shared infrastructure configuration for all tenants.

    These settings are shared across tenants for efficiency.
    Content extraction is handled by the article-extractor library.
    """

    model_config = {"extra": "forbid"}  # Reject any extra keys not in schema

    # HTTP server config
    mcp_host: Annotated[
        str,
        Field(
            description="Server bind address (0.0.0.0 for containers)",
        ),
    ] = "0.0.0.0"

    mcp_port: Annotated[
        int,
        Field(
            ge=1,
            le=65535,
            description="Server listen port",
        ),
    ] = 8000

    default_client_model: Annotated[
        str,
        Field(
            description="Default MCP client model suggested via /mcp.json",
            examples=["claude-haiku-4.5"],
        ),
    ] = "claude-haiku-4.5"

    # Performance tuning
    max_concurrent_requests: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Max concurrent HTTP requests across all tenants",
        ),
    ] = 20

    uvicorn_workers: Annotated[
        int,
        Field(
            ge=1,
            le=16,
            description="Number of Uvicorn worker processes",
        ),
    ] = 1

    uvicorn_limit_concurrency: Annotated[
        int,
        Field(
            ge=10,
            le=1000,
            description="Max concurrent connections per Uvicorn worker",
        ),
    ] = 200

    # Common settings
    log_level: Annotated[
        str,
        Field(
            pattern=r"^(debug|info|warning|error|critical)$",
            description="Logging level (deprecated: use log_profile + log_profiles)",
        ),
    ] = "info"

    log_profile: Annotated[
        str,
        Field(
            description="Active logging profile name (must exist in log_profiles)",
            examples=["default", "trace-drftest"],
        ),
    ] = "default"

    log_profiles: Annotated[
        dict[str, LogProfileConfig],
        Field(
            description="Named logging profiles for different operational modes",
        ),
    ] = Field(default_factory=lambda: {"default": LogProfileConfig()})

    observability_collector: Annotated[
        ObservabilityCollectorConfig,
        Field(
            description="OTLP exporter settings for external trace collectors",
        ),
    ] = Field(default_factory=ObservabilityCollectorConfig)

    search_include_stats: Annotated[
        bool,
        Field(
            description="Include search statistics in search responses",
        ),
    ] = False

    operation_mode: Annotated[
        str,
        Field(
            pattern=r"^(online|offline)$",
            description="Operation mode: online (with sync) or offline (cache only)",
        ),
    ] = "online"

    trusted_hosts: Annotated[
        list[str],
        Field(
            description="Allowed Host headers for TrustedHostMiddleware",
        ),
    ] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver"])

    https_redirect: Annotated[
        bool,
        Field(
            description="Enable HTTPSRedirectMiddleware to enforce HTTPS",
        ),
    ] = False

    allow_index_builds: Annotated[
        bool,
        Field(
            description="Allow server runtime to build search indexes (disable when external workers handle indexing)",
        ),
    ] = False

    http_timeout: Annotated[
        int,
        Field(
            ge=10,
            le=300,
            description="HTTP request timeout in seconds",
        ),
    ] = 120

    search_timeout: Annotated[
        int,
        Field(
            ge=1,
            le=300,
            description="Search operation timeout in seconds for ripgrep",
        ),
    ] = 30

    # Default context configuration (can be overridden per tenant)
    default_snippet_surrounding_chars: Annotated[
        int,
        Field(
            ge=200,
            le=3000,
            description="Default chars before/after match in search snippets",
        ),
    ] = 1000

    crawler_playwright_first: Annotated[
        bool,
        Field(
            description="Use Playwright as primary crawler method (bypasses bot protection)",
        ),
    ] = True

    fallback_extractor_url: Annotated[
        str | None,
        Field(
            description="Shortcut for article_extractor_fallback.endpoint (e.g., http://10.20.30.1:13005/)",
        ),
    ] = None

    search_max_segments: Annotated[
        int,
        Field(
            ge=1,
            le=512,
            description="Maximum SQLite search segments to retain per tenant before pruning",
        ),
    ] = 32

    article_extractor_fallback: Annotated[
        ArticleExtractorFallbackConfig,
        Field(
            description="Optional remote article extractor invocation when in-process extraction fails",
        ),
    ] = Field(default_factory=ArticleExtractorFallbackConfig)

    @model_validator(mode="after")
    def validate_log_profile_exists(self) -> "SharedInfraConfig":
        """Ensure the selected log_profile exists in log_profiles."""
        if self.log_profile not in self.log_profiles:
            available = ", ".join(sorted(self.log_profiles.keys()))
            raise ValueError(f"log_profile '{self.log_profile}' not found in log_profiles. Available: {available}")
        self._apply_fallback_extractor_url()
        return self

    def get_active_log_profile(self) -> LogProfileConfig:
        """Return the currently active logging profile configuration."""
        return self.log_profiles[self.log_profile]

    def _apply_fallback_extractor_url(self) -> None:
        fallback_url = (self.fallback_extractor_url or "").strip() or None
        if not fallback_url:
            return
        endpoint = (self.article_extractor_fallback.endpoint or "").strip() or None
        if endpoint and endpoint != fallback_url:
            raise ValueError("fallback_extractor_url conflicts with article_extractor_fallback.endpoint")
        if not endpoint:
            self.article_extractor_fallback.endpoint = fallback_url
        if not self.article_extractor_fallback.enabled:
            self.article_extractor_fallback.enabled = True


class DeploymentConfig(BaseModel):
    """Complete deployment configuration for multi-tenant MCP server.

    Schema for deployment.json that defines all documentation sets
    and shared infrastructure.

    Example:
        {
            "infrastructure": {
                "mcp_host": "0.0.0.0",
                "mcp_port": 8000,
                "max_concurrent_requests": 20,
                "log_level": "info"
            },
            "tenants": [
                {
                    "codename": "django",
                    "docs_name": "Django",
                    "docs_sitemap_url": "https://docs.djangoproject.com/sitemap-en.xml",
                    "url_whitelist_prefixes": "https://docs.djangoproject.com/en/5.2/"
                },
                {
                    "codename": "drf",
                    "docs_name": "Django REST Framework",
                    "docs_sitemap_url": "https://www.django-rest-framework.org/sitemap.xml",
                    "url_whitelist_prefixes": "https://www.django-rest-framework.org/"
                }
            ]
        }
    """

    infrastructure: SharedInfraConfig
    tenants: Annotated[
        list[TenantConfig],
        Field(
            min_length=1,
            description="List of documentation tenants to serve",
        ),
    ]

    @model_validator(mode="after")
    def validate_unique_codenames(self) -> "DeploymentConfig":
        """Ensure codenames are unique across tenants."""
        tenant_codes = {t.codename for t in self.tenants}

        # Check for duplicates within tenants
        tenant_codenames = [t.codename for t in self.tenants]
        if len(tenant_codenames) != len(tenant_codes):
            duplicates = [c for c in tenant_codenames if tenant_codenames.count(c) > 1]
            raise ValueError(f"Duplicate tenant codenames found: {duplicates}")

        return self

    @model_validator(mode="after")
    def attach_infrastructure_to_tenants(self) -> "DeploymentConfig":
        """Attach shared infrastructure to each tenant config (Context Object pattern)."""
        for tenant in self.tenants:
            tenant._infrastructure = self.infrastructure
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> "DeploymentConfig":
        """Load configuration from JSON file.

        Environment variables can override infrastructure settings:
        - OPERATION_MODE: Override operation_mode (online/offline)

        Args:
            path: Path to deployment.json

        Returns:
            Validated DeploymentConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Deployment config not found: {path}")

        with path.open() as f:
            data = json.load(f)

        # Apply environment variable overrides
        if "OPERATION_MODE" in os.environ:
            operation_mode = os.environ["OPERATION_MODE"]
            if operation_mode in ("online", "offline"):
                data["infrastructure"]["operation_mode"] = operation_mode
            else:
                raise ValueError(f"Invalid OPERATION_MODE: {operation_mode}. Must be 'online' or 'offline'")

        return cls.model_validate(data)

    def get_tenant(self, codename: str) -> TenantConfig | None:
        """Get tenant configuration by codename.

        Args:
            codename: Tenant codename (e.g., 'django')

        Returns:
            TenantConfig if found, None otherwise
        """
        for tenant in self.tenants:
            if tenant.codename == codename:
                return tenant
        return None

    def list_codenames(self) -> list[str]:
        """Get list of all tenant codenames."""
        return [t.codename for t in self.tenants]

    def to_mcp_json(self) -> dict[str, Any]:
        """Generate mcp.json configuration for the single root server."""

        base_url = f"http://127.0.0.1:{self.infrastructure.mcp_port}"
        return {
            "defaultModel": self.infrastructure.default_client_model,
            "servers": {
                "docs-mcp-root": {
                    "type": "http",
                    "url": f"{base_url}/mcp",
                }
            },
        }
