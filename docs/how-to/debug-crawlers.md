# How-To: Debug Crawlers

**Goal**: Diagnose and fix synchronization failures for online and git tenants.  
**Prerequisites**: Docker container running, basic command-line familiarity.  
**Time**: ~10-30 minutes depending on issue

---

## Quick Diagnosis

### 1. Check Container Health

```bash
curl -s http://localhost:42042/health | jq '{status, tenant_count}'
```

You should see `"status": "healthy"` and your configured tenant count.

### 2. Check Container Logs

```bash
# Recent logs for specific tenant
docker logs docs-mcp-server 2>&1 | grep -i "<tenant>" | tail -30

# All errors
docker logs docs-mcp-server 2>&1 | grep -iE "error|exception|failed" | tail -20
```

### 3. Force Re-sync

```bash
uv run python trigger_all_syncs.py --tenants <tenant> --force
```

---

## Common Issues

### Sync stuck at syncing status

!!! warning "Symptoms"
    Status shows `"syncing"` for extended period (>10 minutes for small tenants).

**Diagnosis**:
```bash
docker logs docs-mcp-server 2>&1 | grep -i "<tenant>" | tail -50
```

**Fixes**:
1. **Rate limiting**: Site may be throttling requests
   - Set `max_crawl_pages` lower (e.g., 500)
   - Add delay between syncs via `refresh_schedule`

2. **Container resource exhaustion**:
   ```bash
   docker stats docs-mcp-server
   ```
   If memory/CPU pegged, restart container.

3. **Network timeout**:
   - Increase `http_timeout` in infrastructure settings
   - Check if site is accessible from container

---

### 0 documents after sync

!!! warning "Symptoms"
    Sync completes but `documents_count: 0`.

**Diagnosis**:
```bash
# Check if sitemap is accessible
curl -s "https://docs.example.com/sitemap.xml" | head -20

# Check whitelist matches actual URLs
curl -s "https://docs.example.com/sitemap.xml" | grep "<loc>" | head -5
```

**Fixes**:
1. **Wrong whitelist prefix**:
   ```json
   // Wrong: sitemap has /en/stable/ but whitelist has /en/5.2/
   "url_whitelist_prefixes": "https://docs.example.com/en/5.2/"
   
   // Fix: match actual URL structure
   "url_whitelist_prefixes": "https://docs.example.com/en/stable/"
   ```

2. **All URLs blacklisted**: Review `url_blacklist_prefixes`

3. **JavaScript-rendered content**: Enable Playwright in infrastructure:
   ```json
   "crawler_playwright_first": true
   ```

---

### Git sync failed - repository not found

!!! warning "Symptoms"
    Git tenant sync fails with authentication or URL error.

**Diagnosis**:
```bash
# Test URL accessibility
git ls-remote https://github.com/org/repo.git

# Check if token is set (for private repos)
docker exec docs-mcp-server printenv | grep -i token
```

**Fixes**:
1. **Invalid URL**: Ensure URL ends with `.git` and uses HTTPS
2. **Private repo without token**:
   ```json
   "git_auth_token_env": "GH_TOKEN"
   ```
   And pass token to container: `docker run -e GH_TOKEN=... ...`
3. **Wrong branch**: Verify branch exists in repository

---

### Search returns no results after sync

!!! warning "Symptoms"
    Sync shows documents_count > 0 but search returns empty.

**Diagnosis**:
```bash
# Check if index exists
ls -la mcp-data/<tenant>/__search_segments/
```

**Fixes**:
1. **Index not built**: Rebuild manually
   ```bash
   uv run python trigger_all_indexing.py --tenants <tenant>
   ```

2. **Stale segments**: Clean and rebuild
   ```bash
   uv run python cleanup_segments.py --tenant <tenant>
   uv run python trigger_all_indexing.py --tenants <tenant>
   ```

---

### Crawler getting blocked

!!! warning "Symptoms"
    HTTP 403/429 errors in logs, partial or no content.

**Diagnosis**:
```bash
# Check for rate limiting
docker logs docs-mcp-server 2>&1 | grep -E "429|403|blocked" | tail -10
```

**Fixes**:
1. **Reduce crawl rate**:
   - Lower `max_crawl_pages`
   - Use sitemap instead of crawler when possible
   - Space out refresh_schedule (e.g., every 14 days instead of daily)

2. **Use sitemap**: Some sites block crawlers but provide sitemaps
   ```json
   "enable_crawler": false,
   "docs_sitemap_url": "https://docs.example.com/sitemap.xml"
   ```

### Crawler lock contention

!!! warning "Symptoms"
   `/tenant/sync/status` shows `crawler_lock_status: contended` for several minutes and no new crawl logs appear.

**Diagnosis**: Call `/tenant/sync/status` and inspect `stats.crawler_lock_status`, `crawler_lock_owner`, and `crawler_lock_expires_at`. If another worker is crawling, the status stays `contended` until the TTL expires (default 180 s).

