---
title: Align Documentation Section (Surgical Fix)
description: Fix a specific section of a documentation file to comply with Divio system and writing guidelines
applyTo:
  - "docs/**/*.md"
  - "README.md"
---

# Align Documentation Section Prompt

## Goal

Surgically fix a specific section of a documentation file without rewriting the entire document. Use when most of the doc is good but one section violates guidelines.

## When to Use

- One section uses passive voice
- Missing examples in a specific section
- Section is in wrong Divio quadrant (e.g., Tutorial has Reference table)
- Code comments need cleanup in a code block
- Cross-references missing from one section

**For complete rewrites, use `docsRewrite.prompt.md` instead.**

## Instructions

You will be provided with:
1. **File path** - The documentation file to fix
2. **Section identifier** - Heading name or line range (e.g., "## Installation" or "lines 45-67")
3. **Issue description** - What's wrong (e.g., "passive voice", "missing example", "no cross-reference")

### Step 1: Locate the Section

- Read the target file
- Find the specified section by heading name or line range
- Identify surrounding context (headings before/after)

### Step 2: Diagnose the Issue

Common issues and fixes:

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Passive voice | "The file can be edited" | Change to active: "Edit the file" |
| Missing example | Describes feature, no code | Add runnable code block with output |
| No cross-reference | Mentions related topic, no link | Add link to related doc |
| Wrong quadrant | Tutorial has reference table | Move table to separate Reference doc, link to it |
| Comment bloat | Code blocks with obvious comments | Delete restating comments, keep intent |

### Step 3: Apply Fix Using Guidelines

**Passive → Active Voice**:
```markdown
<!-- BAD -->
The deployment can be triggered by running the script.

<!-- GOOD -->
Run the deployment script:
\`\`\`bash
uv run python deploy_multi_tenant.py --mode online
\`\`\`
```

**Add Missing Example**:
```markdown
<!-- BAD -->
You can configure Git tenants in deployment.json.

<!-- GOOD -->
Configure Git tenants in `deployment.json`:

\`\`\`json
{
  "source_type": "git",
  "codename": "my-docs",
  "git_repo_url": "https://github.com/org/repo.git"
}
\`\`\`

See [deployment.json Schema](../reference/deployment-json-schema.md) for all options.
```

**Add Cross-Reference**:
```markdown
<!-- BAD (mentions sync without linking) -->
After adding the tenant, trigger a sync.

<!-- GOOD -->
After adding the tenant, [trigger a sync](../how-to/trigger-syncs.md):

\`\`\`bash
curl -X POST "http://localhost:42042/my-docs/sync/trigger"
\`\`\`
```

**Fix Quadrant Mismatch**:
```markdown
<!-- BAD: Tutorial with reference table -->
# Tutorial: Getting Started

## Configuration Options

| Parameter | Type | Description |
|-----------|------|-------------|
| docs_name | string | Documentation name |
| ... | ... | (50 more rows) |

<!-- GOOD: Tutorial with link to Reference -->
# Tutorial: Getting Started

## Basic Configuration

You'll need to configure at minimum:
- `docs_name` - Human-readable name
- `docs_entry_url` - Starting URL for crawler

For all configuration options, see [deployment.json Schema](../reference/deployment-json-schema.md).
```

**Clean Comment Bloat**:
````markdown
<!-- BAD: Code with obvious comments -->
\`\`\`python
# This function fetches a document
def fetch_document(url):
    # Check if URL is valid
    if not url:
        # Return None if invalid
        return None
    # Fetch the document
    return httpx.get(url)
\`\`\`

<!-- GOOD: Only intent comments -->
\`\`\`python
def fetch_document(url):
    # Early return prevents unnecessary HTTP requests
    if not url:
        return None
    return httpx.get(url)
\`\`\`
````

### Step 4: Preserve Context

When fixing a section:
- **Don't change** surrounding sections unless they're also broken
- **Maintain** heading hierarchy (don't change # to ## unless needed)
- **Preserve** existing cross-references unless they're broken
- **Keep** working examples unless they violate guidelines

### Step 5: Validate the Fix

Before submitting:

1. **Section-level check**:
   - Active voice? ✓
   - Real examples? ✓
   - Cross-references? ✓
   - Correct quadrant? ✓

2. **File-level check**:
   - Links work? Run `mkdocs build --strict`
   - Doesn't break surrounding sections? ✓

## Output Format

Return ONLY the fixed section using `replace_string_in_file`:

```python
replace_string_in_file(
    filePath="/path/to/file.md",
    oldString="## Installation\n\nThe dependencies can be installed by...",
    newString="## Installation\n\nInstall dependencies:\n\n```bash\nuv sync\n```\n\nThis installs..."
)
```

**Include context** (surrounding text before/after the section) so the replacement is unambiguous.

## Common Section Fixes

### Fix 1: Installation Section (Missing Example)

**Before**:
```markdown
## Installation

You can install the dependencies using uv.
```

**After**:
```markdown
## Installation

Install dependencies with uv:

\`\`\`bash
uv sync
\`\`\`

This installs all packages from `pyproject.toml`.
```

### Fix 2: Configuration Section (Passive Voice + No Example)

**Before**:
```markdown
## Configuration

The deployment file should be edited to add tenants.
```

**After**:
```markdown
## Configuration

Edit `deployment.json` to add tenants:

\`\`\`json
{
  "codename": "my-docs",
  "docs_name": "My Documentation",
  "docs_entry_url": "https://example.com/docs/"
}
\`\`\`

See [deployment.json Schema](../reference/deployment-json-schema.md) for all options.
```

### Fix 3: Troubleshooting Section (No Cross-Reference)

**Before**:
```markdown
## Troubleshooting

If sync fails, check the logs.
```

**After**:
```markdown
## Troubleshooting

If sync fails, check the Docker logs:

\`\`\`bash
docker logs docs-mcp-server-multi | tail -50
\`\`\`

For more debugging steps, see [How-To: Debug Crawlers](../how-to/debug-crawlers.md).
```

### Fix 4: Code Example (Comment Bloat)

**Before**:
````markdown
## Example

\`\`\`python
# Import the service
from service_layer import services

# Create a document
doc = services.create_document("title", "content")

# Save it
services.save(doc)
\`\`\`
````

**After**:
````markdown
## Example

\`\`\`python
from service_layer import services

# Domain services handle business logic + persistence
doc = services.create_document("title", "content")
services.save(doc)
\`\`\`
````

## Related Files

- `.github/instructions/docs.instructions.md` - Full documentation standards
- `.github/prompts/docsRewrite.prompt.md` - Complete document rewrite
- `.github/prompts/commentIntentAudit.prompt.md` - Systematic comment cleanup
