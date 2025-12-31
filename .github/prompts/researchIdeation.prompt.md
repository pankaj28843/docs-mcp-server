---
name: researchIdeation
description: Explore solution options using TechDocs and repo intel before deciding on code changes.
argument-hint: topic="BM25 scoring improvements" focus="src/docs_mcp_server/search/"
---

## TechDocs Research (Primary Focus)
This prompt centers on `#techdocs` exploration. Prioritize tenants based on the question: `cosmicpython` for patterns, `fastmcp`/`mcp` for tool schemas, `github-copilot` for prompt inspiration. Run `list_tenants` first to discover available architecture and design documentation sources. Follow **.github/instructions/techdocs.instructions.md** for method.

## Goals
- Clarify the problem, constraints, and possible approaches before coding.
- Surface prior art inside this repo (modules, tests, docs) plus TechDocs evidence that informs design trade-offs.
- End with actionable recommendations (next prompt to run, risks, approvals needed).

## Workflow
1. **Inventory sources**: `mcp_techdocs_list_tenants()` → `mcp_techdocs_describe_tenant()` for relevant tenants.
2. **Search smart**: Run focused `mcp_techdocs_root_search` queries. Fetch only high-signal documents and capture URL + snippet references.
3. **Repo sweep**: Use `file_search`, `grep_search`, or targeted `read_file` calls to collect concrete references (paths + line ranges) inside `src/docs_mcp_server/`.
4. **Synthesize**: Organize findings into options (status quo, incremental refactor, new feature slice, spike). Highlight dependencies and cite the relevant docs.
5. **Recommend next action**: Choose the follow-up prompt (bugFix, featureSliceDelivery, cleanCodeRefactor, prpPlanOnly, testHardening, etc.) and list prerequisites or approvals.

## Output
- Narrative covering problem recap → research findings → recommendation, with inline links to repo paths and TechDocs references.
- Bullet list of supporting evidence (TechDocs URLs + repo files/lines).
- Open questions or risks clearly flagged. No code/test changes.
