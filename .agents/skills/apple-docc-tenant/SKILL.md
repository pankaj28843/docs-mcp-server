---
name: apple-docc-tenant
description: >
  Refresh and maintain the Apple Developer Documentation tenant from Apple DocC
  JSON. Use when: adding, repairing, refreshing, or exporting
  developer.apple.com/documentation as a docs-mcp-server tenant, or when cdp
  evidence shows a JavaScript DocC shell instead of crawlable HTML. Skip when:
  the source has a normal sitemap, a stable Markdown mirror, or a git docs repo.
  Produces a filesystem tenant snapshot, rebuilt search index, debug evidence,
  and export archive; verifies with cdp help/preflight, trigger_all_indexing,
  debug_multi_tenant, docsearch, and sync_tenant_data export.
argument-hint: "apple developer docs refresh/export"
---

# Apple DocC Tenant Workflow

Apple Developer Documentation is not a normal online tenant. The public page is a
JavaScript shell and the useful content is DocC JSON loaded from
`/tutorials/data/documentation/`. Use the checked-in snapshot script and keep the
configured tenant as `filesystem`.

## Preconditions

- Work from the repo root.
- `uv sync --extra dev` has been run.
- `cdp` is on `PATH` when investigating browser/runtime changes.
- `deployment.json` is backed up before edits because it is git-ignored.

```bash
mkdir -p tmp/backups && cp deployment.json "tmp/backups/deployment.json.$(date +%Y%m%d-%H%M%S)"
```

## Step 1: Verify cdp locally before browser diagnostics

Do not assume cdp flags. Check installed help before writing commands:

```bash
command -v cdp
cdp --help
cdp doctor --help
cdp workflow --help
cdp workflow page-load --help
cdp workflow debug-bundle --help
cdp workflow rendered-extract --help
cdp workflow network-failures --help
cdp doctor --check daemon --json
cdp doctor --check browser-health --json
cdp daemon health --json
```

If cdp reports a human-required browser approval or unhealthy daemon, stop and
ask the human to approve/repair it. Do not switch to Playwright or a headless
fallback for browser evidence.

## Step 2: Capture Apple DocC evidence when stuck

Save transient artifacts under `tmp/cdp/apple-developer/`:

```bash
mkdir -p tmp/cdp/apple-developer
cdp workflow page-load "https://developer.apple.com/documentation/" \
  --out tmp/cdp/apple-developer/page-load.json \
  --wait 10s \
  --json
cdp workflow debug-bundle \
  --url "https://developer.apple.com/documentation/" \
  --out-dir tmp/cdp/apple-developer/debug-bundle \
  --screenshot-view \
  --json
cdp workflow network-failures \
  --url-contains "developer.apple.com" \
  --wait 5s \
  --limit 0 \
  --json > tmp/cdp/apple-developer/network-failures.json
```

Expected page-load network roots:

- `https://developer.apple.com/tutorials/data/documentation.json`
- `https://developer.apple.com/tutorials/data/documentation/technologies.json`

If the roots change, update `scripts/apple_docc_snapshot.py`,
`docs/how-to/maintain-apple-developer-docs.md`, and this skill in the same diff.

## Step 3: Configure as a filesystem tenant

`apple-developer` should look like this in `deployment.json`:

```json
{
  "source_type": "filesystem",
  "codename": "apple-developer",
  "docs_name": "Apple Developer Documentation",
  "docs_root_dir": "./mcp-data/apple-developer",
  "search": {"analyzer_profile": "code-friendly"},
  "test_queries": {
    "natural": [
      "how to build a SwiftUI app",
      "how to generate content with Foundation Models",
      "how to make apps accessible"
    ],
    "phrases": [
      "Apple Developer Documentation",
      "View fundamentals",
      "Generating content and performing tasks with Foundation Models"
    ],
    "words": ["SwiftUI", "Accessibility", "Xcode", "FoundationModels"]
  }
}
```

Validate config:

```bash
uv run python - <<'PY'
from docs_mcp_server.deployment_config import DeploymentConfig
import json
config = DeploymentConfig(**json.load(open('deployment.json')))
for tenant in config.tenants:
    if tenant.codename == 'apple-developer':
        print(f'{tenant.codename}: {tenant.docs_name} ({tenant.source_type}) - OK')
print(f'Validation passed ({len(config.tenants)} total tenants)')
PY
```

## Step 4: Refresh the snapshot

Run the checked-in script:

```bash
uv run python scripts/apple_docc_snapshot.py --help
uv run python scripts/apple_docc_snapshot.py \
  --docs-root mcp-data/apple-developer \
  --urls-file tmp/apple-docc-snapshot/apple-developer/urls.json \
  --clean \
  --max-docs 20000 \
  --discovery-limit 20000
```

The script writes generated Markdown under
`mcp-data/apple-developer/apple-docs/`, deduplicates lowercase URL variants, and
keeps pinned required pages before applying `--max-docs`.

## Step 5: Rebuild the index

```bash
uv run python trigger_all_indexing.py --tenants apple-developer --dry-run
uv run python trigger_all_indexing.py --tenants apple-developer
```

Expected: thousands of docs indexed and a persisted segment under
`mcp-data/apple-developer/__search_segments/`.

## Step 6: Deploy and verify

```bash
uv run python deploy_multi_tenant.py --mode online
sleep 15 && curl -sf http://127.0.0.1:42042/health | python3 -c \
'import json,sys; d=json.load(sys.stdin); print(d["status"], d["tenant_count"]); print(d["tenants"].get("apple-developer"))'
uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant apple-developer
uv run docsearch search apple-developer "SwiftUI View fundamentals" --json | head -40
```

## Step 7: Export docs

```bash
uv run python sync_tenant_data.py export --tenants apple-developer
```

Default export location: `~/docs-mcp-server-export/apple-developer.7z`. The
export also copies `deployment.json`, so export only after config and indexing
are correct.

## Common failure modes

- **Only one page crawled**: this is expected for the JS shell. Use the DocC
  snapshot script and filesystem tenant mode.
- **`rendered-extract` captures tiny text**: use `page-load` and `debug-bundle`
  network evidence; inspect `Fetch` requests for DocC JSON roots.
- **Duplicate lowercase/mixed-case search results**: rerun the script with
  `--clean`, then rebuild the index.
- **Pinned page missing**: pass `--required-url <developer.apple.com/documentation/...>`
  and rerun with `--clean`.
- **Fetch result body exists but file path is stale**: rebuild the segment with
  `trigger_all_indexing.py --tenants apple-developer` and redeploy if needed.

## Related files

- `scripts/apple_docc_snapshot.py`
- `docs/how-to/maintain-apple-developer-docs.md`
- `sync_tenant_data.py`
