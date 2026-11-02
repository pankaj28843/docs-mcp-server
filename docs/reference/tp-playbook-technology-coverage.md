# TP Playbook technology documentation coverage

This is a **2026-11-02 local audit**, not a completeness claim or a live inventory. It maps the request's technology groups to the TP Playbook checkout's `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `frontend/package-lock.json`, `cli/go.mod`, Compose files, scripts, and architecture and security docs. Versions may change. Declared ranges and resolved versions are shown separately where available. Runtime versions cannot be inferred from a digest-only image. Indirect dependencies are included where directly imported or operationally relevant, not merely because they appear in a lockfile.

The baseline is the local `docsearch` inventory and retrieval audit on that date, before the pending work below. Counts are indexed document counts, not proof of corpus completeness. Unless noted, indexed source version and last successful index/sync are **unknown**; an index creation date or a fetched-page timestamp is not index freshness. A moving `latest`, `stable`, `current`, or unversioned source is not proof of a lock-version match. “Missing” means no exact tenant was found in that baseline; use the linked official source directly. Sections not explicitly verified below remain unverified, including generated API pages, source navigation, extraction fidelity and historical versions.

## Reconciliation after the baseline

The tables below retain the original local baseline, including “missing” and the original counts. Those labels describe the pre-onboarding observation, **not** the merged example configuration or the current live deployment. The following evidence supersedes those baseline labels; deploy, sync and index remain separate from merging a configuration. Each isolated result is a private test, not proof of shared service availability or complete upstream coverage.

| Area | Merged configuration and isolated evidence on 2026-11-02 | Remaining boundaries |
| --- | --- | --- |
| Backend identity | [PR #82](https://github.com/pankaj28843/docs-mcp-server/pull/82) added `django-5-2`, `django-allauth-65-21`, `django-rest-knox-5-1`, `drf-3-18`, and `drf-spectacular-0-30`. Isolated indexes contained 655, 213, 7, 69 and 12 documents respectively; representative CSRF, OIDC, token and schema search/fetch passed. | Versioned corpus availability in the shared deployment and index freshness must be checked there. Protocol specs are separate. |
| Backend data | [PR #85](https://github.com/pankaj28843/docs-mcp-server/pull/85) added `postgresql-16`, `django-storages-1-14-6`, `psycopg3`, `requests`, `pyjwt-2-15-1` and `botocore`. Isolated indexes contained 1,170, 15, 42, 24, 8 and 164 documents; representative search/fetch passed for each. | Psycopg source showed 3.3.7.dev1 vs lock 3.3.6; botocore 1.43.123 vs 1.43.121. Botocore service references are S3-scoped. Use exact release sources for version-sensitive behavior. |
| WhiteNoise | [PR #75](https://github.com/pankaj28843/docs-mcp-server/pull/75) added `whitenoise`; private crawl indexed six documents, and the Django middleware guide was searched and fetched. Stable docs displayed 6.12.0. | Moving `stable` is not a permanent release pin; other versions and unreachable pages excluded. |
| Angular, Material/CDK and RxJS | [PR #80](https://github.com/pankaj28843/docs-mcp-server/pull/80) added `angular`, `angular-eslint`, `angular-material-source`, `angular-material-api`, `rxjs-source`, and `rxjs-api`; [PR #81](https://github.com/pankaj28843/docs-mcp-server/pull/81) added the RxJS API exporter. Isolated indexes held 1,647, 99, 115, 95, 27 and 371 documents, respectively. Representative framework routing and CLI, Material dialog, CDK overlay and RxJS guide/API search and fetch succeeded privately. | Current Angular and Material API sites move. Material API seeds are manually maintained and not proven complete or version-pinned; generated site extraction requires special handling. Versioned Angular v20/v21 and complete historical Material APIs were not indexed in that experiment. RxJS 7.8.2 API is a version-checked filesystem snapshot with unknown index freshness. |
| Frontend tooling | [PR #76](https://github.com/pankaj28843/docs-mcp-server/pull/76) added an isolated example for `nodejs`, `npm`, `eslint`, `prettier`, `typescript-eslint`, `angular-eslint`, `typescript-reference`, and `esbuild`. Private indexes had 68, 87, 413, 24, 53, 6, 299 and 9 documents; sampled search/fetch passed. | Node 24 is a selected compatible version, not proof of deployed runtime. The tooling example's angular-eslint selection contains only six docs, unlike the broader Angular example's 99; a deployment must choose the intended configuration. TypeScript and esbuild sources move; selected Git directories exclude some rule docs and non-Markdown files. |
| Caddy | [PR #84](https://github.com/pankaj28843/docs-mcp-server/pull/84) added `caddy`. Private sync indexed 79 documents including all 40 authored directive pages; export and representative Caddyfile, TLS, proxy, SPA, API, Docker and extension search/fetch passed. The shared deployment operation also reported 79 indexed and exported, but its discovery check hit a proxy timeout. | Current docs are unversioned and include later behavior than development Caddy 2.10.2. Generated module/JSON trees are excluded; Docker Hub image docs are outside the tenant. Shared discovery and retrieval remain to be verified. |
| Go and telemetry | [PR #86](https://github.com/pankaj28843/docs-mcp-server/pull/86) merged `tp-go-keyring-api`, `tp-google-uuid-api`, `tp-go-toolchain-api`, `tp-go-127`, `tp-otel-go-trace-sdk-api`, `tp-otel-go-guide`, `tp-otel-python-guide`, and `tp-otel-python-sdk`. Its private experiment indexed 1, 1, 3, 1, 1, 10, 13 and 16 documents respectively, with representative search/fetch for each. | Private experiment is not shared deployment evidence. Python SDK `latest` moves; keyring uses a versioned README because the package page is license-restricted; exact Go OTLP HTTP exporter API remains a direct fallback. |

[PR #73](https://github.com/pankaj28843/docs-mcp-server/pull/73) merged discovery evidence and project mapping, [PR #74](https://github.com/pankaj28843/docs-mcp-server/pull/74) source-version provenance, and [PR #77](https://github.com/pankaj28843/docs-mcp-server/pull/77) a repeatable retrieval quality gate. Their existence does not mean every live retrieval gate passed. [PR #83](https://github.com/pankaj28843/docs-mcp-server/pull/83) fixed imported local document URLs and [PR #87](https://github.com/pankaj28843/docs-mcp-server/pull/87) full indexed-document fetch; the tooling experiment verified both with representative imported Node/npm data. Use a CLI containing those fixes for comparable checks.

### Shared local deployment evidence

The deployment operator's local ledger records these results for the service at `127.0.0.1:42042` on 2026-11-02. Each listed tenant had a relevant search and full fetch and an exported archive that passed `7z t`. This is local deployment evidence, not a public service or a completeness guarantee. The ledger does not supply an index completion timestamp for each tenant; freshness is unknown unless the service reports it. The backend/data and frontend tooling batch completed by 19:09 UTC; the eight Go and telemetry tenants completed by 19:17 UTC. Their online syncs had no pending, failed or queued URLs.

| Live tenant | Indexed documents | Observed retrieval and constraints |
| --- | ---: | --- |
| `django-5-2` | 655 | Django 5.2 CSRF; zero pending, failed or queued URLs. |
| `django-allauth-65-21` | 213 | OIDC provider, pinned Git revision `f441bf1ff410de80687e28ca7a1643dc4801345c`. |
| `django-rest-knox-5-1` | 7 | Token authentication, revision `76ee3aaccae56486214b277218f04b3d2918e367`. |
| `drf-3-18` | 69 | AJAX CSRF, revision `69694a17d0b6ac14b4ea4d77916b73c68dc5a3e8`. |
| `drf-spectacular-0-30` | 12 | Schema customization, revision `1a5c44a15b2d06744f49285f1f58992f938a05fa`. |
| `whitenoise` | 6 | Django static files; moving stable displayed 6.12.0, zero pending, failed or queued URLs. |
| `angular` | 1,627 | Route guards; moving current site, zero pending, failed or queued URLs. |
| `angular-eslint` | 99 | alt-text rule, revision `7722ad2ab4da81568f19a7a29a3951fa443bf22c`. |
| `angular-material-source` | 115 | MatDialog guide, revision `e28b22e2cc28e7e6bc0850e9a9e7f076e7c75428`. |
| `angular-material-api` | 95 | MatDialog full fetch, 56,351 characters; configured fragments successful, zero pending or failed. Current source is unversioned. |
| `rxjs-source` | 27 | Observable guide, revision `e5351d02e225e275ac0e497c7b66eaa5f0c88791`. |
| `rxjs-api` | 371 | switchMap search and Observable full fetch, 591,925 characters; validated 7.8.2 snapshot captured 2026-11-02 18:44:11 UTC, filesystem freshness reported unknown. |
| `caddy` | 79 | reverse_proxy full fetch, 52,271 characters; all 40 configured directive URLs present, zero pending or failed. An initial discovery proxy timeout was followed by a 300-second non-force retry that skipped all 41 recently visited roots; fresh discovery completeness remains unknown. |
| `postgresql-16` | 1,170 | Transaction isolation; 1,170 configured URLs successful, zero pending, failed or queued. Crawler disabled; this is not proof of discovery completeness. |
| `django-storages-1-14-6` | 14 | Amazon S3; 14 URLs successful, zero pending, failed or queued. |
| `psycopg3` | 42 | Connection pools; moving current docs can differ from lock 3.3.6; one stored document skipped by indexer. |
| `requests` | 24 | Advanced usage; moving stable source; one stored document skipped by indexer. |
| `pyjwt-2-15-1` | 8 | Usage; eight URLs successful, zero pending, failed or queued. |
| `botocore` | 164 | Configuration reference; moving latest can differ from lock 1.43.121; zero pending, failed or queued. |
| `nodejs` | 68 | Test runner; Node 24 source revision `f7f273a9bb6445f6f7fb6349105e7532972045fb`; deployed project runtime unknown. |
| `npm` | 87 | npm description; revision `c276cadf785c1018d82dd287fe7742567055efb9`. |
| `eslint` | 413 | Migration codemods; revision `4637f9827a1ba137498eaee70957850621082815`. |
| `prettier` | 24 | Option philosophy; revision `1172b82c295c4f889fd787dc6c78c3e194ebf353`. |
| `typescript-eslint` | 53 | JavaScript project usage; revision `4ad6b7553781fa3c93fc26642d7219d2e6624504`. |
| `typescript-reference` | 299 | Less context sensitivity; moving source revision `205122bb73dcbf6f3b373de5bdb0d9fa5434d015`. |
| `esbuild` | 9 | API build options; nine URLs successful, zero pending, failed or queued. Moving source. |
| `tp-go-keyring-api` | 1 | Versioned v0.4.0 README; package API remains a direct source fallback. |
| `tp-google-uuid-api` | 1 | Versioned v1.6.0 package API. |
| `tp-go-toolchain-api` | 3 | Go 1.27.1 testing, vet and go command references. |
| `tp-go-127` | 1 | Go 1.27 release notes. |
| `tp-otel-go-trace-sdk-api` | 1 | Go trace SDK 1.47.0; exact version matched in final retrieval gate. |
| `tp-otel-go-guide` | 10 | Moving Go guide; Git revision `6de877a7b417690fb105844ffccdd60c97b97268`. |
| `tp-otel-python-guide` | 13 | Moving Python guide; same Git revision as Go guide. |
| `tp-otel-python-sdk` | 16 | Python SDK trace page; `latest` source version unknown against lock 1.45.1. |

The merged-main retrieval gate on 2026-11-02 returned **12/12 required retrieval cases and 3/3 diagnostics**. It searched and fetched Django 5.2 CSRF and uploaded-HTML security, S3 public-access blocking and presigned URLs, drf-spectacular schema customization, Angular route guards, Material dialog and CDK overlay, RxJS switchMap, Cobra flags, Go and Python telemetry SDKs, and Caddy SPA, proxy and TLS pages. Django 5.2, drf-spectacular 0.30.0, RxJS 7.8.2 and Go telemetry 1.47.0 had version-match evidence. The source-version relationship remained unknown for S3, current Angular and Material, Cobra, Python SDK `latest`, and current Caddy. The diagnostics observed an empty index, unknown S3 freshness, and the Django 6.1-versus-5.2 mismatch; the matching Django 5.2 result was also retrieved. All fetched gate pages were untruncated. These checks demonstrate representative retrieval, not full corpus coverage, version equivalence for unknown cases, or production security configuration.

Do not treat private counts, archive creation or nonzero index size as live retrieval proof.

## Baseline: Backend and data

| Technology; declared → locked/configured | Canonical official documentation and baseline tenant | Evidence, exclusions and fallback |
| --- | --- | --- |
| Python; >=3.12 → runtime unknown | [Python docs](https://docs.python.org/3/12/); `python` | 527 docs from 3.15, freshness unknown; 3.12 compatibility is not established. Use the actual runtime's versioned docs. |
| Django; >=5.2,<5.3 → 5.2.18 | [Django 5.2](https://docs.djangoproject.com/en/5.2/); `django` | 280 docs from 6.1, last sync 2026-10-29; mismatch. Release notes excluded by baseline config. Use 5.2 docs, including [CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/). |
| Django REST Framework; 3.18.2 → 3.18.2 | [DRF](https://www.django-rest-framework.org/); `drf` | 45 docs; unversioned source and coverage unknown. Check version-specific behavior upstream. |
| django-allauth/OIDC; 65.21.0 → 65.21.0 | [allauth](https://docs.allauth.org/en/latest/) and [OIDC provider](https://docs.allauth.org/en/dev/socialaccount/providers/openid_connect.html); missing | Exact-version docs not verified; `latest` and `dev` move. Check release notes and source tag for version-sensitive behavior. |
| Django REST Knox; 5.1.0 → 5.1.0 | [Knox project](https://pypi.org/project/django-rest-knox/); missing | Accessible canonical upstream docs and version coverage unverified; follow project links and verify content. |
| drf-spectacular; 0.30.0 → 0.30.0 | [drf-spectacular](https://drf-spectacular.readthedocs.io/en/latest/); missing | Schema and extensions are available upstream; moving source version unknown. |
| django-storages; >=1.14,<2 → 1.14.6 | [storage backends](https://django-storages.readthedocs.io/en/latest/), including [S3](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html); missing | S3 page displayed 1.14.6 at audit; `latest` may move. |
| psycopg; >=3.2,<4 → 3.3.6 | [Psycopg 3](https://www.psycopg.org/psycopg3/docs/); missing | Current page displayed 3.3.7.dev1; exact lock match unverified. |
| Gunicorn; >=26.2,<27 → 26.2.0 | [Gunicorn](https://docs.gunicorn.org/); `gunicorn` | 34 docs, source version and comprehensive coverage unknown. |
| WhiteNoise; >=6,<7 → 6.12.0 | [WhiteNoise](https://whitenoise.readthedocs.io/en/stable/); missing | `stable` displayed 6.12.0 at audit but moves. See reconciliation above for merged configuration and private evidence. |
| Requests / PyJWT; indirect, directly imported → 2.34.2 / 2.15.1 | [Requests](https://requests.readthedocs.io/), [PyJWT](https://pyjwt.readthedocs.io/); missing | Separate official references are needed for the project's OIDC protocol code; indexed coverage and version unknown. |
| boto3 / botocore; indirect via storage; botocore exceptions imported → 1.43.121 / 1.43.121 | [Boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html), [botocore](https://botocore.amazonaws.com/v1/documentation/api/latest/index.html); `boto3` / missing | 3,137 boto3 docs, scoped to guide and selected services including S3; other services excluded. Moving source version unknown; botocore is not established by boto3 results. |
| PostgreSQL; `postgres:16` digest → patch unknown | [PostgreSQL 16](https://www.postgresql.org/docs/16/); `postgresql` | 1,147 docs from `/docs/current/`, freshness and actual source version unknown. Use 16 docs for version-specific answers. |
| S3; deployment configuration, service version not applicable | [S3 user guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/), [API](https://docs.aws.amazon.com/AmazonS3/latest/API/); `aws-s3` | 1,727 docs; freshness and coverage unknown. Private access requires service policy and deployment evidence, not just a retrieved page. |
| OpenID Connect / OpenAPI; versions not declared | [OIDC Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html), [OpenAPI specifications](https://spec.openapis.org/oas/); no exact tenants found | Choose the protocol version used by the deployment/schema; neither allauth nor drf-spectacular substitutes for the specifications. |

## Baseline: Frontend

| Technology; declared → locked | Canonical official documentation and baseline tenant | Evidence, exclusions and fallback |
| --- | --- | --- |
| Angular core; ^22.2.0 → 22.2.4 | [Guides](https://angular.dev/guide), [API](https://angular.dev/api), [security](https://angular.dev/best-practices/security), [v21](https://v21.angular.dev/), [v20](https://v20.angular.dev/); missing | Current site identified v22 at audit. Components, templates, DI, forms, HTTP, routing, security, testing, tutorials and APIs need crawl and content verification, including archived versions. Direct official sites are fallback. |
| Angular CLI/build; ^22.2.5 → 22.2.5 | [CLI](https://angular.dev/cli), [build tooling](https://angular.dev/tools/cli); missing | No indexed CLI/build proof. Verify `ng build`, workspace and builder reference and supported version archives. |
| Angular Material/CDK; 22.2.4 → 22.2.4 | [Material components](https://material.angular.dev/components/categories), [CDK](https://material.angular.dev/cdk/categories); missing | Current and sampled archived pages returned JavaScript shells to plain extraction; guides, examples and API bodies remain unverified. Android Material is a different tenant. |
| Angular ESLint; 22.6.0 → 22.6.0 | [angular-eslint](https://github.com/angular-eslint/angular-eslint/tree/v22.6.0), [rules](https://github.com/angular-eslint/angular-eslint/tree/main/packages/eslint-plugin/docs/rules); missing | Tagged source can establish release provenance; rule coverage and indexing unverified. |
| RxJS; ~7.8.0 → 7.8.2 | [RxJS guides](https://rxjs.dev/guide/overview), [API](https://rxjs.dev/api); missing | Official site identified stable 7.8.2; sampled guide returned a JavaScript shell to plain extraction. Search and full content remain unverified. |
| TypeScript; ~6.0.2 → 6.0.3 | [TypeScript docs](https://www.typescriptlang.org/docs/), [TSConfig](https://www.typescriptlang.org/tsconfig/); `typescript` | 79 docs; source version/freshness unknown. Baseline excludes release notes and standalone TSConfig; fetched examples showed concatenation. Use official [6.0 notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html) directly. |
| Node.js / npm; Node runtime unknown, npm 12.2.0 | [Node API](https://nodejs.org/docs/), [npm v12](https://docs.npmjs.com/cli/v12/); missing | Angular engine ranges do not establish the runtime. `node:test`, `node:assert`, npm commands and lockfile behavior need the applicable official versions. |
| ESLint / typescript-eslint; 10.13.0 / 8.72.1 | [ESLint](https://eslint.org/docs/latest/), [typescript-eslint](https://typescript-eslint.io/); missing | Core and plugin rules/configuration are distinct; moving versions and indexed coverage unknown. |
| Prettier / esbuild; 3.9.10 / 0.28.2 | [Prettier](https://prettier.io/docs/), [esbuild](https://esbuild.github.io/); missing | Exact version and content extraction unverified. esbuild's long anchor-heavy API pages require search and fetch checks. |

See reconciliation above for merged frontend tooling configuration and private evidence.

## Baseline: CLI, telemetry and platform

| Technology; declared → locked | Canonical official documentation and baseline tenant | Evidence, exclusions and fallback |
| --- | --- | --- |
| Go; 1.27.1 | [Go docs](https://go.dev/doc/), [standard library](https://pkg.go.dev/std), [go command](https://pkg.go.dev/cmd/go), [vet](https://pkg.go.dev/cmd/vet); `golang` | 140 docs, `/doc/` scope excludes package and command API references; version/freshness unknown. Race detector fetch succeeded. |
| Cobra; v1.10.2 | [Cobra guide](https://cobra.dev/docs/), [versioned API](https://pkg.go.dev/github.com/spf13/cobra@v1.10.2); `golang-cobra` | 24 docs; flags page fetched, source version unknown. Versioned package API is outside guide evidence. |
| OS keyring / UUID; v0.4.0 / v1.6.0 | [keyring API](https://pkg.go.dev/github.com/go-keyring/keyring@v0.4.0), [UUID API](https://pkg.go.dev/github.com/google/uuid@v1.6.0); missing | No indexed exact package APIs established. Keyring uses platform backends; see [Windows Credential Manager](https://learn.microsoft.com/en-us/windows/win32/secauthn/credential-manager), [Apple Keychain](https://developer.apple.com/documentation/security/keychain-services), [Secret Service](https://specifications.freedesktop.org/secret-service/latest/). |
| OpenTelemetry Go; v1.47.0, semconv v1.40.0; Python >=1.35,<2 → 1.45.1 | [Go guide](https://opentelemetry.io/docs/languages/go/), [Go API](https://pkg.go.dev/go.opentelemetry.io/otel@v1.47.0), [Python guide](https://opentelemetry.io/docs/languages/python/), [Python SDK](https://opentelemetry-python.readthedocs.io/en/latest/sdk/); `opentelemetry-specs`, `otel-semconv` | Spec 90 and semconv 273 docs; language SDK/API/exporter coverage missing. Spec fetch succeeded but does not prove either language's behavior. Moving Python SDK source version unknown. |
| Platform-specific updates; runtime OS/version unknown | [Go `os`](https://pkg.go.dev/os), [Windows API](https://learn.microsoft.com/en-us/windows/win32/api/), [Apple developer docs](https://developer.apple.com/documentation/); no specific mapping verified | System update and filesystem API applicability depends on platform; direct official references until exact APIs and indexed coverage are verified. |

## Baseline: Runtime and development tools

| Technology; declared/configured → observed | Canonical official documentation and baseline tenant | Evidence, exclusions and fallback |
| --- | --- | --- |
| Caddy; dev 2.10.2 digest; production `TP_CADDY_IMAGE` → unknown | [Caddy docs](https://caddyserver.com/docs/), [official image](https://hub.docker.com/_/caddy); missing | Current docs are unversioned and include later behavior; 2.10.2-matched docs not established. Cover [Caddyfile](https://caddyserver.com/docs/caddyfile), [TLS](https://caddyserver.com/docs/automatic-https), [reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [SPA](https://caddyserver.com/docs/caddyfile/patterns#single-page-apps-spas), headers, compression, API, modules, extensions and Docker. Generated JSON/module content and Docker Hub extraction remain unverified. |
| Docker/Compose; versions unknown | [Docker](https://docs.docker.com/), [Compose](https://docs.docker.com/compose/); `docker` | 1,422 docs, freshness unknown; services and networks reference results found, whole Compose corpus unverified. |
| mkcert; version unknown | [mkcert](https://github.com/FiloSottile/mkcert); missing | Used in local certificate setup; source and version coverage unverified. |
| HTTPS/TLS; protocol version configured by deployment | [TLS 1.3 RFC 8446](https://www.rfc-editor.org/rfc/rfc8446), [TLS 1.2 RFC 5246](https://www.rfc-editor.org/rfc/rfc5246); no exact mapping verified | Use protocol specifications alongside Caddy and OpenSSL docs; no complete indexed protocol coverage established. |
| uv / Ruff; Dockerfile uv 0.13.6, Ruff 0.16.5 | [uv](https://docs.astral.sh/uv/), [Ruff](https://docs.astral.sh/ruff/); `uv`, `ruff` | 72 / 954 docs; moving source versions and freshness unknown. |
| Django testing / Go testing, race and vet | [Django 5.2 testing](https://docs.djangoproject.com/en/5.2/topics/testing/), [Go testing](https://pkg.go.dev/testing), [race detector](https://go.dev/doc/articles/race_detector), [vet](https://pkg.go.dev/cmd/vet); `django`, `golang` | Django tenant is 6.1; Go race page fetched, but package and vet API outside its `/doc/` scope. |
| Make / OpenSSL; versions unknown | [GNU Make manual](https://www.gnu.org/software/make/manual/), [OpenSSL docs](https://docs.openssl.org/); no exact mapping verified | Verify tool and deployed versions before applying version-sensitive command options. |

## Baseline: Representative retrieval evidence

These are baseline search observations, not corpus boundaries. Results were inspected with the installed `docsearch` CLI on 2026-11-02. Where fetch is not stated, a relevant search hit alone is not a fetch pass. `last_fetched_at` belongs to the fetched page.

| Query / expected source | Actual result and limitation |
| --- | --- |
| `django 'CSRF authentication'` / Django 5.2 | Official 6.1 CSRF page searched and fetched, page timestamp 2026-10-29, truncated at 500 characters. Relevant but **version mismatch**; 5.2 retrieval remains unproven. |
| `drf 'SessionAuthentication CSRF'` / DRF | Official AJAX/CSRF and authentication hits; version and fetch unverified. |
| HTML origin isolation / browser and Django security | No targeted search/fetch recorded; use [Django security](https://docs.djangoproject.com/en/5.2/topics/security/) and [MDN same-origin policy](https://developer.mozilla.org/en-US/docs/Web/Security/Same-origin_policy). |
| `boto3 'S3 presigned URL private object'` / boto3 S3 | Official presigned URL guide and S3 API hits; fetch and private policy coverage unverified. |
| API schema / drf-spectacular | No exact baseline tenant; search/fetch not demonstrated. Use [schema docs](https://drf-spectacular.readthedocs.io/en/latest/). |
| `postgresql 'CREATE ROLE row level security'` / PostgreSQL 16 | Official current CREATE ROLE and row-security hits; server-version match and fetch unverified. |
| `docker 'compose services depends_on healthcheck'` / Compose | Official services reference was top hit; fetch and full corpus unverified. |
| Angular routing / CLI build / Material dialog / CDK drag-drop / RxJS observable | No exact baseline tenants; cross-tenant searches returned unrelated results. All five search/fetch demonstrations remain gaps. Direct official links above are fallback. |
| Caddyfile / TLS / reverse proxy / static SPA | No Caddy tenant; `search-all` returned unrelated results. All four search/fetch demonstrations remain gaps. |
| `typescript 'typescript type narrowing'` / TypeScript | Official handbook narrowing hit and substantive page fetched; page timestamp 2026-10-29, truncated. Version match and index freshness unknown. |
| Cobra flags / Go race detector / OTel trace SDK spec | Official pages searched and fetched; page timestamps respectively 2026-10-28, 2026-04-07, 2026-10-29. Source version and language SDK coverage remain unknown. Go `vet` query ranked release notes first. |
| Go/Python telemetry exporter | Language SDK tenants absent; spec fetch is not an exporter pass. Use the language-specific links above. |

## Maintaining this snapshot

Re-run `docsearch list --json`, `find`, `describe`, targeted `search`, and `fetch` using the installed command help. Record tenant, canonical returned URL, expected and observed version, count, successful sync/index time or unknown, page timestamp, content and truncation, and failures. Check official source navigation and excluded sections separately; a representative hit or count cannot establish comprehensive coverage. A result from a different version is a mismatch, not a pass. Empty tenants and unknown freshness must remain visible.

The merged quality gate and source provenance work are identified in the reconciliation above. Reconcile the baseline against successful live indexes and per-query results before treating it as current inventory. Local documentation evidence does not establish real federation, S3 permissions, or deployment readiness.
