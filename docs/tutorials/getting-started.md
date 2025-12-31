# Tutorial: Getting Started with docs-mcp-server

**Time**: ~20 minutes  
**Prerequisites**: Python 3.10+, uv package manager, Docker installed  
**What You'll Learn**: Deploy a multi-tenant MCP server, sync documentation, and integrate with VS Code

---

## Overview

This tutorial walks you through a fresh setup of docs-mcp-server. By the end, you'll have:

1. A Docker container running on port 42042
2. Synced documentation from at least one tenant (e.g., `drf`)
3. VS Code configured to use your MCP server for AI-assisted documentation search

**Important**: Follow the steps in order. Each step depends on the previous one.

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
```

## Step 2: Install Dependencies

```bash
uv sync
```

**Expected output**:
```
Resolved 173 packages in 1ms
Audited 162 packages in 3ms
```

## Step 3: Create Your Configuration

The repository includes an example configuration with 10 documentation tenants. Copy it to create your own:

```bash
cp deployment.example.json deployment.json
```

This creates `deployment.json` with these pre-configured tenants:

| Codename | Documentation Source | Type |
|----------|---------------------|------|
| `django` | Django framework docs | Online |
| `drf` | Django REST Framework docs | Online |
| `fastapi` | FastAPI framework docs | Online |
| `python` | Python standard library docs | Online |
| `pytest` | Pytest testing framework docs | Online |
| `aws-bedrock-agentcore` | AWS Bedrock AgentCore docs | Online |
| `strands-sdk` | Strands SDK docs | Online |
| `cosmicpython` | Cosmic Python patterns (free online) | Online |
| `mkdocs` | MkDocs documentation | Git |
| `aidlc-rules` | AIDLC rules | Git |

> **Note**: You can edit `deployment.json` later to add, remove, or modify tenants.

## Step 4: Deploy to Docker

Build and start the MCP server container:

```bash
uv run python deploy_multi_tenant.py --mode online
```

**Expected output**:
```
📦 Syncing Python environment and updating lock file...
🐳 Building Docker image: pankaj28843/docs-mcp-server:multi-tenant...
🚀 Starting container on port 42042 in online mode...
✅ Deployment complete!
```

Verify the container is running:

```bash
curl -s http://localhost:42042/health | jq .
```

**Expected output**:
```json
{
  "status": "healthy",
  "tenant_count": 10,
  ...
}
```

> **Warning**: The deploy script modifies your local Python environment (uninstalls dev packages) to minimize Docker image size. Run `uv sync` afterward to restore packages for local development.

## Step 5: Trigger Initial Documentation Sync

After deployment, the server is running but **documentation hasn't been crawled yet**. You need to trigger a sync.

Start with a small tenant like `drf` (Django REST Framework) for a quick first sync:

```bash
uv run python trigger_all_syncs.py --tenants drf --force
```

**Expected output**:
```
Triggering sync for drf...
✓ drf: sync triggered
```

### Wait for Sync to Complete

The sync runs in the background. **Wait 1-2 minutes** for the crawl to finish, then check status:

```bash
curl -s http://localhost:42042/drf/sync/status | jq .
```

**Expected output** (when complete):
```json
{
  "status": "idle",
  "last_sync": "2025-12-31T10:30:00Z",
  "documents_count": 127,
  ...
}
```

If you see `"status": "syncing"`, wait a bit longer and check again.

## Step 6: Test Search

Once the sync completes, test that search works:

```bash
curl -s "http://localhost:42042/drf/search?query=serializer" | jq '.results[:2]'
```

**Expected output**:
```json
[
  {
    "title": "Serializers - Django REST Framework",
    "url": "https://www.django-rest-framework.org/api-guide/serializers/",
    "score": 12.45,
    "snippet": "Serializers allow complex data such as querysets..."
  },
  ...
]
```

You can also use the debug script:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

**Expected output**:
```
✅ Search successful, returned 5 results
```

## Step 7: Sync Additional Tenants (Optional)

Now that `drf` works, sync other tenants you want to use:

```bash
# Sync Django docs (larger, takes 5-10 minutes)
uv run python trigger_all_syncs.py --tenants django --force

# Sync multiple tenants
uv run python trigger_all_syncs.py --tenants fastapi,pytest --force

# Sync all configured tenants (may take 30+ minutes)
uv run python trigger_all_syncs.py --force
```

Check sync status for any tenant:

```bash
curl -s http://localhost:42042/django/sync/status | jq .
```

## Step 8: Connect VS Code

Add the MCP server to your VS Code configuration.

**Linux**: `~/.config/Code/User/mcp.json`  
**macOS**: `~/Library/Application Support/Code/User/mcp.json`  
**Windows**: `%APPDATA%\Code\User\mcp.json`

Create or edit the file:

```json
{
  "servers": {
    "TechDocs": {
      "type": "http",
      "url": "http://127.0.0.1:42042/mcp"
    }
  }
}
```

**Restart VS Code** after saving the configuration.

## Step 9: Verify AI Integration

Open VS Code and start a conversation with Copilot or Claude. Ask a question about a synced tenant:

> "How do I create a ModelSerializer in Django REST Framework?"

The AI should be able to:
1. Search your `drf` tenant using MCP tools
2. Find relevant documentation
3. Answer with accurate, up-to-date information

---

## Verification Checklist

You should now have:

- [x] Docker container running on port 42042
- [x] At least one tenant (`drf`) synced with documentation
- [x] Search returning relevant results
- [x] VS Code configured with MCP server connection

---

## Troubleshooting

### Sync fails or returns no documents

1. Check sync status: `curl http://localhost:42042/drf/sync/status | jq .`
2. Check container logs: `docker logs docs-mcp-server 2>&1 | tail -50`
3. Verify network: `curl -I https://www.django-rest-framework.org/`

### Search returns empty results

1. Verify sync completed: Check that `documents_count > 0` in sync status
2. Try a simpler query: `curl "http://localhost:42042/drf/search?query=serializer"`
3. Trigger re-sync: `uv run python trigger_all_syncs.py --tenants drf --force`

### VS Code doesn't see MCP server

1. Verify container running: `docker ps | grep docs-mcp-server`
2. Test endpoint: `curl http://127.0.0.1:42042/health`
3. Check mcp.json syntax: Valid JSON with no trailing commas
4. Restart VS Code after config changes

---

## Next Steps

- **Add custom tenants**: [Adding Your First Tenant](adding-first-tenant.md) - Add documentation sources not in the example
- **Git-based docs**: [Configure Git Tenant](../how-to/configure-git-tenant.md) - Add GitHub/GitLab repository docs
- **Reference**: [CLI Commands](../reference/cli-commands.md) - Full script documentation
- **Reference**: [deployment.json Schema](../reference/deployment-json-schema.md) - All configuration options
