---
applyTo: docs/**/*.md, README.md
---
# Documentation Instructions

> **GOAL**: Create documentation that is clear, concise, and user-centric using MkDocs + Divio system.

## Core Philosophy

1. **Documentation First**: No feature is done until it is documented in `docs/` and validated with `mkdocs build --strict`.
2. **Audience First**: Always state *who* the doc is for and *what* they need to know in the first paragraph.
3. **Why > What**: Explain the *intent* and *rationale*, not just the mechanics. Design decisions belong in `explanations/`.
4. **Zero Bloat**: Do not restate code in comments. Do not write filler text. Code comments explain WHY, not WHAT.
5. **Divio Quadrants**: Every doc must fit exactly one quadrant (Tutorials, How-To, Reference, Explanations). Mixed docs confuse readers.
6. **Reality Grounding**: Never document a command you haven't run in the current session. Paste actual shell output, don't invent "Expected output".
7. **Navigation Sync**: Ensure `mkdocs.yml` navigation matches file structure.

## The Divio System

Organize all documentation into one of these four quadrants. **Every doc MUST fit exactly ONE quadrant.**

### Divio Decision Tree

**Ask yourself:**
1. Is this for **learning a concept**? → Tutorial
2. Is this for **solving a specific task**? → How-To Guide
3. Is this for **looking up facts**? → Reference
4. Is this for **understanding why/how it works**? → Explanation

### 1. Tutorials (Learning-Oriented)

**Goal**: Take the user by the hand through a complete journey to achieve a specific learning outcome.

**Structure**:
- **Introduction**: What will they learn? Estimated time (e.g., "~15 minutes").
- **Prerequisites**: Required knowledge, tools, environment setup.
- **Steps**: Numbered, actionable steps with expected output after each.
- **Verification**: "You should now see..." - how they know it worked.
- **Next Steps**: Links to related How-To guides or deeper Explanations.

**Style**: 
- Narrative, hand-holding tone
- "In this tutorial, you will..."
- Include every command, every file edit
- Show expected output/screenshots

**Example File**: `docs/tutorials/getting-started.md`
**Bad Example**: "Configure BM25 parameters" (This is a How-To, not a Tutorial)
**Good Example**: "Getting Started: Deploy Your First Documentation Tenant in 15 Minutes"

**Template**:
```markdown
# Tutorial: [Learning Goal]

**Time**: ~X minutes  
**Prerequisites**: Python 3.10+, uv installed  
**What You'll Learn**: [Specific outcome]

## Step 1: [Action]
Run the following command:
\`\`\`bash
uv run python -m docs_mcp_server
\`\`\`

**Expected output**:
\`\`\`
Server started on http://localhost:8000
\`\`\`

## Step 2: [Next Action]
...

## Verification
You should now see [specific result].

## Next Steps
- How-To: [Related task guide]
- Explanation: [Deeper concept]
```

### 2. How-To Guides (Problem-Oriented)

**Goal**: Provide a recipe to solve a specific, practical problem.

**Structure**:
- **Problem Statement**: "How to add a Git tenant to deployment"
- **Prerequisites**: What must exist first (e.g., "A GitHub repository with markdown docs")
- **Steps**: Concise, numbered actions
- **Troubleshooting**: Common failure modes and fixes
- **Related**: Links to Reference (config schema) and Explanations (why this approach)

**Style**:
- Imperative mood ("Add the tenant", "Run the command")
- Minimal explanations (link to Explanations instead)
- "How to..." titles

**Example File**: `docs/how-to/configure-git-tenant.md`
**Bad Example**: "Understanding Git Sync Architecture" (This is an Explanation, not How-To)
**Good Example**: "How to Add a Git-Based Documentation Tenant"

**Template**:
```markdown
# How-To: [Solve Specific Problem]

**Goal**: [One sentence describing the outcome]  
**Prerequisites**: [List requirements]

## Steps

1. **Edit `deployment.json`**:
   \`\`\`json
   {
     "source_type": "git",
     "codename": "my-docs",
     ...
   }
   \`\`\`

2. **Trigger sync**:
   \`\`\`bash
   curl -X POST "http://localhost:42042/my-docs/sync/trigger"
   \`\`\`

3. **Verify**:
   \`\`\`bash
   curl "http://localhost:42042/my-docs/sync/status" | jq .
   \`\`\`

## Troubleshooting

**Symptom**: Sync fails with "Git repository not found"  
**Fix**: Verify `git_repo_url` is publicly accessible

## Related
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md)
- Explanation: [Git Sync Strategy](../explanations/sync-strategies.md)
```

