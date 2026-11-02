# TP Playbook frontend tooling documentation

The isolated example in [`examples/tp-playbook-frontend-tooling.json`](https://github.com/pankaj28843/docs-mcp-server/blob/main/examples/tp-playbook-frontend-tooling.json) configures documentation sources for the frontend tooling found in TP Playbook on 2026-11-02. It is a standalone example, not the running deployment. Copy or merge its tenant entries into a deployment configuration after choosing local data paths, ports, and a browser endpoint. It does not modify TP Playbook dependencies.

The project declares Node-compatible Angular tooling, npm 12.2.0, TypeScript ~6.0.2 (lockfile 6.0.3), ESLint 10.13.0, Prettier 3.9.10, esbuild 0.28.2, typescript-eslint 8.72.1 and angular-eslint 22.6.0. Its tests import `node:test` and `node:assert`, and the test script invokes esbuild. Its Angular application uses the `@angular/build:application` builder; Angular framework and CLI documentation are covered separately from this example.

## Sources and scope

| Tenant | Source and version | Synced files / indexed documents |
|---|---|---:|
| `nodejs` | [Node 24.22.2 API source](https://github.com/nodejs/node/tree/v24.22.2/doc/api), commit `f7f273a9bb6445f6f7fb6349105e7532972045fb` | 68 / 68 |
| `npm` | [npm 12.2.0 CLI source](https://github.com/npm/cli/tree/v12.2.0/docs/lib/content), commit `c276cadf785c1018d82dd287fe7742567055efb9` | 88 / 87 |
| `eslint` | [ESLint 10.13.0 documentation source](https://github.com/eslint/eslint/tree/v10.13.0/docs/src), commit `4637f9827a1ba137498eaee70957850621082815` | 466 / 413 |
| `prettier` | [Prettier 3.9.10 documentation source](https://github.com/prettier/prettier/tree/3.9.10/website/versioned_docs/version-stable), commit `1172b82c295c4f889fd787dc6c78c3e194ebf353` | 24 / 24 |
| `typescript-eslint` | [typescript-eslint 8.72.1 documentation source](https://github.com/typescript-eslint/typescript-eslint/tree/v8.72.1/docs), commit `4ad6b7553781fa3c93fc26642d7219d2e6624504` | 53 / 53 |
| `angular-eslint` | [angular-eslint 22.6.0 documentation source](https://github.com/angular-eslint/angular-eslint/tree/v22.6.0/docs), commit `7722ad2ab4da81568f19a7a29a3951fa443bf22c` | 6 / 6 |
| `typescript-reference` | [TypeScript website source](https://github.com/microsoft/TypeScript-Website/tree/v2/packages), `v2` branch at commit `205122bb73dcbf6f3b373de5bdb0d9fa5434d015` | 300 / 299 |
| `esbuild` | [esbuild documentation](https://esbuild.github.io/), rolling website | 9 discovered / 9 indexed |

The existing `typescript` tenant restricts URLs to `/docs/` and excludes `/docs/handbook/release-notes/`. `typescript-reference` supplements it with the upstream handbook, release notes and individual TSConfig option sources. The website's `v2` branch is moving; the recorded commit describes this run, not a permanent TypeScript 6.0 snapshot. A query for “TypeScript 6.0” alone ranked unrelated pages above the release notes; the distinctive heading “Less Context-Sensitivity on this-less Functions” located them. Confirm versions against [TypeScript 6.0 release notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html) and the [TSConfig reference](https://www.typescriptlang.org/tsconfig/).

Node 24 is a selected compatible major, not proof of the project's deployed runtime. Angular's lockfile lists compatible Node versions including 22 and 26; index those majors separately when the runtime requires them. Release tags provide patch-level source snapshots for the Git tenants, while the esbuild website is rolling and is not pinned to the project's 0.28.2. The narrow angular-eslint `docs` directory does not include the complete rule catalog, and typescript-eslint's rule implementation documentation is outside its selected `docs` directory. ESLint source includes templates and assets; exported and indexed counts differ. Raw Git source can include front matter, MDX, relative links and template directives rather than rendered pages.

The npm source contains 87 Markdown files and one YAML file; the YAML file is not indexed. The ESLint source contains 408 Markdown and five text files, which are indexed, plus 37 HTML, 14 JSON and two YAML files, which are not. These counts describe the selected source directories, not all upstream documentation.

## Retrieval evidence

On 2026-11-02 an isolated server, browser, data root and deployment configuration were used to sync the eight tenants. Git scheduler status recorded one successful sync per tenant, zero errors and the commits above. The esbuild crawler reported nine discovered and nine successful metadata URLs, zero queued, pending or failed URLs. Indexing produced the counts above. Counts alone do not prove complete upstream documentation coverage.

Local `docsearch` searches followed by fetches retrieved the Node test runner, npm ci, ESLint configuration files, Prettier configuration, typescript-eslint typed linting, angular-eslint configuration, TypeScript 6.0 notes and the esbuild API. The TypeScript `moduleResolution` source was also fetched. Searches for npm ci and several configuration topics returned relevant documents below the top rank, so results should be inspected rather than assuming the first hit is the answer. The Git-backed results use local `file://` paths, not portable official web links; use the source links above when citing documentation. Use `--max-chars` to bound a fetch response or `--out` to save full content; the options are mutually exclusive.

An export of all eight tenants imported successfully into a separate data directory. After the local document URL relocation fix, a fresh export and import of Node and npm was tested with the producer data temporarily unavailable. Searches returned consumer-local `file://` URLs. With a CLI containing the full-fetch fix, fetching the Node test runner to a file returned 168,711 bytes, identical to the imported source by byte comparison and SHA-256 (`1abd67ee59af09d2c426c0223cb7f7adce5693f596371368fff07b34142786a1`). Deploy a CLI containing the relocation and full-fetch fixes (merged in PRs #83 and #87); an older installed CLI returned the original producer paths and truncated this fetch. These checks cover two representative Git tenants, not every exported document.

For tenant configuration fields see the [deployment schema](deployment-json-schema.md); for Git source configuration see [Configure a Git tenant](../how-to/configure-git-tenant.md).
