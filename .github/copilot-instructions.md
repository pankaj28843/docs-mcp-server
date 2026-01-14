# AI Coding Agent Instructions

**Project**: Multi-tenant MCP server (FastMCP + ripgrep + article-extractor)

## Core Rules
- **No backward compatibility** - Break freely, delete legacy code
- **Minimal code** - Fewer lines over new layers
- **Deep modules, simple interfaces** - Reduce complexity at boundaries  
- **Let exceptions bubble** - No silent error handling
- **>=95% test coverage** - Enforced via pytest-cov

## Validation Loop (Always Run)
```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

## Hooks Active
- **post-write**: Auto-format on file changes
- **stop**: Full validation after responses
- **pre-commit**: Format + lint (git)
- **pre-push**: Tests + coverage (git)

- `AppBuilder` (src/docs_mcp_server/app_builder.py) is the sole entry for wiring FastMCP routes, health endpoints, and startup logic. Extend the builder or `runtime/*` helpers instead of adding bespoke wiring back to `app.py`.
- Tenants are composed from `StorageContext`, `IndexRuntime`, and `SyncRuntime`. Add behavior by extending those contexts; never reintroduce loose globals or boolean webs inside `TenantServices`.
- All schedulers—including git—implement `SyncSchedulerProtocol`. HTTP endpoints never branch on tenant type or scheduler flavor; add new knobs by evolving the shared protocol.
- Background tasks belong to owner objects with explicit `start/stop/drain`. Health/readiness endpoints must read those owners, not recompute filesystem state or spawn ad-hoc tasks.
- Delete pass-through plumbing. If a method only forwards arguments, inline it or convert the collaborators into a context so every exported function adds real behavior.

## Prime Directives (ALWAYS)

- Use `uv run` **before any Python command**: `uv run pytest`, `uv run python -m docs_mcp_server`, etc.
- **Green-before-done**: Do not say "done" until edited Python files import cleanly and tests are green.
- **Tests are mandatory** for any change affecting code paths
- **Never hallucinate**: do not invent files, paths, models, or settings. Search the repo first.
- **TechDocs-first research**: Always check TechDocs before implementing (see workflow below)
- **Verify docs with real commands**: Before documenting any command, run it and paste actual output. Never invent "Expected output" blocks.

## TechDocs Research Workflow

**ALWAYS start with this sequence**:
1. `mcp_techdocs_list_tenants()` → discover available documentation sources
2. `mcp_techdocs_describe_tenant(codename="...")` → understand tenant capabilities and test queries
3. `mcp_techdocs_root_search(tenant_codename="...", query="...")` → find relevant patterns
4. `mcp_techdocs_root_fetch(tenant_codename="...", uri="...")` → read full documentation

**Key tenants for this project**: `cosmicpython` (DDD patterns), `fastmcp`/`mcp` (MCP tools), `python`/`pytest` (Python best practices), `github-copilot` (prompt engineering)

**Full TechDocs guide**: See `.github/instructions/techdocs.instructions.md`

## Validation & Testing

**ALL code changes require validation loop**:
```bash
uv sync --extra dev
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

**Full 5-phase validation checklist**: See `.github/instructions/validation.instructions.md`

Critical scripts that MUST work after changes:
- `debug_multi_tenant.py` - Local/remote testing
- `deploy_multi_tenant.py` - Docker deployment (always use `--mode online`)
- `trigger_all_syncs.py` - Crawler/sync jobs
- `trigger_all_indexing.py` - Rebuild BM25 indexes

## Documentation Standards

- Follow Divio quadrants (Tutorial/How-To/Reference/Explanation)
- `mkdocs build --strict` before committing
- Active voice, second person, short paragraphs
- Clarity principles: state WHO the doc is for in the first paragraph; declare prerequisites explicitly; answer both HOW (steps) and WHY (rationale/trade-offs); include FAQ/Troubleshooting with real errors; end procedures with explicit verification commands.

**Complete guide**: `.github/instructions/docs.instructions.md`

## Testing Rules

- Unit tests for EVERY new function/class
- Use FakeUnitOfWork for isolation (Cosmic Python pattern)
- Test behavior, not implementation
- `timeout 120` prefix for all pytest commands
- Keep tests MECE (mutually exclusive, collectively exhaustive) with >=95% line coverage enforced via pytest-cov

**Pytest patterns & examples**: `.github/instructions/tests.instructions.md`

## Planning & Memory

For non-trivial tasks, create a PRP plan at `~/codex-prp-plans/{ISO-timestamp}-{slug}-plan.md`

**PRP template & methodology**: `.github/instructions/PRP-README.md`

## AI-Bloat Prevention

- No giant drops: prefer small, incremental diffs
- No verbose/obvious comments, no placeholder TODOs
- **No backward-looking comments** - Never add comments explaining how code "used to work" or what's "no longer needed". Code should have no baggage from previous implementations.
- Function complexity >15 → refactor; single function >120 LOC → refactor
- Minimize rename/reordering churn unless clarity win is undeniable

## Path-Specific Instructions

Detailed rules for specific code paths:

| Pattern | File | Purpose |
|---------|------|---------|
| `**/*.py`, `deployment.json` | [validation.instructions.md](instructions/validation.instructions.md) | Mandatory validation loop, deploy workflows |
| `tests/**/*.py` | [tests.instructions.md](instructions/tests.instructions.md) | Pytest standards, Cosmic Python test patterns |
| `docs/**/*.md`, `README.md` | [docs.instructions.md](instructions/docs.instructions.md) | Divio documentation system guidelines |
| `src/docs_mcp_server/search/**` | [search.instructions.md](instructions/search.instructions.md) | BM25 search implementation rules |
| GitHub CLI workflows | [gh-cli.instructions.md](instructions/gh-cli.instructions.md) | Non-interactive mode patterns |

## Prompt Library

Reusable templates in `.github/prompts/`:

- `prpPlanOnly.prompt.md` - Planning mode (no code changes until approved)
- `cleanCodeRefactor.prompt.md` - Rename/restructure without behavior changes
- `addOnlineTenant.prompt.md` - Add new documentation source
- `testHardening.prompt.md` - Improve test coverage/reliability
- `docsRewrite.prompt.md` - Rewrite docs per Divio system
- `visualDocsQA.prompt.md` - Screenshot and analyze rendered docs (requires LLM vision)

**See [all prompts](prompts/)**

## Where to Learn More

### Project Documentation

| Topic | Location | Description |
|-------|----------|-------------|
| **Architecture** | [docs/explanations/architecture.md](../docs/explanations/architecture.md) | System design, DDD patterns, trade-offs |
| **Operations** | [docs/how-to/operations.md](../docs/how-to/operations.md) | Deploy, sync, troubleshoot |
| **Search internals** | [docs/reference/search-engine.md](../docs/reference/search-engine.md) | BM25 algorithm, indexing |
| **Contributing** | [docs/contributing.md](../docs/contributing.md) | Development setup, workflows |

### Quick Links to Detailed Rules

- **Validation workflow**: [5-phase loop](instructions/validation.instructions.md#validation-loop-mandatory)
- **Unit testing**: [Cosmic Python style](instructions/tests.instructions.md#unit-test-standards-cosmic-python-style)
- **Documentation**: [Divio quadrants](instructions/docs.instructions.md#documentation-philosophy)
- **TechDocs workflow**: [Discovery patterns](instructions/techdocs.instructions.md)
- **GitHub CLI**: [Non-interactive mode](instructions/gh-cli.instructions.md)
