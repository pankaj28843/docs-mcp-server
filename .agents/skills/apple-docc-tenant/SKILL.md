---
name: apple-docc-tenant
description: >
  Refresh and maintain the Apple Developer Documentation tenant from Apple DocC
  JSON plus rendered documentation-link BFS. Use when: adding, repairing,
  refreshing, or exporting developer.apple.com/documentation as a
  docs-mcp-server tenant, or when cdp evidence shows a JavaScript DocC shell
  instead of crawlable HTML. Skip when: the source has a normal sitemap, a
  stable Markdown mirror, or a git docs repo. Produces a filesystem tenant
  snapshot, rebuilt search index, rendered-link evidence, debug evidence, and
  export archive; verifies with cdp help/preflight, rendered BFS, DocC snapshot,
  trigger_all_indexing, debug_multi_tenant, docsearch help/search/fetch, and
  sync_tenant_data export.
argument-hint: "apple developer docs refresh/export"
---

# Apple DocC Tenant Workflow

Apple Developer Documentation is not a normal online tenant. The public page is a
JavaScript DocC shell, useful content is DocC JSON under
`/tutorials/data/documentation/`, and some public docs are only reliably found by
visiting hydrated documentation pages and reading their anchors.

**All-docs rule:** if an Apple documentation URL exists under
`https://developer.apple.com/documentation/`, it must be discovered, rendered,
indexed, and fetchable by `docsearch`. Do not use `--max-docs` caps for final
Apple refreshes. Use the rendered-link BFS plus the DocC JSON graph, then render
as a `filesystem` tenant.

## Preconditions

- Work from the repo root.
- `uv sync --extra dev` has been run.
- `cdp` is on `PATH` for rendered browser crawling and diagnostics.
- `deployment.json` is backed up before edits because it is git-ignored.

```bash
mkdir -p tmp/backups && cp deployment.json "tmp/backups/deployment.json.$(date +%Y%m%d-%H%M%S)"
```

## Step 1: Verify cdp locally before browser work

`cdp --help` is the source of truth. Do not assume flags and do not switch to
Playwright, Selenium, or a headless fallback.

```bash
command -v cdp
cdp --help
cdp open --help
cdp eval --help
cdp wait eval --help
cdp workflow --help
cdp workflow page-load --help
cdp workflow debug-bundle --help
cdp workflow rendered-extract --help
cdp workflow network-failures --help
cdp doctor --check daemon --json
cdp doctor --check browser-health --json
cdp daemon health --json
uv run python scripts/apple_rendered_link_bfs.py --help
uv run python scripts/apple_rendered_link_bfs.py --preflight-only
```

If cdp reports a human-required browser approval or unhealthy daemon, stop and
ask the human to approve/repair it.

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

## Step 4: Discover every rendered documentation link with BFS

Run the rendered-link BFS before building the snapshot. The script opens the
root `https://developer.apple.com/documentation/`, seeds every first-level root
group from Apple DocC JSON (for example
`https://developer.apple.com/documentation/xcode`), waits for the hydrated anchor
set to settle, then continues breadth-first. Every extracted anchor is collected
with JavaScript equivalent to:

```javascript
Array.from(new Set(Array.from(document.querySelectorAll("a"))
  .map((x) => new URL(x.href, window.location.href).toString())
  .filter((x) => x.startsWith("https://developer.apple.com/documentation/"))))
```

Run a fresh full crawl for releases; if interrupted, rerun without `--reset` to
resume from the checkpointed state.

```bash
uv run python scripts/apple_rendered_link_bfs.py \
  --reset \
  --seed-docc-root-groups \
  --urls-file tmp/apple-docc-snapshot/apple-developer/rendered-bfs-urls.json \
  --state-file tmp/apple-docc-snapshot/apple-developer/rendered-bfs-state.json \
  --checkpoint-every 25 \
  --retries 3 \
  --wait-timeout 20s \
  --settle-seconds 2 \
  --poll-seconds 1
```

Use `--limit N` only for debugging. Final refreshes must not set a limit. The
state file is the proof/resume artifact; check that root groups such as Xcode are
queued or visited before trusting a crawl.

## Step 5: Refresh the DocC Markdown snapshot without caps

Merge the rendered BFS URL list with the DocC JSON graph and render all selected
pages. `--max-docs 0` and `--discovery-limit 0` mean no cap.
Existing rendered docs newer than `--refresh-max-age-hours` are reused instead
of fetched again; the default is 72 hours and `0` disables reuse.

```bash
uv run python scripts/apple_docc_snapshot.py --help
uv run python scripts/apple_docc_snapshot.py \
  --docs-root mcp-data/apple-developer \
  --urls-file tmp/apple-docc-snapshot/apple-developer/urls.json \
  --extra-urls-file tmp/apple-docc-snapshot/apple-developer/rendered-bfs-urls.json \
  --clean \
  --refresh-max-age-hours 72 \
  --max-docs 0 \
  --discovery-limit 0
```

The snapshot script writes generated Markdown under
`mcp-data/apple-developer/apple-docs/`, deduplicates lowercase URL variants,
prefers Apple's canonical mixed-case paths, and keeps pinned required pages.

## On-demand scoped sync: iOS, iPadOS, and Xcode

