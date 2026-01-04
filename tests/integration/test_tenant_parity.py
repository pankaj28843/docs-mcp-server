"""Integration tests verifying tenant storage/metadata parity.

These tests check real tenant data on disk to catch drift between
metadata entries and actual stored documents.

Run with: uv run pytest tests/integration/test_tenant_parity.py -v
"""

import json
from pathlib import Path

import pytest


# Integration tests are excluded by default (pytest.ini/pyproject.toml)
# Run explicitly when needed for regression checks


def _count_markdown_files(docs_root: Path) -> int:
    """Count .md files under the docs root, excluding __scheduler_meta."""
    if not docs_root.exists():
        return 0
    count = 0
    for item in docs_root.rglob("*.md"):
        # Skip metadata directories
        if "__scheduler_meta" in str(item):
            continue
        count += 1
    return count


def _count_metadata_successes(docs_root: Path) -> tuple[int, int]:
    """Count successful vs total metadata entries.

    Returns:
        (success_count, total_count)
    """
    meta_dir = docs_root / "__scheduler_meta"
    if not meta_dir.exists():
        return 0, 0

    total = 0
    successes = 0
    for meta_file in meta_dir.glob("url_*.json"):
        try:
            data = json.loads(meta_file.read_text())
            total += 1
            if data.get("last_status") == "success":
                successes += 1
        except (json.JSONDecodeError, OSError):
            continue
    return successes, total


@pytest.mark.integration
class TestTenantStorageParity:
    """Verify that on-disk storage matches metadata success counts."""

    @pytest.fixture
    def deployment_config(self):
        """Load the real deployment.json configuration."""
        config_path = Path(__file__).parent.parent.parent / "deployment.json"
        if not config_path.exists():
            pytest.skip("deployment.json not found")
        return json.loads(config_path.read_text())

    @pytest.fixture
    def mcp_data_root(self):
        """Return the mcp-data directory path."""
        return Path(__file__).parent.parent.parent / "mcp-data"

    def test_transformerlens_parity(self, deployment_config, mcp_data_root):
        """TransformerLens storage vs metadata drift should be ≤2%."""
        # Find transformerlens tenant config
        tenant = next(
            (t for t in deployment_config.get("tenants", []) if t.get("codename") == "transformerlens"),
            None,
        )
        if not tenant:
            pytest.skip("transformerlens tenant not configured")

        docs_root = mcp_data_root / "transformerlens"
        if not docs_root.exists():
            pytest.skip("transformerlens data not synced")

        storage_count = _count_markdown_files(docs_root)
        metadata_successes, metadata_total = _count_metadata_successes(docs_root)

        # Skip if no data
        if metadata_total == 0:
            pytest.skip("No metadata entries found")

        # Calculate drift
        if metadata_successes == 0:
            drift_pct = 100.0
        else:
            drift_pct = abs(storage_count - metadata_successes) / metadata_successes * 100

        # Report metrics
        print("\nTransformerLens parity check:")
        print(f"  Storage documents: {storage_count}")
        print(f"  Metadata successes: {metadata_successes}/{metadata_total}")
        print(f"  Drift: {drift_pct:.1f}%")

        # Assert ≤2% drift (success metric from PRP)
        assert drift_pct <= 2.0, (
            f"Storage/metadata drift {drift_pct:.1f}% exceeds 2% threshold. "
            f"Storage={storage_count}, Metadata successes={metadata_successes}"
        )

    def test_drf_parity(self, deployment_config, mcp_data_root):
        """DRF storage vs metadata drift should be 0% (reference tenant)."""
        tenant = next(
            (t for t in deployment_config.get("tenants", []) if t.get("codename") == "drf"),
            None,
        )
        if not tenant:
            pytest.skip("drf tenant not configured")

        docs_root = mcp_data_root / "drf"
        if not docs_root.exists():
            pytest.skip("drf data not synced")

        storage_count = _count_markdown_files(docs_root)
        metadata_successes, metadata_total = _count_metadata_successes(docs_root)

        if metadata_total == 0:
            pytest.skip("No metadata entries found")

        drift_pct = abs(storage_count - metadata_successes) / max(metadata_successes, 1) * 100

        print("\nDRF parity check:")
        print(f"  Storage documents: {storage_count}")
        print(f"  Metadata successes: {metadata_successes}/{metadata_total}")
        print(f"  Drift: {drift_pct:.1f}%")

        # DRF should have perfect parity
        assert drift_pct == 0, (
            f"DRF storage/metadata drift {drift_pct:.1f}% - expected 0%. "
            f"Storage={storage_count}, Metadata successes={metadata_successes}"
        )

    def test_all_online_tenants_parity_report(self, deployment_config, mcp_data_root):
        """Report storage/metadata drift for all online tenants.

        This is an informational test that warns about drift but only fails
        on critical tenants (transformerlens, drf). Other tenants may have
        ongoing extraction issues that don't block the main PRP goal.
        """
        tenants = deployment_config.get("tenants", [])
        online_tenants = [t for t in tenants if t.get("source_type") != "git"]

        # Critical tenants that must meet ≤2% drift (PRP success metric)
        critical_tenants = {"transformerlens", "drf"}

        results = []
        for tenant in online_tenants:
            codename = tenant.get("codename")
            docs_root = mcp_data_root / codename
            if not docs_root.exists():
                continue

            storage_count = _count_markdown_files(docs_root)
            metadata_successes, metadata_total = _count_metadata_successes(docs_root)

            if metadata_total == 0 or metadata_successes == 0:
                continue

            drift_pct = abs(storage_count - metadata_successes) / metadata_successes * 100
            results.append(
                {
                    "codename": codename,
                    "storage": storage_count,
                    "metadata_successes": metadata_successes,
                    "drift_pct": drift_pct,
                    "is_critical": codename in critical_tenants,
                }
            )

        if not results:
            pytest.skip("No online tenants with synced data")

        # Report all results
        print("\nOnline tenant parity summary:")
        critical_failures = []
        warnings = []
        for r in sorted(results, key=lambda x: x["drift_pct"], reverse=True):
            threshold = 2.0 if r["is_critical"] else 10.0
            exceeds = r["drift_pct"] > threshold
            status = "❌" if exceeds else "✅"
            label = " [CRITICAL]" if r["is_critical"] else ""
            print(
                f"  {status} {r['codename']}{label}: storage={r['storage']}, "
                f"metadata={r['metadata_successes']}, drift={r['drift_pct']:.1f}%"
            )
            if exceeds:
                if r["is_critical"]:
                    critical_failures.append(r)
                else:
                    warnings.append(r)

        if warnings:
            print(f"\n⚠️  {len(warnings)} non-critical tenant(s) exceed 10% drift")

        # Only fail on critical tenants
        assert not critical_failures, (
            f"{len(critical_failures)} critical tenant(s) exceed 2% drift threshold: "
            f"{', '.join(f['codename'] for f in critical_failures)}"
        )