### 3. Reference (Information-Oriented)

**Goal**: Describe the machinery completely, accurately, and without explanation.

**Structure**:
- Tables, lists, schemas
- Every parameter/option documented
- Data types, defaults, constraints
- No opinions or recommendations (those go in Explanations)

**Style**:
- Dry, factual, exhaustive
- Alphabetical or logical ordering
- "The `docs_name` parameter specifies..."

**Example File**: `docs/reference/deployment-json-schema.md`
**Bad Example**: "We recommend using `max_crawl_pages: 5000` because..." (This is an Explanation)
**Good Example**: "`max_crawl_pages` (integer, default: 10000) - Maximum number of pages to crawl"

**Template**:
```markdown
# Reference: [System Component]

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `docs_name` | string | *required* | Human-readable documentation name |
| `enable_crawler` | boolean | false | Enable web crawler for URL discovery |
| `max_crawl_pages` | integer | 10000 | Maximum pages to crawl (1-50000) |

## CLI Commands

### `trigger_all_syncs.py`

**Synopsis**: `uv run python trigger_all_syncs.py [OPTIONS]`

**Options**:
- `--tenants CODENAME [CODENAME...]` - Sync specific tenants only
- `--force` - Force sync even if recently synced
- `--host HOST` - Server host (default: localhost)
- `--port PORT` - Server port (default: 42042)

**Exit Codes**:
- `0` - Success
- `1` - HTTP request failed
- `2` - Invalid tenant codename
```

### 4. Explanations (Understanding-Oriented)

**Goal**: Illuminate concepts, design decisions, trade-offs, and context.

**Structure**:
- Problem/Context: "Why does this exist?"
- Design Discussion: Alternatives considered, trade-offs
- Diagrams: Architecture, flows, sequences
- History: "We used to X, now we Y because..."
- References: Links to papers, blog posts, prior art

**Style**:
- Conversational, teaching tone
- "We chose X because Y..."
- Diagrams and visuals encouraged
- No step-by-step instructions (those are Tutorials/How-Tos)

**Example File**: `docs/explanations/search-ranking.md`
**Bad Example**: "Run `uv run pytest` to test BM25" (This is a How-To)
**Good Example**: "Why We Use BM25 with IDF Floor Instead of TF-IDF"

**Template**:
```markdown
# Explanation: [Concept or Decision]

## The Problem

[Context: what problem does this solve? What pain points exist?]

## Our Approach

[Describe the chosen solution]

## Alternatives Considered

| Approach | Pros | Cons | Why Not Chosen |
|----------|------|------|----------------|
| TF-IDF | Simple | Negative scores for common terms | Poor for small corpora |
| BM25 | Handles length normalization | More parameters | **Chosen**: Best balance |

## Architecture Diagram

\`\`\`mermaid
graph LR
    A[Query] --> B[Tokenizer]
    B --> C[BM25 Scorer]
    C --> D[Results]
\`\`\`

## Further Reading
- [BM25 Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Cosmic Python: Repository Pattern](https://www.cosmicpython.com/book/chapter_02_repository.html)
```

## Writing Style Best Practices

### Active Voice & Second Person
- **BAD** (Passive): "The configuration file should be edited"
- **GOOD** (Active): "Edit the configuration file"
- **BAD** (Third person): "Users can configure tenants"
- **GOOD** (Second person): "You can configure tenants by editing `deployment.json`"

### Concise & Scannable
- Short paragraphs (3-5 sentences max)
- Bullet points for lists
- Tables for comparisons
- Code blocks for all commands (never inline for multi-line)

### Real, Runnable Examples
- Every code snippet must be **copy-pasteable** and **runnable**
- Include expected output after commands
- Use actual repo file paths (not `path/to/file`)
- **BAD**: "Configure your settings appropriately"
- **GOOD**: 
  ```json
  {
    "docs_name": "Django",
    "enable_crawler": true
  }
  ```

