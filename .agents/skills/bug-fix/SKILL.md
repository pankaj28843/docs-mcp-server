---
name: bug-fix
description: Minimal, surgical fix for a reported defect with focused validation
---

## Steps
1. **Confirm scope**: Identify exact entrypoints and data involved.
2. **Add/extend a failing test** or capture the failing command output.
3. **Patch**: Respect service-layer boundaries per Cosmic Python patterns. Use guard clauses, clear errors.
4. **Verify**:
   ```bash
   timeout 120 uv run pytest -m unit --no-cov -k $ARGUMENTS
   uv run ruff check <edited file>
   ```
5. **Report**: Summarize root cause, fix, and validation commands run.

## Output
- Focused diff + brief explanation of behavioral change.
- Updated/added test demonstrating the fix.
