# Reference: Python API

## Package Structure

```
src/docs_mcp_server/
├── __init__.py              # Package exports
├── app.py                   # FastMCP application factory
├── config.py                # Pydantic settings (single-tenant mode)
├── deployment_config.py     # Multi-tenant deployment schema
├── registry.py              # Tenant registry and metadata
├── root_hub.py              # Root MCP server (proxies to tenants)
├── tenant.py                # Per-tenant FastMCP instance
├── search/                  # BM25 search engine
│   ├── bm25_engine.py       # Core BM25 scoring
│   ├── indexer.py           # Document indexing
│   ├── snippet.py           # Snippet extraction
│   ├── storage.py           # Segment persistence
│   └── schema.py            # Search result dataclasses
├── services/                # Business logic layer
│   ├── search_service.py    # Search orchestration
│   ├── cache_service.py     # Document caching
│   └── git_sync_scheduler_service.py  # Git sync scheduler
├── utils/                   # Utilities
│   ├── git_sync.py          # GitRepoSyncer for sparse checkout
│   ├── sync_scheduler.py    # Online tenant sync scheduler
│   └── models.py            # Shared Pydantic models
└── repository/              # Data access layer
    └── filesystem_unit_of_work.py  # Repository pattern implementation
```

---

## Core Modules

### `registry.py` - TenantRegistry

Manages tenant lifecycle and metadata.

```python
from docs_mcp_server.registry import TenantRegistry

registry = TenantRegistry()
registry.register(tenant_config)

# Get tenant application
tenant_app = registry.get_tenant("django")

# List all tenants
for meta in registry.list_tenants():
    print(meta.codename, meta.display_name)
```

**Key classes**:
- `TenantRegistry`: Central registry holding all tenants
- `TenantMetadata`: Dataclass with tenant info for MCP discovery

---

### `root_hub.py` - RootHub

Creates the root MCP server that proxies to tenants.

```python
from docs_mcp_server.root_hub import create_root_hub

mcp = create_root_hub(registry)
# mcp is a FastMCP instance with 5 MCP tools for tenant discovery and content access
```

**Registered tools**:
- `list_tenants()` → List all available documentation sources
- `find_tenant(query)` → Fuzzy search to find tenants by topic
- `describe_tenant(codename)` → Get tenant details and example queries
- `root_search(tenant_codename, query, ...)` → Search documentation within a tenant
- `root_fetch(tenant_codename, uri)` → Fetch full page content by URL

---

### `tenant.py` - TenantApp

Per-tenant FastMCP instance with search/fetch logic.

```python
from docs_mcp_server.tenant import TenantApp

tenant = TenantApp(tenant_config)
results = await tenant.search(query="serializer", size=10, word_match=False)
doc = await tenant.fetch(uri="https://...")
```

**Initialization**:
- Infrastructure is embedded in `TenantConfig._infrastructure` (set by `DeploymentConfig` validator)
- No separate `SharedInfraConfig` or `Settings` objects needed
- Single parameter: `tenant_config: TenantConfig`

**Methods**:
- `search(query, size, word_match)` → SearchDocsResponse
- `fetch(uri)` → FetchDocResponse

---

### `search/bm25_engine.py` - BM25Engine

Core BM25 search implementation.

```python
from docs_mcp_server.search.bm25_engine import BM25Engine

engine = BM25Engine(documents, k1=1.2, b=0.75)
results = engine.search("django forms", size=10)
```

**Key features**:
- IDF floor prevents negative scores
- Length normalization via `b` parameter
- Term saturation via `k1` parameter

---

### `utils/git_sync.py` - GitRepoSyncer

Handles git repository synchronization via sparse checkout.

```python
from docs_mcp_server.utils.git_sync import GitRepoSyncer

syncer = GitRepoSyncer(
    repo_url="https://github.com/mkdocs/mkdocs.git",
    branch="master",
    subpaths=["docs"],
    target_dir="/path/to/output"
)
result = await syncer.sync()
print(f"Synced {result.file_count} files, commit {result.commit_hash}")
```

---

## Repository Pattern

Following Cosmic Python patterns, data access uses the Repository pattern.

### `FilesystemUnitOfWork`

```python
from docs_mcp_server.repository.filesystem_unit_of_work import FilesystemUnitOfWork

async with FilesystemUnitOfWork(root_dir) as uow:
    doc = await uow.documents.get(url)
    await uow.documents.add(doc)
    await uow.commit()
```

---

## Service Layer

Business logic is encapsulated in services.

### `SearchService`

```python
from docs_mcp_server.services.search_service import SearchService

service = SearchService(index_path, config)
results = await service.search(query, size=10)
```

### `CacheService`

```python
from docs_mcp_server.services.cache_service import CacheService

cache = CacheService(root_dir)
content = await cache.get(url)
await cache.set(url, content, metadata)
```

---

## Data Models

### `utils/models.py`

Pydantic models for API responses:

```python
from docs_mcp_server.utils.models import (
    SearchDocsResponse,
    SearchResult,
    FetchDocResponse,
)
```

**SearchDocsResponse**:
```python
@dataclass
class SearchDocsResponse:
    query: str
    results: list[SearchResult]
    stats: dict | None = None
    error: str | None = None
```

**SearchResult**:
```python
@dataclass
class SearchResult:
    url: str
    title: str
    score: float
    snippet: str
```

---

## Testing

Unit tests use `FakeUnitOfWork` for isolation:

```python
from tests.fakes import FakeUnitOfWork

@pytest.fixture
def uow():
    return FakeUnitOfWork()

async def test_search_returns_results(uow):
    # Test with fake data, no filesystem access
    ...
```

Run tests:
```bash
uv run pytest -m unit
```

---

## Related

- Explanation: [Architecture](../explanations/architecture.md) — System design overview
- Explanation: [Cosmic Python Patterns](../explanations/cosmic-python.md) — Repository/UoW patterns
- Reference: [MCP Tools API](mcp-tools.md) — Public API
