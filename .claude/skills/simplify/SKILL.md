---
name: simplify
description: Review changed code for reuse, quality, and efficiency, then fix issues
---

## Steps
1. Review recent changes (git diff or specified files)
2. Check for:
   - Code duplication that could be consolidated
   - Unnecessary abstractions or indirection
   - Pass-through functions that add no value
   - Overly complex control flow
   - Unused imports or variables
3. Apply simplifications
4. Run validation: `uv run ruff format . && uv run ruff check --fix . && timeout 120 uv run pytest -m unit --no-cov`
5. Report what was simplified and why
