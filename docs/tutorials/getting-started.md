# Tutorial: Getting Started with docs-mcp-server

**Time**: ~20 minutes  
**Prerequisites**: Python 3.10+, uv package manager, Docker installed  
**What You'll Learn**: Deploy a multi-tenant MCP server, sync documentation, and integrate with VS Code

---

## Why This Matters

AI assistants work best when they have access to accurate, up-to-date documentation. Without this, they hallucinate API details or give outdated advice. This tutorial shows you how to give your AI assistant direct access to authoritative docs—so it answers with real documentation quotes, not guesses.

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

This resolves dependencies and prepares the environment. You should see output showing packages resolved and synced.

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

The script builds a Docker image and starts the container. When complete, you'll see "✅ Deployment complete!" with the server URL.

Verify the container is running:

```bash
curl -s http://localhost:42042/health | jq '{status, tenant_count}'
```

You should see `"status": "healthy"` and a tenant count matching your configuration.

> **Warning**: The deploy script modifies your local Python environment (uninstalls dev packages) to minimize Docker image size. Run `uv sync` afterward to restore packages for local development.

## Step 5: Trigger Initial Documentation Sync

After deployment, the server is running but **documentation hasn't been crawled yet**. You need to trigger a sync.

Start with a small tenant like `drf` (Django REST Framework) for a quick first sync:

```bash
uv run python trigger_all_syncs.py --tenants drf --force
```

The script will show progress and confirm when sync is complete. If the tenant was already synced, you'll see "Sync cycle completed" immediately.

### Wait for Sync to Complete

The sync runs in the background. **Wait 1-2 minutes** for the crawl to finish. Check progress in container logs:

```bash
docker logs docs-mcp-server 2>&1 | grep -i drf | tail -10
```

When sync completes, you'll see a message like "Sync cycle completed" in the logs.

## Step 6: Test Search

Once the sync completes, test that search works using the debug script:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

This runs a local server, executes test queries from your tenant configuration, and shows the results with scores and snippets.

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
