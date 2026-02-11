# How to evaluate online vs offline runtime modes

Use this guide for a reproducible deep dive before demos, talks, or release reviews.

## Goal

Compare behavior differences between `online` and `offline` operation modes, including endpoint availability and sync capabilities.

## Prerequisites

- `deployment.json` is present
- Docker is running
- Dependencies installed with `uv sync`

## Phase 1: Evaluate `offline` mode

1. Deploy in offline mode:

```bash
uv run python deploy_multi_tenant.py --mode offline
```

2. Verify core health and MCP metadata:

```bash
curl -s http://localhost:42042/health
curl -s http://localhost:42042/mcp.json
```

3. Verify dashboard is not available:

```bash
curl -i http://localhost:42042/dashboard | head -n 20
```

4. Verify retrieval path still works:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

## Phase 2: Evaluate `online` mode

1. Redeploy in online mode:

```bash
uv run python deploy_multi_tenant.py --mode online
```

2. Verify dashboard is available:

```bash
curl -i http://localhost:42042/dashboard | head -n 20
```

3. Trigger sync and verify indexing path:

```bash
uv run python trigger_all_syncs.py --host localhost --port 42042 --tenants drf --force
uv run python trigger_all_indexing.py --tenants drf
```

4. Re-run retrieval validation:

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

## Expected behavior summary

| Surface | Offline | Online |
|---|---|---|
| `/mcp` root tools | available | available |
| `/health` | available | available |
| `/dashboard` | unavailable or 503 | available |
| Sync trigger endpoints | blocked | available |
| Search/fetch via MCP | available | available |

## Why this evaluation works

It maps directly to mode-gated route behavior in `src/docs_mcp_server/app_builder.py` and lets you demonstrate separation of retrieval vs operational mutation surfaces.

## Related

- [Explanation: Runtime modes and Starlette](../explanations/runtime-modes-and-starlette.md)
- [Reference: Entrypoint walkthrough](../reference/entrypoint-walkthrough.md)
