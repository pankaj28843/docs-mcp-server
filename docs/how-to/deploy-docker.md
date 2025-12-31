# How-To: Run the GHCR Image

**Goal**: Launch the published docs-mcp-server container from GHCR and verify it is healthy.  
**Audience**: Engineers who already have a `deployment.json` and want to run the prebuilt image (no local build).  
**Prerequisites**: Docker installed, `deployment.json` present on the host, host port available for mapping.  
**Time**: ~5 minutes.  
**What you’ll get**: A running MCP server mapped to a host port, ready for searches and syncs.

<!-- Verified: docs/_reality-log/2025-12-31-ghcr-run.md -->

---

## Steps

1. **Pull the published image**

  ```bash
  docker pull ghcr.io/pankaj28843/docs-mcp-server:v0.0.1
  ```

  Uses the tag we just released; swap to `latest` if you prefer tracking main.

2. **Run the container with your config and data**

  The container reads `DEPLOYMENT_CONFIG` (default: `/home/mcp/app/deployment.json`) and stores tenant data under `/home/mcp/app/mcp-data`. Mount both so the server uses your configuration and persists data on the host.

  ```bash
  docker run -d --name docs-mcp-ghcr \
    -p 42043:42042 \
    -v "$PWD/deployment.json:/home/mcp/app/deployment.json:ro" \
    -v "$PWD/mcp-data:/home/mcp/app/mcp-data" \
    ghcr.io/pankaj28843/docs-mcp-server:v0.0.1
  ```

  - This example maps host port `42043` to container port `42042` to avoid a port already in use. If `42042` is free on your host, change `-p 42043:42042` to `-p 42042:42042`.
  - The server listens on the port defined in `deployment.json` (default `42042`).

3. **Check health**

  ```bash
  curl -s http://localhost:42043/health | head -n 5
  ```

  Expected: status `healthy` and a tenant count matching your config.

4. **Stop and remove when you’re done**

  ```bash
  docker stop docs-mcp-ghcr && docker rm docs-mcp-ghcr
  ```

---

## Troubleshooting

- **Port already allocated**: Map to a different host port (example above uses `42043`). List current bindings with `docker ps --format "{{.Names}} {{.Ports}}"`.
- **Missing config**: Ensure `deployment.json` exists on the host and is mounted read-only at `/home/mcp/app/deployment.json` (or set `DEPLOYMENT_CONFIG` to another path inside the container).
- **Data not persisting**: Confirm the `mcp-data` volume is mounted to `/home/mcp/app/mcp-data` so crawls and indexes survive restarts.

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) — full setup walkthrough
- How-To: [Trigger Syncs](trigger-syncs.md) — force refresh documentation
- Reference: [CLI Commands](../reference/cli-commands.md) — full script options
