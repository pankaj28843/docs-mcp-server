# Contributing

Thanks for improving `docs-mcp-server`.

This guide is for contributors who change code, tests, or documentation.

## Local setup

```bash
uv sync --extra dev
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

## Development workflow

1. Create a focused branch.
2. Keep changes small and reviewable.
3. Run the full validation loop before opening a PR.

## Mandatory validation loop

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

## Documentation standards

Documentation follows Divio quadrants:

- Tutorials: learning journeys
- How-to guides: task recipes
- Reference: factual lookup
- Explanations: architecture and trade-offs

When you update docs:

- Ensure commands are real and executable.
- End procedures with explicit verification.
- Keep README concise; move depth into `docs/`.

## Testing standards

- Add or update tests for behavioral changes.
- Prefer unit tests for isolated logic.
- Keep test scope MECE where practical.

## Pull request checklist

- [ ] Scope is focused and intentional
- [ ] Validation loop passed locally
- [ ] Docs updated for behavior changes
- [ ] `mkdocs build --strict` succeeds
- [ ] PR description explains user-visible impact

## Need help

- Architecture: `docs/explanations/architecture.md`
- Test patterns: `.github/instructions/tests.instructions.md`
- Validation rules: `.github/instructions/validation.instructions.md`
