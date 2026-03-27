# AGENTS.md (docs-mcp-server)

## Agent: Claude Code

Configuration:
- `CLAUDE.md` - Main project instructions
- `.claude/rules/` - Path-specific rules (testing, search, engineering, docs, validation, PRP)
- `.claude/skills/` - Slash commands (`/validate`, `/bug-fix`, `/clean-refactor`, `/dead-code-audit`, `/coverage`, `/docs-rewrite`, `/simplify`)
- `.claude/settings.json` - Permissions

## Core Principles

- **No backward compatibility** - Break freely, delete unused code
- **Minimal code** - Fewer lines over new layers
- **>=95% test coverage** - Enforced via pytest-cov
- **Green-before-done** - Never say "done" until tests pass

## Mandatory Validation Loop

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```
