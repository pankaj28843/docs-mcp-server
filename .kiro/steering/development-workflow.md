# Development Workflow - docs-mcp-server

## Command Patterns

### Always Use `uv run`
All Python commands must be prefixed with `uv run`:

```bash
# Development commands
uv run pytest -m unit
uv run python -m docs_mcp_server
uv run mkdocs serve
uv run ruff format .

# Never run Python directly
python -m pytest  # ❌ Wrong
uv run pytest     # ✅ Correct
```

### Mandatory Validation Loop
Before any commit or "done" declaration:

```bash
# 1. Sync dependencies
uv sync --extra dev

# 2. Format and lint
uv run ruff format . && uv run ruff check --fix .

# 3. Run unit tests with timeout
timeout 60 uv run pytest -m unit

# 4. Build documentation
uv run mkdocs build --strict

# 5. Test core functionality
uv run python debug_multi_tenant.py --tenant drf --test search
```

## Development Principles

### Green-Before-Done
- Never say "done" until tests pass
- All edited Python files must import cleanly
- No failing tests left behind
- Fix, update, or delete broken tests

### No Silent Errors
- Let exceptions bubble up naturally
- Don't catch and ignore errors
- Add context to exceptions when re-raising
- Use specific exception types for domain errors

### Minimal Implementation
- Ship the smallest code that works
- Delete more than you add when refactoring
- Avoid abstraction until proven necessary
- Prefer composition over configuration

## Git Workflow

### Commit Standards
```bash
# Good commit messages
git commit -m "Add SQLite storage backend for search segments"
git commit -m "Fix BM25 scoring for empty documents"
git commit -m "Remove deprecated JSON segment format"

# Bad commit messages  
git commit -m "Fix bug"
git commit -m "Update code"
git commit -m "WIP"
```

### Branch Strategy
- **main**: Always deployable
- **feature/**: New functionality
- **fix/**: Bug fixes
- **refactor/**: Code improvements without behavior changes

### Pre-commit Checklist
- [ ] Validation loop passes
- [ ] Tests cover new functionality
- [ ] Documentation updated if needed
- [ ] No debug prints or commented code
- [ ] Commit message describes the change

## Documentation Workflow

### Divio Documentation System
Follow the four quadrants:

1. **Tutorials** (`docs/tutorials/`): Learning-oriented
2. **How-to Guides** (`docs/how-to/`): Problem-oriented  
3. **Reference** (`docs/reference/`): Information-oriented
4. **Explanations** (`docs/explanations/`): Understanding-oriented

### Documentation Standards
```bash
# Always build docs before committing
uv run mkdocs build --strict

# Serve locally for review
uv run mkdocs serve

# Check for broken links
uv run mkdocs build --strict --verbose
```

### Writing Guidelines
- **Active voice**: "Configure the tenant" not "The tenant should be configured"
- **Second person**: "You can search" not "One can search"
- **Short paragraphs**: 1-3 sentences maximum
- **Clear prerequisites**: State what users need upfront
- **Verification steps**: End procedures with "verify it works"

## Testing Workflow

### Test-Driven Development
1. **Red**: Write failing test for new behavior
2. **Green**: Write minimal code to make test pass
3. **Refactor**: Improve code while keeping tests green

### Test Categories
```bash
# Fast unit tests (< 1 second each)
uv run pytest -m unit

# Integration tests (database, HTTP)
uv run pytest -m integration

# End-to-end tests (full system)
uv run pytest -m e2e

# All tests with coverage
uv run pytest --cov=src --cov-report=term-missing
```

### Coverage Requirements
- **>=95% line coverage**: Enforced automatically
- **MECE tests**: Mutually Exclusive, Collectively Exhaustive
- **Behavior testing**: Test what code does, not how

## Debugging Workflow

### Local Testing
```bash
# Test specific tenant
uv run python debug_multi_tenant.py --tenant drf --test search

# Test with custom host/port
uv run python debug_multi_tenant.py --host localhost --port 8080

# Deploy and test
uv run python deploy_multi_tenant.py --mode online
```

### Log Analysis
```bash
# View container logs
docker logs docs-mcp-server

# Follow logs in real-time
docker logs -f docs-mcp-server

# Search logs for errors
docker logs docs-mcp-server 2>&1 | grep ERROR
```

### Performance Profiling
```bash
# Profile search performance
uv run python -m cProfile -o profile.stats debug_multi_tenant.py

# Analyze profile
uv run python -c "import pstats; pstats.Stats('profile.stats').sort_stats('cumulative').print_stats(20)"
```

## Deployment Workflow

### Local Development
```bash
# Start development server
uv run python -m docs_mcp_server

# Deploy to Docker (always use --mode online)
uv run python deploy_multi_tenant.py --mode online

# Trigger sync for specific tenant
uv run python trigger_all_syncs.py --tenants drf --force

# Rebuild search indexes
uv run python trigger_all_indexing.py
```

### Production Deployment
```bash
# Build and deploy
docker build -t docs-mcp-server .
docker run -p 8080:8080 docs-mcp-server

# Health check
curl http://localhost:8080/health

# Test MCP endpoint
curl http://localhost:8080/mcp
```

## Troubleshooting Workflow

### Common Issues

#### Import Errors
```bash
# Check Python path
uv run python -c "import sys; print(sys.path)"

# Verify package installation
uv run pip list | grep docs-mcp-server
```

#### Test Failures
```bash
# Run specific failing test
uv run pytest tests/unit/test_specific.py::test_method -v

# Run with debugging
uv run pytest --pdb tests/unit/test_specific.py::test_method

# Check coverage for specific file
uv run pytest --cov=src/docs_mcp_server/module.py --cov-report=term-missing
```

#### Search Issues
```bash
# Test search directly
uv run python debug_multi_tenant.py --tenant drf --test search

# Check segment files
ls -la test-docs/__search_segments/

# Verify tenant configuration
uv run python -c "from docs_mcp_server.deployment_config import DeploymentConfig; print(DeploymentConfig.from_file('deployment.json').tenants[0])"
```

## Planning Workflow

### PRP (Problem-Requirements-Plan) Method
For non-trivial tasks, create a plan at `~/codex-prp-plans/{timestamp}-{slug}-plan.md`:

```markdown
# Problem
What specific issue needs solving?

# Requirements  
What must the solution accomplish?

# Plan
Step-by-step approach with phases and validation points.
```

### Plan Updates
- Update after each phase completion
- Include UTC timestamps with `Z` suffix
- Store outside repository (`~/codex-prp-plans/`)
- Reference plan in commit messages
