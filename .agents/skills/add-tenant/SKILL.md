---
name: add-tenant
description: Add new documentation tenants to deployment.json — supports git, online, and filesystem types with backup, validation, deploy, and debug
---

# Add New Tenant Workflow

Add documentation sources as searchable tenants. Supports three source types:
- **git** — GitHub/GitLab repos with sparse checkout
- **online** — Documentation websites crawled via sitemap or entry URLs
- **filesystem** — Pre-existing local Markdown/HTML directories

## Step 0: Backup deployment.json

ALWAYS back up before any changes. deployment.json is untracked (git-ignored).

```bash
mkdir -p tmp/backups && cp deployment.json "tmp/backups/deployment.json.$(date +%Y%m%d-%H%M%S)"
```

## Step 1: Study existing tenants of the same type

Before adding anything, sample 2-3 existing tenants of the same source_type to match conventions.

```bash
python3 -c "
import json
with open('deployment.json') as f:
    config = json.load(f)
for t in config['tenants']:
    if t['source_type'] == '<TYPE>':  # git | online | filesystem
        print(json.dumps(t, indent=2))
        print()
" | head -80
```

Also list all codenames to check for duplicates:

```bash
python3 -c "import json; d=json.load(open('deployment.json')); print(json.dumps(sorted([t['codename'] for t in d['tenants']])))"
```

## Step 2: Determine tenant configuration

### For `git` tenants (GitHub repos)

Identify from the URL:
- `git_branch`: Usually `main` or `master` — check the repo's default branch
- `git_subpaths`: The subdirectory containing docs (e.g., `["docs"]`, `["cheatsheets"]`)
- `git_strip_prefix`: Usually matches `git_subpaths[0]` to flatten the directory structure
- `search.analyzer_profile`: Use `"code-friendly"` for code-heavy repos, `"default"` otherwise

Required fields:

```json
{
  "source_type": "git",
  "codename": "<lowercase-hyphen-name>",
  "docs_name": "<Human Readable Name>",
  "git_repo_url": "https://github.com/<org>/<repo>.git",
  "git_branch": "main",
  "git_subpaths": ["<subpath>"],
  "git_strip_prefix": "<subpath>",
  "docs_root_dir": "./mcp-data/<codename>",
  "refresh_schedule": "<M> <H> <cron-tail>"
}
```

Optional fields:
- `git_auth_token_env`: Env var name for private repo PAT (e.g., `"GITHUB_TOKEN"`)
- `git_sync_interval_minutes`: Override sync cadence (5-1440 min)
- `search.analyzer_profile`: `"default"` | `"aggressive-stem"` | `"code-friendly"`

### For `online` tenants (documentation websites)

Two discovery methods (need at least one):
1. **Sitemap**: `docs_sitemap_url` — list or comma-separated string of sitemap XML URLs
2. **Crawler entry**: `docs_entry_url` + `enable_crawler: true` — starts from URL and follows links

Required fields:

```json
{
  "source_type": "online",
  "codename": "<name>",
  "docs_name": "<Human Readable Name>",
  "docs_root_dir": "./mcp-data/<codename>",
  "refresh_schedule": "<M> <H> <cron-tail>"
}
```

Plus ONE of:
```json
"docs_sitemap_url": "https://example.com/sitemap.xml"
```
OR:
```json
"docs_entry_url": "https://example.com/docs/",
"enable_crawler": true,
"max_crawl_pages": 20000
```

Optional URL filtering (comma-separated prefixes):
- `url_whitelist_prefixes`: Only include URLs matching these prefixes
- `url_blacklist_prefixes`: Exclude URLs matching these prefixes (e.g., release notes, changelogs)
- `markdown_url_suffix`: Append suffix to URLs for Markdown mirrors (e.g., `".md"`)
- `preserve_query_strings`: Keep query params in canonical paths (default: true)

### For `filesystem` tenants (local directories)

Minimal config — docs are pre-indexed locally, no sync needed.

```json
{
  "source_type": "filesystem",
  "codename": "<name>",
  "docs_name": "<Human Readable Name>",
  "docs_root_dir": "./mcp-data/<codename>"
}
```

