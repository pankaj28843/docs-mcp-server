"""CLI for auditing and rebuilding search segments at boot time."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import sys
import time

from docs_mcp_server.deployment_config import DeploymentConfig, TenantConfig
from docs_mcp_server.search.indexer import TenantIndexer, TenantIndexingContext
from docs_mcp_server.search.indexing_utils import DEFAULT_SEGMENTS_SUBDIR, build_indexing_context


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TenantAuditReport:
    """Structured result for a single tenant audit."""

    tenant: str
    fingerprint: str | None
    current_segment_id: str | None
    needs_rebuild: bool
    rebuilt: bool
    duration_s: float
    documents_indexed: int | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.rebuilt:
            return "rebuilt"
        if self.needs_rebuild:
            return "stale"
        return "ok"

    def to_dict(self) -> dict[str, object | None]:
        payload = asdict(self)
        payload["status"] = self.status
        return payload


def audit_single_tenant(context: TenantIndexingContext, *, rebuild: bool) -> TenantAuditReport:
    """Run a fingerprint audit (and optional rebuild) for a tenant."""

    start = time.perf_counter()
    indexer = TenantIndexer(context)
    audit = None
    documents_indexed: int | None = None

    try:
        audit = indexer.fingerprint_audit()
        needs_rebuild = audit.needs_rebuild
        rebuilt = False

        if rebuild and needs_rebuild:
            build_result = indexer.build_segment()
            documents_indexed = build_result.documents_indexed
            rebuilt = True
            audit = indexer.fingerprint_audit()
            needs_rebuild = audit.needs_rebuild
            if needs_rebuild:
                return TenantAuditReport(
                    tenant=context.codename,
                    fingerprint=audit.fingerprint,
                    current_segment_id=audit.current_segment_id,
                    needs_rebuild=True,
                    rebuilt=True,
                    duration_s=time.perf_counter() - start,
                    documents_indexed=documents_indexed,
                    error="Fingerprint mismatch persists after rebuild",
                )

        return TenantAuditReport(
            tenant=context.codename,
            fingerprint=audit.fingerprint,
            current_segment_id=audit.current_segment_id,
            needs_rebuild=needs_rebuild,
            rebuilt=rebuilt,
            duration_s=time.perf_counter() - start,
            documents_indexed=documents_indexed,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        return TenantAuditReport(
            tenant=context.codename,
            fingerprint=audit.fingerprint if audit else None,
            current_segment_id=audit.current_segment_id if audit else None,
            needs_rebuild=True,
            rebuilt=False,
            duration_s=time.perf_counter() - start,
            documents_indexed=documents_indexed,
            error=str(exc),
        )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit BM25 segments and optionally rebuild mismatched tenants",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("deployment.json"),
        help="Path to deployment.json",
    )
    parser.add_argument(
        "--tenants",
        nargs="+",
        metavar="TENANT",
        help="Optional tenant codename filters",
    )
    parser.add_argument(
        "--segments-root",
        type=Path,
        help="Directory where search segments are stored (defaults to docs_root_dir)",
    )
    parser.add_argument(
        "--segments-subdir",
        default=DEFAULT_SEGMENTS_SUBDIR,
        help=f"Subdirectory created when --segments-root is not set (default: {DEFAULT_SEGMENTS_SUBDIR})",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=_default_max_parallel(),
        help="Maximum tenants audited concurrently",
    )
    parser.add_argument(
        "--tenant-timeout",
        type=int,
        default=300,
        help="Timeout in seconds for each tenant audit",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild tenants whose fingerprints disagree with the manifest",
    )
    return parser


def _default_max_parallel() -> int:
    cpu_count = os.cpu_count() or 1
    if cpu_count <= 2:
        return 1
    if cpu_count <= 4:
        return 2
    return min(4, cpu_count // 2)


def _select_tenants(config: DeploymentConfig, filters: Sequence[str] | None) -> list[TenantConfig]:
    eligible = [tenant for tenant in config.tenants if tenant.search.enabled]
    if not filters:
        return eligible
    selected: list[TenantConfig] = []
    unknown: list[str] = []
    allowed = {tenant.codename for tenant in eligible}
    for codename in filters:
        if codename not in allowed:
            unknown.append(codename)
            continue
        selected.append(next(tenant for tenant in eligible if tenant.codename == codename))
    if unknown:
        raise ValueError(f"Unknown tenant(s): {', '.join(sorted(unknown))}")
    return selected


def _format_report(report: TenantAuditReport) -> str:
    fingerprint = report.fingerprint or "-"
    current = report.current_segment_id or "-"
    base = (
        f"{report.tenant:<16} status={report.status:<7} fingerprint={fingerprint}"
        f" current={current} rebuilt={report.rebuilt} duration={report.duration_s:.2f}s"
    )
    if report.error:
        return f"{base} error={report.error}"
    return base


def _audit_from_config(
    tenant: TenantConfig,
    *,
    segments_root: Path | None,
    segments_subdir: str,
    rebuild: bool,
) -> TenantAuditReport:
    context = build_indexing_context(
        tenant,
        segments_root=segments_root,
        segments_subdir=segments_subdir,
    )
    return audit_single_tenant(context, rebuild=rebuild)


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _determine_segments_root(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path.expanduser().resolve()


def _determine_exit_code(results: Sequence[TenantAuditReport], *, rebuild: bool) -> int:
    if any(report.error for report in results):
        return 3
    if rebuild:
        return 0 if all(not report.needs_rebuild for report in results) else 3
    return 0 if all(not report.needs_rebuild for report in results) else 2


def _print_reports(results: Sequence[TenantAuditReport]) -> None:
    for report in results:
        payload = report.to_dict()
        logger.info(_format_report(report))
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def _validate_args(args: argparse.Namespace) -> None:
    if args.max_parallel < 1:
        raise ValueError("--max-parallel must be >= 1")
    if args.tenant_timeout < 5:
        raise ValueError("--tenant-timeout must be >= 5 seconds")


async def _run_audits_async(args: argparse.Namespace, tenants: Sequence[TenantConfig]) -> list[TenantAuditReport]:
    if not tenants:
        return []

    sem = asyncio.Semaphore(args.max_parallel)
    segments_root = _determine_segments_root(args.segments_root)

    async def run_for_tenant(tenant: TenantConfig) -> TenantAuditReport:
        async with sem:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        _audit_from_config,
                        tenant,
                        segments_root=segments_root,
                        segments_subdir=args.segments_subdir,
                        rebuild=args.rebuild,
                    ),
                    timeout=args.tenant_timeout,
                )
            except asyncio.TimeoutError:
                return TenantAuditReport(
                    tenant=tenant.codename,
                    fingerprint=None,
                    current_segment_id=None,
                    needs_rebuild=True,
                    rebuilt=False,
                    duration_s=float(args.tenant_timeout),
                    error=f"Timed out after {args.tenant_timeout}s",
                )

    tasks = [run_for_tenant(tenant) for tenant in tenants]
    return await asyncio.gather(*tasks)


def main(argv: Sequence[str] | None = None) -> int:
    _configure_logging()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    try:
        config = DeploymentConfig.from_json_file(args.config)
    except FileNotFoundError as exc:
        logger.error("Deployment config not found: %s", exc)
        return 1
    except ValueError as exc:
        logger.error("Invalid deployment config: %s", exc)
        return 1

    try:
        tenants = _select_tenants(config, args.tenants)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not tenants:
        logger.info("No search-enabled tenants selected; nothing to audit")
        return 0

    results = asyncio.run(_run_audits_async(args, tenants))
    _print_reports(results)

    exit_code = _determine_exit_code(results, rebuild=args.rebuild)
    if exit_code == 0:
        logger.info("Audit completed successfully")
    elif exit_code == 2:
        logger.warning("Fingerprint mismatches detected; rerun with --rebuild to repair")
    else:
        logger.error("Audit completed with errors")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
