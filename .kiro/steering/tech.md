# Technology Stack - docs-mcp-server

## Core Framework
- **Python 3.10+**: Primary language with modern type hints
- **FastMCP**: Model Context Protocol server framework
- **FastAPI**: HTTP API endpoints and health checks
- **Pydantic**: Data validation and settings management

## Search & Indexing
- **BM25 Algorithm**: Full-text search with IDF floor
- **Ripgrep**: High-performance text search
- **SQLite**: Optional storage backend for segments
- **JSON**: Default segment storage format

## Documentation Processing
- **Article Extractor**: Web content extraction
- **Playwright**: Browser automation for dynamic content
- **BeautifulSoup**: HTML parsing and cleaning
- **Markdown**: Primary documentation format

## Development Tools
- **uv**: Python package manager and task runner
- **pytest**: Testing framework with coverage
- **ruff**: Code formatting and linting
- **mkdocs**: Documentation generation

## Infrastructure
- **Docker**: Containerized deployment
- **GitHub Actions**: CI/CD workflows
- **Cron**: Scheduled sync operations
- **Git**: Repository synchronization

## Architectural Patterns
- **Domain-Driven Design**: Following Cosmic Python patterns
- **Repository Pattern**: Data access abstraction
- **Unit of Work**: Transaction management
- **Dependency Injection**: Via context objects

## Performance Optimizations
- **Connection Pooling**: SQLite and HTTP connections
- **Memory Mapping**: Large file handling
- **Binary Encoding**: Position data compression
- **Lazy Loading**: On-demand resource initialization

## Constraints
- **No Vector Embeddings**: BM25 only for search
- **No Backward Compatibility**: Active development project
- **Minimal Dependencies**: Prefer standard library
- **Offline-First**: Local operation capability
