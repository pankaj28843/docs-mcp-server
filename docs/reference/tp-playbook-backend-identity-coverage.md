# TP Playbook backend identity and API documentation coverage

The example deployment uses current documentation for TP Playbook's backend and identity stack. The project versions below were inspected on 2026-11-02; current sources can differ from those locks. The `django`, `drf`, and three identity library tenants follow their latest stable Git tags. Select and deploy tenants with your own `deployment.json` and data volume.

| Tenant | TP Playbook lock at audit | Current source |
| --- | --- | --- |
| `django` | Django 5.2.18 | [Django repository](https://github.com/django/django), `docs/` |
| `drf` | Django REST framework 3.18.2 | [DRF repository](https://github.com/encode/django-rest-framework), `docs/` |
| `django-allauth` | django-allauth 65.21.0 | [allauth repository](https://codeberg.org/allauth/django-allauth), `docs/` |
| `django-rest-knox` | Django REST Knox 5.1.0 | [Knox repository](https://github.com/jazzband/django-rest-knox), `docs/` |
| `drf-spectacular` | drf-spectacular 0.30.0 | [drf-spectacular repository](https://github.com/tfranzel/drf-spectacular), `docs/` |

Check the source revision or version against the project lock for version-sensitive behavior.

## Representative retrieval checks

Run each query against the named tenant, then fetch the returned source URL. The search target is a relevant page, not a particular ranking position.

| Question | Tenant | Expected source |
| --- | --- | --- |
| How do AJAX clients send CSRF tokens? | `django` | `ref/csrf/` or `howto/csrf/` in the configured Django release |
| What does `SessionAuthentication` require for CSRF? | `drf` | the AJAX/CSRF or authentication guide |
| How is an OpenID Connect provider configured? | `django-allauth` | `socialaccount/providers/openid_connect.rst` |
| How are auth tokens issued, expired, and revoked? | `django-rest-knox` | `auth.md` or `api.md` |
| How is an OpenAPI schema customized? | `drf-spectacular` | `customization.rst` |

In the 2026-11-02 experiment, `docsearch search` and `docsearch fetch` with an isolated local data directory returned the allauth OpenID Connect, Knox token authentication, and drf-spectacular schema customization pages from the pinned revisions. The source revisions were `f441bf1ff410de80687e28ca7a1643dc4801345c`, `76ee3aaccae56486214b277218f04b3d2918e367`, and `1a5c44a15b2d06744f49285f1f58992f938a05fa` respectively. The DRF tag resolves to `69694a17d0b6ac14b4ea4d77916b73c68dc5a3e8`.

The isolated sync indexed 655 Django 5.2 pages, 213 allauth pages, 7 Knox pages, 69 DRF pages, and 12 drf-spectacular pages. Django's sitemap supplied 654 version-filtered URLs plus the entry URL. Its final crawl status had 655 successful URLs, zero pending, zero failed, and zero queued. Search for `CSRF AJAX fetch X-CSRFToken` returned `https://docs.djangoproject.com/en/5.2/howto/csrf/` first; fetching it returned the `X-CSRFToken` example and online provenance restricted to `/en/5.2/`. Search for `SessionAuthentication CSRF` returned DRF's `topics/ajax-csrf-cors.md` first; fetching it returned the pinned Git revision above.

## Boundaries and deployment checks

These tenants cover framework and library documentation. They do not supply the OpenID Connect Core or OpenAPI protocol specifications, nor TP Playbook's own application routes and settings. For protocol-level questions consult the [OpenID Connect Core specification](https://openid.net/specs/openid-connect-core-1_0.html) and [OpenAPI specification](https://spec.openapis.org/oas/). For application behavior, inspect TP Playbook's code.

Before exporting a crawl, verify `metadata_pending = 0`, `failed_url_count = 0`, and `queue_depth = 0` on each online tenant's `/sync/status` endpoint. Use `/sync/retry-failed` for recoverable extraction failures. A source revision and successful search plus fetch should be checked for each Git tenant after syncing. Exports should include the same tenant names as the deployment config.

The historical DRF Git source applies Git LFS to one `docs/theme/src/drf-logos.fig` design file. Hosts syncing that Git source need `git-lfs` installed, or an explicit local Git filter that leaves LFS pointer files untouched. The documentation text itself is plain Markdown; the isolated validation clone used the latter setting and indexed 69 text pages. A missing `git-lfs` binary otherwise makes sparse checkout fail before indexing.
