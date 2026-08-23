# Share documentation data with `docsearchd`

Use the Go daemon when several machines need the same documentation indexes.
The daemon reads one canonical `mcp-data` directory on the host and exposes the
existing list, discovery, search, and fetch operations over a versioned HTTP
API. Consumer machines install only the small `docsearch` binary and config.

## Configure the data host

Create `~/.config/docs-search/config.json`:

```json
{
  "data_dir": "/srv/docs-mcp-server/mcp-data",
  "deployment_config": "/srv/docs-mcp-server/deployment.json",
  "server_url": "http://docs-host.example:42142",
  "mode": "auto",
  "listen": "0.0.0.0:42142",
  "cache_max_bytes": 67108864,
  "cache_ttl_seconds": 30,
  "search_max_concurrent": 16
}
```

`cache_max_bytes` may be zero to disable caching and must not exceed 524288000
bytes (500 MiB). The cache contains encoded responses only; it never preloads
or copies the corpus.

Install both binaries and the persistent user service:

```bash
make daemon-install
make daemon-status
curl --fail http://127.0.0.1:42142/healthz
```

The installed service has graceful shutdown, bounded concurrent search,
restart-on-failure, and user-level systemd hardening. User lingering must be
enabled if the service must remain active after logout.

!!! warning

    The API currently has no authentication or TLS. Bind it only to a trusted
    private network interface and restrict port `42142` at the host/network
    firewall. Use a TLS/authenticating reverse proxy before exposing it beyond
    that boundary.

## Configure a consumer machine

Install the `docsearch` binary without copying `mcp-data`, then create the same
config path with remote mode:

```json
{
  "server_url": "http://docs-host.example:42142",
  "mode": "remote"
}
```

Verify representative operations:

```bash
docsearch list --json
docsearch search android-developers "foreground service" --json
docsearch fetch android-developers "URL_FROM_SEARCH" --max-chars 12000 --json
```

`remote` mode fails clearly when the daemon is unavailable. `local` always
uses the configured data directory. `auto` tries a configured healthy daemon
first and otherwise uses local data, which is useful on the data host.

Flags override shared configuration for one invocation:

```bash
docsearch --config /path/config.json --server http://host:42142 --mode remote list
```

## Keep the daemon aligned with deployments

The normal deployment command conservatively refreshes the daemon only when a
shared config or existing user unit is present:

```bash
uv run python deploy_multi_tenant.py deployment.json --mode online --docsearch-daemon auto
```

Use `--docsearch-daemon require` when daemon installation is part of the
deployment contract, or `skip` when the host must remain untouched.

The daemon is read-only. Crawling, indexing, repair, and export remain owned by
the normal server and worker lifecycle.
