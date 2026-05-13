# Maintain the Apple Developer Documentation tenant

Apple Developer Documentation is a JavaScript-rendered DocC site. The normal
online crawler can fetch `https://developer.apple.com/documentation/`, but link
crawling only sees the shell page reliably. The canonical content is loaded from
DocC JSON endpoints under `https://developer.apple.com/tutorials/data/documentation/`.

Use this recipe to refresh the local filesystem snapshot, rebuild the search
index, deploy it, debug it, and export it for offline machines.

## Preconditions

- `deployment.json` contains `apple-developer` as a `filesystem` tenant.
- `uv sync --extra dev` has been run.
- `cdp` is installed for browser diagnostics.
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

## 1. Probe Apple with cdp before changing the script

Do not assume `cdp` flags. Check the installed CLI every time the workflow needs
browser evidence:

```bash
cdp --help
cdp doctor --help
cdp workflow --help
cdp workflow page-load --help
cdp workflow debug-bundle --help
cdp workflow rendered-extract --help
cdp workflow network-failures --help
```

Then collect evidence under `tmp/cdp/apple-developer/`:

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

## 2. Refresh the DocC Markdown snapshot

Run the checked-in snapshot script:

```bash
uv run python scripts/apple_docc_snapshot.py --help
uv run python scripts/apple_docc_snapshot.py \
  --docs-root mcp-data/apple-developer \
  --urls-file tmp/apple-docc-snapshot/apple-developer/urls.json \
  --clean \
  --max-docs 20000 \
  --discovery-limit 20000
```

The script:

1. Walks DocC JSON references from the Apple documentation roots.
2. Converts each selected JSON page into Markdown with YAML front matter.
3. Deduplicates lowercase and mixed-case URL variants, preferring Apple's
   canonical mixed-case paths.
4. Writes generated files under `mcp-data/apple-developer/apple-docs/`.

Use `--required-url` to pin pages that must survive the `--max-docs` cap.

## 3. Rebuild the search segment

Dry-run first, then persist:

```bash
uv run python trigger_all_indexing.py --tenants apple-developer --dry-run
uv run python trigger_all_indexing.py --tenants apple-developer
```

A healthy run indexes the generated Markdown plus the root documentation page.

## 4. Deploy and debug

```bash
uv run python deploy_multi_tenant.py --mode online
sleep 15 && curl -sf http://127.0.0.1:42042/health | python3 -c \
'import json,sys; d=json.load(sys.stdin); print(d["status"], d["tenant_count"]); print(d["tenants"].get("apple-developer"))'
uv run python debug_multi_tenant.py --host 127.0.0.1 --port 42042 --tenant apple-developer
uv run docsearch search apple-developer "SwiftUI View fundamentals" --json | head -40
```

## 5. Export for offline use

```bash
uv run python sync_tenant_data.py export --tenants apple-developer
```

The default export location is `~/docs-mcp-server-export/`. The export command
also copies the current `deployment.json`, so run it after the tenant config and
search index are correct.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Crawler discovers only one page | Apple docs are JS-rendered and DocC JSON backed | Keep `apple-developer` as a filesystem tenant and use the snapshot script |
| `rendered-extract` reports tiny visible text | The readiness gate saw the shell before app hydration | Use `debug-bundle` and `page-load` network evidence instead |
| Search shows duplicate lowercase/mixed-case pages | Old generated files remain | Rerun the script with `--clean`, then rebuild the index |
| Required docs fall out of the cap | The graph order changed | Add one or more `--required-url` values |
| Fetch works for search result body but file path is missing | Stale index segment | Rebuild with `uv run python trigger_all_indexing.py --tenants apple-developer` |
