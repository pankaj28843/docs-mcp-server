---
paths:
  - "src/docs_mcp_server/**"
---

# Engineering Principles

## Simplicity Over Patterns
- Prefer one well-factored module over sprawling helper layers
- Default to composition. Configuration flags only with 2+ real callers needing different behavior
- Remove pass-through functions - every public method must enforce an invariant or transform data
- Watch the change amplification / cognitive load / unknown-unknowns triad

## Information Hiding
- A tenant's infrastructure knowledge lives in one context object
- Search, sync, and FastMCP adapters communicate through DTOs
- Domain code never imports web framework, FastMCP, or HTTP layers
- `StorageContext`, `IndexRuntime`, and `SyncRuntime` encapsulate their own invariants

## Background Work Discipline
- Every recurring task has a single owner object responsible for lifecycle (`start`, `stop`, `drain`)
- Health endpoints report residency/readiness from those owners
- No anonymous asyncio tasks - thread everything through owning runtimes

## Complexity Red Flags
- Change amplification: editing AppBuilder + TenantServices + scheduler for same behavior = leaked boundaries
- Cognitive load spikes: if you explain a module with "and/or/but", split it
- Boolean webs: when lifecycle needs multiple flags, introduce a dedicated runtime object

## AI-Bloat Prevention
- No giant drops: prefer small, incremental diffs
- No verbose/obvious comments, no placeholder TODOs
- No backward-looking comments about how code "used to work"
- Function complexity >15 -> refactor; single function >120 LOC -> refactor