### Cross-References
- Link to related docs in other quadrants
- Use relative links: `../how-to/deploy-docker.md`
- Format: `See [Tutorial: Getting Started](../tutorials/getting-started.md)`

## Commenting Code (Anti-Bloat Rules)

**Purpose of Comments**: Explain WHY (intent, rationale, trade-offs), not WHAT (code already says that).

### DELETE These Comments
```python
# Bad: Restates code
i = i + 1  # Increment i

# Bad: Obvious from function name
def fetch_document(url):
    """Fetch a document."""  # Adds zero value

# Bad: Placeholder
# TODO: Implement this  # If not doing it now, delete the comment
```

### KEEP These Comments
```python
# Good: Explains intent/trade-off
# Using a set here to deduplicate URLs in O(1) time instead of list (O(n))
visited = set()

# Good: Explains non-obvious constraint
# IDF floor prevents negative BM25 scores in small corpora (<100 docs)
idf = max(0.0, math.log((N - df + 0.5) / (df + 0.5) + 1))

# Good: Known issue with context
# FIXME: This fails on Windows due to path separator mismatch (Issue #42)
path = uri.replace("/", os.sep)

# Good: Explains why NOT doing something obvious
# Don't cache search results - query variance too high for cache hits
return self._bm25_search(query)
```

### Comment Audit Process
When editing code, **actively delete** comment noise:
1. Read each comment
2. Ask: "Does this explain WHY or add context the code doesn't?"
3. If NO → Delete
4. If YES → Keep and verify accuracy

Use `commentIntentAudit.prompt.md` for systematic audits of modules.

## MkDocs Tooling

### Local Development
```bash
# Build documentation (fails on warnings/errors with --strict)
mkdocs build --strict

# Serve locally with live reload
mkdocs serve

# Clean build directory before rebuilding
mkdocs build --strict --clean
```

### File Structure
```
docs/
├── index.md                    # Home page (elevator pitch)
├── tutorials/                  # Learning-oriented (Divio quadrant 1)
│   ├── getting-started.md
│   └── adding-first-tenant.md
├── how-to/                     # Problem-oriented (Divio quadrant 2)
│   ├── configure-git-tenant.md
│   └── debug-crawlers.md
├── reference/                  # Information-oriented (Divio quadrant 3)
│   ├── deployment-json-schema.md
│   └── cli-commands.md
├── explanations/               # Understanding-oriented (Divio quadrant 4)
│   ├── architecture.md
│   └── search-ranking.md
└── contributing.md             # Contributor guide
```

### Navigation in mkdocs.yml
```yaml
nav:
  - Home: index.md
  - Tutorials:
      - Getting Started: tutorials/getting-started.md
      - Your First Tenant: tutorials/adding-first-tenant.md
  - How-To Guides:
      - Configure Git Tenant: how-to/configure-git-tenant.md
  - Reference:
      - deployment.json Schema: reference/deployment-json-schema.md
  - Explanations:
      - Architecture: explanations/architecture.md
```

### Validation
- **Always run** `mkdocs build --strict` before committing
- This catches:
  - Broken internal links
  - Missing nav entries
  - Invalid markdown
  - Orphaned files

## Cross-References & Related Docs

Every doc should link to related docs in other quadrants:

**From Tutorial**:
```markdown
## Next Steps
- How-To: [Configure Git Tenant](../how-to/configure-git-tenant.md)
- Reference: [deployment.json Schema](../reference/deployment-json-schema.md)
```

**From How-To**:
```markdown
## Related
- Tutorial: [Getting Started](../tutorials/getting-started.md) (if new to the project)
- Reference: [CLI Commands](../reference/cli-commands.md)
- Explanation: [Sync Strategies](../explanations/sync-strategies.md)
```

**From Reference**:
```markdown
## See Also
- How-To: [Trigger Syncs](../how-to/trigger-syncs.md)
```

**From Explanation**:
```markdown
## Practical Applications
- Tutorial: [Custom Search Configuration](../tutorials/custom-search.md)
- How-To: [Tune Search Ranking](../how-to/tune-search.md)
```

## Review Checklist

Before committing any documentation changes:

