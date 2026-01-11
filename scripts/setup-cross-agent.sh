#!/bin/bash
# Setup script for cross-agent alignment and maximally permissive Kiro configuration

set -e

echo "🔧 Setting up cross-agent development environment..."

# Ensure global Kiro directory exists
mkdir -p ~/.kiro/steering

# Create global maximally permissive configuration
cat > ~/.kiro/config.json << 'EOF'
{
  "autoApprove": ["*"],
  "tools": ["*"],
  "toolsSettings": {
    "shell": {
      "autoAllowReadonly": true
    }
  },
  "hooks": {
    "agentSpawn": [
      {
        "command": "echo '🚀 Global Kiro environment ready - all tools auto-approved'"
      }
    ]
  }
}
EOF

echo "✅ Global Kiro configuration created with maximally permissive settings"

# Ensure project validation script is executable
chmod +x ./scripts/validate.sh

echo "✅ Validation script permissions set"

# Verify all steering files exist
echo "📋 Checking steering files..."
for file in product.md tech.md workflow.md code-conventions.md testing-standards.md prompt.md; do
  if [[ -f ".kiro/steering/$file" ]]; then
    echo "  ✅ .kiro/steering/$file"
  else
    echo "  ❌ Missing: .kiro/steering/$file"
  fi
done

# Verify GitHub Copilot instructions exist
if [[ -f ".github/copilot-instructions.md" ]]; then
  echo "  ✅ .github/copilot-instructions.md"
else
  echo "  ❌ Missing: .github/copilot-instructions.md"
fi

# Verify AGENTS.md exists
if [[ -f "AGENTS.md" ]]; then
  echo "  ✅ AGENTS.md"
else
  echo "  ❌ Missing: AGENTS.md"
fi

echo ""
echo "🎯 Cross-agent alignment setup complete!"
echo ""
echo "Configuration summary:"
echo "  • Kiro: Auto-approved tools, validation hooks, steering files"
echo "  • GitHub Copilot: .github/copilot-instructions.md + AGENTS.md"
echo "  • Gemini CLI: Shared AGENTS.md standard"
echo "  • All agents: Same validation loop and code conventions"
echo ""
echo "To test the setup:"
echo "  kiro-cli chat"
echo "  /tools trust-all  # (if needed)"
echo ""
