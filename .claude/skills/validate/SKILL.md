---
name: validate
description: Run the mandatory validation loop (format, lint, test, docs)
---

Run the full validation loop for this project:

```bash
uv run ruff format . && uv run ruff check --fix .
timeout 120 uv run pytest -m unit
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

Report results for each phase. Stop on first failure and diagnose.
