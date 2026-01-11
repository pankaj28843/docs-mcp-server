#!/usr/bin/env python3
"""Lightweight benchmark: JSON vs SQLite for two tenants of different sizes."""

import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List

from docs_mcp_server.deployment_config import DeploymentConfig
from docs_mcp_server.tenant import tenant


async def benchmark_search(tenant_obj, queries: List[str]) -> Dict[str, float]:
    """Benchmark search performance."""
    times = []
    
    for query in queries:
        start = time.perf_counter()
        results = await tenant_obj.search(query, size=10)
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms
    
    return {
        "avg_ms": sum(times) / len(times),
        "p95_ms": sorted(times)[int(len(times) * 0.95)],
        "min_ms": min(times),
        "max_ms": max(times)
    }


def get_storage_stats(storage_path: Path) -> Dict[str, float]:
    """Get storage size statistics."""
    json_files = list(storage_path.glob("*.json"))
    json_size = sum(f.stat().st_size for f in json_files)
    
    sqlite_files = list(storage_path.glob("*.db*"))
    sqlite_size = sum(f.stat().st_size for f in sqlite_files) if sqlite_files else 0
    
    return {
        "json_mb": json_size / (1024 * 1024),
        "sqlite_mb": sqlite_size / (1024 * 1024)
    }


async def main():
    """Run lightweight benchmark."""
    
    queries = ["serializer", "authentication", "viewset", "model field", "permission"]
    
    # Load configs
    json_config = DeploymentConfig.from_file("deployment.json")
    sqlite_config = DeploymentConfig.from_file("deployment.sqlite.json")
    
    # Test two tenants of different sizes
    tenant_names = ["drf", "django"]
    
    for tenant_name in tenant_names:
        print(f"\n=== {tenant_name.upper()} ===")
        
        # Create tenant instances
        json_tenant = tenant(tenant_name, json_config.tenants[tenant_name], json_config.infrastructure)
        sqlite_tenant = tenant(tenant_name, sqlite_config.tenants[tenant_name], sqlite_config.infrastructure)
        
        # Get storage stats
        json_stats = get_storage_stats(json_tenant.storage_path)
        sqlite_stats = get_storage_stats(sqlite_tenant.storage_path)
        
        print(f"JSON: {json_stats['json_mb']:.1f}MB")
        print(f"SQLite: {sqlite_stats['sqlite_mb']:.1f}MB")
        
        # Benchmark performance
        print("Testing JSON...")
        json_perf = await benchmark_search(json_tenant, queries)
        
        print("Testing SQLite...")
        sqlite_perf = await benchmark_search(sqlite_tenant, queries)
        
        # Compare results
        size_ratio = sqlite_stats['sqlite_mb'] / json_stats['json_mb'] if json_stats['json_mb'] > 0 else 0
        speed_ratio = json_perf['avg_ms'] / sqlite_perf['avg_ms'] if sqlite_perf['avg_ms'] > 0 else 0
        
        print(f"JSON avg: {json_perf['avg_ms']:.1f}ms")
        print(f"SQLite avg: {sqlite_perf['avg_ms']:.1f}ms")
        print(f"Size ratio: SQLite {size_ratio:.1f}x")
        print(f"Speed ratio: SQLite {speed_ratio:.1f}x {'faster' if speed_ratio > 1 else 'slower'}")


if __name__ == "__main__":
    asyncio.run(main())
