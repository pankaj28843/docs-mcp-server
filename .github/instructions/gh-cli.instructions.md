# GitHub CLI (gh) Non-Interactive Usage Instructions

> **CRITICAL: Always use non-interactive mode when automating gh commands in scripts or agent workflows.**

## The Problem: Interactive Pagers

By default, `gh` commands open interactive pagers (less/more) that require manual intervention:
- User must press `q` to exit
- Blocks automated workflows
- Cannot capture output programmatically
- Terminal hangs waiting for user input

**NEVER run bare `gh` commands without piping to head/tail!**

## The Solution: Pipe to head/tail

**ALWAYS pipe gh output to `head` or `tail` with `-n` flag:**

```bash
# BAD: Opens interactive pager
gh run list --limit 5

# GOOD: Non-interactive, shows first 10 lines
gh run list --limit 5 | head -n 10

# GOOD: Non-interactive, shows last 50 lines
gh run view --log-failed | tail -n 50
```

## Core Patterns

### 1. List Workflow Runs

```bash
# Show recent runs (first 10 lines)
gh run list --limit 5 | head -n 10

# Show specific workflow
gh run list --workflow="Deploy MkDocs to GitHub Pages" --limit 3 | head -n 5

# JSON output for programmatic parsing
gh run list --limit 3 --json conclusion,status,workflowName,createdAt | head -n 20
```

### 2. View Workflow Logs

```bash
# Show failure logs (last 100 lines most useful)
gh run view 20613814328 --log-failed | tail -n 100

# Show all logs (first 50 lines for overview)
gh run view 20613814328 --log | head -n 50

# Show specific job logs
gh run view 20613814328 --job=12345 --log | tail -n 50
```

### 3. Repository Operations

```bash
# Check repo visibility
gh repo view pankaj28843/docs-mcp-server --json visibility,isPrivate | head -n 5

# Make repo public (no output expected)
gh repo edit pankaj28843/docs-mcp-server --visibility public --accept-visibility-change-consequences | head -n 5

# View repo details
gh repo view --json name,description,isPrivate,url | head -n 10
```

### 4. GitHub API Direct Access

```bash
# Enable GitHub Pages
gh api repos/pankaj28843/docs-mcp-server/pages -X POST -F build_type=workflow | head -n 20

# Get workflow runs via API
gh api repos/pankaj28843/docs-mcp-server/actions/runs --jq '.workflow_runs[0] | {id, conclusion, status, name}' | head -n 10

# Check Pages status
gh api repos/pankaj28843/docs-mcp-server/pages | head -n 15
```

### 5. Re-running Workflows

```bash
# Re-run failed workflow (no output expected)
gh run rerun 20613814328 | head -n 5

# Re-run all failed jobs
gh run rerun 20613814328 --failed | head -n 5

# Watch workflow progress (limit output)
gh run watch 20613814328 | head -n 50
```

## When to Use head vs tail

| Command Type | Use | Reason |
|--------------|-----|--------|
| `gh run list` | `head -n 10` | Most recent runs at top, need overview |
| `gh run view --log-failed` | `tail -n 100` | Error messages typically at end of logs |
| `gh run view --log` | `head -n 50` | Overview of execution, or `tail` for errors |
| `gh api` | `head -n 20` | JSON responses, need complete structure |
| `gh repo view` | `head -n 10` | Compact output, shows all needed info |
| `gh run watch` | `head -n 50` | Live updates, limit scrolling |

## Always Check gh help First

**Before guessing gh command syntax, ALWAYS consult help:**

```bash
# Get command-specific help
gh run list --help | head -n 50
gh api --help | head -n 40
gh repo edit --help | tail -n 100

# Discover available flags
gh run view --help | grep -E "^\s+--" | head -n 30

# Find JSON fields
gh run list --help | grep -A 10 "json" | head -n 20
```

## Real-World Example: This Session

### Problem Encountered
Attempted to monitor GitHub Actions workflow deployment but gh commands opened interactive pagers:

```bash
# ATTEMPT 1: Blocked by pager
gh run list --workflow="Deploy MkDocs to GitHub Pages" --limit 5
# Result: User had to press 'q' to exit

# ATTEMPT 2: Still blocked
gh run view --log-failed --limit 50
# Result: Interactive pager, then tool error
```

### Solution Applied

