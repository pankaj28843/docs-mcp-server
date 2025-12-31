# Reference: MCP Tools API

**Audience**: Developers integrating with docs-mcp-server via MCP protocol.  
**Prerequisites**: Understanding of Model Context Protocol (MCP) basics.

docs-mcp-server exposes MCP tools through a single HTTP endpoint. AI assistants (VS Code Copilot, Claude Desktop) call these tools to search and fetch documentation.

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
      "description": "Django Docs - Official Django documentation"
    },
    {
      "codename": "drf", 
      "description": "Django REST Framework Docs - REST framework for Django"
    }
  ]
}
```

**Usage**: Call this first to discover what documentation is available.

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
  "display_name": "Django Docs",
  "description": "Official Django documentation",
  "source_type": "online",
  "supports_browse": false,
  "url_prefixes": ["https://docs.djangoproject.com/en/5.2/"],
  "test_queries": {
    "natural": ["How to create a Django model with foreign key"],
    "phrases": ["model", "form"],
    "words": ["django", "model", "view"]
  }
}
```

**Usage**: Call before searching to understand tenant capabilities and get query hints.

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
| `include_stats` | boolean | No | `false` | Include search statistics |

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

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `tenant_codename` | string | Yes | — | Tenant containing the document |
| `uri` | string | Yes | — | Document URL |
| `context` | string | No | `null` | `"full"` or `"surrounding"` |

**Context modes**:
- `"full"`: Return entire document content
- `"surrounding"`: Return only sections relevant to previous search

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

### `root_browse`

Browse directory structure of filesystem or git-based tenants.

**Parameters**:

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `tenant_codename` | string | Yes | — | Tenant to browse |
| `path` | string | No | `""` | Relative path (empty for root) |
| `depth` | integer | No | `2` | Levels to traverse (1-5) |

**Note**: Only works for tenants with `supports_browse: true` (filesystem or git sources).

**Returns**:
```json
{
  "root_path": "/",
  "depth": 2,
  "nodes": [
    {
      "name": "getting-started.md",
      "type": "file",
      "title": "Getting Started",
      "url": "https://..."
    },
    {
      "name": "api/",
      "type": "directory",
      "children": [...]
    }
  ],
  "error": null
}
```

**Error for non-browsable tenants**:
```json
{
  "error": "Tenant 'django' does not support browse"
}
```

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
| `Tenant 'X' not found` | Invalid codename | Call `list_tenants` to see available tenants |
| `Tenant 'X' does not support browse` | Online tenant | Use `root_search` instead |
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

## HTTP REST Endpoints (Alternative)

For non-MCP clients, direct HTTP endpoints are available:

```bash
# Health check
curl http://localhost:42042/health

# Search
curl "http://localhost:42042/drf/search?query=serializer"

# Fetch
curl -X POST "http://localhost:42042/drf/fetch" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.django-rest-framework.org/api-guide/serializers/"}'

# Sync status
curl "http://localhost:42042/drf/sync/status"

# Trigger sync
curl -X POST "http://localhost:42042/drf/sync/trigger"
```

---

## Related

- Tutorial: [Getting Started](../tutorials/getting-started.md) — Setup and VS Code integration
- Reference: [CLI Commands](cli-commands.md) — Command-line tools
- Explanation: [Architecture](../explanations/architecture.md) — System design

