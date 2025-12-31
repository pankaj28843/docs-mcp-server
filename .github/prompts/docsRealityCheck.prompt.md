# Documentation Reality Check Prompt

## Purpose
Prevent documentation drift by enforcing reality-grounded workflows.

## Checklist (All Must Pass)

### Command Verification
- [ ] Every shell command in the diff was executed on this machine within the last 7 days
- [ ] Outputs are copy-pasted from `docs/_reality-log/`, not invented
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

## Reality Log Citation
If adding/changing commands, reference the Reality Log entry:
```
<!-- Verified: docs/_reality-log/phase2.md#deploy-flow (2025-12-31) -->
```

## Failure Actions
If any checkbox fails:
1. Re-run commands and update Reality Log.
2. Rewrite sections violating clarity/anti-bloat rules.
3. Add missing How/Why content per Divio quadrant.
4. Solicit review before merging.