```bash
# STEP 1: List runs non-interactively
gh run list --limit 5 | head -n 10
# Output: Found failed run ID 20613814328

# STEP 2: View failure logs
gh run view 20613814328 --log-failed | tail -n 100
# Output: "Creating Pages deployment failed - Not Found (404)"
# Root cause: GitHub Pages not enabled

# STEP 3: Check repo visibility
gh repo view pankaj28843/docs-mcp-server --json visibility,isPrivate | head -n 5
# Output: {"isPrivate":true,"visibility":"PRIVATE"}

# STEP 4: Make repo public
gh repo edit pankaj28843/docs-mcp-server --visibility public --accept-visibility-change-consequences | head -n 5
# Output: (silent success)

# STEP 5: Enable Pages via API
gh api repos/pankaj28843/docs-mcp-server/pages -X POST -F build_type=workflow | head -n 20
# Output: JSON confirming Pages enabled at pankaj28843.github.io/docs-mcp-server

# STEP 6: Re-run failed workflow
gh run rerun 20613814328 | head -n 5
# Output: (silent success)

# STEP 7: Monitor completion
gh run list --limit 1 | head -n 3
# Output: "completed success" - deployment succeeded
```

### Key Learnings

1. **ALWAYS pipe to head/tail** - No exceptions for automation
2. **Use tail -n 100 for error logs** - Errors appear at end
3. **Use head -n 10 for lists** - Overview of recent items
4. **Check --help first** - Don't guess flag syntax (e.g., `--accept-visibility-change-consequences` required for visibility change)
5. **Use gh api for complex operations** - Direct API access avoids gh CLI limitations
6. **Sleep between checks** - Give workflows time to start/complete before polling

## Common Pitfalls

### ❌ Anti-Pattern 1: Bare gh Commands
```bash
gh run list  # Opens pager, blocks workflow
gh run view --log  # User must press 'q' to continue
```

### ✅ Correct Pattern
```bash
gh run list | head -n 10  # Non-interactive, shows overview
gh run view --log | tail -n 50  # Non-interactive, shows errors
```

### ❌ Anti-Pattern 2: Assuming Silent Success
```bash
gh run rerun 12345  # Did it work? No output to verify
```

### ✅ Correct Pattern
```bash
gh run rerun 12345 | head -n 5  # Pipe even if no output expected
sleep 5 && gh run list --limit 1 | head -n 3  # Verify it started
```

### ❌ Anti-Pattern 3: Guessing Flag Names
```bash
gh repo edit --visibility public  # ERROR: missing required flag
```

### ✅ Correct Pattern
```bash
gh repo edit --help | grep -A 5 "visibility" | head -n 10
# Discover: --accept-visibility-change-consequences required
gh repo edit --visibility public --accept-visibility-change-consequences | head -n 5
```

## Integration with AI Agents

When using gh CLI in automated workflows:

1. **Pre-flight check**: Always run `gh auth status | head -n 5` to verify authentication
2. **Error handling**: Pipe stderr to stdout: `gh run list 2>&1 | head -n 10`
3. **JSON parsing**: Use `--json` + `jq` for structured data
4. **Timeouts**: Add `timeout 30` prefix for commands that might hang
5. **Progress tracking**: Use `sleep N &&` between dependent commands

## Validation Checklist

Before committing any script using gh CLI:

- [ ] All `gh` commands pipe to `head` or `tail`
- [ ] Tested command with `--help` flag first
- [ ] JSON output uses `--json` flag explicitly
- [ ] Error logs use `tail -n 100` (errors at end)
- [ ] List commands use `head -n 10` (overview at top)
- [ ] Sleep added between dependent operations
- [ ] No bare `gh` commands without pipes

## Reference: Useful Flags

```bash
# Limit output size
--limit N           # Limit number of items returned
--json FIELDS       # Machine-readable output
--jq EXPRESSION     # Filter JSON with jq syntax

# Avoid confirmation prompts  
--yes, -y           # Auto-confirm dangerous operations
--accept-*          # Accept consequences (visibility, etc.)

# Control verbosity
--verbose           # Show detailed output
-q, --quiet         # Suppress output (still pipe to head!)

# Format control
--template STRING   # Custom output format
--pretty            # Human-readable JSON (still needs pipe!)
```

## Appendix: Shell Escaping Issues

When using gh API with complex data:

```bash
# BAD: Shell interprets brackets
gh api -f source[branch]=main  # zsh: no matches found

# GOOD: Use -F flag for form data
gh api -F build_type=workflow

# GOOD: Quote the parameter
gh api -f 'source[branch]=main'

# BEST: Use JSON payload file
echo '{"source":{"branch":"main"}}' | gh api -X POST --input -
```

---

**Remember: When in doubt, run `gh <command> --help | head -n 50` first!**
