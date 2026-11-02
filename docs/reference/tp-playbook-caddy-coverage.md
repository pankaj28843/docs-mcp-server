# Caddy documentation coverage for TP Playbook

This reference records the official Caddy source used for TP Playbook's proxy
configuration and the limits of its version coverage. The reusable tenant
configuration is `examples/caddy-deployment.json`.
It is an isolated example, not a change to a local `deployment.json`.

## Source and version

| Item | Evidence | Interpretation |
| --- | --- | --- |
| TP Playbook development image | Its `compose.yaml` specifies `caddy:2.10.2-alpine` with a digest | Development runs Caddy 2.10.2. |
| TP Playbook deployed image | Its `compose.deploy.yaml` takes `TP_CADDY_IMAGE` | The deployed version cannot be inferred from the repository alone. |
| Tenant source | [Official Caddy documentation](https://caddyserver.com/docs/) at unversioned URLs | This corpus follows the current website, with no pinned Caddy release. |
| Version boundary | The current [`reverse_proxy` reference](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) describes upstream HTTPS `Host` behavior introduced in v2.11.0; [running guidance](https://caddyserver.com/docs/running) labels `SIGUSR1` reload as v2.11.0+ | These instructions must not be applied to the 2.10.2 development image without checking that release's behavior. |

The [v2.10.2 Caddy release](https://github.com/caddyserver/caddy/releases/tag/v2.10.2)
is the fallback for release-specific behavior. A comprehensive, release-matched
2.10.2 documentation tree has not been verified. Search results from this tenant
should be described as **current, unversioned Caddy docs**, not as 2.10.2 docs.

## Covered documentation areas

The crawler starts at the [official docs index](https://caddyserver.com/docs/)
and all 40 authored directive URLs listed in the [official website source
tree](https://github.com/caddyserver/website/tree/master/src/docs/markdown/caddyfile/directives).
It follows links within `/docs/`. Explicit directive seeds cover links that the
rendered discovery pass misses in the directives table. The source has no
usable sitemap at the usual `/sitemap.xml` or `/docs/sitemap.xml` paths. The
crawler is bounded to 2,000 pages and excludes links outside the official
`/docs/` subtree. It also excludes generated `/docs/json/` and
`/docs/modules/` trees: a trial crawl found over 1,600 generated URLs, while
sampled pages contained empty reference templates. New directive pages need a
seed-list refresh against the official source tree.

| Area | Canonical references | TP Playbook use |
| --- | --- | --- |
| Caddyfile and routing | [Concepts](https://caddyserver.com/docs/caddyfile/concepts), [directives](https://caddyserver.com/docs/caddyfile/directives), [request matchers](https://caddyserver.com/docs/caddyfile/matchers), [global options](https://caddyserver.com/docs/caddyfile/options), [patterns](https://caddyserver.com/docs/caddyfile/patterns) | Site addresses, wildcard hosts, and route precedence. |
| TLS and certificates | [Automatic HTTPS](https://caddyserver.com/docs/automatic-https), [`tls`](https://caddyserver.com/docs/caddyfile/directives/tls), [HTTPS quick start](https://caddyserver.com/docs/quick-starts/https) | Explicit local certificate and key files, protocols, wildcard names. |
| Proxy and headers | [`reverse_proxy`](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [`handle`](https://caddyserver.com/docs/caddyfile/directives/handle), [`handle_path`](https://caddyserver.com/docs/caddyfile/directives/handle_path), [`header`](https://caddyserver.com/docs/caddyfile/directives/header) | Django upstream, `/app/*` prefix stripping, security and cache headers. |
| Static SPA | [`root`](https://caddyserver.com/docs/caddyfile/directives/root), [`try_files`](https://caddyserver.com/docs/caddyfile/directives/try_files), [`file_server`](https://caddyserver.com/docs/caddyfile/directives/file_server), [`encode`](https://caddyserver.com/docs/caddyfile/directives/encode), [SPA pattern](https://caddyserver.com/docs/caddyfile/patterns#single-page-apps-spas) | Frontend files, `/index.html` fallback, compression. |
| APIs and extension | [Admin API](https://caddyserver.com/docs/api), [command line](https://caddyserver.com/docs/command-line), [JSON config](https://caddyserver.com/docs/json), [modules](https://caddyserver.com/docs/modules), [extending Caddy](https://caddyserver.com/docs/extending-caddy) | Config operations and module boundaries. |
| Runtime and Docker | [Keep Caddy Running](https://caddyserver.com/docs/running), [install](https://caddyserver.com/docs/install), [logging](https://caddyserver.com/docs/logging), [metrics](https://caddyserver.com/docs/metrics), [troubleshooting](https://caddyserver.com/docs/troubleshooting), [official Docker image](https://hub.docker.com/_/caddy) | Compose setup, volumes, reload, logging and container operations. |

The official Docker image page is outside the `/docs/` URL boundary and is a
direct-link supplement, not an indexed page in this tenant. The existing Docker
tenant covers Docker Compose semantics separately. Third-party module manuals,
community posts, and plugin registry descriptions are outside this official
core. The generated JSON/module reference trees are direct-link fallbacks, not
indexed coverage in this tenant. Their sampled bodies did not contain usable
module or field reference content; a 200 response or indexed title alone is
not evidence of content coverage.

## Crawl, index, and retrieval evidence

An isolated run on 2026-11-02 used a private worktree, a private browser
endpoint, and the example configuration. The first root-only trial discovered
1,656 URLs, largely generated JSON/module templates, but stored just 14 of
the 40 official directive pages. The revised seed list and URL exclusions
produced the following completed run:

| Check | Observed result |
| --- | --- |
| Crawler completion | `last_crawler_run: 2026-11-02T18:16:56Z`; one completed run |
| Queue and failures | `queue_depth: 0`, `metadata_pending: 0`, `failed_url_count: 0` |
| Stored source pages | `metadata_total_urls: 79`, `metadata_successful: 79` |
| Directive coverage | 40 of 40 authored directive pages in the official website source tree |
| Search index | 79 documents in one persisted BM25 segment, created `2026-11-02T18:17:46Z` |
| Freshness evidence | Newest document fetch `2026-11-02T18:17:06Z`; this measures the crawl, not the Caddy release version |
| Export | `sync_tenant_data.py export --tenants caddy` produced a 0.70 MB `caddy.7z` archive containing the completed corpus and persisted index; the private export also included its isolated example-based `deployment.json` |

Representative local `docsearch search caddy` queries returned these first
results, and `docsearch fetch caddy <result URL>` returned the full indexed
content at each URL:

| Query | First result | Fetch evidence |
| --- | --- | --- |
| `Caddyfile site address wildcard one label host matching` | [Caddyfile Concepts](https://caddyserver.com/docs/caddyfile/concepts) | 26,309 characters; site address and wildcard discussion |
| `tls certificate key files protocols tls1.2 tls1.3 wildcard` | [`tls` directive](https://caddyserver.com/docs/caddyfile/directives/tls) | 31,726 characters; certificate/key and protocol reference |
| `reverse_proxy upstream X-Forwarded-Proto Host header trusted proxies` | [`reverse_proxy` directive](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) | 52,271 characters; upstream and header behavior, including v2.11+ notes |
| `handle_path /app/* try_files {path} /index.html file_server SPA` | [Common Caddyfile Patterns](https://caddyserver.com/docs/caddyfile/patterns) | 12,972 characters; SPA fallback pattern; `file_server`, `handle_path`, and `try_files` appeared in the top four |
| `Caddy admin API load config extensions modules Docker Compose reload` | [API](https://caddyserver.com/docs/api) | 15,500 characters; [running](https://caddyserver.com/docs/running) ranked second and fetched with 16,424 characters; [extending](https://caddyserver.com/docs/extending-caddy) ranked fourth and fetched with 19,085 characters |

The exact local CLI check used a private `docsearch` config pointing
`data_dir` at the isolated `mcp-data`, `deployment_config` at the isolated
tenant config, and `mode: local`. This matters when a machine's default
`docsearch` config points at a different deployment: passing only environment
variables may leave its configured `deployment_config` in effect.
