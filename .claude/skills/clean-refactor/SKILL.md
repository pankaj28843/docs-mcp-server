---
name: clean-refactor
description: Rename/restructure without behavior changes - tests must remain green
---

## Principles
- Zero behavior changes - only structural improvements
- Tests must pass before AND after
- Minimize rename/reordering churn unless clarity win is undeniable

## Steps
1. Run baseline tests: `timeout 120 uv run pytest -m unit --no-cov`
2. Apply structural changes (renames, moves, simplifications)
3. Run tests again - must be identical pass/fail
4. Run `uv run ruff format . && uv run ruff check --fix .`
5. Report what changed and why it's cleaner
