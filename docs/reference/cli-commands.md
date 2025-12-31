# Reference: CLI Commands

This reference documents the command-line tools available for managing the docs-mcp-server.

> **Prerequisite**: All commands require `deployment.json` to exist. If you haven't created one yet:
> ```bash
> cp deployment.example.json deployment.json
> ```

## `debug_multi_tenant.py`

**Purpose**: Run the server locally for testing and debugging. Supports both offline (filesystem only) and online modes.

**Synopsis**:
```bash
uv run python debug_multi_tenant.py [OPTIONS]
```

**Options**:
- `--tenant CODENAME` - Filter to specific tenant(s) (comma-separated)
- `--test TEST_TYPE` - Run automated tests (`search`, `fetch`, `all`)
- `--host HOST` - Bind host (default: 127.0.0.1)
- `--port PORT` - Bind port (default: 42043)

**Example** (using `drf` from `deployment.example.json`):
```bash
uv run python debug_multi_tenant.py --tenant drf --test search
```

**Output**:
```
🔒 Running in OFFLINE mode
🎯 Filtered to 1 tenant(s) from 10 total
📝 Created debug config: /tmp/docs-mcp-server-multi-debug/deployment.debug.json
🚀 Starting multi-tenant server...
✅ Server ready at http://127.0.0.1:42043
```

---

## `deploy_multi_tenant.py`

**Purpose**: Deploy the server to Docker. This is the standard way to run in production.

**Synopsis**:
```bash
uv run python deploy_multi_tenant.py [OPTIONS]
```

**Options**:
- `--mode MODE` - Deployment mode (`online` or `offline`). **Always use `online`**.
- `--port PORT` - Host port to map (default: 42042)

**Warning**: This script uninstalls development packages to minimize the Docker image size.

**Example**:
```bash
uv run python deploy_multi_tenant.py --mode online
```

**Output**:
```
📦 Syncing Python environment and updating lock file...
Resolved 173 packages in 1ms
Uninstalled 46 packages in 263ms
...
🐳 Building Docker image: pankaj28843/docs-mcp-server:multi-tenant...
🚀 Starting container on port 42042 in online mode...
✅ Deployment complete!
```

---

## `trigger_all_syncs.py`

**Purpose**: Force synchronization of documentation sources (crawlers for websites, git pull for repos).

**Synopsis**:
```bash
uv run python trigger_all_syncs.py [OPTIONS]
```

**Options**:
- `--tenants CODENAME` - Sync specific tenants only (space-separated)
- `--force` - Force sync even if recently synced (ignores 24h cache)

**Example**:
```bash
uv run python trigger_all_syncs.py --tenants drf --force
```

**Output**:
```
=== Triggering sync for online tenants ===
Server: http://localhost:42042
Filter: drf
Force:  True (ignores idempotency)

Found 1 online tenant(s):
drf                            ✅ Sync cycle completed
```

---

## `trigger_all_indexing.py`

**Purpose**: Rebuild BM25 search indexes for tenants.

**Synopsis**:
```bash
uv run python trigger_all_indexing.py [OPTIONS]
```

**Options**:
- `--tenants CODENAME` - Index specific tenants only (space-separated)

**Example**:
```bash
uv run python trigger_all_indexing.py --tenants drf
```

**Output**:
```
=== Docs MCP Search Indexing ===
Config: deployment.json
Filters: drf
Dry run: False

- drf                  indexed 44 docs (skipped 0) in 0.88s [persisted]
```

