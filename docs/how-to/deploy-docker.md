# How to deploy docs-mcp-server with Docker

Use this guide when you need a repeatable deployment and health validation loop.

## Prerequisites

- `deployment.json` exists in repo root
- Docker daemon is running
- Dependencies installed via `uv sync`

## Step 1: Deploy container

```bash
uv run python deploy_multi_tenant.py --mode online
```

`online` mode enables sync schedulers for online tenants.

## Step 2: Check health endpoint

```bash
curl -s http://localhost:42042/health
```

You should see JSON status output including tenant counts.

## Step 3: Trigger sync for selected tenants

```bash
uv run python trigger_all_syncs.py --host localhost --port 42042 --tenants django drf --force
```

Use `--force` for first-time or recovery sync.

## Step 4: Build search segments (optional but recommended after sync)

```bash
uv run python trigger_all_indexing.py --tenants django drf
```

## Step 5: Validate search path

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

## Verification checklist

- Health endpoint responds
- Target tenants sync successfully
- Search test returns ranked results

## Troubleshooting

### Deployment script fails quickly

- Validate config JSON syntax:
  ```bash
  uv run python -m json.tool deployment.json > /dev/null
  ```
- Confirm required files/paths referenced by tenants exist.

### Health endpoint shows tenant issues

- Inspect container logs:
  ```bash
  docker logs docs-mcp-server | tail -n 100
  ```
- Re-run sync for failing tenant with `--force`.

### Search is slow on first query

- First query can be cold-start behavior while indexes load.
- Pre-build with `trigger_all_indexing.py` for critical tenants.

## Why this workflow

Deploy → health check → sync → optional indexing → search verification gives a deterministic operational loop and isolates failures by stage.

## Related

- [How to configure an online tenant](configure-online-tenant.md)
- [How to trigger syncs](trigger-syncs.md)
- [Reference: CLI commands](../reference/cli-commands.md)
