---
paths:
  - "**/*.py"
  - "**/*.json"
  - "pyproject.toml"
---

# Mandatory Validation Loop

Run after ANY code change. A change is NOT complete until all pass.

## Quick Validation (Minimum Required)

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit --no-cov
```

## Full Validation

```bash
# Phase 1: Code Quality
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit
timeout 120 uv run python integration_tests/ci_mcp_test.py

# Phase 1.5: Docs (if docs/ changed)
uv run mkdocs build --strict
```
