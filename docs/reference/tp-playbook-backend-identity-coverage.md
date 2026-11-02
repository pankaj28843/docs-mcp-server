# TP Playbook backend identity and API documentation coverage

This example configuration adds version-specific documentation tenants for TP Playbook's backend and identity stack. The version source is `backend/uv.lock` in the TP Playbook workspace as inspected on 2026-11-02. The tenants are examples in `deployment.example.json`; operators select and deploy them with their own `deployment.json` and data volume.

| Tenant | TP Playbook lock | Official source and scope |
| --- | --- | --- |
| `django-5-2` | Django 5.2.18 | [Django 5.2 documentation](https://docs.djangoproject.com/en/5.2/), filtered from the [English sitemap](https://docs.djangoproject.com/sitemap-en.xml) to `/en/5.2/` |
| `drf-3-18` | Django REST framework 3.18.2 | [DRF repository tag 3.18.2](https://github.com/encode/django-rest-framework/tree/3.18.2/docs), `docs/` |
| `django-allauth-65-21` | django-allauth 65.21.0 | [allauth repository tag 65.21.0](https://codeberg.org/allauth/django-allauth/src/tag/65.21.0/docs), `docs/` |
| `django-rest-knox-5-1` | Django REST Knox 5.1.0 | [Knox repository tag 5.1.0](https://github.com/jazzband/django-rest-knox/tree/5.1.0/docs), `docs/` |
| `drf-spectacular-0-30` | drf-spectacular 0.30.0 | [drf-spectacular repository tag 0.30.0](https://github.com/tfranzel/drf-spectacular/tree/0.30.0/docs), `docs/` |

Git tags avoid drift from projects' unversioned documentation sites. Django's official URL explicitly selects the 5.2 documentation line; its sitemap is filtered to that path. Django 5.2 patch releases share this versioned documentation URL. The existing generic `django` tenant may cover a newer line, and the existing generic `drf` tenant follows a live site, so use these named tenants when matching TP Playbook code.

## Representative retrieval checks

Run each query against the named tenant, then fetch the returned source URL. The search target is a relevant page, not a particular ranking position.

| Question | Tenant | Expected source |
| --- | --- | --- |
| How do AJAX clients send CSRF tokens? | `django-5-2` | `ref/csrf/` or `howto/csrf/` under `/en/5.2/` |
| What does `SessionAuthentication` require for CSRF? | `drf-3-18` | `topics/ajax-csrf-cors.md` or `api-guide/authentication.md` |
| How is an OpenID Connect provider configured? | `django-allauth-65-21` | `socialaccount/providers/openid_connect.rst` |
| How are auth tokens issued, expired, and revoked? | `django-rest-knox-5-1` | `auth.md` or `api.md` |
| How is an OpenAPI schema customized? | `drf-spectacular-0-30` | `customization.rst` |

`docsearch search` and `docsearch fetch` with an isolated local data directory returned the allauth OpenID Connect, Knox token authentication, and drf-spectacular schema customization pages from the pinned revisions. The source revisions were `f441bf1ff410de80687e28ca7a1643dc4801345c`, `76ee3aaccae56486214b277218f04b3d2918e367`, and `1a5c44a15b2d06744f49285f1f58992f938a05fa` respectively. The DRF tag resolves to `69694a17d0b6ac14b4ea4d77916b73c68dc5a3e8`.

The isolated sync indexed 655 Django 5.2 pages, 213 allauth pages, 7 Knox pages, 69 DRF pages, and 12 drf-spectacular pages. Django's sitemap supplied 654 version-filtered URLs plus the entry URL. Its final crawl status had 655 successful URLs, zero pending, zero failed, and zero queued. Search for `CSRF AJAX fetch X-CSRFToken` returned `https://docs.djangoproject.com/en/5.2/howto/csrf/` first; fetching it returned the `X-CSRFToken` example and online provenance restricted to `/en/5.2/`. Search for `SessionAuthentication CSRF` returned DRF's `topics/ajax-csrf-cors.md` first; fetching it returned the pinned Git revision above.

## Boundaries and deployment checks

These tenants cover framework and library documentation. They do not supply the OpenID Connect Core or OpenAPI protocol specifications, nor TP Playbook's own application routes and settings. For protocol-level questions consult the [OpenID Connect Core specification](https://openid.net/specs/openid-connect-core-1_0.html) and [OpenAPI specification](https://spec.openapis.org/oas/). For application behavior, inspect TP Playbook's code.

Before exporting a crawl, verify `metadata_pending = 0`, `failed_url_count = 0`, and `queue_depth = 0` on each online tenant's `/sync/status` endpoint. Use `/sync/retry-failed` for recoverable extraction failures. A source revision and successful search plus fetch should be checked for each Git tenant after syncing. Exports should include the same tenant names as the deployment config.

The DRF repository applies Git LFS to one `docs/theme/src/drf-logos.fig` design file. Hosts syncing the Git tenant need `git-lfs` installed, or an explicit local Git filter that leaves LFS pointer files untouched. The documentation text itself is plain Markdown; the isolated validation clone used the latter setting and indexed 69 text pages. A missing `git-lfs` binary otherwise makes sparse checkout fail before indexing.
