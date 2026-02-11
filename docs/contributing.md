# Contributing

## Development Workflow

```bash
# 1. Install dependencies
uv sync --extra dev

# 2. Run code quality checks
uv run ruff format . && uv run ruff check --fix .

# 3. Verify docs build
uv run mkdocs build --strict

# 4. Run unit tests
timeout 120 uv run pytest -m unit
```

## Git Hooks (pre-commit)

This repo uses `pre-commit` hooks for formatting and safety checks.

```bash
uv run pre-commit install
uv run pre-commit install --hook-type pre-push
```

!!! example "Critical Validation Scripts"
    Run these to verify changes work end-to-end:
    
    ```bash
    uv run python debug_multi_tenant.py --tenant drf --test search
    uv run python trigger_all_syncs.py --tenants aidlc-rules --force
    uv run python trigger_all_indexing.py --tenants drf django
    uv run python deploy_multi_tenant.py --mode online
    ```

---

## Verifying Documentation

!!! warning "Reality Grounding"
    Before documenting commands, **run them and capture actual output**. Paste real terminal output into docs—never invent "Expected output" blocks. This ensures docs stay accurate.

See [How-To: Preview Docs Locally](how-to/preview-docs-locally.md) for the live-reload workflow and verified output.

See [How-To: Create Demo Artifacts (Showboat / Rodney)](how-to/create-demo-artifacts.md) for agent-friendly proof documents that capture command outputs.

---

## Documentation Standards

!!! info "Divio Quadrants"
    Every doc must fit exactly one category:
    
    - **Tutorial**: Learning-oriented, step-by-step guide
    - **How-To**: Problem-oriented recipe for specific task
    - **Reference**: Factual, exhaustive lookup information
    - **Explanation**: Understanding-oriented discussion

**Additional guidelines**:

- Include verification at the end of every procedure
- Avoid filler words ("Simply", "Feel free", "As mentioned earlier")
- Keep README concise (<200 lines) and defer detail to docs/

---

## Getting Help

| Resource | Location |
|----------|----------|
| Validation details | `.github/instructions/validation.instructions.md` |
| Docs standards | `.github/instructions/docs.instructions.md` |
| Reality checks | `.github/prompts/docsRealityCheck.prompt.md` |
