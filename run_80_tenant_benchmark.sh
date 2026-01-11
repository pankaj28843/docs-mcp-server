#!/bin/bash
# 80-Tenant E2E Benchmark Suite
# PRIVATE - Do not commit to GitHub

set -e

CONFIG_FILE="$1"
if [ -z "$CONFIG_FILE" ]; then
    echo "Usage: $0 <deployment.json>"
    exit 1
fi

echo "🚀 80-Tenant SQLite vs JSON E2E Benchmark"
echo "=========================================="
echo "Config: $CONFIG_FILE"
echo "Time: $(date)"
echo ""

# Ensure we're in the right directory
cd /home/pankaj/Personal/Code/docs-mcp-server

# 1. Clean slate
echo "🧹 Cleaning previous test data..."
find . -name "__search_segments" -type d -exec rm -rf {} + 2>/dev/null || true
docker stop docs-mcp-server 2>/dev/null || true
docker rm docs-mcp-server 2>/dev/null || true

# 2. Run comprehensive benchmark
echo ""
echo "📊 Running comprehensive benchmark..."
uv run python benchmark_80_tenants.py "$CONFIG_FILE"

# 3. Run concurrent load test
echo ""
echo "🔥 Running concurrent load test..."
uv run python load_test_80_tenants.py "$CONFIG_FILE"

# 4. Docker E2E test
echo ""
echo "🐳 Testing Docker deployment with SQLite..."

# Create SQLite config
SQLITE_CONFIG="/tmp/e2e_sqlite_config.json"
python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
config['infrastructure']['search_use_sqlite'] = True
with open('$SQLITE_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
"

# Deploy with Docker
echo "Deploying with SQLite storage..."
uv run python deploy_multi_tenant.py --mode online --config "$SQLITE_CONFIG"

# Wait for deployment
sleep 10

# Test health
echo "Testing health endpoint..."
curl -s http://localhost:42042/health | jq .

# Test search on first 5 tenants
echo "Testing search on sample tenants..."
TENANTS=$(python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
tenants = [t['codename'] for t in config['tenants'][:5]]
print(' '.join(tenants))
")

for tenant in $TENANTS; do
    echo "Testing $tenant..."
    timeout 30 uv run python debug_multi_tenant.py --tenant "$tenant" --test search --config "$SQLITE_CONFIG" > /dev/null
    if [ $? -eq 0 ]; then
        echo "✅ $tenant search OK"
    else
        echo "❌ $tenant search FAILED"
    fi
done

# Cleanup Docker
echo "Cleaning up Docker..."
docker stop docs-mcp-server 2>/dev/null || true

# 5. Compare file sizes
echo ""
echo "📁 File size comparison..."
echo "JSON segments:"
find . -name "*.json" -path "*/__search_segments/*" -exec ls -lh {} + | head -5

echo ""
echo "SQLite segments:"  
find . -name "*.db" -path "*/__search_segments/*" -exec ls -lh {} + | head -5

# 6. Generate final summary
echo ""
echo "📈 Benchmark Complete!"
echo "Results saved to: /home/pankaj/codex-prp-plans/sqlite-benchmark-80-tenants-2026-01-11T02:16:23Z.md"
echo ""
echo "Key metrics to check:"
echo "- Storage size reduction"
echo "- Search latency improvement" 
echo "- Memory usage under load"
echo "- Docker deployment speed"
echo "- Concurrent request handling"
