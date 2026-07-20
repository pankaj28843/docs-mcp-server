# Reference: CLI Commands

!!! tip "Quick Reference"
    | Script | Purpose |
    |--------|---------|
    | `docsearch` | Search and fetch indexed documentation locally |
    | `debug_multi_tenant.py` | Local testing and debugging |
    | `deploy_multi_tenant.py` | Docker deployment |
    | `trigger_all_syncs.py` | Force sync documentation sources |
    | `trigger_all_indexing.py` | Rebuild BM25 search indexes |
    | `cleanup_segments.py` | Remove stale search segments |
    | `sync_tenant_data.py` | Export/import tenant data |

## `docsearch`

**Purpose**: Search exported documentation indexes and fetch cached pages without
starting the MCP server. Install or build the Go CLI, then point it at an
`mcp-data` directory:

```bash
cd cli
go build -o docsearch ./cmd/docsearch
./docsearch list --data-dir ../mcp-data
```

`TECHDOCS_DATA_DIR` supplies the default data directory, and
`TECHDOCS_DEPLOYMENT_CONFIG` supplies display names, source types, and canonical
public URL prefixes. Explicit flags take precedence.

### Search workflow

```bash
docsearch search-all "middleware" --json
docsearch search django,fastapi "middleware" --size 8 --json
docsearch search django "select_related prefetch_related" --size 5
docsearch fetch django "https://docs.djangoproject.com/en/5.2/topics/db/queries/"
```

`search` and `search-all` accept 1–100 results through `--size`. `search-all`
also accepts `--total` to bound the combined result count. Invalid limits fail
before any index is opened.

The `list`, `describe`, `search`, and `fetch` JSON responses include provenance
for the index used by the command:

- source type and sanitized canonical public URL prefixes;
- opaque index generation ID, creation time, and document count;
- source freshness state (`known`, `partial`, or `unknown`), timestamp, and
  evidence type when available;
- a Git commit only when it was persisted by a completed Git sync.

Human-readable output shows the same source, index age, and freshness status in
a compact line. Older indexes without manifest-bound source evidence remain
usable and report `partial` or `unknown`; the CLI does not guess a Git revision
from the current checkout or expose local filesystem paths.

### Bound fetch output

The default `fetch` behavior remains a full inline response. Use one explicit
output policy when the document may be large:

```bash
docsearch fetch react URL --json --max-chars 12000
docsearch fetch react URL --json --out tmp/react-page.md
```

`--max-chars` is Unicode-safe and reports `truncated`, original/returned
character counts, and original/returned byte counts. `--out` atomically replaces
the destination with the full content and returns artifact path, byte count, and
SHA-256 instead of embedding content. The two flags are mutually exclusive and
neither accepts an empty or non-positive value.

### Machine-readable failures

With `--json`, every command failure writes one JSON object to stdout and no
duplicate prose to stderr:

```json
{
  "error": {
    "code": "tenant_not_found",
    "class": "tenant",
    "message": "Tenant 'missing' not found.",
    "actions": ["run `docsearch list` to inspect available tenants"]
  }
}
```

Automation should branch on `error.code` or the process exit status, not parse
the human message.

| Exit | Class | Typical codes |
| ---: | --- | --- |
| 0 | success | Successful result, including an empty result set |
| 1 | internal | `internal_error` |
| 2 | usage | `invalid_argument` |
| 3 | storage | `data_root_unavailable`, `artifact_write_failed` |
| 4 | tenant | `tenant_not_found` |
| 5 | index | `index_unavailable` |
| 6 | document | `document_not_found`, `invalid_document_encoding` |

Without `--json`, failures use concise stderr text and the same exit statuses.

## `debug_multi_tenant.py`

**Purpose**: Run the server locally for testing and debugging. Supports offline and online modes.

**Synopsis**:
```bash
uv run python debug_multi_tenant.py [OPTIONS]
```

**Options** (excerpt from `--help`):
- `--tenant TENANT [TENANT ...]`
- `--test {all,search,fetch,crawl,parity}`
- `--host HOST` / `--port PORT`
- `--enable-sync`, `--trigger-sync`, `--root`, `--root-test {all,list,describe,search,fetch}`

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
uv run python sync_tenant_data.py export [--output DIR] [--tenants TENANT ...] [--dry-run] [--force]
uv run python sync_tenant_data.py import [--input DIR] [--tenants TENANT ...] [--dry-run] [--force] [--no-preserve-local]
```

**Options** (from `--help` excerpt):
- `export|import` subcommands
- `--tenants TENANT [TENANT ...]`
- `--dry-run`
- `--force`
- `--output DIR` / `--input DIR`
- `--no-preserve-local` (import only)

When `--output` or `--input` is omitted, the script uses `SYNC_TENANT_DATA_DIR`
from the process environment or repo-local `.env`. If unset, it falls back to
`~/docs-mcp-server-export`.

**Import incremental behavior**:
- Default import reads `manifest.json` from the input directory and local state from `mcp-data/.sync_tenant_import_manifest.json`.
- Tenants whose `source_snapshot.signature` already matches local import state are skipped before archive listing or extraction.
- `--tenants` and `--force` are operator overrides; they import selected tenants even when local state matches.
- If `manifest.json` is missing or invalid, import falls back to the old behavior: import all discovered `*.7z` archives.
- Successful real imports update local import state atomically after each tenant succeeds. `--dry-run` never writes import state.

Use `import --dry-run` on source machines when you only need to verify what would change.

**Actual output (incremental import dry run)**:
```
Importing 1 tenant(s)...
  Incremental unchanged skip: True

[1/1] django
  Skipping unchanged tenant import
```
