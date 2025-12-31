# How-To: Configure Git Tenant

**Goal**: Add documentation from a GitHub or GitLab repository to your deployment.  
**Prerequisites**: Repository with markdown files, `deployment.json` configured, Docker container running.  
**Time**: ~10 minutes

---

## When to Use Git Tenants

Use git tenants when:
- Documentation lives in a GitHub/GitLab repository
- You want version-controlled, deterministic syncs
- The repository has a `docs/` folder with markdown files
- You prefer git-based updates over web crawling

---

## Steps

### 1. Identify Repository Details

Gather this information:
- **Repository URL**: HTTPS URL (e.g., `https://github.com/mkdocs/mkdocs.git`)
- **Branch**: Usually `main` or `master`
- **Documentation path**: Folder containing markdown files (e.g., `docs/`)

### 2. Add Tenant to deployment.json

Edit `deployment.json` and add a new tenant to the `tenants` array:

```json
{
  "source_type": "git",
  "codename": "mkdocs",
  "docs_name": "MkDocs Documentation",
  "git_repo_url": "https://github.com/mkdocs/mkdocs.git",
  "git_branch": "master",
  "git_subpaths": ["docs"],
  "git_strip_prefix": "docs",
  "docs_root_dir": "./mcp-data/mkdocs",
  "refresh_schedule": "0 */6 * * *",
  "test_queries": {
    "natural": ["How to create a new MkDocs project"],
    "phrases": ["configuration", "navigation"],
    "words": ["mkdocs", "theme", "plugins"]
  }
}
```

**Required fields**:
- `source_type`: Must be `"git"`
- `codename`: Unique lowercase identifier
- `docs_name`: Human-readable name
- `git_repo_url`: HTTPS repository URL
- `git_subpaths`: Array of paths to include (at least one)
- `docs_root_dir`: Local storage path

**Optional fields**:
- `git_branch`: Branch name (default: `"main"`)
- `git_strip_prefix`: Remove leading path when copying files
- `refresh_schedule`: Cron schedule for auto-sync

### 3. Redeploy the Container

```bash
uv run python deploy_multi_tenant.py --mode online
```

### 4. Trigger Initial Sync

```bash
uv run python trigger_all_syncs.py --tenants mkdocs --force
```

Wait for sync to complete (usually 30-60 seconds for git tenants).

### 5. Verify Sync Status

Check container logs for sync completion:

```bash
docker logs docs-mcp-server 2>&1 | grep -i mkdocs | tail -10
```

You should see a message like "Git sync completed" with a file count and commit hash.

### 6. Test Search

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant mkdocs --test search
```

---

## Private Repositories

For private repositories, use a personal access token:

### 1. Create Token

- **GitHub**: Settings → Developer settings → Personal access tokens → Generate new token (repo scope)
- **GitLab**: User Settings → Access Tokens → Create token (read_repository scope)

### 2. Set Environment Variable

```bash
export GH_TOKEN="ghp_xxxxxxxxxxxx"
```

### 3. Reference in deployment.json

```json
{
  "source_type": "git",
  "codename": "private-docs",
  "git_repo_url": "https://github.com/org/private-repo.git",
  "git_auth_token_env": "GH_TOKEN",
  "git_subpaths": ["docs"],
  "docs_root_dir": "./mcp-data/private-docs"
}
```

### 4. Pass to Docker

```bash
docker run -e GH_TOKEN="$GH_TOKEN" ...
```

---

## Multiple Documentation Paths

To include multiple folders from one repository:

```json
{
  "git_subpaths": ["docs", "tutorials", "reference"],
  "git_strip_prefix": ""
}
```

This syncs `docs/`, `tutorials/`, and `reference/` folders, keeping their directory structure.

---

## Troubleshooting

### Sync fails with "Repository not found"

**Cause**: Invalid URL or private repo without token.

**Fix**:
1. Verify URL: `git ls-remote https://github.com/org/repo.git`
2. For private repos, set `git_auth_token_env` and pass the token

### No documents after sync

**Cause**: Wrong `git_subpaths` or no markdown files.

**Fix**:
1. Check repository structure: `git clone --depth 1 <url> && tree <path>`
2. Verify `git_subpaths` points to folders with `.md` files

### Sync completes but search returns no results

**Cause**: Index not rebuilt after sync.

**Fix**:
```bash
uv run python trigger_all_indexing.py --tenants mkdocs
```

---

## Related

- Tutorial: [Adding Your First Tenant](../tutorials/adding-first-tenant.md) — Step-by-step tenant setup
- How-To: [Configure Online Tenant](configure-online-tenant.md) — For website documentation
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md) — All configuration options
- Explanation: [Sync Strategies](../explanations/sync-strategies.md) — Git vs online sync
