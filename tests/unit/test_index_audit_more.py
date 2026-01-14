"""Additional unit tests for index audit helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from docs_mcp_server import index_audit


@pytest.mark.unit
def test_tenant_audit_report_status_variants():
    assert (
        index_audit.TenantAuditReport(
            tenant="t",
            fingerprint=None,
            current_segment_id=None,
            needs_rebuild=False,
            rebuilt=False,
            duration_s=0.0,
            error="boom",
        ).status
        == "error"
    )

    assert (
        index_audit.TenantAuditReport(
            tenant="t",
            fingerprint=None,
            current_segment_id=None,
            needs_rebuild=False,
            rebuilt=True,
            duration_s=0.0,
        ).status
        == "rebuilt"
    )

    assert (
        index_audit.TenantAuditReport(
            tenant="t",
            fingerprint=None,
            current_segment_id=None,
            needs_rebuild=True,
            rebuilt=False,
            duration_s=0.0,
        ).status
        == "stale"
    )


@pytest.mark.unit
def test_default_max_parallel_respects_cpu_counts(monkeypatch):
    monkeypatch.setattr(index_audit.os, "cpu_count", lambda: 2)
    assert index_audit._default_max_parallel() == 1
    monkeypatch.setattr(index_audit.os, "cpu_count", lambda: 4)
    assert index_audit._default_max_parallel() == 2
    monkeypatch.setattr(index_audit.os, "cpu_count", lambda: 10)
    assert index_audit._default_max_parallel() == 4


@pytest.mark.unit
def test_select_tenants_rejects_unknown():
    tenant = SimpleNamespace(codename="known", search=SimpleNamespace(enabled=True))
    config = SimpleNamespace(tenants=[tenant])

    with pytest.raises(ValueError, match="Unknown tenant"):
        index_audit._select_tenants(config, filters=["missing"])


@pytest.mark.unit
def test_audit_single_tenant_rebuild_persists_mismatch(monkeypatch):
    audit = SimpleNamespace(needs_rebuild=True, fingerprint="fp", current_segment_id="seg")
    indexer = Mock()
    indexer.fingerprint_audit.side_effect = [audit, audit]
    indexer.build_segment.return_value = SimpleNamespace(documents_indexed=1)
    monkeypatch.setattr(index_audit, "TenantIndexer", Mock(return_value=indexer))

    context = SimpleNamespace(codename="tenant")
    report = index_audit.audit_single_tenant(context, rebuild=True)

    assert report.error == "Fingerprint mismatch persists after rebuild"


@pytest.mark.unit
def test_audit_from_config_uses_build_indexing_context(monkeypatch):
    tenant = SimpleNamespace(codename="tenant")
    context = SimpleNamespace(codename="tenant")
    monkeypatch.setattr(index_audit, "build_indexing_context", Mock(return_value=context))
    monkeypatch.setattr(index_audit, "audit_single_tenant", Mock(return_value="ok"))

    result = index_audit._audit_from_config(
        tenant, segments_root=None, segments_subdir="__search_segments", rebuild=False
    )

    assert result == "ok"


@pytest.mark.unit
def test_determine_exit_code_handles_errors():
    report = index_audit.TenantAuditReport(
        tenant="t",
        fingerprint=None,
        current_segment_id=None,
        needs_rebuild=True,
        rebuilt=False,
        duration_s=0.0,
        error="boom",
    )

    assert index_audit._determine_exit_code([report], rebuild=False) == 3


@pytest.mark.unit
def test_configure_logging_noop_when_handlers_present(monkeypatch):
    logger = index_audit.logging.getLogger()
    handler = index_audit.logging.StreamHandler()
    logger.addHandler(handler)
    try:
        index_audit._configure_logging()
        assert handler in logger.handlers
    finally:
        logger.removeHandler(handler)


@pytest.mark.unit
def test_configure_logging_sets_basic_config():
    root_logger = logging.getLogger()
    previous = list(root_logger.handlers)
    for handler in previous:
        root_logger.removeHandler(handler)
    try:
        index_audit._configure_logging()
        assert root_logger.handlers
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
        for handler in previous:
            root_logger.addHandler(handler)


@pytest.mark.unit
def test_main_handles_missing_config(tmp_path):
    missing = tmp_path / "missing.json"

    assert index_audit.main(["--config", str(missing)]) == 1


@pytest.mark.unit
def test_main_handles_invalid_config(tmp_path):
    path = tmp_path / "deployment.json"
    path.write_text("invalid", encoding="utf-8")

    assert index_audit.main(["--config", str(path)]) == 1


@pytest.mark.unit
def test_main_reports_warning_for_mismatches(tmp_path, monkeypatch):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(index_audit.DeploymentConfig, "from_json_file", Mock(return_value=SimpleNamespace(tenants=[])))
    monkeypatch.setattr(index_audit, "_select_tenants", Mock(return_value=[SimpleNamespace(codename="t")]))
    monkeypatch.setattr(
        index_audit,
        "_run_audits_async",
        AsyncMock(
            return_value=[
                index_audit.TenantAuditReport(
                    tenant="t",
                    fingerprint=None,
                    current_segment_id=None,
                    needs_rebuild=True,
                    rebuilt=False,
                    duration_s=0.0,
                )
            ]
        ),
    )

    assert index_audit.main(["--config", str(path)]) == 2


@pytest.mark.unit
def test_main_reports_error_for_failures(tmp_path, monkeypatch):
    path = tmp_path / "deployment.json"
    path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(index_audit.DeploymentConfig, "from_json_file", Mock(return_value=SimpleNamespace(tenants=[])))
    monkeypatch.setattr(index_audit, "_select_tenants", Mock(return_value=[SimpleNamespace(codename="t")]))
    monkeypatch.setattr(
        index_audit,
        "_run_audits_async",
        AsyncMock(
            return_value=[
                index_audit.TenantAuditReport(
                    tenant="t",
                    fingerprint=None,
                    current_segment_id=None,
                    needs_rebuild=True,
                    rebuilt=False,
                    duration_s=0.0,
                    error="boom",
                )
            ]
        ),
    )

    assert index_audit.main(["--config", str(path)]) == 3
