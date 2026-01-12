# Search Functionality

The MCP search system provides powerful full-text search capabilities across all your documentation sources.

## Search Features

### Full-Text Search

Search across all document content with relevance scoring:

```python
results = client.search("configuration settings")
```

### Filtered Search

Search within specific tenants or document types:

```python
results = client.search("API", tenant="fastapi-docs")
```

### Advanced Queries

Use boolean operators and field-specific searches:

```python
results = client.search("title:configuration AND content:yaml")
```

## Search Configuration

Configure search behavior in your deployment:

```yaml
search_timeout: 30
search_include_stats: true
default_fetch_mode: "surrounding"
```

## Performance Tips

- Use specific terms rather than generic words
- Combine multiple search terms for better results
- Use tenant filtering for faster searches
- Enable search statistics for debugging
