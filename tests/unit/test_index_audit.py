"""Unit tests for the boot-time index audit helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from docs_mcp_server import index_audit
from docs_mcp_server.deployment_config import DeploymentConfig, SharedInfraConfig, TenantConfig
from docs_mcp_server.index_audit import (
    TenantAuditReport,
    _default_max_parallel,
    _determine_exit_code,
    _determine_segments_root,
    _format_report,
    _run_audits_async,
    _select_tenants,
    _validate_args,
    audit_single_tenant,
    build_argument_parser,
)
from docs_mcp_server.search.indexer import TenantIndexer, TenantIndexingContext


pytestmark = pytest.mark.unit


@pytest.fixture
def tenant_root(tmp_path: Path) -> Path:
    (tmp_path / "__docs_metadata").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_audit_single_tenant_reports_ok(tenant_root: Path) -> None:
    markdown_path = tenant_root / "docs" / "example.md"
    _write_markdown_doc(markdown_path, title="Example", body="# Example\n\ncontent")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    TenantIndexer(context).build_segment()

    report = audit_single_tenant(context, rebuild=False)
    assert report.status == "ok"
    assert report.fingerprint == report.current_segment_id
    assert report.rebuilt is False
    assert report.error is None


def test_audit_single_tenant_rebuilds_when_needed(tenant_root: Path) -> None:
    markdown_path = tenant_root / "docs" / "stale.md"
    _write_markdown_doc(markdown_path, title="Stale", body="# Stale\n\ncontent")

    context = TenantIndexingContext(
        codename="demo",
        docs_root=tenant_root,
        segments_dir=tenant_root / "segments",
        source_type="filesystem",
    )
    indexer = TenantIndexer(context)
    indexer.build_segment()

    markdown_path.write_text(
        "-----\ntitle: Stale\nurl: https://example.com/docs/stale\n-----\n# Stale\n\nupdated",
        encoding="utf-8",
    )

    stale_report = audit_single_tenant(context, rebuild=False)
    assert stale_report.needs_rebuild is True
    assert stale_report.rebuilt is False

    rebuild_report = audit_single_tenant(context, rebuild=True)
    assert rebuild_report.rebuilt is True
    assert rebuild_report.needs_rebuild is False
    assert rebuild_report.documents_indexed == 1
    assert rebuild_report.error is None


def test_default_max_parallel_scales_with_cpu(monkeypatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 1)
    assert _default_max_parallel() == 1
    monkeypatch.setattr("os.cpu_count", lambda: 4)
    assert _default_max_parallel() == 2


def test_select_tenants_filters_and_rejects_unknown() -> None:
    tenants = [
        TenantConfig(source_type="filesystem", codename="aa", docs_name="A", docs_root_dir="/tmp/a"),
        TenantConfig(source_type="filesystem", codename="bb", docs_name="B", docs_root_dir="/tmp/b"),
    ]
    config = DeploymentConfig(infrastructure=SharedInfraConfig(), tenants=tenants)

    selected = _select_tenants(config, ["bb"])
    assert [tenant.codename for tenant in selected] == ["bb"]

    with pytest.raises(ValueError, match="Unknown tenant"):
        _select_tenants(config, ["missing"])


def test_format_report_includes_error() -> None:
    report = TenantAuditReport(
        tenant="demo",
        fingerprint=None,
        current_segment_id=None,
        needs_rebuild=True,
        rebuilt=False,
        duration_s=1.2,
        error="boom",
    )

    formatted = _format_report(report)

    assert "status=error" in formatted
    assert "error=boom" in formatted


def test_determine_exit_code_respects_rebuild_flag() -> None:
    ok = TenantAuditReport(
        tenant="demo",
        fingerprint="a",
        current_segment_id="a",
        needs_rebuild=False,
        rebuilt=False,
        duration_s=0.1,
    )
    stale = TenantAuditReport(
        tenant="demo",
        fingerprint="a",
        current_segment_id="b",
        needs_rebuild=True,
        rebuilt=False,
        duration_s=0.1,
    )

    assert _determine_exit_code([ok], rebuild=False) == 0
    assert _determine_exit_code([stale], rebuild=False) == 2
    assert _determine_exit_code([stale], rebuild=True) == 3


def test_validate_args_rejects_invalid_limits() -> None:
    parser = build_argument_parser()
    args = parser.parse_args([])
    args.max_parallel = 0

    with pytest.raises(ValueError, match="--max-parallel must be"):
        _validate_args(args)

    args.max_parallel = 1
    args.tenant_timeout = 1
    with pytest.raises(ValueError, match="--tenant-timeout must be"):
        _validate_args(args)


def test_determine_segments_root_handles_none(tmp_path: Path) -> None:
    assert _determine_segments_root(None) is None
    assert _determine_segments_root(tmp_path) == tmp_path.resolve()


@pytest.mark.asyncio
async def test_run_audits_async_returns_empty_for_no_tenants() -> None:
    parser = build_argument_parser()
    args = parser.parse_args([])

    assert await _run_audits_async(args, []) == []


@pytest.mark.asyncio
async def test_run_audits_async_reports_timeout(monkeypatch) -> None:
    parser = build_argument_parser()
    args = parser.parse_args([])
    args.tenant_timeout = 1
    tenants = [TenantConfig(source_type="filesystem", codename="aa", docs_name="A", docs_root_dir="/tmp/a")]

    async def _raise_timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr("docs_mcp_server.index_audit.asyncio.wait_for", _raise_timeout)

    reports = await _run_audits_async(args, tenants)

    assert reports[0].status == "error"
    assert "Timed out" in (reports[0].error or "")


def test_main_returns_zero_when_no_tenants(monkeypatch) -> None:
    tenant = TenantConfig(
        source_type="filesystem",
        codename="aa",
        docs_name="A",
        docs_root_dir="/tmp/a",
        search={"enabled": False},
    )
    config = DeploymentConfig(infrastructure=SharedInfraConfig(), tenants=[tenant])

    monkeypatch.setattr("docs_mcp_server.index_audit.DeploymentConfig.from_json_file", lambda _path: config)

    assert index_audit.main(["--config", "deployment.json"]) == 0


def test_main_returns_one_for_unknown_tenant(monkeypatch) -> None:
    tenant = TenantConfig(source_type="filesystem", codename="aa", docs_name="A", docs_root_dir="/tmp/a")
    config = DeploymentConfig(infrastructure=SharedInfraConfig(), tenants=[tenant])

    monkeypatch.setattr("docs_mcp_server.index_audit.DeploymentConfig.from_json_file", lambda _path: config)

    assert index_audit.main(["--config", "deployment.json", "--tenants", "missing"]) == 1


def test_main_runs_audit_and_returns_success(monkeypatch) -> None:
    tenant = TenantConfig(source_type="filesystem", codename="aa", docs_name="A", docs_root_dir="/tmp/a")
    config = DeploymentConfig(infrastructure=SharedInfraConfig(), tenants=[tenant])
    report = TenantAuditReport(
        tenant="aa",
        fingerprint="seg",
        current_segment_id="seg",
        needs_rebuild=False,
        rebuilt=False,
        duration_s=0.01,
    )

    monkeypatch.setattr("docs_mcp_server.index_audit.DeploymentConfig.from_json_file", lambda _path: config)

    async def _run(*_args, **_kwargs):
        return [report]

    monkeypatch.setattr("docs_mcp_server.index_audit._run_audits_async", _run)

    assert index_audit.main(["--config", "deployment.json"]) == 0


def _write_markdown_doc(path: Path, *, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = (
        path.parent.parent / "__docs_metadata" / path.relative_to(path.parent.parent).with_suffix(".meta.json")
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://example.com/{path.relative_to(path.parent.parent).with_suffix('').as_posix()}"
    path.write_text(f"-----\ntitle: {title}\nurl: {url}\n-----\n{body}", encoding="utf-8")
    metadata_path.write_text(
        (
            "{\n"
            f'  "url": "{url}",\n'
            f'  "title": "{title}",\n'
            '  "metadata": {\n'
            f'    "markdown_rel_path": "{path.relative_to(path.parent.parent)}",\n'
            '    "last_fetched_at": "2025-01-01T00:00:00+00:00"\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )
