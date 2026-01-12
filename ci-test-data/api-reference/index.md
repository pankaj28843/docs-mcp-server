# API Reference

Complete API reference for CI testing.

## Classes

### Client

Main client class for API interactions.

#### Methods

##### search(query: str) -> List[Result]

Search for documents matching the query.

**Parameters:**
- `query`: Search query string

**Returns:**
- List of search results

**Example:**
```python
results = client.search("MCP tools")
```

##### fetch(url: str) -> Document

Fetch a document by URL.

**Parameters:**
- `url`: Document URL or file path

**Returns:**
- Document object

##### browse(path: str, depth: int = 2) -> DirectoryTree

Browse directory structure.

**Parameters:**
- `path`: Directory path
- `depth`: Maximum depth to traverse

**Returns:**
- Directory tree structure

## Functions

### list_tenants() -> List[Tenant]

List all available tenants.

### describe_tenant(codename: str) -> TenantInfo

Get detailed tenant information.

This API reference tests all MCP tool functionality including list, describe, fetch, search, and browse operations.
