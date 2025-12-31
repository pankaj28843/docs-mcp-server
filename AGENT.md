# Codex Agent Handbook

## TechDocs-first workflow

1. **List tenants before every major change**  
   Always run `TechDocs:list_tenants` so you know what documentation sources the MCP server exposes (e.g., `pytest`, `python`, `uv`, `fastapi`, `playwright`, etc.).

2. **Pick the most targeted tenant**  
   - Runtime/standard-library questions → `python`.  
   - Test infrastructure, CLI flags, or plugins → `pytest`.  
   - `uv`/CLI tooling → `uv`.  
   - HTTP, routing, and MCP endpoints → `fastapi`/`starlette`.  
   - Browser automation → `playwright`.

3. **Search the tenant before guessing**  
   Use `TechDocs:search` scoped to the selected tenant (e.g., “`pytest-timeout`” in the `pytest` tenant, “`asyncio wait_for`” in the `python` tenant). Capture the tenant + URL so you can cite it later.

4. **Document every recurring rule you learn**  
   If you discover a guardrail (e.g., always prefix `uv run pytest` with `timeout 60`, `asyncio.wait_for` cancels awaited tasks and raises `TimeoutError`, etc.), add it here along with the TechDocs citation.

5. **Cite your sources**  
   When describing behavior in notes, code comments, or plans, mention the tenant URL (for example: “https://docs.pytest.org/en/stable/plugins.html: pytest-timeout provides per-test/global timeouts”). This keeps the chain of evidence intact.

6. **Trust TechDocs over guesswork**  
   Before refactoring or debugging, check the relevant tenant for the expected behavior so we don’t invent semantics that conflict with the official docs.

## Repository guardrails

- **Consult `.github/copilot-instructions.md` regularly** (link it here) for the repo-specific mandate list—particularly that every `uv run pytest ...` command must be wrapped with `timeout 60`, `pytest-timeout` should remain enabled, and interruptions should provide stack traces.  
- **Let pytest report timeout exceptions**. The `pytest-timeout` plugin (https://docs.pytest.org/en/stable/plugins.html#pytest-timeout) exists so we can see where tests hang; don’t swallow the exception.  
- **Use `asyncio.wait_for` knowledge**. The CPython docs (https://docs.python.org/3.13/library/asyncio-task.html#asyncio.wait_for) explain that `wait_for` cancels the awaited task and raises `TimeoutError` when the deadline hits—use this to pinpoint stuck awaits.  
- **Command discipline**: always run Python tooling via `uv run`, prefix long-running runs with `timeout` (e.g., `timeout 60 uv run pytest …`), and use `time` when you need to know the wall-clock duration so we can measure regressions.

## Keeping the handbook current

Every time you learn a new MCP workflow detail, add it here so future agents inherit the knowledge. If `.github/copilot-instructions.md` already covers a rule, summarize it here with a link; if not, add the new rule plus the TechDocs citation that taught it.
