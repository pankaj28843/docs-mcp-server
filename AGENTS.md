# docs-mcp-server

This is the canonical repo instruction file for Codex, Claude Code, OpenCode,
GitHub Copilot, and other coding agents. `CLAUDE.md` is compatibility-only and
points here for Claude Code auto-discovery.

Multi-tenant MCP server for documentation search (FastMCP + BM25 +
article-extractor).

## Agent Compatibility

- `AGENTS.md` is canonical.
- `CLAUDE.md` is compatibility-only for Claude Code.
- `.agents/skills` is canonical for repo-local skills.
- `.claude/skills`, `.codex/skills`, `.opencode/skills`, and `.github/skills`
  are compatibility symlinks to `.agents/skills`.
- `.github/copilot-instructions.md` points GitHub Copilot at these same repo
  instructions.
- `.claude/rules/` contains detailed project rule documents referenced by this
  canonical file.
- `.claude/settings.json` and `.claude/settings.local.json` remain
  Claude-specific permission/settings files.

## Build & Test Commands

```bash
# Always prefix Python commands with uv run
uv sync --extra dev
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

## Core Principles

- **No backward compatibility** - Break freely, delete legacy code
- **Minimal code** - Fewer lines over new layers, delete more than you add
- **Deep modules, simple interfaces** - Reduce complexity at boundaries
- **Let exceptions bubble** - No silent error handling
- **>=95% test coverage** - Enforced via pytest-cov
- **Green-before-done** - Never say "done" until tests pass

## Architecture

- `AppBuilder` (`src/docs_mcp_server/app_builder.py`) is the sole entry for
  wiring FastMCP routes, health endpoints, and startup logic.
- Tenants are composed from `StorageContext`, `IndexRuntime`, and
  `SyncRuntime`.
- All schedulers implement `SyncSchedulerProtocol` - HTTP endpoints never
  branch on tenant type.
- Background tasks belong to owner objects with explicit `start/stop/drain`.
- Domain code never imports web framework, FastMCP, or HTTP layers; use DTOs at
  boundaries.

## Key Patterns

- **Cosmic Python** - Repository pattern, FakeUnitOfWork for test isolation
- **Test behavior, not implementation** - No mocking internal methods
- **Divio documentation** - Tutorial/How-To/Reference/Explanation quadrants
- **`uv run` prefix** for all Python commands

## Path-Specific Rules

See `.claude/rules/` for detailed rules scoped to specific paths:

- `testing.md` - Pytest standards, Cosmic Python patterns
- `search.md` - BM25 search implementation rules
- `engineering.md` - Software engineering principles
- `docs.md` - Documentation standards (Divio system)
- `validation.md` - Mandatory validation loop

## Planning

For non-trivial tasks, create a PRP plan at
`~/codex-prp-plans/docs-mcp-server/<yyyy-mm-dd>-<slug>.md`. See
`.claude/rules/prp.md` for the PRP methodology and template.

## Supply Chain Security

- All GitHub Actions must be pinned to commit SHAs, not mutable tags.
- Lockfile (`uv.lock`) must be committed with full hashes.
- Use `uv lock --exclude-newer` with 7-day cooldown for production dependency
  updates.
- `article-extractor` is maintained by the project owner - safe direct
  dependency.

## Mandatory Validation Loop

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```
