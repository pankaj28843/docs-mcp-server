# AGENTS.md (docs-mcp-server)

## Scope
- Follow `.github/copilot-instructions.md` and docs in `docs/`.
- Keep modules deep and interfaces small; prefer fewer lines over new layers.
- Avoid backward compatibility unless explicitly requested.

## Workflow
- Use `uv run` for all Python commands.
- No silent error handling; let real failures surface.
- Do not add summary reports unless explicitly requested.
- Keep unit tests MECE (mutually exclusive, collectively exhaustive) and maintain >=95% line coverage.

## Validation
- Run: `uv sync --extra dev`
- Run: `uv run ruff format . && uv run ruff check --fix .`
- Run: `timeout 120 uv run pytest -m unit`
- Run: `uv run mkdocs build --strict`
- Run: `uv run python debug_multi_tenant.py --tenant drf --test search`

## Planning
- Store PRP plans in `~/codex-prp-plans` (not in-repo).
- Update the plan after each phase; keep UTC timestamps with `Z` suffix.

## Privacy / Safety
- Do not include local machine details, IPs, or tenant-specific data in code or docs.
- Avoid embedding local paths or runtime secrets in docs/examples.
