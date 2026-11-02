# TP Playbook Go and telemetry documentation coverage

The example deployment defines eight small tenants for the versions and APIs used by TP Playbook. These entries were synced and indexed in an isolated local deployment on 2026-11-02. Add the entries from `deployment.example.json` to a deployment that needs this coverage; each uses its own `mcp-data` directory.

| Tenant | Source and version | Indexed documents | Representative search and fetch |
| --- | --- | ---: | --- |
| `tp-go-keyring-api` | [go-keyring README at v0.4.0](https://github.com/go-keyring/keyring/blob/v0.4.0/README.md) | 1 | `ErrNotFound` → versioned README, with `Set`, `Get`, `Delete`, and `Available` |
| `tp-google-uuid-api` | [google/uuid API at v1.6.0](https://pkg.go.dev/github.com/google/uuid@v1.6.0) | 1 | `NewRandom Parse` → package API |
| `tp-go-toolchain-api` | [testing](https://pkg.go.dev/testing@go1.27.1), [vet](https://pkg.go.dev/cmd/vet@go1.27.1), and [go](https://pkg.go.dev/cmd/go@go1.27.1) at Go 1.27.1 | 3 | `go vet` → vet command reference |
| `tp-go-127` | [Go 1.27 release notes](https://go.dev/doc/go1.27) | 1 | `Go 1.27` → release notes |
| `tp-otel-go-trace-sdk-api` | [OpenTelemetry Go trace SDK at v1.47.0](https://pkg.go.dev/go.opentelemetry.io/otel/sdk/trace@v1.47.0) | 1 | `NewTracerProvider WithBatcher` → versioned trace SDK API |
| `tp-otel-go-guide` | [OpenTelemetry Go language guide source](https://github.com/open-telemetry/opentelemetry.io/tree/main/content/en/docs/languages/go), `main` at sync | 10 | `manual instrumentation tracer provider` → `instrumentation.md` |
| `tp-otel-python-guide` | [OpenTelemetry Python language guide source](https://github.com/open-telemetry/opentelemetry.io/tree/main/content/en/docs/languages/python), `main` at sync | 13 | `tracer exporter` → `instrumentation.md` |
| `tp-otel-python-sdk` | [OpenTelemetry Python SDK API](https://opentelemetry-python.readthedocs.io/en/latest/sdk/), `latest` | 16 | `BatchSpanProcessor TracerProvider` → SDK trace exporter API |

All eight representative searches returned results, and fetching each top result returned content from the named source. The local index contains **46 documents**. The private export completed for all eight tenants; its archives and manifest are in `tmp/export/` in the verification worktree and are not committed.

## Version boundaries and remaining gaps

TP Playbook declares Go **1.27.1**, Cobra **v1.10.2**, go-keyring **v0.4.0**, google/uuid **v1.6.0**, and OpenTelemetry Go **v1.47.0** in `cli/go.mod`. Its backend declares OpenTelemetry Python `>=1.35,<2`, with **1.45.1** resolved in `backend/uv.lock`. The Python SDK API tenant follows Read the Docs `latest`, so check the installed 1.45.1 API before relying on a signature. The language guide tenants follow the upstream website `main` branch and are guidance, not SDK release snapshots. Their synced revision was `9552787a7c5cdcdc5a5fb7f982687c9cf82e05a7`.

Existing tenants cover [Cobra usage](https://cobra.dev/docs/), [Go race detector](https://go.dev/doc/articles/race_detector), and the [OpenTelemetry trace specification](https://opentelemetry.io/docs/specs/otel/trace/sdk/); live search and fetch were verified for each. `golang-cobra` is usage guidance rather than a pinned v1.10.2 package API. `golang` covers `go.dev/doc/` but its indexed race detector article was last fetched on 2026-04-07. `opentelemetry-specs` describes the cross-language contract rather than language SDK calls. The new trace SDK tenant covers `NewTracerProvider`, span processors, and trace SDK options at v1.47.0. For other exact Go signatures, use [OTel Go API](https://pkg.go.dev/go.opentelemetry.io/otel@v1.47.0) and [OTLP/HTTP exporter](https://pkg.go.dev/go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp@v1.47.0) directly. An exploratory broad package crawl queued hundreds of unrelated pages, so the added API tenant is restricted to the exact trace SDK page.

The versioned keyring page on `pkg.go.dev` displayed only “Documentation not displayed due to license restrictions.” Its upstream v0.4.0 README is the indexed source instead. The keyring README is a concise usage guide; inspect the tagged source for implementation detail. Native vault references remain direct links: [Windows Credential Manager](https://learn.microsoft.com/en-us/windows/win32/secauthn/credential-manager), [Apple Keychain Services](https://developer.apple.com/documentation/security/keychain-services), and [freedesktop Secret Service](https://specifications.freedesktop.org/secret-service/latest/). No platform API tenant was needed for this slice.

The Go and Python language guide tenants are Git sources, with `file://` index URLs. After the [imported local URL repair](https://github.com/pankaj28843/docs-mcp-server/pull/83), the Go guide archive was imported into a separate data directory. A freshly built `docsearch` resolved its `instrumentation.md` search URL to that directory and fetched 4,096 characters from the imported file. This proves the Go guide CLI import path; the Python guide archive was exported and fetched at the producer, but its imported path was not separately exercised. Online tenant URLs are public canonical URLs.

## Reproduce the checks

With the tenant entries in a private deployment, start the service, confirm each online tenant's `/sync/status` reports zero queue depth, pending URLs, and failures, then index and export:

```bash
uv run python trigger_all_indexing.py --config deployment.json --tenants tp-go-keyring-api tp-google-uuid-api tp-go-toolchain-api tp-go-127 tp-otel-go-trace-sdk-api tp-otel-go-guide tp-otel-python-guide tp-otel-python-sdk
uv run python sync_tenant_data.py export --tenants tp-go-keyring-api tp-google-uuid-api tp-go-toolchain-api tp-go-127 tp-otel-go-trace-sdk-api tp-otel-go-guide tp-otel-python-guide tp-otel-python-sdk
docsearch search tp-go-keyring-api ErrNotFound --json
docsearch fetch tp-go-keyring-api https://github.com/go-keyring/keyring/blob/v0.4.0/README.md --json
```

The OpenTelemetry website content is [CC BY 4.0](https://github.com/open-telemetry/opentelemetry.io/blob/main/LICENSE); its code examples have a separate [Apache 2.0 license](https://github.com/open-telemetry/opentelemetry.io/blob/main/LICENSE-CODE). The [Go toolchain](https://go.dev/LICENSE), [go-keyring](https://github.com/go-keyring/keyring/blob/v0.4.0/LICENSE), [google/uuid](https://github.com/google/uuid/blob/master/LICENSE), and [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE) publish their own licenses. The sample export is for local validation; observe each source's terms when distributing snapshots.
