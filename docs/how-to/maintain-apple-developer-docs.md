# Maintain the Apple Developer Documentation tenant

Apple Developer Documentation is a JavaScript-rendered DocC site. The normal
online crawler can fetch `https://developer.apple.com/documentation/`, but link
crawling only sees the shell page reliably. The canonical content is loaded from
DocC JSON endpoints under `https://developer.apple.com/tutorials/data/documentation/`,
and the complete public URL set is discovered by breadth-first crawling hydrated
`https://developer.apple.com/documentation/` pages with `cdp`.

Use this recipe to refresh the local filesystem snapshot, rebuild the search
index, deploy it, debug it, and export it for offline machines.

## Preconditions

- `deployment.json` contains `apple-developer` as a `filesystem` tenant.
- `uv sync --extra dev` has been run.
- `cdp` is installed for rendered-link discovery and browser diagnostics.
- Docker is available for deployment.

The tenant shape is intentionally filesystem-based:

```json
{
  "source_type": "filesystem",
  "codename": "apple-developer",
  "docs_name": "Apple Developer Documentation",
  "docs_root_dir": "./mcp-data/apple-developer",
  "search": {"analyzer_profile": "code-friendly"}
}
```

## 1. Probe Apple with cdp before changing scripts

Do not assume `cdp` flags. Check the installed CLI every time the workflow needs
browser evidence:

```bash
cdp --help
cdp open --help
cdp eval --help
cdp wait eval --help
cdp workflow --help
cdp workflow page-load --help
cdp workflow debug-bundle --help
cdp workflow rendered-extract --help
cdp workflow network-failures --help
uv run python scripts/apple_rendered_link_bfs.py --help
uv run python scripts/apple_rendered_link_bfs.py --preflight-only
```

Then collect evidence under `tmp/cdp/apple-developer/` when the site behavior is
unclear:

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

Inspect `page-load.json` for `Fetch` requests. The expected roots are:

- `https://developer.apple.com/tutorials/data/documentation.json`
- `https://developer.apple.com/tutorials/data/documentation/technologies.json`

If Apple changes those endpoints, update `scripts/apple_docc_snapshot.py` and
this recipe together.

## 2. Crawl rendered documentation links with BFS

Run the cdp-backed rendered-link BFS first. It starts at
`https://developer.apple.com/documentation/`, seeds every first-level root group
from Apple DocC JSON (such as `https://developer.apple.com/documentation/xcode`),
waits for hydrated anchor sets to settle, and only queues links that start with
`https://developer.apple.com/documentation/`.

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

If the crawl is interrupted, rerun the same command without `--reset` to resume.
Use `--limit` only for debugging; final refreshes should crawl all reachable
Apple documentation URLs. Inspect the state file to confirm key root groups such
as Xcode are queued or visited.

## 3. Refresh the DocC Markdown snapshot

Merge the rendered BFS URLs with the DocC JSON graph and render without caps.
`--max-docs 0` and `--discovery-limit 0` mean no cap. Existing rendered docs
newer than `--refresh-max-age-hours` are reused instead of fetched again; the
default is 72 hours and `0` disables reuse.

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

The script:

1. Walks DocC JSON references from the Apple documentation roots.
2. Merges rendered-link BFS URLs from hydrated public pages.
3. Converts each selected JSON page into Markdown with YAML front matter.
4. Deduplicates lowercase and mixed-case URL variants, preferring Apple's
   canonical mixed-case paths.
5. Writes generated files under `mcp-data/apple-developer/apple-docs/`.

Use `--required-url` to pin pages that must always render.

## On-demand scoped sync: iOS, iPadOS, and Xcode

Use a scoped run for targeted refreshes before a full Apple crawl. Do not pass
`--clean` with scoped filters; the snapshot script refuses that combination so a
partial sync cannot prune unrelated tenant docs.

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

Then rebuild the `apple-developer` search segment. The next full unscoped sync
can reuse anything rendered less than 72 hours ago by keeping
`--refresh-max-age-hours 72`.

## 4. Rebuild the search segment

Dry-run first, then persist:

```bash
uv run python trigger_all_indexing.py --tenants apple-developer --dry-run
uv run python trigger_all_indexing.py --tenants apple-developer
```

A healthy run indexes the generated Markdown plus the root documentation page.

## 5. Deploy and debug

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
`docsearch fetch apple-developer <url> --json` should return content instead of a
missing-document error.

## 6. Export for offline use

```bash
uv run python sync_tenant_data.py export --tenants apple-developer
```

The default export location is `~/docs-mcp-server-export/`. The export command
also copies the current `deployment.json`, so run it after the tenant config,
rendered BFS, search index, and verification are correct.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Crawler discovers only one page | Apple docs are JS-rendered and DocC JSON backed | Keep `apple-developer` as a filesystem tenant and use rendered BFS plus the snapshot script |
| Rendered BFS misses pages | cdp unhealthy, crawl limited, missing root seeds, or interrupted state | Check `cdp --help`, daemon health, rerun with `--seed-docc-root-groups` and without `--limit`, resume from the state file |
| `rendered-extract` reports tiny visible text | The readiness gate saw the shell before app hydration | Use `debug-bundle` and `page-load` network evidence instead |
| Search shows duplicate lowercase/mixed-case pages | Old generated files remain | Rerun the script with `--clean`, then rebuild the index |
| Required docs fall out of the cap | A capped run was used | Use `--max-docs 0` and add one or more `--required-url` values |
| Scoped sync tries to delete unrelated docs | `--clean` was combined with `--scope-term` or `--include-url-regex` | Drop `--clean` for on-demand sync; use it only for full unscoped sync |
| Full sync refetches too much after scoped sync | Freshness window is disabled or too small | Keep `--refresh-max-age-hours 72` or set a larger value |
| `docsearch fetch` cannot find a served Apple doc | The rendered URL was not in the snapshot/index | Rerun rendered BFS, merge with `--extra-urls-file`, rebuild, and redeploy |
| Fetch works for search result body but file path is missing | Stale index segment | Rebuild with `uv run python trigger_all_indexing.py --tenants apple-developer` |
