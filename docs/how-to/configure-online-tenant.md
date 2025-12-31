# How-To: Configure Online Tenant

**Goal**: Add documentation from a website (via sitemap or crawler) to your deployment.  
**Prerequisites**: Website URL with accessible documentation, `deployment.json` configured, Docker container running.  
**Time**: ~15 minutes

---

## When to Use Online Tenants

Use online tenants when:
- Documentation is hosted on a website (not in a git repo)
- The site has a sitemap.xml or crawlable structure
- You want the latest published documentation
- Examples: Django docs, FastAPI docs, any public documentation site

---

## Steps

### 1. Find the Sitemap URL

Most documentation sites have a sitemap. Common locations:
- `https://docs.example.com/sitemap.xml`
- `https://example.com/docs/sitemap.xml`

Check by visiting the URL directly. If no sitemap exists, you'll use the crawler (Step 2b).

### 2a. Configure with Sitemap (Recommended)

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
  "refresh_schedule": "0 2 */14 * *",
  "test_queries": {
    "natural": ["How to create a Django model"],
    "phrases": ["model", "view"],
    "words": ["django", "queryset"]
  }
}
```

### 2b. Configure with Crawler (No Sitemap)

When no sitemap is available, enable the crawler:

```json
{
  "source_type": "online",
  "codename": "custom-docs",
  "docs_name": "Custom Documentation",
  "docs_entry_url": "https://docs.example.com/",
  "url_whitelist_prefixes": "https://docs.example.com/",
  "enable_crawler": true,
  "max_crawl_pages": 500,
  "docs_root_dir": "./mcp-data/custom-docs",
  "refresh_schedule": "0 4 * * 1"
}
```

**Note**: Crawler follows links from `docs_entry_url`, respecting `url_whitelist_prefixes`.

### 3. URL Filtering

Use prefixes to control what gets indexed:

```json
{
  "url_whitelist_prefixes": "https://docs.djangoproject.com/en/5.2/",
  "url_blacklist_prefixes": "https://docs.djangoproject.com/en/5.2/releases/,https://docs.djangoproject.com/en/5.2/_"
}
```

- **Whitelist**: Only URLs starting with these prefixes are indexed
- **Blacklist**: URLs starting with these prefixes are excluded (even if whitelisted)
- **Multiple values**: Comma-separated

**Common exclusions**:
- `/releases/` - Version changelogs
- `/_` - Internal/private pages
- `/api/` - Auto-generated API docs (if too verbose)

### 4. Redeploy and Sync

```bash
# Redeploy container
uv run python deploy_multi_tenant.py --mode online

# Trigger sync
uv run python trigger_all_syncs.py --tenants django --force
```

### 5. Monitor Sync Progress

Syncing large sites can take several minutes. Watch container logs:

```bash
docker logs -f docs-mcp-server 2>&1 | grep -i django
```

When sync completes, you'll see "Sync cycle completed" in the logs.

### 6. Verify Search Works

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant django --test search
```

---

## Configuration Reference

| Field | Required | Description |
|-------|----------|-------------|
| `source_type` | Yes | Must be `"online"` |
| `codename` | Yes | Unique lowercase identifier |
| `docs_name` | Yes | Human-readable name |
| `docs_sitemap_url` | Conditional | Sitemap URL(s), comma-separated |
| `docs_entry_url` | Conditional | Entry URL(s) for crawler |
| `url_whitelist_prefixes` | Recommended | Include only matching URLs |
| `url_blacklist_prefixes` | Optional | Exclude matching URLs |
| `enable_crawler` | Optional | Enable link-following crawler |
| `max_crawl_pages` | Optional | Page limit (default: 10000) |
| `refresh_schedule` | Optional | Cron schedule for auto-sync |

**Note**: At least one of `docs_sitemap_url` or `docs_entry_url` is required.

---

## Examples

### FastAPI Documentation

```json
{
  "source_type": "online",
  "codename": "fastapi",
  "docs_name": "FastAPI Docs",
  "docs_sitemap_url": "https://fastapi.tiangolo.com/sitemap.xml",
  "url_whitelist_prefixes": "https://fastapi.tiangolo.com/",
  "url_blacklist_prefixes": "https://fastapi.tiangolo.com/release-notes/",
  "docs_root_dir": "./mcp-data/fastapi",
  "refresh_schedule": "0 4 */14 * *"
}
```

### Python Standard Library

```json
{
  "source_type": "online",
  "codename": "python",
  "docs_name": "Python Docs",
  "docs_sitemap_url": "https://docs.python.org/sitemap.xml",
  "url_whitelist_prefixes": "https://docs.python.org/3.13/,https://docs.python.org/3.14/",
  "url_blacklist_prefixes": "https://docs.python.org/3.13/whatsnew/",
  "docs_root_dir": "./mcp-data/python",
  "refresh_schedule": "0 5 1,15 * *"
}
```

### Pytest Documentation (Crawler-based)

```json
{
  "source_type": "online",
  "codename": "pytest",
  "docs_name": "Pytest Docs",
  "docs_sitemap_url": "https://docs.pytest.org/sitemap.xml",
  "docs_entry_url": "https://docs.pytest.org/en/stable/",
  "url_whitelist_prefixes": "https://docs.pytest.org/en/stable/",
  "enable_crawler": true,
  "docs_root_dir": "./mcp-data/pytest",
  "refresh_schedule": "0 9 */14 * *"
}
```

---

## Troubleshooting

### Sync stuck or very slow

**Cause**: Large site or rate limiting.

**Fix**:
1. Set `max_crawl_pages` to a reasonable limit
2. Narrow `url_whitelist_prefixes` to essential sections
3. Check container logs: `docker logs docs-mcp-server 2>&1 | tail -50`

### No documents after sync

**Cause**: All URLs filtered out or site blocking requests.

**Fix**:
1. Verify URL is accessible: `curl -I https://docs.example.com/`
2. Check whitelist covers actual URLs in sitemap
3. Try enabling crawler if sitemap URLs don't match content

### JavaScript-rendered content missing

**Cause**: Some sites render content with JavaScript.

**Fix**: Ensure `crawler_playwright_first: true` in infrastructure settings (default is enabled).

### Search returns irrelevant results

**Cause**: Too much content indexed, including low-value pages.

**Fix**:
1. Add more `url_blacklist_prefixes` for changelogs, API refs, etc.
2. Re-sync: `uv run python trigger_all_syncs.py --tenants <tenant> --force`
3. Rebuild index: `uv run python trigger_all_indexing.py --tenants <tenant>`

---

## Related

- Tutorial: [Adding Your First Tenant](../tutorials/adding-first-tenant.md) — Step-by-step tenant setup
- How-To: [Configure Git Tenant](configure-git-tenant.md) — For git-based documentation
- How-To: [Debug Crawlers](debug-crawlers.md) — Troubleshoot sync issues
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md) — All configuration options
