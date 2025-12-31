# How-To: Trigger Syncs

**Goal**: Force refresh documentation from online sources or git repos.  
**Prerequisites**: Docker container running, tenants configured in `deployment.json`.  
**Time**: ~5 minutes (plus sync wait time).

---

## Steps

### Sync Specific Tenants

```bash
# Sync one tenant
uv run python trigger_all_syncs.py --tenants drf --force

# Sync multiple tenants
uv run python trigger_all_syncs.py --tenants django,fastapi,pytest --force
```

### Sync All Tenants

```bash
uv run python trigger_all_syncs.py --force
```

> **Warning**: Syncing all tenants can take 30+ minutes depending on documentation size.

### Check Sync Status

```bash
# Check container logs for sync progress
docker logs docs-mcp-server 2>&1 | grep -i drf | tail -10
```

When sync completes, you'll see "Sync cycle completed" for online tenants or "Git sync completed" for git tenants.

### Rebuild Search Index

After syncing, you may want to rebuild the BM25 search index:

```bash
uv run python trigger_all_indexing.py --tenants drf django
```

---

## Troubleshooting

**Sync stuck or failing**:
```bash
# Check container logs
docker logs docs-mcp-server 2>&1 | grep -i "drf" | tail -20

# Force restart and re-sync
docker restart docs-mcp-server
sleep 10
uv run python trigger_all_syncs.py --tenants drf --force
```

**No documents after sync**:
1. Verify the source URL is accessible: `curl -I https://www.django-rest-framework.org/`
2. Check whitelist/blacklist prefixes in `deployment.json`
3. For git tenants, verify the repo is public and branch exists

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) - Initial setup and sync
- How-To: [Deploy to Docker](deploy-docker.md) - Container deployment
- Reference: [CLI Commands](../reference/cli-commands.md) - Full script options
