# Tutorial: Lightning talk walkthrough (quick + deep dive)

**Time**: ~20 minutes  
**Audience**: technical users evaluating architecture and runtime behavior  
**Outcome**: run a fast demo, then walk through internals with source code and docs

## Why this tutorial exists

A good lightning talk needs two tracks:

1. A fast “it works” path for newcomers.
2. A compact “how it works” path for experienced engineers.

This tutorial gives you both.

## Part A — Quick demo path (5–7 minutes)

### Step 1: Deploy and sync one tenant

```bash
uv run python deploy_multi_tenant.py --mode online
uv run python trigger_all_syncs.py --tenants drf --force
```

### Step 2: Validate retrieval path

```bash
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant drf --test search
```

### Step 3: Show MCP endpoint metadata

```bash
curl -s http://localhost:42042/mcp.json
```

## Part B — Deep-dive path (10–12 minutes)

### Step 1: Explain runtime modes

Use the comparison guide:

- [How to evaluate runtime modes](../how-to/evaluate-runtime-modes.md)
- [Runtime modes and Starlette integration](../explanations/runtime-modes-and-starlette.md)

### Step 2: Walk source entrypoints live

Open these files in order:

1. `src/docs_mcp_server/app.py`
2. `src/docs_mcp_server/app_builder.py`
3. `src/docs_mcp_server/root_hub.py`
4. `src/docs_mcp_server/tenant.py`

Companion reading:

- [Entrypoint walkthrough](../reference/entrypoint-walkthrough.md)

### Step 3: Explain MCP tool design

Tool surface and rationale:

- [MCP tools API](../reference/mcp-tools.md)
- Root tool implementation: `src/docs_mcp_server/root_hub.py`

### Step 4: Map library decisions to implementation

Use:

- [Core library map](../reference/core-library-map.md)

## Verification checklist

- Quick demo search returns ranked snippets and URLs.
- `/mcp.json` returns valid server config.
- Team can explain online vs offline behavior from docs + source.
- Team can point to exact files implementing MCP tools and app wiring.

## Next steps

- For architecture context: [Explanation: Architecture](../explanations/architecture.md)
- For onboarding path: [Tutorial: Getting started](getting-started.md)