### Content Quality
- [ ] **Audience declared** in first paragraph ("This guide is for developers who...")
- [ ] **Divio quadrant** is clear (Tutorial/How-To/Reference/Explanation)
- [ ] **Real examples** included (every concept has runnable code/command)
- [ ] **Active voice** and second person ("You run..." not "The user runs...")
- [ ] **Cross-references** to related docs in other quadrants
- [ ] **No comment noise** in code samples (deleted obvious/restated comments)

### Technical Validation
- [ ] **All commands tested** and output verified
- [ ] **All file paths** are accurate (relative to repo root)
- [ ] **All links work** (verified by `mkdocs build --strict`)
- [ ] **Code blocks** use correct language tags (\`\`\`python, \`\`\`bash, \`\`\`json)
- [ ] **Screenshots/diagrams** added to `docs/assets/` if used

### MkDocs Integration
- [ ] **Navigation entry** added to `mkdocs.yml` `nav:` section
- [ ] **Strict build passes**: `mkdocs build --strict --clean` with 0 errors
- [ ] **Local preview** checked with `mkdocs serve`

### Divio Compliance
- [ ] **Not a hybrid doc** (e.g., not mixing Tutorial + Reference)
- [ ] **Correct quadrant**:
  - Tutorial: Has numbered steps, prerequisites, expected outcomes
  - How-To: Starts with problem statement, ends with verification
  - Reference: Tables/lists/schemas, no opinions
  - Explanation: Has "Why?" section, diagrams, trade-off discussion

## Common Mistakes

### Mistake 1: Hybrid Docs
**BAD**: A "Tutorial" that includes a reference table of all config options
**FIX**: Split into Tutorial (getting-started.md) + Reference (deployment-json-schema.md)

### Mistake 2: Missing Context
**BAD**: "Run `trigger_all_syncs.py`" (Where? With what args? What happens?)
**FIX**: "From your repo root, run: `uv run python trigger_all_syncs.py --tenants django --force`. This triggers an immediate sync, bypassing the 24h cache."

### Mistake 3: Passive Voice
**BAD**: "The deployment can be triggered by running..."
**FIX**: "Run `deploy_multi_tenant.py` to trigger deployment"

### Mistake 4: Comment Bloat
**BAD**:
```python
# This function fetches a document
def fetch_document(url):
    # Check if URL is valid
    if not url:
        # Return None if invalid
        return None
```
**FIX**:
```python
def fetch_document(url):
    # Early return prevents unnecessary HTTP requests for invalid inputs
    if not url:
        return None
```

### Mistake 5: Broken Links
**BAD**: `[See config](deployment.json)` (file, not doc)
**FIX**: `[See deployment.json schema](../reference/deployment-json-schema.md)`

## Documentation Lifecycle

### Creating New Docs
1. **Determine quadrant** using Divio decision tree
2. **Create file** in correct `docs/` subdirectory
3. **Use template** from this file (see Divio System section)
4. **Add to navigation** in `mkdocs.yml`
5. **Build & test**: `mkdocs build --strict`
6. **Preview**: `mkdocs serve` and visit http://localhost:8000

### Updating Existing Docs
1. **Check current quadrant** - is it still correct?
2. **Update content** following style guide
3. **Delete stale info** - docs ROT fast, be ruthless
4. **Update cross-references** if related docs changed
5. **Rebuild**: `mkdocs build --strict`

### Deprecating Docs
1. **Add deprecation notice** at top:
   ```markdown
   > **DEPRECATED**: This feature was removed in v2.0. See [New Approach](../how-to/new-approach.md).
   ```
2. **Update navigation** - move to "Archive" section or remove
3. **After 2 releases**: Delete the file entirely

## When to Use Prompts

| Task | Prompt | When to Use |
|------|--------|-------------|
| Rewrite entire doc | `docsRewrite.prompt.md` | Doc is outdated, wrong quadrant, or poor quality |
| Fix one section | `alignDocsSection.prompt.md` | Single section violates style guide |
| Clean comments | `commentIntentAudit.prompt.md` | Code comments need systematic review |

## Related Files
- `.github/copilot-instructions.md` - Master AI agent instructions (includes this file's rules)
- `.github/prompts/docsRewrite.prompt.md` - Rewrite documentation files
- `.github/prompts/alignDocsSection.prompt.md` - Fix specific doc sections
- `.github/prompts/commentIntentAudit.prompt.md` - Audit code comments
- `mkdocs.yml` - MkDocs configuration
