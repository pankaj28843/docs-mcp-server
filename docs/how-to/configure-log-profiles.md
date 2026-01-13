# How-To: Configure Log Profiles

**Goal**: Switch between production (quiet) and debug (verbose) logging without code changes.  
**Prerequisites**: Running docs-mcp-server locally or in Docker.

---

## Problem

By default, the server logs at `INFO` level, hiding detailed trace information needed for debugging search, sync, and MCP tool issues.

---

## Steps

### 1. Define profiles in deployment.json

Add or edit the `log_profiles` block under `infrastructure`:

```json
{
  "infrastructure": {
    "log_profile": "default",
    "log_profiles": {
      "default": {
        "level": "info",
        "json_output": true,
        "trace_categories": [],
        "trace_level": "debug",
        "logger_levels": {
          "uvicorn.access": "warning",
          "fastmcp": "warning"
        },
        "access_log": false
      },
      "trace-drftest": {
        "level": "debug",
        "json_output": false,
        "trace_categories": [
          "docs_mcp_server",
          "uvicorn.error",
          "uvicorn.access",
          "fastmcp"
        ],
        "trace_level": "debug",
        "logger_levels": {
          "docs_mcp_server.search.segment_search_index": "debug",
          "mcp.server.lowlevel": "debug"
        },
        "access_log": true
      }
    }
  }
}
```

### 2. Switch profiles

**Option A: Edit deployment.json**

Change `log_profile` to the desired profile name:

```json
"log_profile": "trace-drftest"
```

**Option B: Use debug script flag**

```bash
uv run python debug_multi_tenant.py --tenant drf --log-profile trace-drftest --test search
```

### 3. Verify logging output

**Local testing**:

```bash
uv run python debug_multi_tenant.py --tenant drf --log-profile trace-drftest --test search
cat /tmp/docs-mcp-server-multi-debug/server.log | head -n 20
```

Actual output (DEBUG-level entries from `docs_mcp_server.*` loggers):

```
2026-01-12 22:48:44,740 - __main__ - INFO - Starting Docs MCP Server
2026-01-12 22:48:44,740 - __main__ - INFO - Configuration: /tmp/docs-mcp-server-multi-debug/deployment.debug.json
2026-01-12 22:48:44,740 - __main__ - INFO - Tenants: 1
2026-01-12 22:48:44,741 - docs_mcp_server.app_builder - INFO - Loading deployment configuration
2026-01-12 22:48:44,741 - docs_mcp_server.search.simd_bm25 - INFO - SIMD vectorization enabled for BM25 calculations
2026-01-12 22:48:44,741 - docs_mcp_server.search.segment_search_index - INFO - Lock-free concurrency enabled
2026-01-12 22:48:44,776 - docs_mcp_server.search.bloom_filter - INFO - Bloom filter initialized: 137353 bits
```

**Docker deployment**:

```bash
uv run python deploy_multi_tenant.py --mode online
docker logs docs-mcp-server-multi --tail 100
```

The container reads `log_profile` from the mounted `deployment.json`.

---

## Profile Fields Reference

| Field | Type | Description |
|-------|------|-------------|
| `level` | string | Root log level (`debug`, `info`, `warning`, `error`, `critical`) |
| `json_output` | boolean | Emit structured JSON logs |
| `trace_categories` | list[string] | Logger names set to `trace_level` |
| `trace_level` | string | Level applied to `trace_categories` loggers |
| `logger_levels` | dict | Per-logger level overrides (takes precedence over `trace_categories`) |
| `access_log` | boolean | Enable uvicorn access logging |

---

## Troubleshooting

**Symptom**: No DEBUG logs despite setting profile to `trace-drftest`

**Fix**: Ensure `log_profile` in `infrastructure` matches an existing key in `log_profiles`. Check for typos.

---

## Related

- Reference: [deployment.json Schema](../reference/deployment-json-schema.md)
- Explanation: [Observability](../explanations/observability.md)
