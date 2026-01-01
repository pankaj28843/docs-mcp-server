# Reference: CLI Commands

**Audience**: Operators running docs-mcp-server scripts.  
**Prerequisites**: `deployment.json` present; `uv sync --extra dev` installed the CLI dependencies.

!!! tip "Quick Reference"
    | Script | Purpose |
    |--------|---------|
    | `debug_multi_tenant.py` | Local testing and debugging |
    | `deploy_multi_tenant.py` | Docker deployment |
    | `trigger_all_syncs.py` | Force sync documentation sources |
    | `trigger_all_indexing.py` | Rebuild BM25 search indexes |
    | `cleanup_segments.py` | Remove stale search segments |
    | `sync_tenant_data.py` | Export/import tenant data |

## `debug_multi_tenant.py`

**Purpose**: Run the server locally for testing and debugging. Supports offline and online modes.

**Synopsis**:
```bash
uv run python debug_multi_tenant.py [OPTIONS]
```

**Options** (excerpt from `--help`):
- `--tenant TENANT [TENANT ...]`
- `--test {all,search,fetch,crawl}`
- `--host HOST` / `--port PORT`
- `--enable-sync`, `--trigger-sync`, `--root`, `--root-test {all,list,describe,search,fetch,browse}`

**Example (search smoke)**:
```bash
uv run python debug_multi_tenant.py --tenant drf --test search
```

**Actual output (2025-12-31)**:
```
✅ Search successful, returned 5 results
```

---

## `deploy_multi_tenant.py`

**Purpose**: Deploy the server to Docker.

**Synopsis**:
```bash
uv run python deploy_multi_tenant.py --mode online
```

**Actual output (2025-12-31)**:
```
#17 naming to docker.io/pankaj28843/docs-mcp-server:multi-tenant done
🚀 Starting container on port 42042 in online mode...
✅ Deployment complete!
Server URL │ http://127.0.0.1:42042
```

---

## `trigger_all_syncs.py`

**Purpose**: Force synchronization of documentation sources (online + git).

**Actual outputs (2025-12-31)**:
```
drf                            ✅ Sync cycle completed
aidlc-rules                    ✅ Git sync completed: 25 files, commit 5119d001
```

---

## `trigger_all_indexing.py`

**Purpose**: Rebuild BM25 search indexes for tenants.

**Actual outputs (2025-12-31)**:
```
drf indexed 44 docs (1.08s)
django indexed 271 docs (7.59s)
mkdocs indexed 19 docs (0.45s)
aidlc-rules indexed 25 docs (0.30s)
```

Command:
```bash
uv run python trigger_all_indexing.py --tenants drf django mkdocs aidlc-rules
```

---

## `cleanup_segments.py`

**Purpose**: Remove stale or oversized search segments to reclaim disk space.

**Synopsis**:
```bash
uv run python cleanup_segments.py [OPTIONS]
```

**Options** (from `--help`):
- `--tenant TENANT [TENANT ...]`
- `--dry-run`
- `--root ROOT`

**Actual output (2025-12-31, dry run)**:
```
Deleted: 0 segments
Space reclaimed: 0 bytes
```

---

## `sync_tenant_data.py`

**Purpose**: Export/import tenant data between machines.

**Synopsis**:
```bash
uv run python sync_tenant_data.py export --tenants drf --dry-run
```

**Options** (from `--help` excerpt):
- `export|import` subcommands
- `--tenants TENANT [TENANT ...]`
- `--dry-run`
- `--root ROOT`

**Actual output (2025-12-31, export dry run)**:
```
Ready to export tenant(s): drf
Dry run: no files written
```