**Fixes**:
1. **Wait for TTL**: The lease auto-expires based on `crawler_lock_ttl_seconds` (minimum 60 s). The next sync run rechecks freshness before crawling again.
2. **Manual cleanup** (advanced): Stop the server and delete `mcp-data/<tenant>/__scheduler_meta/locks/crawler.lock` only if you are sure no crawler is running.
3. **Adjust TTL**: Set `"crawler_lock_ttl_seconds": 300` in infrastructure settings if crawls routinely exceed three minutes.
4. **Verify freshness**: If status stays `stale`, check `last_sync_at`—the scheduler skips reruns when the tenant already refreshed within one schedule interval.

---

### Adaptive concurrency behavior

!!! info "Understanding Concurrency Stats"
    Crawler uses adaptive concurrency to maximize throughput while respecting rate limits. Check `/tenant/sync/status` to see current behavior.

**Concurrency Stats** (from `/tenant/sync/status`):
```json
{
  "current_limit": 12,      // Current active worker ceiling
  "peak_limit": 20,         // Highest limit reached this session
  "active_workers": 8,      // Workers currently fetching pages
  "peak_active": 15         // Peak concurrency reached
}
```

**How It Works**:
- **Starts at min**: Initial concurrency = `crawler_min_concurrency` (default 5)
- **Ramps up**: After 25 successful fetches + 60s without 429s, adds 1 worker slot
- **Backs off**: On 429 response, immediately halves limit (min floor enforced)
- **Caps at max**: Never exceeds `crawler_max_concurrency` (default 20)

**Tuning Environment Variables**:

Set in `deployment.json` infrastructure section:
```json
{
  "crawler_min_concurrency": 10,    // Floor (1-100)
  "crawler_max_concurrency": 30,    // Ceiling (1-100)
  "crawler_max_sessions": 50,       // Hard process limit (1-100)
  "crawler_lock_ttl_seconds": 240   // Lock TTL (≥60)
}
```

**Diagnosing Low Throughput**:
```bash
# Check if stuck at min_limit
curl -s http://localhost:42042/<tenant>/sync/status | jq '{
  current_limit: .stats.current_limit, 
  active_workers: .stats.active_workers,
  urls_processed: .stats.urls_processed
}'
```

If `current_limit == crawler_min_concurrency` and no 429s in logs, possible causes:
1. **Rate limiter aggressive**: Check `AdaptiveRateLimiter` delays in logs
2. **Host slow**: Network latency prevents workers from saturating semaphore
3. **Small queue**: Frontier exhausted before adaptive ramp-up completes

**Forcing Higher Concurrency** (risky):
```json
// Bypass gradual ramp-up by starting higher
"crawler_min_concurrency": 15,
"crawler_max_concurrency": 15  // Same value = no adaptation
```

⚠️ This disables adaptive throttling—use only when confident the host can handle it.

---

## Debugging Tools

### Test Specific Tenant Locally

```bash
uv run python debug_multi_tenant.py --tenant <tenant> --test all
```

Output shows search results, fetch tests, and any errors encountered.

### Inspect Cached Documents

```bash
# List cached files
ls mcp-data/<tenant>/ | head -20

# View a cached document
cat "mcp-data/<tenant>/some-page.md" | head -50
```

### Check Search Index

```bash
# List index segments
ls -lah mcp-data/<tenant>/__search_segments/

# Rebuild index
uv run python trigger_all_indexing.py --tenants <tenant>
```

### Manual HTTP Test

```bash
# Test URL directly
curl -sI "https://docs.example.com/getting-started/"

# Test via container
docker exec docs-mcp-server curl -sI "https://docs.example.com/getting-started/"
```

---

## Log Levels

Increase verbosity for detailed debugging:

```bash
# Set in deployment.json infrastructure section
"log_level": "debug"

# Or via environment variable
docker run -e LOG_LEVEL=debug ...
```

Then check logs:
```bash
docker logs -f docs-mcp-server 2>&1 | grep <tenant>
```

---

## Recovery Steps

### Full Tenant Reset

If all else fails, reset the tenant completely:

```bash
# 1. Stop container
docker stop docs-mcp-server

# 2. Remove tenant data
rm -rf mcp-data/<tenant>

# 3. Restart container
docker start docs-mcp-server

# 4. Trigger fresh sync
uv run python trigger_all_syncs.py --tenants <tenant> --force

# 5. Wait for sync, then rebuild index
uv run python trigger_all_indexing.py --tenants <tenant>
```

---

## Related

- How-To: [Trigger Syncs](trigger-syncs.md) — Force refresh documentation
- How-To: [Configure Online Tenant](configure-online-tenant.md) — Setup guidance
- How-To: [Configure Git Tenant](configure-git-tenant.md) — Git-specific setup
- Reference: [CLI Commands](../reference/cli-commands.md) — Debug and sync scripts
