---
description: 'Capture doc screenshots and analyze rendered output using LLM vision capabilities'
---

# Visual Documentation QA Prompt

## Goal

Screenshot the rendered MkDocs site and **use LLM vision capabilities to analyze each screenshot image**. This prompt is about visual reasoning—actually looking at the rendered output, not just reading markdown source files.

## Vision-First Analysis

> **Use vision capabilities to analyze the rendered output.**
>
> 1. **Visually inspect each screenshot PNG file**
>    - **Option A (Autonomous)**: If your environment supports reading image files directly (e.g., via `#file:` reference or internal vision tool), load the screenshot.
>    - **Option B (Interactive)**: If you cannot self-load images, **ask the user** to attach the generated screenshots to the chat (drag & drop or "Add File to Chat").
> 2. **Describe what you see** in each screenshot before identifying issues.
> 3. **Use visual reasoning** to detect layout problems, spacing issues, broken diagrams, and formatting errors that are only visible in the rendered output.
> 4. **Do NOT rely solely on reading markdown source** — the goal is to catch issues that only appear after rendering.

## Prerequisites

- **docs-html-screenshot**: Available via Docker (`ghcr.io/pankaj28843/docs-html-screenshot:latest`) or PyPI (`uv tool install docs-html-screenshot`)
- Built documentation site (run `uv run mkdocs build --strict` first)

## Workflow

### Step 1: Build Documentation

```bash
# From the project root directory
uv run mkdocs build --strict --clean
```

If build fails, fix errors before proceeding.

### Step 2: Capture Screenshots

Screenshots go to a fixed `tmp/screenshots/` folder with flat filenames for easy `#filename` references:

```bash
# Create/clean screenshot folder
rm -rf tmp/screenshots && mkdir -p tmp/screenshots

# Run screenshot tool via Docker (recommended)
docker run --rm --init --ipc=host \
  -v "$PWD/site:/input:ro" \
  -v "$PWD/tmp/screenshots:/output" \
  ghcr.io/pankaj28843/docs-html-screenshot:latest \
  --input /input --output /output --allow-http-errors

# Alternative: Local install
# uv tool run docs-html-screenshot --input site --output tmp/screenshots --allow-http-errors
```

The `--flat` flag outputs files like `index.html-screenshot.png`, `tutorials-getting-started-index.html-screenshot.png` for easy drag-and-drop.

### Step 3: Analyze Screenshots with Vision

> **IMPORTANT**: Use your vision capabilities to open and analyze each PNG file. This ensures you catch rendering issues that are not visible in the markdown source.

**Instructions for the Agent:**

1. **Locate Screenshots**: `ls tmp/screenshots/*.png`
2. **Ingest Images**:
   - User can reference with `#filename` (e.g., `#index.html-screenshot.png`)
   - Or drag-and-drop PNGs into chat
   - **If you cannot see the images**, ask the user to attach them
3. **Analyze**: For each image, describe the visual layout and check for errors.

**Output Format** (for easy copy-paste context sharing):
```
### #docs/filename.md ✅ PASS | ⚠️ ISSUES

**Visual description**: [What you see in the screenshot]

**Issues found**: [None | List of problems]
```

**Checklist (Visual Inspection):**

**Visual Structure:**
- [ ] Clear heading hierarchy visible (font sizes, spacing)
- [ ] Proper whitespace between sections
- [ ] Code blocks render with syntax highlighting (colored text)
- [ ] Tables are properly aligned and readable
- [ ] Mermaid diagrams render as graphics (no "Syntax error" text)
- [ ] Navigation sidebar displays correctly
- [ ] Admonition boxes render with colors and icons
- [ ] No horizontal scrolling needed at 1920px width

**Content Quality (per notes.md):**
- [ ] Audience/Prerequisites/Time declared at top
- [ ] Real code examples present (not placeholders)
- [ ] Bullet points used for lists (not long paragraphs)
- [ ] Tables used for comparisons
- [ ] Active voice throughout

**Error Detection:**
- [ ] No console errors in tool output (unless --allow-* flags used)
- [ ] No 404 errors for assets
- [ ] No blank/white pages
- [ ] No broken images

### Step 4: Fix Issues

For each issue found:

1. **Identify source file** - Map screenshot path back to `docs/*.md`
2. **Categorize issue**:
   - Mermaid syntax error → Fix diagram code
   - Long paragraph → Split into bullets
   - Missing spacing → Add blank lines
   - Table alignment → Fix markdown table syntax
   - Console error → Check for JS issues in mkdocs.yml extensions
3. **Apply fix** using `replace_string_in_file` or `multi_replace_string_in_file`
4. **Rebuild and re-screenshot** to verify fix

### Step 5: Validation Loop

```bash
# Rebuild docs
uv run mkdocs build --strict --clean

# Re-run screenshots
rm -rf tmp/screenshots && mkdir -p tmp/screenshots
docker run --rm --init --ipc=host \
  -v "$PWD/site:/input:ro" \
  -v "$PWD/tmp/screenshots:/output" \
  ghcr.io/pankaj28843/docs-html-screenshot:latest \
  --input /input --output /output

# Run unit tests to ensure no code breakage
timeout 60 uv run pytest -m unit --no-cov -q
```

## Common Issues & Fixes

| Screenshot Issue | Source Problem | Fix |
|------------------|----------------|-----|
| Mermaid shows "Syntax error in text" | `<br>` or `<br/>` in Mermaid node labels | Replace with `\\n` or remove HTML tags |
| Long text blocks hard to scan | Paragraphs > 5 sentences | Break into bullet points |
| Table columns misaligned | Markdown pipe alignment off | Realign pipe characters |
| Code block no highlighting | Missing language specifier | Add ` ```python `, ` ```bash `, etc. |
| Blank diagram | Invalid Mermaid syntax | Check arrows `-->`, node IDs, quotes |
| Missing navigation | File not in `mkdocs.yml` nav | Add to `nav:` section |
| 404 on assets | Wrong `site_url` for local preview | Expected for 404.html page locally |

## Iteration Strategy

Run **3 iterations** by default:

1. **Iteration 1**: Capture baseline, use vision to identify critical errors (Mermaid, broken pages)
2. **Iteration 2**: Visually inspect formatting (long paragraphs, table alignment, admonition rendering)
3. **Iteration 3**: Final visual polish and validation

After each iteration, re-screenshot and visually compare to previous captures.

## Output

- Screenshots saved to `tmp/screenshots/` (flat structure for easy `#filename` references)
- **Visual analysis notes** for each page inspected
- Summary of issues found and fixed
- Final validation status (all tests pass, docs build clean)

## Related

- **notes.md**: First principles for documentation quality
- **.github/instructions/docs.instructions.md**: Divio system and writing guidelines
- **.github/instructions/validation.instructions.md**: Full validation loop

## Example Usage

When invoking this prompt:

- **No specific ask**: Analyze all touched docs files from recent changes
- **Specific pages**: "Check tutorials/getting-started.md rendering"
- **Specific issue**: "Fix the Mermaid diagram on architecture page"
- **Full QA**: "Run 3-iteration visual QA on entire docs site"
