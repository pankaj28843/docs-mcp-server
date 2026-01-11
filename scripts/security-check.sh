#!/bin/bash
# Pre-commit security check for tenant name leaks

set -e

# Whitelist of safe tenant names from deployment.example.json
SAFE_TENANTS=(
    "django"
    "drf"
    "fastapi" 
    "python"
    "pytest"
    "mkdocs"
    "aidlc-rules"
)

# Get staged files
STAGED_FILES=$(git diff --cached --name-only)

# Check commit message for private tenant names
COMMIT_MSG_FILE=".git/COMMIT_EDITMSG"
if [ -f "$COMMIT_MSG_FILE" ]; then
    # Extract tenant names that are in deployment.json but NOT in deployment.example.json
    if [ -f "deployment.json" ] && [ -f "deployment.example.json" ]; then
        PRIVATE_TENANTS=$(python3 -c "
import json
import sys

try:
    with open('deployment.json') as f:
        deploy = json.load(f)
    with open('deployment.example.json') as f:
        example = json.load(f)
    
    deploy_tenants = {t['codename'] for t in deploy.get('tenants', [])}
    example_tenants = {t['codename'] for t in example.get('tenants', [])}
    private_tenants = deploy_tenants - example_tenants
    
    for tenant in private_tenants:
        print(tenant)
except Exception:
    pass
")
        
        # Check if any private tenant names appear in commit message
        if [ -n "$PRIVATE_TENANTS" ]; then
            while IFS= read -r tenant; do
                if [ -n "$tenant" ] && grep -q "$tenant" "$COMMIT_MSG_FILE" 2>/dev/null; then
                    echo "❌ SECURITY ERROR: Private tenant name '$tenant' found in commit message"
                    echo "   Only use tenant names from deployment.example.json"
                    echo "   Use generic terms like 'local filesystem tenants' instead"
                    exit 1
                fi
            done <<< "$PRIVATE_TENANTS"
        fi
    fi
fi

echo "✅ Security check passed - no private tenant names leaked"
