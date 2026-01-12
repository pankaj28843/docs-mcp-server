#!/bin/bash
# Comprehensive linting script to address PR review comments
# Auto-fixes unused imports, redundant imports, and other common issues

set -e

echo "🔍 Running comprehensive linting..."

# Format code first
echo "📝 Formatting code..."
uv run ruff format .

# Fix all auto-fixable issues including:
# - F401: unused imports
# - F811: redefined unused imports  
# - I001: import sorting
# - UP: pyupgrade modernizations
echo "🔧 Auto-fixing linting issues..."
uv run ruff check --fix .

# Check for remaining issues
echo "✅ Final lint check..."
uv run ruff check .

echo "🎉 Comprehensive linting complete!"
