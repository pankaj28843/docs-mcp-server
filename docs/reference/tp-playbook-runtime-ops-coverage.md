# TP Playbook runtime and operations documentation coverage

Audit: 2026-11-02. This is a point-in-time assessment, not a completeness or
security certification. The TP Playbook checkout uses Compose files, Gunicorn
in `compose.deploy.yaml`, WhiteNoise in `backend/pyproject.toml`, mkcert in
`docs/setup.md`, GNU Make targets, and OpenSSL `pkeyutl` in CLI signing scripts.
The WhiteNoise entry is an example configuration; deployment integration must
add it to the active deployment configuration and sync it before use.
Deployed Docker, Compose, mkcert, Make, and OpenSSL versions are unknown.
Gunicorn is locked to 26.2.0 and WhiteNoise to 6.12.0. Caddy, PostgreSQL and S3
are assessed separately.

| Technology | Official source and version | Tenant and limitation |
| --- | --- | --- |
| Docker and Compose | [Docker manuals](https://docs.docker.com/manuals/), [Compose manual](https://docs.docker.com/compose/), [Compose file reference](https://docs.docker.com/reference/compose-file/) and [CLI reference](https://docs.docker.com/reference/cli/docker/compose/); current, deployed version unknown | Existing `docker`: 1,422 indexed documents; version and freshness unknown. Compose service reference and CLI search results were found. Complete coverage of manuals, APIs and historical versions is unverified; use official pages for gaps. |
| Gunicorn | [Gunicorn documentation](https://gunicorn.org/), including deployment and settings; source version unknown | Existing `gunicorn`: 34 documents, freshness unknown. No evidence that the indexed version matches 26.2.0; consult version-appropriate upstream documentation. |
| WhiteNoise | [Stable documentation](https://whitenoise.readthedocs.io/en/stable/) displayed 6.12.0 at audit, matching the lock; `stable` can move | `whitenoise` configuration uses stable pages and crawler discovery; see the retrieval evidence below. Other releases and pages not reachable from the entry are excluded; consult upstream when a different release is needed. |
| mkcert | [Official repository and README](https://github.com/FiloSottile/mkcert); moving `master`, installed version unknown | No reliable tenant established. A Git sparse checkout of `README.md` failed because the synchronizer accepts directories; an unconstrained website crawl expanded into unrelated GitHub pages and was stopped. Use the official README and release tags. |
| OpenID Connect | [Foundation specification index](https://openid.net/developers/specs/) and [Connect working group](https://openid.net/wg/connect/), including Core, Discovery and logout specifications | No exact protocol tenant verified. Repository does not specify a protocol revision; use the appropriate official specification and errata. |
| OpenAPI | [OpenAPI specifications and schemas](https://spec.openapis.org/oas/) provides versioned specifications, including 3.2.1 | No exact specification tenant verified. Determine the generated contract version before selecting the corresponding specification. |
| HTTPS and TLS | [HTTP Semantics RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html), [TLS 1.3 RFC 8446](https://www.rfc-editor.org/rfc/rfc8446.html), and [TLS deployment recommendations RFC 9325](https://www.rfc-editor.org/rfc/rfc9325.html) | No comprehensive standards tenant verified; negotiated TLS version and deployment settings are unknown. Use the original RFCs and their recorded updates and errata. |
| Make | [GNU Make manual](https://www.gnu.org/software/make/manual/) | No exact tenant verified; Make implementation/version unknown. Use the manual appropriate to the installed implementation. |
| OpenSSL | [OpenSSL documentation](https://docs.openssl.org/), including [pkeyutl](https://docs.openssl.org/master/man1/openssl-pkeyutl/) | No exact tenant verified; installed version unknown. Select the matching OpenSSL release in upstream documentation before using signing commands. |

## Representative retrieval

The installed service was queried with `docsearch search` and `docsearch fetch`
on 2026-11-02. These are sampled pages, not a completeness test. All three fetched
responses contained the official URL, a page fetch timestamp, and truncation
metadata. Docker and Gunicorn reported unknown freshness; the WhiteNoise index
reported document fetch timestamps as freshness evidence.

| Query | Observed source and content | Assessment |
| --- | --- | --- |
| `docker`: `compose services depends_on healthcheck` | [Compose services](https://docs.docker.com/reference/compose-file/services/) ranked first and fetched; page fetch timestamp 2026-10-29 | Relevant service reference; current version relationship unknown. |
| `gunicorn`: `worker settings bind deployment` | [Settings](https://gunicorn.org/reference/settings/) ranked second and fetched; page fetch timestamp 2026-10-29 | Relevant settings reference; source release relationship unknown. |
| `whitenoise`: `Django compressed static files middleware` | [Django guide](https://whitenoise.readthedocs.io/en/stable/django.html) ranked first and fetched with title 6.12.0, timestamp 2026-11-02 and truncation metadata | Relevant guide and matching displayed release at audit; the moving `stable` URL is not a permanent version pin. |

In the isolated sync, the stable sitemap exposed one landing URL and the
crawler discovered five additional URLs. All six URLs had successful metadata,
with zero pending, failed, or queued URLs at the end of the processing cycle.
The persisted index contained six documents, including both `/` and
`/index.html` aliases. The duplicate `_sources/` text copies were excluded;
other versions and pages outside the stable prefix were not crawled. The index
was exported after indexing. This result does not prove upstream completeness.
