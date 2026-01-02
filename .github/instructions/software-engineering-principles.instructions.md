---
applyTo: "src/docs_mcp_server/**"
---

# docs-mcp-server Engineering Principles

**Audience**: Maintainers and contributors touching `src/docs_mcp_server`.  
**Purpose**: Capture the house rules for simplifying the runtime without referencing external playbooks.  
**TL;DR**: Deep modules, minimal interfaces, zero boilerplate.

## Simplicity Over Patterns
- Prefer one well-factored module over sprawling helper layers. If an abstraction does not delete duplication, delete the abstraction instead.
- Default to composition. Configuration flags exist only when we have at least two real callers that need different behavior.
- We never cargo-cult patterns—measure the change in lines-of-code and touch-points to prove a refactor pulled complexity downward.
- Watch the change amplification / cognitive load / unknown-unknowns triad. If a feature edit touches more than one module for the same concept, stop and reshape the boundary before merging.
- Remove pass-through functions. Every public method must enforce an invariant or transform data; forwarders without behavior are deleted or inlined.
- Prefer slightly more general modules over narrow helpers. When in doubt, collapse the behavior into an existing context so callers only need one import.

## Information Hiding
- A tenant's infrastructure knowledge lives in one context object. Changing a crawler timeout or Git branch should require editing that context only.
- Search, sync, and FastMCP adapters communicate through DTOs. Domain code never imports Starlette, FastMCP, or HTTP layers.
- `StorageContext`, `IndexRuntime`, and `SyncRuntime` encapsulate their own invariants. Add fields or helpers inside those classes instead of checking raw config in unrelated files.
- Avoid boolean webs. When a lifecycle requires multiple flags, introduce a dedicated runtime object with clear methods like `ensure_ready()` or `is_resident()`.

## App Builder & Tenant Runtimes
- `AppBuilder` in `src/docs_mcp_server/app_builder.py` is the only entrypoint for wiring routes, health endpoints, and MCP surfaces. Extend the builder or `runtime/` helpers; do not reintroduce bespoke logic into `app.py`.
- Tenant construction flows through `create_tenant_app()` which already assembles `StorageContext`, `IndexRuntime`, and `SyncRuntime`. Adding tenant behavior means extending those contexts, not sprinkling new globals.
- New startup or shutdown hooks must plug into the builder's lifespan manager so drain logic always runs through a single path.
- Health endpoints and CLI tooling consume runtime state via the contexts/owner objects—never recompute residency by scanning the filesystem at request time.

## Scheduler + Search Contracts
- All schedulers (crawler or git) implement the same protocol: `initialize()`, `trigger_sync()`, `stats`, `stop()`. HTTP endpoints treat them identically.
- Search services expose a synchronous "core scorer" plus thin async shells. Unit tests target the core; integration tests exercise the shell via Fake contexts.
- `services/scheduler_protocol.py` defines the contract. Any scheduler-specific feature must live behind that protocol so `/sync/*` endpoints never branch on tenant type.
- Shared retry/backoff helpers live with the protocol. If a scheduler needs a new dial, add it once and keep the implementation symmetrical across crawler + git paths.

## Background Work Discipline
- Every recurring task has a single owner object responsible for lifecycle (`start`, `stop`, `drain`). No anonymous asyncio tasks.
- Health endpoints report residency/readiness from those owners instead of recomputing derived state.
- Do not spin new background tasks from random call sites. Thread everything through the owning runtime so shutdown, health, and telemetry stay honest.

## Complexity Red Flags
- Change amplification: needing to edit AppBuilder, TenantServices, and a scheduler for the same behavior means the boundaries leaked—refactor before adding features.
- Cognitive load spikes: if you need to explain a module with "and/or/but", split it until each class has one reason to change.
- Obscure invariants: whenever flags or ad-hoc dicts encode residency, promote them to a named object and surface explicit methods.
- Unknown-unknowns: duplicated cron math, index warmup logic, or config parsing indicates missing shared helpers. Consolidate before extending functionality.

## Testing + Tooling Expectations
- Favor fakes over mocks. If a collaborator is hard to fake, refactor it until it becomes trivial.
- Validation commands in `.github/instructions/validation.instructions.md` are non-negotiable. A change is incomplete until the full loop is green.

## Documentation
- Internal docs (like this file) describe *what we do* in our own words. User-facing docs live under `docs/` and follow the Divio quadrants.
- Record rationale in these instructions or architecture docs instead of code comments. Once a principle graduates into process, delete stale inline commentary.

## Naming & Comments
- Names broadcast purpose. Persistent entities (tenants, contexts, runtimes, schedulers) need descriptive nouns; short-lived loops may use `i/j` but exported symbols never do.
- Comment intent, not mechanics. When behavior is unclear, refactor until the code explains itself, then add a short note only for non-obvious math or invariants.
- When describing architecture, reference internal files (this doc, architecture explanation) rather than external books.
