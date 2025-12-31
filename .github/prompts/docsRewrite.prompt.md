---
description: Completely rewrite a documentation file to follow Divio system
---

# Documentation Rewrite Prompt

## Goal

Completely rewrite a documentation file to be clear, user-centric, and compliant with the Divio documentation system (Tutorial, How-To, Reference, or Explanation).

## When to Use

- Documentation file is outdated or incorrect
- Doc is in wrong Divio quadrant (e.g., Tutorial mixed with Reference)
- Writing style violates guidelines (passive voice, no examples, unclear audience)
- File needs complete restructuring

## Instructions

You will be provided with:
1. **Target file path** - The documentation file to rewrite
2. **Current content** - Existing documentation
3. **Desired quadrant** - Tutorial, How-To, Reference, or Explanation (optional, will be inferred if not specified)

### Step 1: Analyze Current State

Read the existing documentation and identify:
- Current Divio quadrant (if any)
- Target audience (stated or implied)
- Violations of writing guidelines (passive voice, missing examples, no cross-references)
- Missing information

### Step 2: Determine Correct Quadrant

Use the Divio decision tree from `.github/instructions/docs.instructions.md`:

**Ask:**
1. Is this for **learning a concept**? → Tutorial
2. Is this for **solving a specific task**? → How-To Guide
3. Is this for **looking up facts**? → Reference
4. Is this for **understanding why/how it works**? → Explanation

**If the current file mixes quadrants**, split into multiple files OR choose the primary quadrant and link to related docs in other quadrants.

### Step 3: Gather Context

- Read related code files mentioned in the doc
- Check `deployment.json` if documenting tenant configuration
- Review existing examples in similar docs (same quadrant)
- Search for related docs in other quadrants that should be cross-referenced

### Step 4: Rewrite Using Template

Use the appropriate template from `.github/instructions/docs.instructions.md`:

**For Tutorials**:
```markdown
# Tutorial: [Learning Goal]

**Time**: ~X minutes  
**Prerequisites**: [List requirements]  
**What You'll Learn**: [Specific outcome]

## Step 1: [Action]
[Detailed instructions with commands]

**Expected output**:
\`\`\`
[Show what they should see]
\`\`\`

## Step 2: [Next Action]
...

## Verification
You should now see [specific result].

## Next Steps
- How-To: [Related task guide]
- Explanation: [Deeper concept]
```

**For How-To Guides**:
```markdown
# How-To: [Solve Specific Problem]

**Goal**: [One sentence describing the outcome]  
**Prerequisites**: [List requirements]

## Steps

1. **[Action 1]**:
   \`\`\`bash
   [Command with actual values, not placeholders]
   \`\`\`

2. **[Action 2]**:
   ...

## Troubleshooting

**Symptom**: [Error message or problem]  
**Fix**: [Solution]

## Related
- Reference: [Schema or command reference]
- Explanation: [Why this approach]
```

**For Reference**:
```markdown
# Reference: [System Component]

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `param1` | string | required | [Description] |

## CLI Commands

### `script_name.py`

**Synopsis**: `uv run python script_name.py [OPTIONS]`

**Options**:
- `--option VALUE` - [Description]

**Exit Codes**:
- `0` - Success
- `1` - [Error condition]
```

**For Explanations**:
```markdown
# Explanation: [Concept or Decision]

## The Problem

[Context: what problem does this solve?]

## Our Approach

[Describe the chosen solution]

## Alternatives Considered

| Approach | Pros | Cons | Why Not Chosen |
|----------|------|------|----------------|
| Option A | ... | ... | ... |
| **Our Choice** | ... | ... | **Chosen** |

## Architecture Diagram

\`\`\`mermaid
graph LR
    A[Component] --> B[Component]
\`\`\`

## Further Reading
- [External link]
```

### Step 5: Apply Writing Style Guidelines

From `.github/instructions/docs.instructions.md`:

- **Active voice**: "Run the command" not "The command should be run"
- **Second person**: "You configure..." not "Users configure..." or "One configures..."
- **Concise**: 3-5 sentences per paragraph max
- **Real examples**: All commands copy-pasteable, all code runnable
- **Cross-references**: Link to docs in other quadrants

**Bad Example**:
```markdown
The configuration file can be edited to add new tenants. Users should ensure the syntax is correct.
```

**Good Example**:
```markdown
Edit `deployment.json` to add new tenants:

\`\`\`json
{
  "codename": "my-docs",
  "docs_name": "My Documentation"
}
\`\`\`

See [deployment.json Schema](../reference/deployment-json-schema.md) for all options.
```

### Step 6: Add Cross-References

Every doc should link to related docs in OTHER quadrants:

**From Tutorial** → Link to How-To (next steps) and Explanation (deeper understanding)
**From How-To** → Link to Tutorial (if new), Reference (schema/commands), Explanation (why)
**From Reference** → Link to How-To (usage examples)
**From Explanation** → Link to Tutorial (hands-on), How-To (practical)

### Step 7: Validate

Before submitting the rewrite:

1. **Divio compliance**: Confirm doc fits exactly ONE quadrant
2. **Audience stated**: First paragraph declares who this is for
3. **Real examples**: Every concept has runnable code/command
4. **Active voice**: No passive constructions
5. **Cross-references**: Links to ≥1 related doc in another quadrant
6. **MkDocs validation**: Run `mkdocs build --strict` to check for broken links

## Output Format

Replace the entire file content with the rewritten version. Include:

1. Frontmatter (if needed)
2. Complete rewritten content
3. Navigation update (if new file or renamed)

**Example Output**:

```markdown
<!-- File: docs/tutorials/getting-started.md -->

# Tutorial: Getting Started with docs-mcp-server

**Time**: ~15 minutes  
**Prerequisites**: Python 3.10+, uv package manager installed  
**What You'll Learn**: Deploy your first documentation tenant and perform a search

## Step 1: Clone the Repository

\`\`\`bash
git clone https://github.com/pankaj28843/docs-mcp-server.git
cd docs-mcp-server
\`\`\`

**Expected output**:
\`\`\`
Cloning into 'docs-mcp-server'...
\`\`\`

## Step 2: Install Dependencies

\`\`\`bash
uv sync
\`\`\`

This installs all Python dependencies listed in `pyproject.toml`.

## Step 3: Start the Server

\`\`\`bash
uv run python debug_multi_tenant.py --tenant django
\`\`\`

**Expected output**:
\`\`\`
✓ Health check passed
✓ Search returned 10 results
\`\`\`

## Verification

You should now have:
- A running MCP server on port 42043
- Successfully searched Django documentation

## Next Steps

- How-To: [Add Your First Tenant](../how-to/configure-git-tenant.md)
- Reference: [MCP Tools API](../reference/mcp-tools.md)
- Explanation: [Architecture Overview](../explanations/architecture.md)
```

## Related Files

- `.github/instructions/docs.instructions.md` - Full documentation standards
- `.github/prompts/alignDocsSection.prompt.md` - Fix one section only
- `mkdocs.yml` - Navigation configuration
