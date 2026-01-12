#!/usr/bin/env python3
"""Minimal CI MCP test - reuses deployment config types from src/."""
# ruff: noqa: T201, E402  # CLI prints, imports after path setup

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


# Ensure we run from project root
PROJECT_ROOT = Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "integration_tests"))

from sample_data import create_filesystem_tenant, create_git_tenant, create_online_tenant

from docs_mcp_server.deployment_config import DeploymentConfig


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def create_sample_data(test_dir: Path):
    """Create sample docs for all tenant types."""
    if test_dir.exists():
        shutil.rmtree(test_dir)

    create_online_tenant(test_dir / "webapi-ci")
    create_git_tenant(test_dir / "gitdocs-ci")
    create_filesystem_tenant(test_dir / "localdocs-ci")


def create_config(port: int, test_dir: Path) -> DeploymentConfig:
    """Create validated deployment config using types from src/."""
    return DeploymentConfig(
        infrastructure={"mcp_port": port},
        tenants=[
            {
                "source_type": "online",
                "codename": "webapi-ci",
                "docs_name": "WebAPI CI Test",
                "docs_sitemap_url": ["https://webapi.example.com/sitemap.xml"],
                "url_whitelist_prefixes": "https://webapi.example.com/",
                "docs_root_dir": str(test_dir / "webapi-ci"),
                "test_queries": {"natural": ["routing"], "phrases": ["api"], "words": ["webapi"]},
            },
            {
                "source_type": "git",
                "codename": "gitdocs-ci",
                "docs_name": "GitDocs CI Test",
                "git_repo_url": "https://github.com/example/docs.git",
                "git_subpaths": ["docs"],
                "docs_root_dir": str(test_dir / "gitdocs-ci"),
                "test_queries": {"natural": ["themes"], "phrases": ["config"], "words": ["docs"]},
            },
            {
                "source_type": "filesystem",
                "codename": "localdocs-ci",
                "docs_name": "Local Docs CI Test",
                "docs_root_dir": str(test_dir / "localdocs-ci"),
                "test_queries": {"natural": ["tools"], "phrases": ["api"], "words": ["docs"]},
            },
        ],
    )


def run_tests(config_path: str, config: DeploymentConfig) -> bool:
    """Run MCP tests for all tenants."""
    print("🔍 Testing MCP tools...")

    for tenant in config.tenants:
        print(f"📚 Indexing {tenant.codename}...")
        result = subprocess.run(
            ["uv", "run", "python", "trigger_all_indexing.py", "--config", config_path, "--tenants", tenant.codename],
            capture_output=True,
            timeout=30,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"❌ Index failed: {result.stderr}")
            return False

    for tenant in config.tenants:
        print(f"🧪 Testing {tenant.codename}...")
        test_type = "all" if tenant.source_type == "filesystem" else "search"

        result = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "debug_multi_tenant.py",
                "--config",
                config_path,
                "--use-config-directly",
                "--root",
                "--root-test",
                test_type,
                "--target-tenant",
                tenant.codename,
            ],
            capture_output=True,
            timeout=30,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"❌ {tenant.codename} failed: {result.stdout[-300:]}")
            return False
        print(f"✅ {tenant.codename} passed")

    return True


def main():
    print("🏗️ Setting up CI test...")

    test_dir = Path("./test-mcp-data").resolve()
    config_path = Path("./deployment.ci-test.json")

    port = get_free_port()
    create_sample_data(test_dir)

    config = create_config(port, test_dir)
    config_path.write_text(config.model_dump_json(indent=2))

    success = run_tests(str(config_path), config)

    shutil.rmtree(test_dir, ignore_errors=True)
    config_path.unlink(missing_ok=True)

    print("✅ All tests passed!" if success else "❌ Tests failed!")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
