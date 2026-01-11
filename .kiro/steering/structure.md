# Project Structure - docs-mcp-server

## Directory Organization

```
docs-mcp-server/
├── src/docs_mcp_server/          # Main application code
│   ├── adapters/                 # External system interfaces
│   ├── domain/                   # Business logic and models
│   ├── search/                   # BM25 search implementation
│   ├── service_layer/            # Application services
│   ├── services/                 # Infrastructure services
│   ├── utils/                    # Shared utilities
│   └── runtime/                  # Application runtime
├── tests/                        # Test suite
│   ├── unit/                     # Unit tests (fast)
│   └── integration/              # Integration tests
├── docs/                         # MkDocs documentation
├── .github/                      # GitHub workflows and instructions
└── .kiro/steering/               # Kiro steering files
```

## Naming Conventions

### Files and Directories
- **Snake case**: `sync_scheduler.py`, `search_service.py`
- **Descriptive names**: Avoid abbreviations like `mgr`, `proc`, `util`
- **Domain-specific**: `tenant.py`, `indexer.py`, `repository.py`

### Python Code
- **Classes**: PascalCase (`TenantServices`, `SearchRepository`)
- **Functions/Variables**: snake_case (`build_segment`, `doc_count`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_SEGMENTS`, `DEFAULT_TIMEOUT`)
- **Private members**: Leading underscore (`_pool`, `_create_connection`)

### Test Files
- **Pattern**: `test_{module_name}.py`
- **Classes**: `Test{FeatureName}` (`TestSqliteStorage`)
- **Methods**: `test_{behavior}` (`test_saves_segment_with_metadata`)

## Import Patterns

### Standard Order
1. Standard library imports
2. Third-party imports  
3. Local application imports

### Grouping Rules
```python
# Standard library
from pathlib import Path
import sqlite3

# Third-party
import pytest
from pydantic import BaseModel

# Local imports
from docs_mcp_server.domain.model import Document
from docs_mcp_server.search.storage import SegmentWriter
```

### Relative Imports
- **Avoid**: Use absolute imports from package root
- **Exception**: Within same module directory for utilities

## Architectural Decisions

### Layer Dependencies
- **Domain** → No external dependencies
- **Service Layer** → Domain only
- **Adapters** → Domain + Service Layer
- **Infrastructure** → All layers

### Context Objects
- **StorageContext**: File system and database access
- **IndexRuntime**: Search index management  
- **SyncRuntime**: Documentation synchronization
- **TenantServices**: Composed tenant behavior

### Error Handling
- **Let exceptions bubble**: No silent error swallowing
- **Domain exceptions**: Custom exceptions for business rules
- **Infrastructure errors**: Wrap and re-raise with context

## File Organization Principles

### Single Responsibility
- One class per file (exceptions for small related classes)
- One domain concept per module
- Clear separation of concerns

### Information Hiding
- Private methods start with underscore
- Internal modules in subdirectories
- Public API in `__init__.py` files

### Cohesion Rules
- Related functionality grouped together
- Minimize cross-module dependencies
- Keep related tests near implementation
