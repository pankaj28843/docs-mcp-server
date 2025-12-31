# Contributing

**Audience**: Contributors updating code or docs for docs-mcp-server.  
**Prerequisites**: Python 3.10+, uv installed, Docker for deploy testing.  
**Time**: ~20 minutes for docs changes, ~30 minutes for code + deploy checks.  
**What you'll learn**: Validation loop and doc standards.

## Development Workflow

1. Install deps: `uv sync --extra dev`
2. Run code quality: `uv run ruff format . && uv run ruff check --fix .`
3. Docs sanity: `uv run mkdocs build --strict` and then `rg "Traceback|Exception|ERROR" site`
4. Run unit tests: `timeout 60 uv run pytest -m unit --no-cov`
5. Critical scripts (from validation.instructions.md):
	- `uv run python debug_multi_tenant.py --tenant drf --test search`
	- `uv run python trigger_all_syncs.py --tenants aidlc-rules --force`
	- `uv run python trigger_all_indexing.py --tenants drf django`
	- `uv run python deploy_multi_tenant.py --mode online`

## Verifying Documentation

Before documenting commands, run them and capture actual output. Paste real terminal output into docs—never invent "Expected output" blocks. This ensures docs stay accurate.

## Documentation Standards

- Follow Divio quadrants (Tutorial, How-To, Reference, Explanation).
- Declare audience, prerequisites, time, and learning goals in the intro.
- Include verification at the end of every procedure.
- Avoid filler words ("Simply", "Feel free", "As mentioned earlier").
- Keep README concise (<200 lines) and defer detail to docs/.

## Getting Help

- Validation details: `.github/instructions/validation.instructions.md`
- Docs standards: `.github/instructions/docs.instructions.md`
- Reality checks: `.github/prompts/docsRealityCheck.prompt.md`

