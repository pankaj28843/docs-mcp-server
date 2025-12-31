# AI Coding Agent Instructions for docs-mcp-server

> **WARNING: This file contains instructions for AI coding assistants ONLY.**
> **DO NOT use these guidelines for user-facing documentation.**
> **For project documentation, see README.md and docs/ directory.**

**Project Context**: Multi-tenant MCP server (FastMCP + ripgrep + article-extractor) serving 12+ documentation sources via HTTP/STDIO.

## Core Philosophy

**NO BACKWARD COMPATIBILITY** - This is an active development project. Break things freely unless explicitly asked to maintain compatibility. Focus on making the code better, not preserving old patterns.

**LESS CODE, NO BACKWARD COMPATIBILITY** - Default to deleting legacy branches and feature flags; every refactor should leave fewer lines than before unless there is a compelling reason otherwise.

**LEAST AMOUNT OF CODE NEEDED FOR FUNCTIONALITY** - Ship the minimal implementation that satisfies the requirement, avoid abstraction layers until repeated use proves they are needed.

**MINIMAL DATA STRUCTURES, MAX PERFORMANCE** - Store only the bytes required for functionality, remove vanity metrics/metadata, favor dense arrays over object graphs, and reindex tenants after schema changes so disk and memory footprints continuously shrink.

**RESILIENT SOLUTIONS, BUT NEVER SILENCE ERRORS** - Harden workflows against expected failure modes, yet let exceptions bubble so we immediately see real regressions instead of masking them with broad `try/except` blocks.

**NEVER LEAVE FAILING TESTS BEHIND** - All unit tests and e2e tests MUST pass after every change. If you encounter a failing test:
1. Fix it if it's testing valid behavior that your changes broke
2. Update it if it's testing outdated behavior that no longer applies
3. Delete it if it's testing removed functionality

**DOCUMENTATION-FIRST DELIVERY** - Every README/docs/comment change must obey the `.github/instructions/docs.instructions.md` guidelines: clarity of purpose, Divio-style navigation (Tutorials, How-To, Reference, Explanations), incremental learning, real examples, and honest FAQs.

**NO SUMMARY REPORTS - UNLESS EXPLICITLY REQUESTED** - Do NOT create summary documents, reports, or "what we've accomplished" write-ups unless the user explicitly requests documentation.

**SMART DEFAULTS OVER PER-TENANT CONFIGURATION** - Complexity belongs in the implementation, not the configuration. Users just add a tenant and search works well out of the box.

## Prime Directives (ALWAYS)

- Use `uv run` **before any Python command**: `uv run pytest`, `uv run python -m docs_mcp_server`, etc.
- **Green-before-done**: Do not say "done" until edited Python files import cleanly and tests are green.
- **Tests are mandatory** for any change affecting code paths
- **Never hallucinate**: do not invent files, paths, models, or settings. Search the repo first.
- **TechDocs-first research**: Always check TechDocs before implementing (see workflow below)
- **Reality Log first**: Before editing README/docs, consult `docs/_reality-log/`. If logs are older than 7 days for the commands you’re changing, re-run and update them before editing docs.

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
timeout 60 uv run pytest -m unit --no-cov
uv run mkdocs build --strict
uv run python debug_multi_tenant.py --tenant drf --test search
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
- `timeout 60` prefix for all pytest commands

**Pytest patterns & examples**: `.github/instructions/tests.instructions.md`

## Planning & Memory

For non-trivial tasks, create a PRP plan at `.github/ai-agent-plans/{ISO-timestamp}-{slug}-plan.md`

**PRP template & methodology**: `.github/instructions/PRP-README.md`

## AI-Bloat Prevention

- No giant drops: prefer small, incremental diffs
- No verbose/obvious comments, no placeholder TODOs
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

**See [all 13 prompts](prompts/)**

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
