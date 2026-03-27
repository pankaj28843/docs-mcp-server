# AGENTS.md (docs-mcp-server)

## Primary Agent: Claude Code

Configuration lives in:
- `CLAUDE.md` - Main project instructions
- `.claude/rules/` - Path-specific rules (testing, search, engineering, docs, validation, PRP)
- `.claude/skills/` - Reusable slash commands (`/validate`, `/bug-fix`, `/clean-refactor`, `/dead-code-audit`, `/coverage`, `/docs-rewrite`, `/simplify`)
- `.claude/settings.json` - Permissions and automation

## Legacy: GitHub Copilot

GitHub Copilot configuration remains in `.github/copilot-instructions.md` and `.github/instructions/` for backward compatibility. These files are read-only references; Claude Code uses `CLAUDE.md` and `.claude/` exclusively.

## Cross-Agent Alignment

All agents share the same principles:
- **No backward compatibility** - Break freely, delete legacy code
- **Minimal code** - Fewer lines over new layers
- **>=95% test coverage** - Enforced via pytest-cov
- **Same validation loop** - format, lint, test, docs build

## Mandatory Validation Loop

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```
