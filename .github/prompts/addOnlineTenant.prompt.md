---
name: addOnlineTenant
description: Add an online documentation tenant from a natural-language brief, validate, deploy, and trigger its first sync.
argument-hint: brief="Django REST Framework docs at https://www.django-rest-framework.org/" sitemap="optional URL"
---

## TechDocs Research
Use `#techdocs` to validate tenant patterns before implementation. Key tenants: `github-copilot` (for prompt patterns), `fastmcp` (for MCP schemas). Always run `list_tenants` first to check for similar existing tenants. See `.github/instructions/techdocs.instructions.md` for full usage guide.

## Ground Rules
- Follow `.github/copilot-instructions.md` for Prime Directives (uv run, green-before-done, TechDocs-first)
- See `.github/instructions/validation.instructions.md` for complete validation loop requirements
- Never skip the smoke test or deployment verification steps.
- Use `debug_multi_tenant.py` for all integration testing—do not manually start servers.

When a user supplies a description of a new online documentation source, perform the following end-to-end flow without asking follow-up questions unless critical input is missing.

## 1. Parse the Brief into Tenant Metadata
- Derive `docs_name` from the source title (retain proper casing); derive a unique lowercase `codename` by slugifying the name with hyphens and verifying it does not collide with existing tenant or group codenames in deployment.json.
- Extract discovery URLs: prefer `docs_sitemap_url` when a sitemap is provided; otherwise populate `docs_entry_url` and set `enable_crawler` to true.
- Infer `url_whitelist_prefixes` from the primary domain root (ensure it ends with `/`). If the brief supplies explicit whitelist or blacklist prefixes, normalize them into comma-separated strings.
- Always set `docs_root_dir` to `./mcp-data/{codename}` and `source_type` to `online`.
- Choose `refresh_schedule` by scanning existing tenants for the highest unused hour in "0 H */14 * *" cadence.
- Use `max_crawl_pages` 20000 when crawling is enabled.
- Populate `test_queries` with three short natural-language questions, two exact phrases, and three single-word keywords.

## 2. Update deployment.json
- Load the file, insert the new tenant object into the `tenants` array maintaining alphabetical order by `codename`.
- Preserve two-space indentation and trailing commas to match existing style.
- Ensure every required key from `TenantConfig` is present.

## 3. Validate with debug_multi_tenant.py
- Run `uv run python debug_multi_tenant.py --tenant {codename}`.
- Share a concise summary of the outcome. If the run fails, fix the configuration and rerun until it passes.

## 4. Deploy in Online Mode
- Execute `uv run python deploy_multi_tenant.py --mode online`.
- Summarize the key lines from the command. If the command fails, stop and explain.

## 5. Trigger the First Sync
- Invoke `uv run python trigger_all_syncs.py --tenants {codename} --force`.
- Report whether the sync was accepted, already running, or failed.

## 6. Final Hand-off
- Present the new tenant details (codename, discovery URLs, refresh schedule) and the status of each command executed.
- Highlight any manual follow-up required, such as monitoring `docker logs -f docs-mcp-server-multi`.