No `refresh_schedule` needed (no crawler). Data must already exist in `docs_root_dir`.

## Step 2.5: Source discovery and browser diagnostics

Use this step before editing `deployment.json` when the docs source is unclear, JavaScript-rendered, hidden behind redirects, or likely to need rendered-browser evidence.

### When to use `/search-web-cdp`

Use `/search-web-cdp` to find actual sources when any of these are true:
- Official docs URLs are ambiguous across versions, products, or cloud/on-prem variants
- Sitemap URLs are not obvious from common locations
- The site renders navigation or content with JavaScript
- Vendor search pages reveal canonical docs pages better than static HTML does
- You need to verify whether a GitHub/docs repo, sitemap, Markdown mirror, or crawler entry is the best source

Example query:

```bash
/search-web-cdp "<vendor/product> official docs sitemap markdown source"
```

### Verify `cdp` behavior from local help

Do not assume `cdp` flags. Check the installed CLI before writing commands:

```bash
cdp --help
cdp doctor --help
cdp workflow --help
cdp workflow rendered-extract --help
cdp workflow debug-bundle --help
cdp workflow page-load --help
cdp workflow network-failures --help
```

Follow the user's `/dev-browser` flow for browser automation: headed Chrome on the interactive display, no Playwright, no headless fallback, and no throwaway isolated profile unless project instructions explicitly require it.

### Collect rendered-page evidence

Save transient browser evidence under `tmp/cdp/<codename>/`:

```bash
mkdir -p tmp/cdp/<codename>
cdp workflow rendered-extract "<docs-url>" --out-dir tmp/cdp/<codename> --formats all --keep-open
cdp workflow page-load "<docs-url>" --out tmp/cdp/<codename>/page-load.json --wait 10s
cdp workflow network-failures --url-contains "<docs-host>" --wait 5s --json
cdp workflow debug-bundle --url "<docs-url>" --out-dir tmp/cdp/<codename>/debug-bundle --screenshot-view
```

Use the artifacts to decide:
- Sitemap tenant: XML lists the docs pages directly
- Crawler tenant: rendered links are discoverable from stable entry pages
- Git tenant: docs source is a repo/subpath and HTML crawling adds noise
- Filesystem tenant: content must be prepared outside the server

## Step 3: Add tenant(s) to deployment.json

Use Python CLI to add, sort, and write atomically:

```bash
python3 -c "
import json
with open('deployment.json') as f:
    config = json.load(f)

new_tenants = [
    # ... tenant dicts here ...
]

existing = {t['codename'] for t in config['tenants']}
for t in new_tenants:
    if t['codename'] in existing:
        print(f'DUPLICATE: {t[\"codename\"]}')
    else:
        config['tenants'].append(t)
        print(f'Added: {t[\"codename\"]}')

config['tenants'].sort(key=lambda t: t['codename'])
with open('deployment.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
print(f'Total tenants: {len(config[\"tenants\"])}')
"
```

### Cron schedule guidelines

Spread schedules to avoid all tenants syncing at once:
- Use different minute offsets (0-59)
- Stagger hours across the day
- Weekly for stable docs: `M H * * <DOW>` (e.g., `18 2 * * 0` = Sunday 2:18 AM)
- Biweekly for slow-changing docs: `M H */14 * *`
- Daily for active repos: `M H * * *`

## Step 4: Validate config via Pydantic model

```bash
uv run python -c "
from docs_mcp_server.deployment_config import DeploymentConfig
import json
with open('deployment.json') as f:
    raw = json.load(f)
config = DeploymentConfig(**raw)
targets = ['<codename1>', '<codename2>']
for t in config.tenants:
    if t.codename in targets:
        print(f'{t.codename}: {t.docs_name} ({t.source_type}) - OK')
print(f'Validation passed ({len(config.tenants)} total tenants)')
"
```

If validation fails, restore from backup:
```bash
cp tmp/backups/deployment.json.<latest-timestamp> deployment.json
```

## Step 5: Sample content and add test_queries

