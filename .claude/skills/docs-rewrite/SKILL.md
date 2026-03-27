---
name: docs-rewrite
description: Rewrite documentation following Divio system standards
---

Rewrite the specified documentation file following Divio quadrants:
- Determine correct quadrant (Tutorial/How-To/Reference/Explanation)
- Active voice, second person
- Real, runnable examples only
- Cross-reference related docs
- Validate with `uv run mkdocs build --strict`

Target file: $ARGUMENTS
