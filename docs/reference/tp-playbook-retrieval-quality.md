# TP Playbook retrieval quality

This reference defines the read-only documentation retrieval check in `scripts/quality/tp_playbook_cases.json`. It evaluates representative pages for TP Playbook's declared stack; it does not measure the completeness of a tenant's entire documentation corpus or verify the running application.

## Run the check

Run fixture-backed unit tests:

```sh
timeout 120 uv run pytest -m unit tests/unit/test_tp_playbook_retrieval_quality.py --no-cov
```

Run against the installed `docsearch` data and write a report:

```sh
uv run python scripts/quality/check_tp_playbook_retrieval.py --live --output /tmp/tp-playbook-retrieval-report.json
```

The live command exits with status 1 when a required retrieval or diagnostic expectation fails. The report is written before exit. Use `--docsearch /path/to/docsearch` to select the executable. The installed CLI must support `describe`, `search`, and `fetch` with `--json`.

## Case fields

| Field | Meaning |
| --- | --- |
| `id`, `technology` | Stable case identifier and scope. |
| `project_version` | Version or manifest constraint at the time the case was defined; refresh it when TP Playbook changes. `null` means unverified. |
| `tenant`, `source` | Required tenant and official URL prefix. A result from a different tenant or host does not satisfy the case. |
| `version_pattern` | Pattern for a source version explicit in a published URL. An indexed `versioned` source descriptor takes precedence. |
| `expected_revision` | Curated Git commit for a tagged source. A matching indexed revision establishes the pinned snapshot for a local `file://` result. |
| `content_version_pattern` | Pattern for a source version embedded in fetched content, used by the RxJS generated API snapshot. |
| `pages[].query` | Targeted search phrase. |
| `pages[].path`, `pages[].file_suffix` | Exact public page path, or portable local file suffix for a Git tenant, required among the first 20 targeted results. |
| `pages[].terms` | Case-insensitive content anchors required in the fetched page. |
| `expect` | Diagnostic state (`empty`, `unknown_freshness`, or `version_mismatch`); ordinary cases expect `retrieved`. |
| `fixture_only` | Excludes a synthetic case from live execution, if present. |

The cases cover Django CSRF and uploaded HTML, private S3 access, drf-spectacular schemas, Angular routing and Material/CDK, RxJS, Cobra, OpenTelemetry Go and Python, Caddy SPA/proxy/TLS, and diagnostic states. Consult the case catalog for the current tenant and source expectations. The `django` tenant follows the configured current release; historical Django 5.2 evidence does not establish that the current index matches the project lock.

## Report fields and verdicts

Every case reports expected and actual source, project and source versions, freshness, document count, index ID, page query, top hits, selected rank, fetched URL, content length, missing terms, and a `finding`. A page passes retrieval only when its official URL appears in the targeted results and its retrievable attributable content contains the required anchors. Explicitly truncated or empty content fails. A `truncated: false` CLI response does not prove the indexed page is complete; storage may already contain only a partial body. `version_state` is `match`, `mismatch`, or `unknown`; unknown is preserved for unversioned sources.

The `summary` keeps `retrieval_passed/retrieval_required` separate from `diagnostics_met/diagnostics_required`. Both counts must meet their targets for the command to pass. `empty` and `unknown_freshness` can meet a diagnostic expectation without counting as coverage. A relevant Django 6.1 page cannot satisfy TP Playbook's Django 5.2 requirement. A version mismatch requires a selected search result and fetched content with the required anchors; an absent page is reported as `wrong_page`. When a tenant includes several versions, the fetched result URL supplies the version evidence. A Git page uses the recorded commit and portable file suffix; the catalog's official repository tag maps that commit to the source. RxJS uses the canonical URL and version in its generated page metadata. `index_created_at` is not treated as a source freshness timestamp.

Current site tenants such as Angular Material and the OpenTelemetry Python SDK do not prove compatibility with TP Playbook's locked package versions. Their `version_state` remains `unknown` until a pinned source is indexed. Caddy's current documentation is likewise unversioned relative to the project's 2.10.2 image.

The source URLs and content anchors are intentionally narrow probes. Audit each technology's guides, APIs, tooling, and operational pages separately before claiming complete coverage. Current Angular Material and RxJS entrypoints require rendered-page inspection before indexing; a JavaScript shell is not substantive fetched documentation.

## Current limitations

The live check uses targeted tenant searches. It does not measure cross-tenant discovery rank or source recency beyond the available provenance. The script does not infer version compatibility for unversioned documentation, and it does not compare resolved lockfiles automatically. Update the case catalog alongside TP Playbook's lockfiles and the source audit. Keep live results separate from deterministic unit fixtures because remote documentation and local indexes can change.