After the tenant data is synced (either via deploy or pre-existing), sample actual content using ripgrep:

```bash
# Find headings and key terms
rg '^# |^## ' mcp-data/<codename>/ | head -30

# Find domain-specific terms for word queries
rg -c '<domain-term>' mcp-data/<codename>/ | sort -t: -k2 -rn | head -10
```

Then update deployment.json with test_queries:

```bash
python3 -c "
import json
with open('deployment.json') as f:
    config = json.load(f)
for t in config['tenants']:
    if t['codename'] == '<codename>':
        t['test_queries'] = {
            'natural': [
                'how to <do something from the docs>',
                '<question the docs answer>'
            ],
            'phrases': [
                '<exact heading or phrase from the docs>',
                '<another exact phrase>'
            ],
            'words': [
                '<domain-keyword-1>',
                '<domain-keyword-2>',
                '<domain-keyword-3>'
            ]
        }
        print(f'Updated: {t[\"codename\"]}')
with open('deployment.json', 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
"
```

### test_queries guidelines

- **natural**: Questions a user would ask; should match broad results
- **phrases**: Exact headings or phrases from the docs; should match specific pages
- **words**: Single domain keywords; should always return results
- Pick terms that actually appear in the corpus (sample first!)
- For tiny corpora (< 5 docs), all 3 types should still return >= 1 result

## Step 6: Deploy and verify health

```bash
uv run python deploy_multi_tenant.py --mode online
```

Wait for startup, then verify:

```bash
sleep 15 && curl -sf http://127.0.0.1:42042/health | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d['status'], d['tenant_count'])
for name in sorted(d['tenants']):
    if 'owasp' in name or '<codename>' in name:  # filter to new tenants
        t = d['tenants'][name]
        print(f'  {name}: {t[\"status\"]} ({t[\"source_type\"]})')
"
```

## Step 7: Debug each new tenant against Docker

```bash
uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant <codename>
```

All searches and fetches must pass (green). If 0 search results:
1. Check if data exists: `ls mcp-data/<codename>/`
2. For git tenants: data syncs on container startup, wait 30s and retry
3. For online tenants: trigger sync manually: `uv run python trigger_all_syncs.py --host 127.0.0.1 --port 42042 --tenants <codename> --force`
4. Rebuild index: `uv run python trigger_all_indexing.py --tenants <codename>`

### Failure diagnosis matrix

| Symptom | Check | Fix |
|---|---|---|
| Config validation fails | `uv run python -c "from docs_mcp_server.deployment_config import DeploymentConfig; import json; DeploymentConfig(**json.load(open('deployment.json')))"` | Remove unknown fields, fix codename, or add the required source-specific fields |
| Health endpoint misses tenant | `curl -sf http://127.0.0.1:42042/health` | Redeploy with `uv run python deploy_multi_tenant.py --mode online`; for Docker use `bash scripts/dev_up.sh`, never `docker compose` directly |
| Sync returns zero documents | `uv run python trigger_all_syncs.py --host 127.0.0.1 --port 42042 --tenants <codename> --force` | Recheck sitemap/entry URL, whitelist/blacklist, redirects, and crawler settings |
| Sitemap fetch fails or redirects | `cdp workflow page-load "<sitemap-or-docs-url>" --out tmp/cdp/<codename>/page-load.json --wait 10s` | Use the final canonical URL, a Git source, or a crawler entry URL instead of the failing sitemap |
| Crawler discovers irrelevant pages | Inspect `tmp/cdp/<codename>/links.*` from rendered extraction | Tighten `url_whitelist_prefixes` and add blacklist prefixes for release notes, marketing pages, or generated noise |
| Index rebuild leaves zero searchable results | `uv run python trigger_all_indexing.py --tenants <codename> --dry-run` | Inspect `mcp-data/<codename>/__docs_metadata` and malformed metadata errors before rebuilding |
| `docsearch` returns weak matches | `uv run docsearch search <codename> "<known-good-query>" --json` | Replace `test_queries` with sampled corpus terms and consider `search.analyzer_profile` |
| Fetch-by-URL fails after search works | `uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant <codename> --test fetch` | Compare the result URL to stored metadata and canonicalization settings |

