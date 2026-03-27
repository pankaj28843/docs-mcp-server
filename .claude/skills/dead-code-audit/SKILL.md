---
name: dead-code-audit
description: Find and remove unused code, imports, and dead paths
---

## Steps
1. Run `uv run vulture src/ --min-confidence 80` to find dead code candidates
2. For each candidate, verify it's truly unused (grep for references)
3. Remove confirmed dead code
4. Run full test suite to verify nothing broke
5. Report what was removed and the size reduction
