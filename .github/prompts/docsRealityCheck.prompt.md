# Documentation Reality Check Prompt

## Purpose
Prevent documentation drift by enforcing reality-grounded workflows. This is an internal developer process—verification artifacts should not appear in published docs.

## Workflow

1. **Before editing docs**: Run all commands you plan to document in your current environment.
2. **Capture output**: Copy-paste actual terminal output into docs.
3. **Never invent outputs**: If you haven't run it, don't document it.
4. **Clean up**: Do not leave verification comments or references in published docs.

## Checklist (All Must Pass)

### Command Verification
- [ ] Every shell command in the diff was executed on this machine within the last 7 days
- [ ] Outputs are copy-pasted from actual terminal runs, not invented
- [ ] Long-running commands (>10s) note duration
- [ ] Destructive commands warn about side effects (e.g., package uninstall)

### Audience Clarity (libgodc standard)
- [ ] Doc declares target audience in the first paragraph
- [ ] Prerequisites stated explicitly (required knowledge, tools)
- [ ] Time estimate provided for tutorials/how-tos
- [ ] "What you'll learn" listed concretely, not vaguely

### How & Why Balance
- [ ] Procedures have step-by-step commands (HOW)
- [ ] Explanations include design rationale (WHY)
- [ ] Troubleshooting section exists with real error messages
- [ ] Every multi-step workflow ends with a verification command

### Anti-Bloat
- [ ] No filler phrases ("As mentioned", "Simply", "Feel free")
- [ ] Every sentence teaches something non-obvious
- [ ] Code comments explain intent (WHY), not mechanics (WHAT)
- [ ] Cross-references use links, not repetition

### Divio Compliance
- [ ] Tutorials = learning-oriented, hand-holding, numbered steps
- [ ] How-To = problem-oriented, concise recipes, verification at end
- [ ] Reference = information-oriented, tables/lists, no opinions
- [ ] Explanations = understanding-oriented, diagrams, trade-offs discussed

## Failure Actions
If any checkbox fails:
1. Re-run commands and capture actual output.
2. Rewrite sections violating clarity/anti-bloat rules.
3. Add missing How/Why content per Divio quadrant.
4. Solicit review before merging.