## Step 8: Test with docsearch CLI

```bash
# Single tenant search
uv run docsearch search <codename> "<query>" --json | head -20

# Cross-tenant search-all
uv run docsearch search-all "<query>" --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
hits = [r for r in data.get('results', []) if r['tenant'] == '<codename>']
for r in hits:
    print(f\"{r['score']:.3f} [{r['tenant']}] {r['title'][:70]}\")
print(f'Found {len(hits)} results for <codename>')
"
```

## Step 9: Export if needed

```bash
uv run python sync_tenant_data.py export --tenants <codename1> <codename2>
```

## Reference: all TenantConfig fields

| Field | Type | Default | Applies to | Notes |
|---|---|---|---|---|
| `source_type` | `online\|filesystem\|git` | `online` | all | Determines required fields |
| `codename` | `str` | required | all | `^[a-z][a-z0-9_-]*$`, 2-64 chars, unique |
| `docs_name` | `str` | required | all | Human-readable, 1-200 chars |
| `docs_root_dir` | `str\|null` | null | all | Always `./mcp-data/<codename>` |
| `docs_sitemap_url` | `str\|list` | `[]` | online | Sitemap XML URLs |
| `docs_entry_url` | `str\|list` | `[]` | online | Crawler starting URLs |
| `url_whitelist_prefixes` | `str` | `""` | online | Comma-separated URL prefixes to include |
| `url_blacklist_prefixes` | `str` | `""` | online | Comma-separated URL prefixes to exclude |
| `markdown_url_suffix` | `str\|null` | null | online | Suffix for Markdown mirrors |
| `fetch_user_agent` | `str\|null` | null | online | Override User-Agent for fetches that reject default agents |
| `preserve_query_strings` | `bool` | true | online | Keep query params in paths |
| `enable_crawler` | `bool` | false | online | Follow links from entry URLs |
| `max_crawl_pages` | `int` | 10000 | online | Cap on crawled pages |
| `git_repo_url` | `str\|null` | null | git | HTTPS repo URL |
| `git_branch` | `str` | `"main"` | git | Branch/tag/commit |
| `git_subpaths` | `list[str]\|null` | null | git | Sparse checkout paths (min 1) |
| `git_strip_prefix` | `str\|null` | null | git | Strip leading path from files |
| `git_auth_token_env` | `str\|null` | null | git | Env var for PAT (`^[A-Z_][A-Z0-9_]*$`) |
| `git_sync_interval_minutes` | `int\|null` | null | git | Override sync cadence (5-1440) |
| `refresh_schedule` | `str\|null` | null | online, git | Cron expression |
| `snippet_surrounding_chars` | `int` | 1000 | all | 200-3000 |
| `search.analyzer_profile` | `str` | `"default"` | all | `default\|aggressive-stem\|code-friendly` |
| `allow_index_builds` | `bool\|null` | null | all | Override infra-level toggle |
| `test_queries` | `dict\|null` | null | all | `{natural, phrases, words}` for debug script |

## Validation rules (enforced by Pydantic)

- `model_config = {"extra": "forbid"}` — unknown keys are rejected
- **filesystem**: must have `docs_root_dir`
- **git**: must have `git_repo_url` + at least one `git_subpaths` entry
- **online**: must have `docs_sitemap_url` OR `docs_entry_url`
- **cron**: validated by `cron-converter` library
- **codenames**: must be unique across all tenants

## Important notes

- `deployment.json` is **untracked** (git-ignored) — always back up before editing
- Git tenants auto-sync on container startup — no need for `trigger_all_syncs.py`
- Online tenants sync on their `refresh_schedule` — use `trigger_all_syncs.py --tenants <name>` for immediate sync
- Filesystem tenants have no sync — data must pre-exist in `docs_root_dir`
- Use `code-friendly` analyzer for code-heavy repos (Go, Python, etc.)
- Spread cron schedules to avoid simultaneous syncs across tenants
