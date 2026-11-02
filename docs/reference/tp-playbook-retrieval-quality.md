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

The live command exits with status 1 while any required retrieval case is missing. The report is written before exit. Use `--docsearch /path/to/docsearch` to select the executable. The installed CLI must support `describe`, `search`, and `fetch` with `--json`.

## Case fields

| Field | Meaning |
| --- | --- |
| `id`, `technology` | Stable case identifier and scope. |
| `project_version` | Version or manifest constraint at the time the case was defined; refresh it when TP Playbook changes. `null` means unverified. |
| `tenant`, `source` | Required tenant and official URL prefix. A result from a different tenant or host does not satisfy the case. |
| `version_pattern` | Pattern for a source version that is explicit in the configured URL prefix. An absent pattern yields an unknown version state. |
| `pages[].query` | Targeted search phrase. |
| `pages[].path` | Exact official page path required among the first 20 targeted results. |
| `pages[].terms` | Case-insensitive content anchors required in the fetched page. |
| `expect` | Diagnostic state (`empty`, `unknown_freshness`, or `version_mismatch`); ordinary cases expect `retrieved`. |
| `fixture_only` | Excludes a synthetic version case from live execution. |

The 15 cases cover Django CSRF and uploaded HTML, private S3 access, drf-spectacular schemas, Angular routing and Material/CDK, RxJS, Cobra, OpenTelemetry Go and Python, Caddy SPA/proxy/TLS, an empty tenant, unknown freshness, and matching/mismatching version states. The matching-version case uses a controlled fixture until a verifiable Django 5.2 tenant exists.

## Report fields and verdicts

Every case reports expected and actual source, project and source versions, freshness, document count, index ID, page query, top hits, selected rank, fetched URL, content length, missing terms, and a `finding`. A page passes retrieval only when its official URL appears in the targeted results and its full fetched content contains the required anchors. Truncated or empty content fails. `version_state` is `match`, `mismatch`, or `unknown`; unknown is preserved for unversioned sources.

The `summary` keeps `retrieval_passed/retrieval_required` separate from `diagnostics_met/diagnostics_required`. `empty` and `unknown_freshness` can meet a diagnostic expectation without counting as coverage. A relevant Django 6.1 page cannot satisfy TP Playbook's Django 5.2 requirement. `index_created_at` is not treated as a source freshness timestamp.

The source URLs and content anchors are intentionally narrow probes. Audit each technology's guides, APIs, tooling, and operational pages separately before claiming complete coverage. Current Angular Material and RxJS entrypoints require rendered-page inspection before indexing; a JavaScript shell is not substantive fetched documentation.

## Current limitations

The live check uses targeted tenant searches. It does not measure cross-tenant discovery rank or source recency beyond the available provenance. The script does not infer version compatibility for unversioned documentation, and it does not compare resolved lockfiles automatically. Update the case catalog alongside TP Playbook's lockfiles and the source audit. Keep live results separate from deterministic unit fixtures because remote documentation and local indexes can change.