Use a scoped run when the human asks for a targeted refresh before a full Apple
crawl. Do **not** pass `--clean` with scoped filters; the script refuses it
because it would prune out-of-scope docs from the tenant.

```bash
uv run python scripts/apple_rendered_link_bfs.py \
  --reset \
  --seed-docc-root-groups \
  --scope-term ios \
  --scope-term ipad \
  --scope-term ipados \
  --scope-term xcode \
  --urls-file tmp/apple-docc-snapshot/apple-developer/on-demand-ios-ipad-xcode-urls.json \
  --state-file tmp/apple-docc-snapshot/apple-developer/on-demand-ios-ipad-xcode-state.json \
  --checkpoint-every 25 \
  --retries 3 \
  --wait-timeout 20s \
  --settle-seconds 2 \
  --poll-seconds 1

uv run python scripts/apple_docc_snapshot.py \
  --build-only \
  --docs-root mcp-data/apple-developer \
  --urls-file tmp/apple-docc-snapshot/apple-developer/on-demand-ios-ipad-xcode-urls.json \
  --scope-term ios \
  --scope-term ipad \
  --scope-term ipados \
  --scope-term xcode \
  --refresh-max-age-hours 72 \
  --max-docs 0 \
  --discovery-limit 0
```

After the scoped render, rebuild the `apple-developer` index as usual. The next
full unscoped sync can reuse anything rendered less than 72 hours ago by keeping
`--refresh-max-age-hours 72`.

## Step 6: Rebuild the index

```bash
uv run python trigger_all_indexing.py --tenants apple-developer --dry-run
uv run python trigger_all_indexing.py --tenants apple-developer
```

Expected: all rendered Markdown docs are indexed and a persisted segment exists
under `mcp-data/apple-developer/__search_segments/`.

## Step 7: Deploy and verify docsearch does not error for existing docs

```bash
uv run python deploy_multi_tenant.py --mode online
sleep 15 && curl -sf http://127.0.0.1:42042/health | python3 -c \
'import json,sys; d=json.load(sys.stdin); print(d["status"], d["tenant_count"]); print(d["tenants"].get("apple-developer"))'
uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant apple-developer
uv run docsearch --help
uv run docsearch search apple-developer "SwiftUI View fundamentals" --json | head -40
uv run docsearch search apple-developer "writing code with intelligence in xcode" --json | head -40
uv run docsearch fetch apple-developer "https://developer.apple.com/documentation/xcode" --json | head -40
```

For any URL in `rendered-bfs-urls.json` that Apple still serves with DocC JSON,
`docsearch fetch apple-developer <url> --json` should return content, not a
missing-document error. If a fetch fails for an existing doc, rerun Step 4 and
Step 5 without caps, rebuild, redeploy, and retry.

## Step 8: Export docs

```bash
uv run python sync_tenant_data.py export --tenants apple-developer
```

Default export location: `~/docs-mcp-server-export/apple-developer.7z`. The
export also copies `deployment.json`, so export only after config, BFS discovery,
rendering, and indexing are correct.

## Common failure modes

- **Only one page crawled**: this is expected for the JS shell. Keep
  `apple-developer` as a filesystem tenant and use rendered BFS plus DocC JSON.
- **BFS misses a group page**: rerun `scripts/apple_rendered_link_bfs.py` with
  `--seed-docc-root-groups` and without `--limit`; confirm cdp help/daemon
  health; inspect the state file queue and failures.
+- **Scoped sync wants to delete unrelated docs**: wrong; never use `--clean`
  with `--scope-term` or `--include-url-regex`. Run scoped on-demand sync
  without `--clean`, then rebuild the index.
- **`rendered-extract` captures tiny text**: use `page-load` and `debug-bundle`
  network evidence; inspect `Fetch` requests for DocC JSON roots.
- **Duplicate lowercase/mixed-case search results**: rerun the snapshot with
  `--clean`, then rebuild the index.
- **Required page missing**: pass `--required-url <developer.apple.com/documentation/...>`
  and rerun with `--clean --max-docs 0`.
- **`docsearch fetch` says a served Apple doc is missing**: rerun rendered BFS,
  merge it via `--extra-urls-file`, rebuild `trigger_all_indexing.py`, and
  redeploy before testing again.
+- **Full sync is too slow after a recent scoped sync**: keep
  `--refresh-max-age-hours 72` or set a different hour value; use `0` only when
  every selected DocC page must be refetched.
- **Fetch result body exists but file path is stale**: rebuild the segment with
  `trigger_all_indexing.py --tenants apple-developer` and redeploy if needed.

## Trigger eval cases

| Prompt | Should trigger? | Expected behavior |
|---|---:|---|
| "Refresh Apple Developer docs and export the tenant" | yes | Run cdp preflight, seeded rendered BFS, DocC snapshot, index, verify, export |
| "developer.apple.com/documentation/xcode is missing from docsearch" | yes | Repair Apple tenant discovery/indexing with BFS and fetch verification |
| "Add a normal docs site with a sitemap" | no | Use the add-tenant workflow, not this Apple DocC exception |

## Related files

- `scripts/apple_rendered_link_bfs.py`
- `scripts/apple_docc_snapshot.py`
- `docs/how-to/maintain-apple-developer-docs.md`
- `sync_tenant_data.py`
