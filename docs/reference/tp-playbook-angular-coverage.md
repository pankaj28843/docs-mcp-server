# TP Playbook Angular documentation coverage

This reference records an isolated onboarding experiment on 2026-11-02. The example deployment contains candidate tenants; adding them to a deployment, syncing them, and exporting their data are separate operations. The experiment did not modify the shared deployment or data.

## Versions and sources

TP Playbook's `frontend/package-lock.json` locks Angular core 22.2.4, CLI 22.2.5, Angular Material and CDK 22.2.4, angular-eslint 22.6.0, and RxJS 7.8.2. Its manifest uses ranges for some packages. The official [Angular release policy](https://angular.dev/reference/releases) identifies v22 as current at the time of this experiment; the unversioned site moves with the current release and is not a permanent 22.2.4 snapshot. [Angular v21](https://v21.angular.dev/) and [Angular v20](https://v20.angular.dev/) have separate sites; neither was indexed in this experiment.

| Example tenant | Source and revision | Indexed documents | Scope |
| --- | --- | ---: | --- |
| `angular` | [angular.dev sitemap](https://angular.dev/sitemap.xml), current site | 1,647 | Sitemap and configured entry pages, including framework guides, CLI and some CDK APIs. |
| `angular-eslint` | [angular-eslint](https://github.com/angular-eslint/angular-eslint/tree/v22.6.0), tag `v22.6.0`, commit `7722ad2ab4da81568f19a7a29a3951fa443bf22c` | 99 | `docs` and both TypeScript and template rule documentation trees. Root README is excluded. |
| `angular-material-api` | [Material API fragments](https://material.angular.dev/docs-content/api-docs/material-dialog), current site; 95 explicit entry URLs | 96 | Published Material and CDK API fragments found by the bounded enumeration described below. |
| `angular-material-source` | [Angular components](https://github.com/angular/components/tree/v22.2.4), tag `v22.2.4`, commit `e28b22e2cc28e7e6bc0850e9a9e7f076e7c75428` | 115 | Markdown guides in `guides`, `src/material` and `src/cdk`; generated API reference is excluded. |
| `rxjs-source` | [RxJS](https://github.com/ReactiveX/rxjs/tree/7.8.2), tag `7.8.2`, commit `e5351d02e225e275ac0e497c7b66eaa5f0c88791` | 27 | Markdown guides in `docs_app/content`; generated API reference is excluded. |

The Git tenants return `file://` URLs from their local checkouts. Their tags and commits identify the source snapshot, but these URLs are not canonical published documentation links. Counts describe indexed documents in this run, not proof that every possible official page has been covered. Tags require deliberate updates when TP Playbook upgrades.

## Retrieval evidence

The isolated Angular online sync finished with 1,647 successful pages, zero pending pages, zero queued pages and zero failed URLs. The index persisted 1,647 documents at 18:03 UTC. The official sitemap listed 1,626 URLs; the additional pages came from the configured entries and the resumed queue. A search for `Angular routing route guards` returned [Control route access with guards](https://angular.dev/guide/routing/route-guards), and fetch returned the guide. A search for `ng build application builder` returned the CLI builder guide; fetch of [ng build](https://angular.dev/cli/build) returned its command reference. `CDK drag drop` returned the [drag and drop guide](https://angular.dev/guide/drag-drop) and [CDK_DROP_LIST API](https://angular.dev/api/cdk/drag-drop/CDK_DROP_LIST); fetch returned the API description.

The Git snapshots also completed sync and indexing. `alt-text accessibility` returned and fetched `packages/eslint-plugin-template/docs/rules/alt-text.md`; `MatDialog open dialog` returned and fetched `src/material/dialog/dialog.md`; `CDK overlay scroll strategy` returned `src/cdk/overlay/scroll/scroll-strategy.md`; and `Observable subscribe` returned and fetched `guide/observable.md`. All five tenant datasets were exported from the isolated data directory. Results are bounded by the indexed sources above; a matching query is not a completeness test.

## Known gaps and follow-up

- [Angular Material](https://material.angular.dev/) and [RxJS](https://rxjs.dev/) are JavaScript-rendered. Online discovery from their ordinary component and guide routes failed to extract pages in this server, although a headed browser rendered them. Do not treat the Git guide tenants as complete API coverage.
- The browser showed that Material's generated reference has substantive HTML fragments such as [material-dialog](https://material.angular.dev/docs-content/api-docs/material-dialog) and [material-dialog-testing](https://material.angular.dev/docs-content/api-docs/material-dialog-testing). Enumerating names derived from the tagged Material/CDK source directories found 95 fragments among 126 candidates; this is a lower bound, not a verified complete published inventory. The isolated sync eventually recorded 95 successes, zero pending and zero queued, with 15 retained failure records from earlier attempts. Its index contained 96 documents, including one leftover from the earlier attempt. Search for `MatDialog open dialog` ranked the Material and CDK dialog API fragments first; fetch returned the Material dialog API, with 56,351 original characters. The example tenant contains the 95 successful URLs as a fixed list; it does not automatically discover new packages. Rebuild the list and investigate retained failures on refresh.
- RxJS serves generated JSON with HTML content, for example [Observable](https://rxjs.dev/generated/docs/api/index/class/Observable.json), whose source link identifies 7.8.2. A generated-content adapter or snapshot pipeline, a complete API manifest, and search/fetch tests are still needed. The JSON route alone does not prove complete API coverage.
- Versioned Angular v20/v21, versioned Material/CDK, older angular-eslint tags, and complete RxJS/Material APIs remain unindexed. Use the official sites and repositories above until separately ingested and verified. The existing TypeScript tenant also needs a separate version and completeness audit against TP Playbook's locked 6.0.3.

For a deployed copy, re-run sync, indexing and export against its own configuration and data directory, then use `docsearch search` and `docsearch fetch` on the examples above. Record the index timestamp, source version and failures; do not infer freshness from this historical experiment.
