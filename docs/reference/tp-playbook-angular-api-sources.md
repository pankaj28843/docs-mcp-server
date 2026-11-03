# TP Playbook Angular ecosystem API sources

This reference records the generated API feeds checked on 2026-11-02 for the
TP Playbook frontend. The lockfile uses `@angular/material` and `@angular/cdk`
22.2.4 and RxJS 7.8.2. These feeds are distinct from guide and overview pages.

## RxJS 7.8.2 public API snapshot

The [RxJS documentation generator at tag 7.8.2](https://github.com/ReactiveX/rxjs/blob/7.8.2/docs_app/tools/transforms/angular-api-package/processors/generateApiListDoc.js)
creates `api-list.json` from module exports and excludes internal, private, and
duplicate exports. The [site's API service](https://github.com/ReactiveX/rxjs/blob/7.8.2/docs_app/src/app/custom-elements/api/api.service.ts)
loads that list for the public API viewer. The live
[`api-list.json`](https://rxjs.dev/generated/docs/api/api-list.json) lists six
modules and 365 distinct public items. Each module and item has a JSON page at
`https://rxjs.dev/generated/docs/<api-path>.json` with a rendered HTML body.

The managed tenant refreshes and reindexes the snapshot on its schedule or when
sync is triggered. To generate a snapshot manually:

```bash
uv run python scripts/rxjs_api_snapshot.py \
  --output-dir ./mcp-data/rxjs-api/snapshot
uv run python trigger_all_indexing.py --tenants rxjs-api
```

The exporter validates the complete manifest, fetches every listed item and
module page, checks each payload ID and body, and requires each page's official
`View Source` link to name the expected release tag. It writes Markdown with
the canonical `https://rxjs.dev/api/...` URL, generated JSON URL, release tag,
repository, and capture time in the repository's five-dash front matter format.
It stages all pages in a `.staging_` directory under the tenant root. The
indexer excludes that prefix, and staging stays on the tenant's filesystem even
when the root is mounted separately. Linux `renameat2` or macOS `renamex_np`
then swaps an existing snapshot with the validated one atomically. A failed or
unsupported swap leaves the old snapshot in place. The default version comes
from npm's `latest` distribution tag. Use `--expected-version 7.8.2` to check a
specific release instead. A mixed source tag or a site that has not yet caught
up with npm fails the run and preserves the previous snapshot. The managed tenant runs the exporter before reindexing. For manual exports, run
indexing after the exporter exits; a concurrent index traversal can span the
directory swap and mix two snapshot generations.

The output directory contains `snapshot-manifest.json` with the exact list of
exported API paths, source manifest URL, version, capture time, and page count.

Use a filesystem tenant with `docs_root_dir` set to `./mcp-data/rxjs-api`:

```json
{
  "source_type": "filesystem",
  "codename": "rxjs-api",
  "snapshot_source": "rxjs_api",
  "docs_name": "RxJS API",
  "docs_root_dir": "./mcp-data/rxjs-api",
  "search": {"analyzer_profile": "code-friendly"}
}
```

The snapshot directory is nested beneath that root. A current-site online tenant
may cover guides separately, but its JavaScript shell does not supply the API
body to ordinary extraction.

### Verification on 2026-11-02

The manifest contained 365 unique item paths in `index` (228), `operators`
(124), `ajax` (7), `fetch` (1), `websocket` (3), and `testing` (2). Adding their
six module pages yielded 371 JSON endpoints. All 371 returned HTTP 200 with
matching payload IDs, nonempty content, and `7.8.2` source links. The isolated
filesystem index built 371 documents with zero skips or errors. Searches for
`switchMap cancels previous inner observable` and `ajax AjaxResponse` ranked
the canonical `switchMap` and `AjaxResponse` API pages first; lookup by
`https://rxjs.dev/api/index/class/Observable`,
`https://rxjs.dev/api/operators/switchMap`, and
`https://rxjs.dev/api/ajax/AjaxResponse` returned indexed bodies. The exported
Observable page is 591,925 bytes and includes `subscribe` and `pipe` signatures.
The index stores a 4,096-character body preview. The tenant's HTTP-URL fetch
path resolved the nested snapshot and returned the full 591,925-byte Observable
page and 54,288-byte `switchMap` page.

This proves coverage of the site's published public API inventory for 7.8.2.
It does not claim private exports, unlisted guides, or future RxJS versions.

## Angular Material and CDK generated API fragments

The current official site exposes substantive HTML fragments under
`https://material.angular.dev/docs-content/api-docs/<package-id>`, for example
[`material-dialog`](https://material.angular.dev/docs-content/api-docs/material-dialog)
and [`cdk-overlay`](https://material.angular.dev/docs-content/api-docs/cdk-overlay).
The [official component source tree at v22.2.4](https://github.com/angular/components/tree/v22.2.4/src)
can enumerate candidate package IDs, and the [site documentation item list](https://github.com/angular/material.angular.io/blob/main/src/app/shared/documentation-items/documentation-items.ts)
describes component API document IDs. These are generated site artifacts, not
an immutable versioned JSON API or an authoritative complete manifest at the
current host.

An isolated direct online crawl of 95 verified fragment URLs reported 95
successful fetches. Its index contained 96 documents, including one prior
stale page. `MatDialog open dialog` ranked `material-dialog`; fetching that URL
returned 56,351 characters of API content. `CDK overlay position strategy`
ranked `cdk-overlay`; fetching it returned 162,870 characters. Fifteen old
failure records remained after retries despite zero pending URLs. These
results show the fragment route works for the checked pages, but the 95 URL
list is manually derived and does not prove full or future coverage. Do not
label the current Material API corpus comprehensive or version-pinned until
the host's displayed release and an authoritative complete enumeration can be
verified on each refresh. Material/CDK overview and guide routes need their own
content checks.
