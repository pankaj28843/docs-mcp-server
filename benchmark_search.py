#!/usr/bin/env python3
"""
Performance benchmarking tool for docs-mcp-server search functionality.

Establishes baseline measurements for:
- Latency (P50, P95, P99)
- Memory usage per tenant
- CPU utilization under load
- Concurrent user simulation

Usage:
    uv run python benchmark_search.py --tenant django --queries 1000 --concurrent 10
"""

import asyncio
import time
import tracemalloc
import psutil
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Dict, Any
import argparse
import json
import sys
import requests
from pathlib import Path


@dataclass
class BenchmarkResult:
    """Performance benchmark results."""
    tenant: str
    total_queries: int
    concurrent_users: int
    
    # Latency metrics (milliseconds)
    latency_p50: float
    latency_p95: float
    latency_p99: float
    latency_mean: float
    latency_max: float
    
    # Memory metrics (MB)
    memory_peak_mb: float
    memory_current_mb: float
    
    # CPU metrics (%)
    cpu_percent: float
    
    # Throughput
    queries_per_second: float
    
    # Error metrics
    success_count: int
    error_count: int
    error_rate: float


class SearchBenchmark:
    """Performance benchmark for search functionality."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:42042"):
        self.base_url = base_url
        self.test_queries = [
            "authentication",
            "models and databases", 
            "REST API",
            "serializers",
            "permissions",
            "views and viewsets",
            "routing",
            "middleware",
            "testing",
            "deployment"
        ]
    
    def single_search_request(self, tenant: str, query: str) -> Dict[str, Any]:
        """Execute a single search request and measure latency."""
        start_time = time.perf_counter()
        
        try:
            response = requests.post(
                f"{self.base_url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "root_search",
                        "arguments": {
                            "tenant_codename": tenant,
                            "query": query,
                            "size": 10
                        }
                    }
                },
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=30
            )
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            if response.status_code == 200:
                result = response.json()
                if "error" not in result:
                    return {
                        "success": True,
                        "latency_ms": latency_ms,
                        "results_count": len(result.get("result", {}).get("content", [{}])[0].get("results", []))
                    }
            
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": f"HTTP {response.status_code}: {response.text[:200]}"
            }
            
        except Exception as e:
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": str(e)
            }
    
    def run_concurrent_benchmark(self, tenant: str, num_queries: int, concurrent_users: int) -> BenchmarkResult:
        """Run concurrent benchmark with multiple users."""
        print(f"🚀 Starting benchmark: {num_queries} queries, {concurrent_users} concurrent users")
        
        # Start memory tracking
        tracemalloc.start()
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Prepare query list
        queries = []
        for i in range(num_queries):
            query = self.test_queries[i % len(self.test_queries)]
            queries.append(query)
        
        # Execute concurrent requests
        start_time = time.perf_counter()
        results = []
        
        with ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = []
            for query in queries:
                future = executor.submit(self.single_search_request, tenant, query)
                futures.append(future)
            
        # Collect results
        for future in futures:
            result = future.result()
            results.append(result)
            if not result["success"]:
                print(f"❌ Error: {result['error']}")  # Debug output
        
        end_time = time.perf_counter()
        total_duration = end_time - start_time
        
        # Memory measurements
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        cpu_percent = process.cpu_percent()
        
        # Calculate metrics
        successful_results = [r for r in results if r["success"]]
        failed_results = [r for r in results if not r["success"]]
        
        if successful_results:
            latencies = [r["latency_ms"] for r in successful_results]
            latency_p50 = statistics.median(latencies)
            latency_p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
            latency_p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile
            latency_mean = statistics.mean(latencies)
            latency_max = max(latencies)
        else:
            latency_p50 = latency_p95 = latency_p99 = latency_mean = latency_max = 0
        
        return BenchmarkResult(
            tenant=tenant,
            total_queries=num_queries,
            concurrent_users=concurrent_users,
            latency_p50=latency_p50,
            latency_p95=latency_p95,
            latency_p99=latency_p99,
            latency_mean=latency_mean,
            latency_max=latency_max,
            memory_peak_mb=peak_memory / 1024 / 1024,
            memory_current_mb=final_memory,
            cpu_percent=cpu_percent,
            queries_per_second=num_queries / total_duration,
            success_count=len(successful_results),
            error_count=len(failed_results),
            error_rate=len(failed_results) / num_queries * 100
        )
    
    def print_results(self, result: BenchmarkResult):
        """Print benchmark results in a readable format."""
        print("\n" + "="*60)
        print(f"📊 BENCHMARK RESULTS - {result.tenant.upper()}")
        print("="*60)
        
        print(f"\n🎯 Test Configuration:")
        print(f"   Total Queries: {result.total_queries}")
        print(f"   Concurrent Users: {result.concurrent_users}")
        
        print(f"\n⚡ Latency Metrics (ms):")
        print(f"   P50 (median): {result.latency_p50:.2f}")
        print(f"   P95: {result.latency_p95:.2f}")
        print(f"   P99: {result.latency_p99:.2f}")
        print(f"   Mean: {result.latency_mean:.2f}")
        print(f"   Max: {result.latency_max:.2f}")
        
        print(f"\n💾 Memory Usage (MB):")
        print(f"   Peak: {result.memory_peak_mb:.2f}")
        print(f"   Current: {result.memory_current_mb:.2f}")
        
        print(f"\n🖥️  System Metrics:")
        print(f"   CPU Usage: {result.cpu_percent:.1f}%")
        print(f"   Throughput: {result.queries_per_second:.1f} queries/sec")
        
        print(f"\n✅ Success Metrics:")
        print(f"   Successful: {result.success_count}/{result.total_queries}")
        print(f"   Error Rate: {result.error_rate:.1f}%")
        
        # Performance assessment
        print(f"\n🎯 Performance Assessment:")
        if result.latency_p99 < 5:
            print("   ✅ EXCELLENT: P99 < 5ms")
        elif result.latency_p99 < 50:
            print("   ✅ GOOD: P99 < 50ms")
        elif result.latency_p99 < 200:
            print("   ⚠️  ACCEPTABLE: P99 < 200ms")
        else:
            print("   ❌ POOR: P99 > 200ms")
        
        if result.memory_current_mb < 10:
            print("   ✅ EXCELLENT: Memory < 10MB")
        elif result.memory_current_mb < 50:
            print("   ✅ GOOD: Memory < 50MB")
        else:
            print("   ⚠️  HIGH: Memory > 50MB")
        
        if result.error_rate < 1:
            print("   ✅ RELIABLE: Error rate < 1%")
        elif result.error_rate < 5:
            print("   ⚠️  ACCEPTABLE: Error rate < 5%")
        else:
            print("   ❌ UNRELIABLE: Error rate > 5%")


def main():
    parser = argparse.ArgumentParser(description="Benchmark docs-mcp-server search performance")
    parser.add_argument("--tenant", required=True, help="Tenant to benchmark (e.g., django, drf, fastapi)")
    parser.add_argument("--queries", type=int, default=100, help="Number of queries to execute")
    parser.add_argument("--concurrent", type=int, default=5, help="Number of concurrent users")
    parser.add_argument("--url", default="http://127.0.0.1:42042", help="Server base URL")
    parser.add_argument("--output", help="Output JSON file for results")
    
    args = parser.parse_args()
    
    benchmark = SearchBenchmark(args.url)
    
    try:
        result = benchmark.run_concurrent_benchmark(
            args.tenant, 
            args.queries, 
            args.concurrent
        )
        
        benchmark.print_results(result)
        
        if args.output:
            output_data = {
                "timestamp": time.time(),
                "tenant": result.tenant,
                "config": {
                    "queries": result.total_queries,
                    "concurrent_users": result.concurrent_users
                },
                "metrics": {
                    "latency": {
                        "p50_ms": result.latency_p50,
                        "p95_ms": result.latency_p95,
                        "p99_ms": result.latency_p99,
                        "mean_ms": result.latency_mean,
                        "max_ms": result.latency_max
                    },
                    "memory": {
                        "peak_mb": result.memory_peak_mb,
                        "current_mb": result.memory_current_mb
                    },
                    "system": {
                        "cpu_percent": result.cpu_percent,
                        "queries_per_second": result.queries_per_second
                    },
                    "reliability": {
                        "success_count": result.success_count,
                        "error_count": result.error_count,
                        "error_rate_percent": result.error_rate
                    }
                }
            }
            
            Path(args.output).write_text(json.dumps(output_data, indent=2))
            print(f"\n💾 Results saved to: {args.output}")
        
    except KeyboardInterrupt:
        print("\n⚠️  Benchmark interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
