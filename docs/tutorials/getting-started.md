# Tutorial: Get docs-mcp-server running in 15 minutes

**Time**: ~15 minutes  
**Audience**: first-time users who want a working tenant quickly  
**Outcome**: you deploy the server, sync one tenant, and run a real search test

## Why this matters

Most documentation tools stop at static hosting. This server is different: it exposes your docs as MCP tools so assistants can search and fetch authoritative content programmatically.

By the end of this tutorial, you have a working retrieval path you can connect to your MCP client.

## Prerequisites

- Python 3.12+
- `uv`
- Docker running locally
- `git`

## Step 1: Clone and install dependencies

```bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
uv sync
```

## Step 2: Create deployment config

```bash
cp deployment.example.json deployment.json
```

This gives you preconfigured tenants like `drf`, `django`, and `fastapi`.

## Step 3: Deploy the server container

```bash
uv run python deploy_multi_tenant.py --mode online
```

This starts the MCP server with online sync enabled.

## Step 4: Sync one tenant

Start small with `drf`.

```bash
uv run python trigger_all_syncs.py --tenants drf --force
```

`--force` bypasses freshness/idempotency checks, which is useful for first-run verification.

## Step 5: Run a search test

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

If this returns ranked documents with snippets and URLs, your retrieval path works.

## Step 6: Connect your MCP client

Add the server endpoint to your MCP client's configuration file:

- VS Code (Linux): `~/.config/Code/User/mcp.json`
- VS Code (macOS): `~/Library/Application Support/Code/User/mcp.json`
- VS Code (Windows): `%APPDATA%\\Code\\User\\mcp.json`

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

Restart your MCP-aware client/editor after editing the config.

## Verification

Run these checks:

```bash
curl -sS http://localhost:42042/health | head -c 200
curl -sS http://localhost:42042/mcp.json
```

Actual output from 2026-02-11T06:17:34+01:00:

```text
{"status":"healthy","tenant_count":105,"tenants":{"a-philosophy-of-software-design":{"status":"healthy","tenant":"a-philosophy-of-software-design","source_type":"filesystem"},"a2a-protocol":{"status":"healthy","t
{"defaultModel":"claude-haiku-4.5","servers":{"docs-mcp-root":{"type":"http","url":"http://127.0.0.1:42042/mcp"}}}
```

If both commands return JSON, your server is reachable and MCP metadata is available.

## Troubleshooting

### `Connection refused` on localhost:42042

- Ensure Docker is running.
- Re-run: `uv run python deploy_multi_tenant.py --mode online`

### Search returns no results

- Confirm sync completed.
- Re-run force sync: `uv run python trigger_all_syncs.py --tenants drf --force`

### Tenant not found

- Open `deployment.json` and confirm the tenant codename exists.

## Next steps

- Add your own source: [Tutorial: Adding your first tenant](adding-first-tenant.md)
- Operate production-like workflows: [How-to: Deploy Docker](../how-to/deploy-docker.md)
- Understand internals: [Explanation: Architecture](../explanations/architecture.md)
