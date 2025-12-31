# How-To: Deploy to Docker

**Goal**: Deploy docs-mcp-server to a Docker container for production use.  
**Prerequisites**: Docker installed, `deployment.json` configured

---

## Steps

### 1. Ensure Configuration Exists

If you haven't already, copy the example configuration:

```bash
cp deployment.example.json deployment.json
```

Edit `deployment.json` to customize which tenants to include.

### 2. Deploy the Container

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

### 3. Verify Deployment

```bash
curl -s http://localhost:42042/health | jq .
```

**Expected output**:
```json
{
  "status": "healthy",
  "tenant_count": 10
}
```

### 4. Trigger Initial Syncs

After deployment, trigger documentation syncs:

```bash
# Sync a small tenant first
uv run python trigger_all_syncs.py --tenants drf --force

# Wait 1-2 minutes, then sync others
uv run python trigger_all_syncs.py --tenants django,fastapi --force
```

Check sync status:

```bash
curl -s http://localhost:42042/drf/sync/status | jq .
```

---

## Troubleshooting

**Container won't start**:
```bash
docker logs docs-mcp-server 2>&1 | tail -20
```

**Port already in use**:
```bash
# Check what's using port 42042
lsof -i :42042

# Stop existing container
docker stop docs-mcp-server && docker rm docs-mcp-server
```

**Rebuild from scratch**:
```bash
docker stop docs-mcp-server && docker rm docs-mcp-server
uv run python deploy_multi_tenant.py --mode online
```

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) - Full setup walkthrough
- How-To: [Trigger Syncs](trigger-syncs.md) - Force refresh documentation
- Reference: [CLI Commands](../reference/cli-commands.md) - Full script options
