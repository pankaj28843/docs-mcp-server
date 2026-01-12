# AGENTS.md (docs-mcp-server)

## Primary Instructions
**All coding agents must follow `.github/copilot-instructions.md`** - This is the authoritative source for:
- Core philosophy and design principles
- Runtime guardrails and architectural patterns  
- Validation workflow and testing standards
- Documentation requirements and TechDocs workflow
- Path-specific instructions and prompt library

## Quick Reference

### Core Principles
- **No backward compatibility** - Break things freely unless explicitly requested
- **Minimal code** - Fewer lines over new layers, delete more than you add
- **Deep modules, simple interfaces** - Reduce complexity at boundaries
- **Let exceptions bubble** - No silent error handling

### Mandatory Validation Loop
```bash
# Always use uv run prefix
uv run ruff format . && uv run ruff check --fix .
timeout 60 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95
timeout 120 uv run python integration_tests/ci_mcp_test.py
uv run mkdocs build --strict
```

### Testing Standards
- **>=95% line coverage** enforced via pytest-cov
- **MECE tests** (mutually exclusive, collectively exhaustive)
- **Cosmic Python patterns** - Use FakeRepository for isolation
- **Behavior over implementation** - Test what code does, not how

### Cross-Agent Alignment
This project maintains consistency across multiple AI agents:
- **Kiro CLI**: Auto-approved tools, validation hooks, steering files in `.kiro/`
- **GitHub Copilot**: Repository instructions in `.github/copilot-instructions.md`
- **Gemini CLI**: Shared AGENTS.md standard (this file)
- **All agents**: Same validation loop, code conventions, testing standards

### Execution Environment
- **Maximally permissive** - All tools auto-approved in safe VM environment
- **Debugging-first** - Explicit validation, observability, reproducibility
- **Validation hooks** - Auto-format on write, full validation on completion

### Privacy / Safety
- No local machine details, IPs, or tenant-specific data in code/docs
- No runtime secrets in docs/examples
- Follow security guidelines in `.github/copilot-instructions.md`

## Kiro Steering Integration
This project uses Kiro steering files in `.kiro/steering/` for additional context:
- `product.md` - Product overview and objectives
- `tech.md` - Technology stack and constraints  
- `workflow.md` - Development workflow and cross-agent alignment
- `code-conventions.md` - Python style and anti-patterns
- `testing-standards.md` - Test patterns and coverage requirements

**Note**: Kiro steering files supplement but do not override the primary instructions in `.github/copilot-instructions.md`. In case of conflicts, the GitHub instructions take precedence.
