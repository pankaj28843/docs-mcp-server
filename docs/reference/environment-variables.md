# Reference: Environment Variables

**Audience**: Operators deploying docs-mcp-server.  
**Prerequisites**: Basic Docker and shell environment knowledge.

Environment variables configure server behavior at runtime. Most settings should be configured in `deployment.json`, but these variables can override or supplement the configuration.

---

## Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEPLOYMENT_CONFIG` | `deployment.json` | Path to deployment configuration file |
| `MCP_HOST` | `0.0.0.0` | Server bind address |
| `MCP_PORT` | `42042` | Server port |
| `LOG_LEVEL` | `info` | Logging level: `debug`, `info`, `warning`, `error` |
| `OPERATION_MODE` | `online` | `online` (sync enabled) or `offline` (read-only) |

---

## Sync & Crawl Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_CRAWLER` | `true` | Enable web crawling for online tenants |
| `HTTP_TIMEOUT` | `120` | HTTP request timeout in seconds |
| `MAX_CRAWL_PAGES` | `10000` | Maximum pages to crawl per tenant |
| `CRAWLER_PLAYWRIGHT_FIRST` | `true` | Use Playwright for JavaScript-rendered pages |

---

## Search Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARCH_TIMEOUT` | `30` | Search operation timeout in seconds |
| `SEARCH_INCLUDE_STATS` | `true` | Include statistics in search responses |
| `DEFAULT_FETCH_MODE` | `surrounding` | Default fetch mode: `full` or `surrounding` |
| `DEFAULT_FETCH_SURROUNDING_CHARS` | `1000` | Characters around match in surrounding mode |

---

## Git Authentication

For private git repositories, set authentication tokens via environment variables:

| Variable | Description |
|----------|-------------|
| `GH_TOKEN` | GitHub personal access token |
| `GITLAB_TOKEN` | GitLab access token |

Reference in `deployment.json`:
```json
{
  "source_type": "git",
  "codename": "private-docs",
  "git_repo_url": "https://github.com/org/private-repo.git",
  "git_auth_token_env": "GH_TOKEN"
}
```

---

## Docker Deployment

When running in Docker, pass environment variables with `-e`:

```bash
docker run -d \
  -p 42042:42042 \
  -e LOG_LEVEL=debug \
  -e OPERATION_MODE=online \
  -v "$PWD/deployment.json:/home/mcp/app/deployment.json:ro" \
  -v "$PWD/mcp-data:/home/mcp/app/mcp-data" \
  ghcr.io/pankaj28843/docs-mcp-server:v0.0.1
```

Or use an environment file:

```bash
# .env file
LOG_LEVEL=debug
OPERATION_MODE=online
GH_TOKEN=ghp_xxxxx

docker run --env-file .env ...
```

---

## Precedence

Configuration is resolved in this order (later overrides earlier):

1. **Defaults** (hardcoded in code)
2. **deployment.json** (infrastructure section)
3. **Environment variables** (runtime override)

Example: If `deployment.json` sets `"log_level": "info"` but you run with `LOG_LEVEL=debug`, debug logging is used.

---

## Debugging

Check current configuration:

```bash
# View effective settings
docker exec docs-mcp-server env | grep -E "MCP|LOG|OPERATION"

# Check health with tenant count
curl -s http://localhost:42042/health | jq '{status, tenant_count}'
```

---

## Related

- Reference: [deployment.json Schema](deployment-json-schema.md) — Full configuration file reference
- How-To: [Run GHCR Image](../how-to/deploy-docker.md) — Docker deployment
- Reference: [CLI Commands](cli-commands.md) — Command-line tools

