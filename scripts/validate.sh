#!/bin/bash
# Validation script for docs-mcp-server

set -e

echo "🔧 Running validation loop..."

echo "📝 Formatting code..."
uv run ruff format .

echo "🔍 Linting code..."
uv run ruff check --fix .

echo "🧪 Running unit tests with coverage..."
timeout 60 uv run pytest -m unit --cov=src/docs_mcp_server --cov-fail-under=95 -q

echo "📚 Building documentation..."
uv run mkdocs build --strict

echo "✅ All validations passed!"
