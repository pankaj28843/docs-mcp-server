# MCP Tools API Reference

Complete reference for all available MCP tools.

## Core Tools

### list_tenants()

Lists all available documentation tenants.

**Returns:** List of tenant metadata

**Example:**
```python
tenants = client.list_tenants()
for tenant in tenants:
    print(f"{tenant.codename}: {tenant.display_name}")
```

### describe_tenant(codename: str)

Get detailed information about a specific tenant.

**Parameters:**
- `codename`: Tenant identifier

**Returns:** Tenant configuration and metadata

### root_search(tenant: str, query: str, **kwargs)

Search within a specific tenant.

**Parameters:**
- `tenant`: Target tenant codename
- `query`: Search query string
- `size`: Maximum results (default: 10)
- `word_match`: Enable whole word matching

**Returns:** Search results with scores and snippets

### root_fetch(tenant: str, uri: str, context: str)

Fetch document content by URI.

**Parameters:**
- `tenant`: Target tenant codename
- `uri`: Document URI (supports file:// and http://)
- `context`: Context mode ("full" or "surrounding")

**Returns:** Document content and metadata

### root_browse(tenant: str, path: str, depth: int)

Browse directory structure for filesystem tenants.

**Parameters:**
- `tenant`: Target tenant codename
- `path`: Directory path (empty for root)
- `depth`: Maximum traversal depth

**Returns:** Directory tree structure
