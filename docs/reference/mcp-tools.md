# Reference: MCP Tools API

docs-mcp-server exposes 5 MCP tools through a single HTTP endpoint. AI assistants (VS Code Copilot, Claude Desktop) call these tools to discover, search, and fetch documentation.

**Tools summary**:

| Tool | Purpose |
|------|---------|
| `list_tenants` | List all available documentation sources |
| `find_tenant` | Find tenants by topic (fuzzy search) |
| `describe_tenant` | Get tenant details and example queries |
| `root_search` | Search documentation within a tenant |
| `root_fetch` | Fetch full page content by URL |

---

## Endpoint

```
http://127.0.0.1:42042/mcp
```

The server uses the MCP HTTP transport. Configure your MCP client to connect to this URL.

---

## Discovery Tools

### `list_tenants`

List all available documentation sources.

**Parameters**: None

**Returns**:
```json
{
  "count": 10,
  "tenants": [
    {
      "codename": "django",
      "description": "Django - Official Django docs covering models, views, ..."
    },
    {
      "codename": "drf", 
      "description": "Django REST Framework - Official Django REST Framework docs"
    }
  ]
}
```

**Usage**: Call to browse all available tenants. Prefer `find_tenant` when you know the topic.

---

### `find_tenant`

Find documentation tenants matching a topic using fuzzy search.

**Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | Yes | Topic to find (e.g., `"django"`, `"react"`, `"aws"`) |

**Returns**:
```json
{
  "query": "django",
  "count": 2,
  "tenants": [
    {"codename": "django", "description": "Django - Official Django docs"},
    {"codename": "drf", "description": "Django REST Framework - REST framework for Django"}
  ]
}
```

**Usage**: Recommended first step. Saves context window by returning only matching tenants (not all 100+). Supports typo tolerance (e.g., `"djano"` finds `"django"`).

**Workflow**:
1. `find_tenant("topic")` → get matching tenant codenames
2. `root_search(codename, "query")` → search within that tenant
3. `root_fetch(codename, url)` → read full page content

---

### `describe_tenant`

Get detailed information about a specific tenant.

**Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `codename` | string | Yes | Tenant codename (e.g., `"django"`) |

**Returns**:
```json
{
  "codename": "django",
  "display_name": "Django",
  "description": "Official Django docs covering models, views, forms (docs.djangoproject.com)",
  "source_type": "online",
  "test_queries": ["models", "views", "forms", "How to create a model"],
  "url_prefixes": ["https://docs.djangoproject.com/en/5.2/"]
}
```

**Usage**: Call before searching to understand tenant capabilities and get example queries.

---

## Content Tools

### `root_search`

Search documentation within a specific tenant.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `tenant_codename` | string | Yes | — | Tenant to search |
| `query` | string | Yes | — | Search query |
| `size` | integer | No | `10` | Max results (1-100) |
| `word_match` | boolean | No | `false` | Exact word matching |

> **Note**: Search diagnostics (stats, match trace) are controlled globally via `infrastructure.search_include_stats` in `deployment.json`. Clients cannot toggle diagnostics per request.

**Returns**:
```json
{
  "query": "serializer validation",
  "results": [
    {
      "url": "https://www.django-rest-framework.org/api-guide/serializers/",
      "title": "Serializers - Django REST Framework",
      "score": 12.45,
      "snippet": "Serializers allow complex data such as querysets and model instances to be converted to native Python datatypes..."
    }
  ],
  "stats": {
    "total_docs": 127,
    "query_time_ms": 15.2
  }
}
```

**Example call from AI assistant**:
```
mcp_techdocs_root_search(tenant_codename="drf", query="serializer validation", size=5)
```

---

### `root_fetch`

Fetch the full content of a documentation page.

**Parameters**:

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `tenant_codename` | string | Yes | Tenant containing the document |
| `uri` | string | Yes | Document URL (from search results) |

**Returns**:
```json
{
  "url": "https://www.django-rest-framework.org/api-guide/serializers/",
  "title": "Serializers - Django REST Framework",
  "content": "# Serializers\n\nSerializers allow complex data...",
  "error": null
}
```

**Example workflow**:
1. Search: `root_search(tenant_codename="drf", query="validation")`
2. Get top result URL from response
3. Fetch: `root_fetch(tenant_codename="drf", uri="https://...")`

---

## Error Handling

All tools return an `error` field when something goes wrong:

```json
{
  "error": "Tenant 'unknown' not found. Available: django, drf, fastapi",
  "results": []
}
```

**Common errors**:

| Error | Cause | Solution |
|-------|-------|----------|
| `Tenant 'X' not found` | Invalid codename | Call `list_tenants` or `find_tenant` to see available tenants |
| `Search timeout` | Query too slow | Simplify query or reduce `size` |

---

## VS Code Configuration

Add to `~/.config/Code/User/mcp.json` (Linux) or equivalent:

```json
{
  "servers": {
    "TechDocs": {
      "type": "http",
      "url": "http://127.0.0.1:42042/mcp"
    }
  }
}
```

After restart, VS Code Copilot can use these tools to search documentation.

---

## Claude Desktop Configuration

Add to Claude Desktop's MCP configuration:

```json
{
  "mcpServers": {
    "TechDocs": {
      "type": "http",
      "url": "http://127.0.0.1:42042/mcp"
    }
  }
}
```

---

## HTTP Endpoints (Non-MCP)

For operational tasks, direct HTTP endpoints are available:

```bash
# Health check
curl http://localhost:42042/health

# Sync status
curl http://localhost:42042/drf/sync/status

# Trigger sync
curl -X POST http://localhost:42042/drf/sync/trigger
```

Search and fetch are MCP-only tools. Use the MCP endpoint (`/mcp`) with an MCP client.

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) — Setup and VS Code integration
- Reference: [CLI Commands](cli-commands.md) — Command-line tools
- Explanation: [Architecture](../explanations/architecture.md) — System design

