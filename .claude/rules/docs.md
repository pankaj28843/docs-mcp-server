---
paths:
  - "docs/**/*.md"
  - "README.md"
---

# Documentation Standards (Divio System)

Every doc must fit exactly one quadrant:
1. **Tutorial** - Learning-oriented, hand-holding, "you will learn..."
2. **How-To** - Problem-oriented, imperative, "How to..."
3. **Reference** - Information-oriented, dry, factual, tables
4. **Explanation** - Understanding-oriented, "we chose X because Y..."

## Style Rules
- Active voice, second person ("Edit the file", not "The file should be edited")
- Short paragraphs (3-5 sentences max)
- Real, runnable code examples - never invent "Expected output" blocks
- `mkdocs build --strict` before committing
- Cross-reference related docs in other quadrants

## Anti-Bloat
- Delete: "As mentioned earlier", "It should be noted", "Simply run", "Feel free to"
- Comment intent, not mechanics - if the code explains itself, no comment needed
- README under 200 lines - defer details to `docs/`
