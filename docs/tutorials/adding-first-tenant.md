# Tutorial: Adding Your First Tenant

**Time**: ~10 minutes  
**Prerequisites**: Completed [Getting Started](getting-started.md) tutorial, server running  
**What You'll Learn**: Add a custom documentation source to your deployment

---

## Overview

The example `deployment.json` includes 10 pre-configured tenants. This tutorial shows you how to add your own documentation source.

---

## Step 1: Choose Your Documentation Source

Decide what type of documentation you want to add:

| Type | Use Case | Example |
|------|----------|---------|
| **Online** | Website with sitemap or crawlable pages | FastAPI docs, Django docs |
| **Git** | Markdown files in a GitHub/GitLab repo | MkDocs project, README collection |
| **Filesystem** | Local markdown files | Your own project docs |

---

## Step 2: Edit deployment.json

Open `deployment.json` and add a new tenant to the `"tenants"` array.

### Example: Online Tenant (Website)

```json
{
  "source_type": "online",
  "codename": "httpx",
  "docs_name": "HTTPX Docs",
  "docs_sitemap_url": "https://www.python-httpx.org/sitemap.xml",
  "url_whitelist_prefixes": "https://www.python-httpx.org/",
  "enable_crawler": false,
  "docs_root_dir": "./mcp-data/httpx",
  "refresh_schedule": "0 2 */14 * *",
  "test_queries": {
    "natural": ["How to make async HTTP requests"],
    "phrases": ["async", "client"],
    "words": ["httpx", "request", "response"]
  }
}
```

### Example: Git Tenant (GitHub Repo)

```json
{
  "source_type": "git",
  "codename": "my-project",
  "docs_name": "My Project Docs",
  "git_repo_url": "https://github.com/username/my-project.git",
  "git_branch": "main",
  "git_subpaths": ["docs"],
  "git_strip_prefix": "docs",
  "docs_root_dir": "./mcp-data/my-project",
  "refresh_schedule": "0 */6 * * *",
  "test_queries": {
    "natural": ["Getting started with my project"],
    "phrases": ["installation"],
    "words": ["setup", "config"]
  }
}
```

---

## Step 3: Redeploy

After editing `deployment.json`, redeploy the container:

```bash
uv run python deploy_multi_tenant.py --mode online
```

---

## Step 4: Trigger Sync

Sync your new tenant:

```bash
uv run python trigger_all_syncs.py --tenants httpx --force
```

Wait 1-2 minutes, then check status:

```bash
curl -s http://localhost:42042/httpx/sync/status | jq .
```

---

## Step 5: Test Search

```bash
curl -s "http://localhost:42042/httpx/search?query=async+client" | jq '.results[:2]'
```

---

## Verification

Your new tenant should now appear in the server and return search results.

---

## Next Steps

- How-To: [Configure Online Tenant](../how-to/configure-online-tenant.md) - Detailed options for websites
- How-To: [Configure Git Tenant](../how-to/configure-git-tenant.md) - Detailed options for git repos
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md) - All configuration options
