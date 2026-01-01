# How-To: Deploy to Docker

**Goal**: Run docs-mcp-server in Docker using either the published GHCR image or a local build.  
**Prerequisites**: Docker installed, `deployment.json` present on the host.  
**Time**: ~5 minutes


---

## Steps

1. **Pull the published image**

   ```bash
   docker pull ghcr.io/pankaj28843/docs-mcp-server:latest
   ```

   The `:latest` tag tracks the `main` branch. Use a specific version tag (e.g., `:v0.0.1`) if you need pinned releases.

2. **Run the container with your config and data**

   Mount your configuration and data directories:

   ```bash
   docker run -d --name docs-mcp-ghcr \
     -p 42043:42042 \
     -v "$PWD/deployment.json:/home/mcp/app/deployment.json:ro" \
     -v "$PWD/mcp-data:/home/mcp/app/mcp-data" \
     ghcr.io/pankaj28843/docs-mcp-server:latest
   ```

   !!! info "Mount Points"
       - Maps host port `42043` to container port `42042` (change if `42042` is free)
       - Mounts `deployment.json` read-only at `/home/mcp/app/deployment.json`
       - Mounts `mcp-data/` for persistent storage of crawled docs and indexes

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

!!! warning "Port already allocated"
    Map to a different host port (example above uses `42043`). List current bindings with `docker ps --format "{{.Names}} {{.Ports}}"`.

!!! warning "Missing config"
    Ensure `deployment.json` exists on the host and is mounted read-only at `/home/mcp/app/deployment.json` (or set `DEPLOYMENT_CONFIG` to another path inside the container).

!!! warning "Data not persisting"
    Confirm the `mcp-data` volume is mounted to `/home/mcp/app/mcp-data` so crawls and indexes survive restarts.

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) — full setup walkthrough
- How-To: [Trigger Syncs](trigger-syncs.md) — force refresh documentation
- Reference: [CLI Commands](../reference/cli-commands.md) — full script options
