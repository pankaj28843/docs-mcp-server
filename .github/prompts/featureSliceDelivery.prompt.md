---
name: featureSliceDelivery
description: Implement a vertical slice (model/service/api/tests) for a new capability.
argument-hint: feature="short name" scope="files or services" verification="command"
---

## TechDocs Research
Use `#techdocs` to validate patterns before implementation. Key tenants: `cosmicpython`, `fastmcp`, `mcp`, `python`. Always run `list_tenants` first, then `describe_tenant` to get optimal queries. See **.github/instructions/techdocs.instructions.md** for full usage guide.

## Ground Rules
- Start from a plan (use prpPlanOnly if not done). Break delivery into thin commits.
- Apply Cosmic Python architecture rules: keep entrypoints thin, push logic into services, reuse shared utilities.
- Use debug_multi_tenant.py for all integration testing—never manually start servers.

## Delivery Flow
1. **Context sync**: Read existing models/services, note dependencies, confirm config requirements.
2. **Design mini blueprint**: Outline data shape, MCP tools, and tests before coding.
3. **Implement in layers** (stop after each to validate):
   - Data/model changes (if needed).
   - Service layer + domain logic.
   - Entry points (MCP tools, endpoints).
   - Tests (unit + integration as appropriate).
4. **Documentation** (REQUIRED for new features):
   - Determine Divio quadrant(s):
     - **Tutorial**: If feature needs step-by-step learning journey
     - **How-To**: If feature solves specific user task
     - **Reference**: If feature adds new config/CLI options
     - **Explanation**: If feature changes architecture/design
   - Create or update docs in `docs/` using templates from `.github/instructions/docs.instructions.md`
   - Add to `mkdocs.yml` navigation
   - Run `mkdocs build --strict` to validate
5. **Validation**:
   - `timeout 60 uv run pytest -m unit --no-cov`
   - `uv run python debug_multi_tenant.py --tenant <codename>`
   - `uv run ruff check <each touched file>`
   - `mkdocs build --strict` (if docs changed)

## Output
- Summary of scope + files touched per layer.
- Commands run with outcomes.
- Follow-up checklist (deploy steps, config) if any.
