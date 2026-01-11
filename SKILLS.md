# SKILLS.md

## Core Development Skills

### Validation & Quality Assurance
- **Auto-formatting**: `ruff format . && ruff check --fix .`
- **Test execution**: `pytest -m unit --cov --cov-fail-under=95`
- **Documentation building**: `mkdocs build --strict`
- **Full validation loop**: `./scripts/validate.sh`

### Multi-tenant MCP Server Operations
- **Deploy server**: `uv run python deploy_multi_tenant.py --mode online`
- **Sync tenants**: `uv run python trigger_all_syncs.py --tenants <name> --force`
- **Test search**: `uv run python debug_multi_tenant.py --tenant <name> --test search`
- **Cleanup segments**: `uv run python cleanup_segments.py`

### Cross-Agent Coordination
- **Kiro CLI**: Maximally permissive execution with validation hooks
- **GitHub Copilot**: Repository instructions + AGENTS.md alignment
- **Gemini CLI**: Shared AGENTS.md standard
- **All agents**: Consistent validation workflows and code conventions

### Architecture Patterns
- **FastMCP integration**: AppBuilder for route wiring
- **Tenant composition**: StorageContext + IndexRuntime + SyncRuntime
- **Scheduler protocols**: SyncSchedulerProtocol for all sync types
- **Background tasks**: Explicit start/stop/drain lifecycle

### Testing Expertise
- **Unit tests**: Fast, isolated, `@pytest.mark.unit`
- **Integration tests**: Real services, `@pytest.mark.integration`
- **Coverage enforcement**: >=95% line coverage via pytest-cov
- **MECE patterns**: Mutually exclusive, collectively exhaustive

### Documentation & Research
- **TechDocs integration**: Search and fetch from 50+ documentation sources
- **MkDocs publishing**: Strict builds with material theme
- **API documentation**: FastAPI auto-generated schemas
- **Cross-reference validation**: Ensure all links work

## Debugging & Observability
- **Explicit validation**: Clear error surfaces and actionable diagnostics
- **Progress tracking**: Live updates for long-running operations
- **Health endpoints**: Background task status monitoring
- **Search diagnostics**: BM25 scoring and match tracing
