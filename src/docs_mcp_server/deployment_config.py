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

from pydantic import BaseModel, Field, model_validator


def _split_csv(raw_value: str | None) -> list[str]:
    """Split comma-separated config strings into trimmed entries."""

    if not raw_value:
        return []
    return [entry.strip() for entry in raw_value.split(",") if entry.strip()]


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

    enable_proximity_bonus: Annotated[
        bool,
        Field(
            description="If True, phrase matches receive a minor proximity boost",
        ),
    ] = True


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
        str,
        Field(
            description="Comma-separated sitemap URLs",
            examples=["https://docs.djangoproject.com/sitemap-en.xml"],
        ),
    ] = ""

    docs_entry_url: Annotated[
        str,
        Field(
            description="Comma-separated entry URLs for crawler",
            examples=["https://fastapi.tiangolo.com/"],
        ),
    ] = ""

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

    fetch_default_mode: Annotated[
        str,
        Field(
            description="Default fetch mode: 'full' or 'surrounding'",
            pattern=r"^(full|surrounding)$",
        ),
    ] = "full"

    fetch_surrounding_chars: Annotated[
        int,
        Field(
            ge=100,
            le=5000,
            description="Number of characters to include before/after match in surrounding fetch mode",
        ),
    ] = 1000

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

    # --- derived helpers -------------------------------------------------

    def get_url_whitelist_prefixes(self) -> list[str]:
        """Return normalized whitelist prefixes for this tenant."""

        return _split_csv(self.url_whitelist_prefixes)

    def get_url_blacklist_prefixes(self) -> list[str]:
        """Return normalized blacklist prefixes for this tenant."""

        return _split_csv(self.url_blacklist_prefixes)

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

    @model_validator(mode="after")
    def validate_refresh_schedule(self) -> "TenantConfig":
        """Validate cron schedule syntax if provided."""
        if self.refresh_schedule:
            try:
                from cron_converter import Cron

                # Validate cron syntax by parsing it
                Cron(self.refresh_schedule)
            except Exception as e:
                raise ValueError(
                    f"Invalid cron schedule '{self.refresh_schedule}' for tenant '{self.codename}': {e}"
                ) from e
        return self


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
            description="Logging level",
        ),
    ] = "info"

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

    default_fetch_mode: Annotated[
        str,
        Field(
            description="Default fetch mode: 'full' or 'surrounding'",
            pattern=r"^(full|surrounding)$",
        ),
    ] = "full"

    default_fetch_surrounding_chars: Annotated[
        int,
        Field(
            ge=100,
            le=5000,
            description="Default chars before/after match in surrounding fetch mode",
        ),
    ] = 1000

    crawler_playwright_first: Annotated[
        bool,
        Field(
            description="Use Playwright as primary crawler method (bypasses bot protection)",
        ),
    ] = True

    search_max_segments: Annotated[
        int,
        Field(
            ge=1,
            le=512,
            description="Maximum JSON search segments to retain per tenant before pruning",
        ),
    ] = 32


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
