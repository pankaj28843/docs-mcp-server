# How-To: Enforce Boot-Time Index Audit

## 1. Run a manual fingerprint check

Use the audit CLI before shipping a release so you know every tenant already has a fresh segment. The CLI runs purely offline against `mcp-data/` and will exit with `2` if any tenant needs a rebuild.

```bash
uv run python -m docs_mcp_server.index_audit --tenants drf --tenant-timeout 30 --max-parallel 2
```

**Actual output from 2026-01-02T15:42:18+00:00**:
```
drf              status=ok      fingerprint=8a38f210e60f24a2cb9fe7a7fd7623eb34d2390425840546137e11b2f6f3e875 current=8a38f210e60f24a2cb9fe7a7fd7623eb34d2390425840546137e11b2f6f3e875 rebuilt=False duration=1.10s
Audit completed successfully
{"current_segment_id": "8a38f210e60f24a2cb9fe7a7fd7623eb34d2390425840546137e11b2f6f3e875", "documents_indexed": null, "duration_s": 1.0986139440210536, "error": null, "fingerprint": "8a38f210e60f24a2cb9fe7a7fd7623eb34d2390425840546137e11b2f6f3e875", "needs_rebuild": false, "rebuilt": false, "status": "ok", "tenant": "drf"}
```

Interpretation:
- `status=ok` means the manifest fingerprint already matches the live docs.
- When `needs_rebuild=true`, rerun with `--rebuild` to persist a fresh BM25 segment before deploying.

## 2. Rely on the boot-time audit

`create_app()` now launches the same CLI in a subprocess after every startup. The audit:
- Uses the deployment config on disk (or skips if you’re running single-tenant env mode).
- Honors `DOCS_BOOT_AUDIT_TIMEOUT` (default `300s * tenant_count`) and logs a warning if it times out.
- Can be skipped by setting `DOCS_SKIP_BOOT_AUDIT=1` for emergency rollbacks.

During deployment you’ll see log lines such as `Running boot-time index audit for 12 tenant(s) (timeout=3600s)` followed by per-tenant JSON summaries. Failures never block the HTTP server—they are logged so you can investigate while traffic continues to flow.

## Troubleshooting

| Symptom | Actual output | Fix |
|---------|---------------|-----|
| Wrong tenant codename | ```
Unknown tenant(s): does-not-exist
``` | Use `deployment.json`’s `codename` (see `docs/reference/cli-commands.md`) or drop `--tenants` to audit everyone. |
| Audit takes too long | (Appears as `Boot-time index audit timed out after XXXX s` in logs) | Increase `DOCS_BOOT_AUDIT_TIMEOUT` or run the CLI manually to narrow down the slow tenant. |
| Rebuild loop | `status=stale` even after `--rebuild` | Check that the docs directory is writable and that `mcp-data/<tenant>/__search_segments` isn’t mounted read-only; fix filesystem permissions, then rerun the CLI. |

## Related

- Reference: [CLI Commands](../reference/cli-commands.md) — includes full flag list for `index_audit`.
- Reference: [Environment Variables](../reference/environment-variables.md) — documents `DOCS_SKIP_BOOT_AUDIT` and `DOCS_BOOT_AUDIT_TIMEOUT`.
- How-To: [Run GHCR Image](deploy-docker.md) — covers deployment workflow that now triggers the audit automatically.
