## What is PRP?

Product Requirement Prompt (PRP)

## In short

A PRP is PRD + curated codebase intelligence + agent/runbook—the minimum viable packet an AI needs to plausibly ship production-ready code on the first pass.

Product Requirement Prompt (PRP) is a structured prompt methodology first established in summer 2024 with context engineering at heart. A PRP supplies an AI coding agent with everything it needs to deliver a vertical slice of working software—no more, no less.

### How PRP Differs from Traditional PRD

A traditional PRD clarifies what the product must do and why customers need it, but deliberately avoids how it will be built.

A PRP keeps the goal and justification sections of a PRD yet adds three AI-critical layers:

### Context

Precise file paths and content, library versions and library context, code snippets examples. LLMs generate higher-quality code when given direct, in-prompt references instead of broad descriptions. Usage of a ai_docs/ directory to pipe in library and other docs.

## Creating Effective PRP Plans

### When to Create a PRP Plan

Create a detailed PRP plan for **non-trivial** tasks that require:
- **Multiple actions** across several files or modules
- **Complex logic** that needs careful analysis before implementation
- **Refactoring** that impacts existing functionality
- **Integration** between multiple systems or services
- **Testing strategy** that spans multiple layers (unit, integration, e2e)

**Skip PRP planning for trivial tasks** like:
- Single file edits or bug fixes
- Adding simple fields to models
- Basic configuration changes
- Straightforward documentation updates

### PRP Plan Structure

A comprehensive PRP plan should include:

#### 1. Goal (What & Why)
- **What**: Clear, specific description of what needs to be built/changed
- **Why**: Business justification and value proposition
- **Success Criteria**: Measurable outcomes and acceptance criteria

#### 2. Current State Analysis
- **Existing Code Review**: Detailed analysis of current implementation
- **Dependencies**: What systems/modules are involved
- **Constraints**: Technical limitations or requirements
- **Risk Assessment**: What could go wrong and mitigation strategies

#### 3. Implementation Blueprint
- **Phased Approach**: Break work into logical, sequential phases
- **File-by-File Changes**: Specific files that need modification
- **Data Structures**: New models, fields, or schema changes needed
- **API Changes**: New endpoints or modifications to existing ones
- **Testing Strategy**: What needs to be tested and how

#### 4. Context & Anti-Patterns
- **Known Gotchas**: Project-specific patterns and pitfalls to avoid
- **Code Quality Standards**: Style guides and quality requirements
- **Integration Points**: How changes interact with existing systems
- **docs-mcp-server Patterns**: Cosmic Python, FastMCP, and BM25 conventions

#### 5. Validation Loop
- **Level 1**: Syntax, imports, and basic compilation
- **Level 2**: Unit tests and focused validation (`uv run pytest -m unit --no-cov`)
- **Level 3**: Integration tests (`uv run python debug_multi_tenant.py`)
- **Level 4**: Docker deployment and end-to-end validation

### Anti-Patterns in PRP Planning

**Avoid These Planning Mistakes**:

**Over-Planning Trivial Tasks**:
- Don't create 50-line PRPs for single-method changes
- Skip formal planning for obvious implementations
- Use judgment - if it's a 5-minute fix, just do it

**Under-Analyzing Complex Changes**:
- Don't start coding complex refactors without understanding current state
- Always analyze existing patterns before introducing new ones
- Map out dependencies and integration points first

**Generic Implementation Blueprints**:
- Avoid vague steps like "update the models" or "add tests"
- Include specific file paths, method names, and code patterns
- Reference existing code examples and conventions

**Missing Anti-Pattern Analysis**:
- Always include project-specific patterns to follow/avoid
- Document quality standards and tooling requirements
- Include validation steps that catch common mistakes

**Inadequate Context Gathering**:
- Don't assume - search existing codebase for similar patterns
- Include related code snippets and integration examples
- Document dependencies and potential side effects

### Example PRP Plan Quality Markers

**High-Quality PRP Plan Indicators**:
- Includes specific file paths and method names
- References existing code patterns and conventions
- Has concrete validation steps with actual commands
- Breaks complex work into logical phases
- Documents anti-patterns and gotchas specific to the project
- Includes risk mitigation strategies
- Has measurable success criteria

**Low-Quality PRP Plan Red Flags**:
- Vague implementation steps
- No analysis of existing code
- Missing validation strategy
- Generic advice not specific to the project
- No anti-pattern documentation
- Lacks concrete examples and references

## docs-mcp-server Specific Context

### Key Files to Reference
```yaml
- file: .github/copilot-instructions.md
  sections: "Core Philosophy, Definition of Done, Validation Loop"
  why: Prime directives and quality gates

- file: src/docs_mcp_server/app.py
  why: Main ASGI entry point, tenant routing

- file: src/docs_mcp_server/tenant.py
  why: Tenant factory, DDD aggregate pattern

- file: deployment.json
  why: All tenant configurations

- file: src/docs_mcp_server/search/bm25_engine.py
  why: Search ranking algorithm
```

### Validation Commands
```bash
# Format and lint
uv run ruff format . && uv run ruff check --fix .

# Unit tests
timeout 60 uv run pytest -m unit --no-cov

# Integration testing
uv run python debug_multi_tenant.py --tenant <codename>

# Docker deployment
uv run python deploy_multi_tenant.py --mode online

# Docker testing
uv run python debug_multi_tenant.py --host localhost --port 42042 --tenant <codename>
```
