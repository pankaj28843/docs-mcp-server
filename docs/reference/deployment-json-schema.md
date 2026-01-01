# Reference: deployment.json Schema

**Audience**: Operators configuring docs-mcp-server tenants.  
**Prerequisites**: Familiarity with JSON configuration files.

The `deployment.json` file defines all tenants and shared infrastructure settings. The server validates this file at startup and rejects invalid configurations.

!!! tip "Quick Navigation"
    
    **Just adding a tenant?** Jump to:
    - [Online Tenant Fields](#online-tenant-fields) - Website docs
    - [Git Tenant Fields](#git-tenant-fields) - GitHub/GitLab repos
    - [Filesystem Tenant Fields](#filesystem-tenant-fields) - Local markdown
    
    **Tuning performance?** See:
    - [Infrastructure Section](#infrastructure-section) - Timeouts, concurrency
    - [Search Configuration](#search-configuration-optional) - BM25 params

---

## File Structure

```json
{
  "infrastructure": { ... },
  "tenants": [ ... ]
}
```

---

## Infrastructure Section

Shared settings applied to all tenants.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mcp_host` | string | `"0.0.0.0"` | Server bind address |
| `mcp_port` | integer | `42042` | Server port |
| `default_client_model` | string | `"claude-haiku-4.5"` | Default model for MCP clients |
| `max_concurrent_requests` | integer | `20` | Max concurrent HTTP requests |
| `uvicorn_workers` | integer | `1` | Number of uvicorn workers |
| `uvicorn_limit_concurrency` | integer | `200` | Max concurrent connections |
| `log_level` | string | `"info"` | Logging level (debug, info, warning, error) |
| `operation_mode` | string | `"online"` | `"online"` or `"offline"` mode |
| `http_timeout` | integer | `120` | HTTP request timeout (seconds) |
| `search_timeout` | integer | `30` | Search operation timeout (seconds) |
| `search_include_stats` | boolean | `true` | Include search statistics in responses |
| `default_fetch_mode` | string | `"surrounding"` | Default fetch mode: `"full"` or `"surrounding"` |
| `default_fetch_surrounding_chars` | integer | `1000` | Characters around match in surrounding mode |
| `crawler_playwright_first` | boolean | `true` | Use Playwright for JavaScript-rendered pages |

**Example:**
```json
{
  "infrastructure": {
    "mcp_host": "0.0.0.0",
    "mcp_port": 42042,
    "log_level": "info",
    "operation_mode": "online",
    "http_timeout": 120,
    "search_timeout": 30
  }
}
```

---

## Tenant Section

Each tenant is an object in the `tenants` array. Required fields depend on `source_type`.

### Common Fields (All Tenant Types)

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_type` | string | Yes | — | `"online"`, `"git"`, or `"filesystem"` |
| `codename` | string | Yes | — | Unique identifier for routing (lowercase, 2-64 chars) |
| `docs_name` | string | Yes | — | Human-readable name |
| `docs_root_dir` | string | Yes | — | Local storage path (e.g., `"./mcp-data/django"`) |
| `refresh_schedule` | string | No | `null` | Cron expression for auto-sync (e.g., `"0 2 */14 * *"`) |
| `test_queries` | object | No | `null` | Test queries for validation (see below) |

### Online Tenant Fields

For websites with sitemaps or crawlable pages.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `docs_sitemap_url` | string | Conditional | `""` | Comma-separated sitemap URLs |
| `docs_entry_url` | string | Conditional | `""` | Comma-separated entry URLs for crawler |
| `url_whitelist_prefixes` | string | No | `""` | Comma-separated URL prefixes to include |
| `url_blacklist_prefixes` | string | No | `""` | Comma-separated URL prefixes to exclude |
| `enable_crawler` | boolean | No | `false` | Enable link crawler for discovery |
| `max_crawl_pages` | integer | No | `10000` | Maximum pages to crawl per sync |

**Note**: At least one of `docs_sitemap_url` or `docs_entry_url` is required for online tenants.

**Example (Online Tenant):**
```json
{
  "source_type": "online",
  "codename": "django",
  "docs_name": "Django Docs",
  "docs_sitemap_url": "https://docs.djangoproject.com/sitemap-en.xml",
  "url_whitelist_prefixes": "https://docs.djangoproject.com/en/5.2/",
  "url_blacklist_prefixes": "https://docs.djangoproject.com/en/5.2/releases/",
  "enable_crawler": false,
  "docs_root_dir": "./mcp-data/django",
  "refresh_schedule": "0 2 */14 * *"
}
```

### Git Tenant Fields

For markdown files in GitHub/GitLab repositories.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `git_repo_url` | string | Yes | — | Repository URL (HTTPS preferred) |
| `git_branch` | string | No | `"main"` | Branch, tag, or commit to checkout |
| `git_subpaths` | array | Yes | — | Paths to include via sparse checkout |
| `git_strip_prefix` | string | No | `null` | Leading path to strip when copying |
| `git_auth_token_env` | string | No | `null` | Env var name for private repo auth |
| `git_sync_interval_minutes` | integer | No | `null` | Override sync cadence (5-1440 minutes) |

**Example (Git Tenant):**
```json
{
  "source_type": "git",
  "codename": "mkdocs",
  "docs_name": "MkDocs",
  "git_repo_url": "https://github.com/mkdocs/mkdocs.git",
  "git_branch": "master",
  "git_subpaths": ["docs"],
  "git_strip_prefix": "docs",
  "docs_root_dir": "./mcp-data/mkdocs",
  "refresh_schedule": "0 18 */14 * *"
}
```

### Filesystem Tenant Fields

For local markdown files (no sync needed).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `docs_root_dir` | string | Yes | — | Path to local markdown directory |

**Example (Filesystem Tenant):**
```json
{
  "source_type": "filesystem",
  "codename": "my-docs",
  "docs_name": "My Local Docs",
  "docs_root_dir": "./mcp-data/my-docs"
}
```

---

## Search Configuration (Optional)

Fine-tune search behavior per tenant. Most users should use defaults.

```json
{
  "search": {
    "enabled": true,
    "engine": "bm25",
    "analyzer_profile": "default",
    "ranking": {
      "bm25_k1": 1.2,
      "bm25_b": 0.75,
      "enable_proximity_bonus": true
    },
    "boosts": {
      "title": 2.5,
      "headings_h1": 2.5,
      "headings_h2": 2.0,
      "headings": 1.5,
      "body": 1.0,
      "code": 1.2,
      "path": 1.5,
      "url": 1.5
    },
    "snippet": {
      "style": "plain",
      "fragment_char_limit": 240,
      "max_fragments": 2,
      "surrounding_context_chars": 120
    }
  }
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search.enabled` | boolean | `true` | Enable search for this tenant |
| `search.engine` | string | `"bm25"` | Search engine (only `"bm25"` supported) |
| `search.analyzer_profile` | string | `"default"` | Tokenization profile: `"default"`, `"aggressive-stem"`, `"code-friendly"` |
| `search.ranking.bm25_k1` | float | `1.2` | BM25 term saturation (0.5-3.0) |
| `search.ranking.bm25_b` | float | `0.75` | BM25 length normalization (0.1-1.0) |

---

## Test Queries

Define queries for automated validation with `debug_multi_tenant.py`.

```json
{
  "test_queries": {
    "natural": [
      "How to create a Django model with foreign key",
      "Django form validation"
    ],
    "phrases": ["model", "form", "view"],
    "words": ["django", "model", "view", "template"]
  }
}
```

| Key | Description |
|-----|-------------|
| `natural` | Full natural language questions |
| `phrases` | Short phrases or exact terms |
| `words` | Single keywords |

---

## Cron Schedule Syntax

The `refresh_schedule` field uses standard 5-field cron syntax:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

**Examples:**

| Schedule | Description |
|----------|-------------|
| `0 2 * * 1` | Weekly Monday at 2:00 AM |
| `0 0 * * *` | Daily at midnight |
| `0 */6 * * *` | Every 6 hours |
| `0 2 */14 * *` | Every 14 days at 2:00 AM |
| `0 2 1,15 * *` | 1st and 15th of month at 2:00 AM |

---

## Validation Rules

The server validates `deployment.json` at startup:

1. **Online tenants**: Must have `docs_sitemap_url` OR `docs_entry_url`
2. **Git tenants**: Must have `git_repo_url` AND `git_subpaths`
3. **Filesystem tenants**: Must have `docs_root_dir`
4. **Codenames**: Must be lowercase, 2-64 characters, start with letter
5. **Cron schedules**: Must be valid 5-field cron syntax
6. **No extra fields**: Unknown fields are rejected (`extra: "forbid"`)

**Startup error example:**
```
ValueError: Tenant 'my-tenant' must specify either docs_sitemap_url or docs_entry_url
```

---

## Complete Example

```json
{
  "infrastructure": {
    "mcp_host": "0.0.0.0",
    "mcp_port": 42042,
    "log_level": "info",
    "operation_mode": "online"
  },
  "tenants": [
    {
      "source_type": "online",
      "codename": "drf",
      "docs_name": "Django REST Framework Docs",
      "docs_sitemap_url": "https://www.django-rest-framework.org/sitemap.xml",
      "url_whitelist_prefixes": "https://www.django-rest-framework.org/",
      "docs_root_dir": "./mcp-data/drf",
      "refresh_schedule": "0 3 */14 * *",
      "test_queries": {
        "natural": ["How to create a serializer"],
        "phrases": ["serializer", "viewset"],
        "words": ["drf", "api"]
      }
    },
    {
      "source_type": "git",
      "codename": "mkdocs",
      "docs_name": "MkDocs",
      "git_repo_url": "https://github.com/mkdocs/mkdocs.git",
      "git_branch": "master",
      "git_subpaths": ["docs"],
      "git_strip_prefix": "docs",
      "docs_root_dir": "./mcp-data/mkdocs",
      "refresh_schedule": "0 18 */14 * *"
    }
  ]
}
```

---

## Related

- Tutorial: [Adding Your First Tenant](../tutorials/adding-first-tenant.md)
- How-To: [Configure Online Tenant](../how-to/configure-online-tenant.md)
- How-To: [Configure Git Tenant](../how-to/configure-git-tenant.md)
- Explanation: [Sync Strategies](../explanations/sync-strategies.md)

