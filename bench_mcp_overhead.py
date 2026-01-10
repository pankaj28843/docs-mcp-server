"""Benchmark MCP overhead across direct, in-process, and HTTP paths."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from pathlib import Path

from fastmcp import Client

from docs_mcp_server.deployment_config import DeploymentConfig
from docs_mcp_server.registry import TenantRegistry
from docs_mcp_server.root_hub import create_root_hub
from docs_mcp_server.tenant import create_tenant_app


def p95(samples: list[float]) -> float:
    if not samples:
        raise ValueError("no samples")
    samples = sorted(samples)
    idx = max(0, math.ceil(0.95 * len(samples)) - 1)
    return samples[idx]


async def measure_async(fn, *, warmup: int, iterations: int) -> list[float]:
    for _ in range(warmup):
        await fn()
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


def _pick_query(test_queries: object) -> str:
    query = None
    if isinstance(test_queries, dict):
        for value in test_queries.values():
            if isinstance(value, list) and value:
                query = value[0]
                break
    elif isinstance(test_queries, list) and test_queries:
        query = test_queries[0]
    return query or "configuration"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MCP overhead.")
    parser.add_argument("--config", default="deployment.json")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--http-url", default=None)
    args = parser.parse_args()

    config = DeploymentConfig.from_json_file(Path(args.config))
    tenant_config = config.tenants[0]
    query = _pick_query(tenant_config.test_queries or {})

    registry = TenantRegistry()
    tenant_app = create_tenant_app(tenant_config)
    registry.register(tenant_config, tenant_app)
    await tenant_app.initialize()

    search_endpoint = getattr(getattr(tenant_app, "endpoints", None), "search", None)
    fetch_endpoint = getattr(getattr(tenant_app, "endpoints", None), "fetch", None)

    async def run_direct_search() -> str:
        if search_endpoint is not None:
            response = await search_endpoint.handle(query=query, size=5, word_match=False)
        else:
            response = await tenant_app.search(query, size=5, word_match=False)
        if response.error:
            raise RuntimeError(response.error)
        return response.results[0].url if response.results else ""

    fetch_url = await run_direct_search()
    if not fetch_url:
        raise RuntimeError("search returned no results")

    async def run_direct_fetch() -> None:
        if fetch_endpoint is not None:
            response = await fetch_endpoint.handle(fetch_url, "surrounding")
        else:
            response = await tenant_app.fetch(fetch_url, context="surrounding")
        if response.error:
            raise RuntimeError(response.error)

    direct_search_samples = await measure_async(
        run_direct_search, warmup=args.warmup, iterations=args.iterations
    )
    direct_fetch_samples = await measure_async(
        run_direct_fetch, warmup=args.warmup, iterations=args.iterations
    )

    root_hub = create_root_hub(registry)
    async with Client(root_hub) as client:
        async def run_mcp_search() -> str:
            result = await client.call_tool(
                "root_search",
                arguments={
                    "tenant_codename": tenant_config.codename,
                    "query": query,
                    "size": 5,
                    "word_match": False,
                },
            )
            content = result.content[0]
            payload = json.loads(content.text)  # type: ignore[union-attr]
            if payload.get("error"):
                raise RuntimeError(payload["error"])
            results = payload.get("results", [])
            return results[0]["url"] if results else ""

        async def run_mcp_fetch() -> None:
            result = await client.call_tool(
                "root_fetch",
                arguments={
                    "tenant_codename": tenant_config.codename,
                    "uri": fetch_url,
                    "context": "surrounding",
                },
            )
            content = result.content[0]
            payload = json.loads(content.text)  # type: ignore[union-attr]
            if payload.get("error"):
                raise RuntimeError(payload["error"])

        mcp_search_samples = await measure_async(
            run_mcp_search, warmup=args.warmup, iterations=args.iterations
        )
        mcp_fetch_samples = await measure_async(
            run_mcp_fetch, warmup=args.warmup, iterations=args.iterations
        )

    http_search_p95: float | None = None
    http_fetch_p95: float | None = None
    if args.http_url:
        mcp_url = args.http_url.rstrip("/") + "/mcp/"
        async with Client(mcp_url) as http_client:
            async def run_http_search() -> str:
                result = await http_client.call_tool(
                    "root_search",
                    arguments={
                        "tenant_codename": tenant_config.codename,
                        "query": query,
                        "size": 5,
                        "word_match": False,
                    },
                )
                content = result.content[0]
                payload = json.loads(content.text)  # type: ignore[union-attr]
                if payload.get("error"):
                    raise RuntimeError(payload["error"])
                results = payload.get("results", [])
                return results[0]["url"] if results else ""

            async def run_http_fetch() -> None:
                result = await http_client.call_tool(
                    "root_fetch",
                    arguments={
                        "tenant_codename": tenant_config.codename,
                        "uri": fetch_url,
                        "context": "surrounding",
                    },
                )
                content = result.content[0]
                payload = json.loads(content.text)  # type: ignore[union-attr]
                if payload.get("error"):
                    raise RuntimeError(payload["error"])

            search_samples = await measure_async(
                run_http_search, warmup=args.warmup, iterations=args.iterations
            )
            fetch_samples = await measure_async(
                run_http_fetch, warmup=args.warmup, iterations=args.iterations
            )
            http_search_p95 = round(p95(search_samples), 2)
            http_fetch_p95 = round(p95(fetch_samples), 2)

    direct_search_p95 = round(p95(direct_search_samples), 2)
    direct_fetch_p95 = round(p95(direct_fetch_samples), 2)
    mcp_search_p95 = round(p95(mcp_search_samples), 2)
    mcp_fetch_p95 = round(p95(mcp_fetch_samples), 2)

    report = {
        "direct_search_p95_ms": direct_search_p95,
        "direct_fetch_p95_ms": direct_fetch_p95,
        "mcp_in_process_search_p95_ms": mcp_search_p95,
        "mcp_in_process_fetch_p95_ms": mcp_fetch_p95,
        "http_search_p95_ms": http_search_p95,
        "http_fetch_p95_ms": http_fetch_p95,
        "mcp_overhead_search_ms": round(mcp_search_p95 - direct_search_p95, 2),
        "mcp_overhead_fetch_ms": round(mcp_fetch_p95 - direct_fetch_p95, 2),
        "http_overhead_search_ms": round(http_search_p95 - mcp_search_p95, 2)
        if http_search_p95 is not None
        else None,
        "http_overhead_fetch_ms": round(http_fetch_p95 - mcp_fetch_p95, 2)
        if http_fetch_p95 is not None
        else None,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("fastmcp.client.from_server").setLevel(logging.WARNING)
    logging.getLogger("fastmcp").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    asyncio.run(main())
