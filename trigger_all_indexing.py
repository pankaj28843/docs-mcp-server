#!/usr/bin/env python3
"""Trigger per-tenant indexing runs for the SQLite-based search stack.

The CLI mirrors the ergonomics of trigger_all_syncs.py so operators can
iterate on the search indexer without diving into Python REPLs.
It reads deployment.json, filters tenants (if requested), and invokes the
filesystem-backed TenantIndexer to build SQLite segment artifacts.
"""

# ruff: noqa: T201  # CLI intentionally prints operator feedback

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
import textwrap
import time

from docs_mcp_server.deployment_config import DeploymentConfig, TenantConfig
from docs_mcp_server.search.indexer import TenantIndexer
from docs_mcp_server.search.indexing_utils import DEFAULT_SEGMENTS_SUBDIR, build_indexing_context
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore


DEFAULT_CONFIG_PATH = Path("deployment.json")


@dataclass
class TenantRunResult:
    """Summary for a single tenant indexing run."""

    tenant: str
    documents_indexed: int
    documents_skipped: int
    errors: tuple[str, ...]
    duration_s: float
    segment_ids: tuple[str, ...]
    segment_paths: tuple[Path, ...]
    dry_run: bool


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trigger per-tenant search indexing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              uv run python trigger_all_indexing.py
              uv run python trigger_all_indexing.py --tenants django drf
              uv run python trigger_all_indexing.py --tenants django --dry-run --changed-only
              uv run python trigger_all_indexing.py --segments-root ./mcp-indexes
            """
        ).strip(),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to deployment.json (default: ./deployment.json)",
    )
    parser.add_argument(
        "--tenants",
        nargs="+",
        metavar="TENANT",
        help="Optional tenant codename filters (default: all tenants with search enabled)",
    )
    parser.add_argument(
        "--segments-root",
        type=Path,
        help="Directory where search segments should be written. When omitted, segments live under each docs_root_dir",
    )
    parser.add_argument(
        "--segments-subdir",
        default=DEFAULT_SEGMENTS_SUBDIR,
        help=f"Subdirectory created inside docs_root_dir when --segments-root is not set (default: {DEFAULT_SEGMENTS_SUBDIR})",
    )
    parser.add_argument(
        "--changed-path",
        dest="changed_paths",
        action="append",
        default=None,
        metavar="PATH",
        help="Relative or absolute path filter. Pass multiple times to limit indexing to specific docs",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Skip documents whose metadata + markdown mtime predates the last saved segment",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of documents to index per tenant (useful for smoke tests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute the pipeline without writing SQLite segment files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        config = DeploymentConfig.from_json_file(args.config)
    except FileNotFoundError as exc:  # pragma: no cover - CLI guardrail
        print(f"Config not found: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:  # pragma: no cover - CLI guardrail
        print(f"Invalid deployment config: {exc}", file=sys.stderr)
        return 1

    SqliteSegmentStore.set_max_segments(config.infrastructure.search_max_segments)

    try:
        target_tenants = _select_tenants(config, args.tenants)
    except ValueError as exc:
        print(str(exc))
        return 1
    if not target_tenants:
        print("No tenants matched the provided filters.")
        return 1

    print("=== Docs MCP Search Indexing ===")
    print(f"Config: {args.config}")
    if args.tenants:
        print(f"Filters: {', '.join(args.tenants)}")
    else:
        print("Filters: (all tenants)")
    print(f"Dry run: {args.dry_run}")
    print()

    processed = 0
    failures: list[str] = []

    for tenant in target_tenants:
        try:
            result = _run_for_tenant(tenant, args, config)
        except FileNotFoundError as exc:
            failures.append(f"{tenant.codename}: {exc}")
            print(f"- {tenant.codename:<20} ERROR  {exc}")
            continue

        processed += 1
        _print_result(result, changed_only=args.changed_only)
        if result.errors:
            failures.append(f"{result.tenant}: {len(result.errors)} errors")

    if processed == 0:
        print("No tenants were indexed. Enable search.enabled or adjust filters.")
        return 1

    if failures:
        print()
        print("Failures detected:")
        for entry in failures:
            print(f"  - {entry}")
        return 1

    return 0


def _select_tenants(config: DeploymentConfig, filters: Sequence[str] | None) -> list[TenantConfig]:
    if not filters:
        return list(config.tenants)
    selected: list[TenantConfig] = []
    unknown: list[str] = []
    for codename in filters:
        tenant = config.get_tenant(codename)
        if tenant is None:
            unknown.append(codename)
        else:
            selected.append(tenant)
    if unknown:
        raise ValueError(f"Unknown tenant(s): {', '.join(unknown)}")
    return selected


def _run_for_tenant(tenant: TenantConfig, args: argparse.Namespace, config: DeploymentConfig) -> TenantRunResult:
    context = build_indexing_context(
        tenant,
        segments_root=args.segments_root,
        segments_subdir=args.segments_subdir,
    )
    indexer = TenantIndexer(context)
    start = time.perf_counter()
    result = indexer.build_segment(
        changed_paths=args.changed_paths,
        limit=args.limit,
        changed_only=args.changed_only,
        persist=not args.dry_run,
    )
    if not args.dry_run:
        _prune_segments(context.segments_dir, result.segment_ids)
    duration = time.perf_counter() - start
    return TenantRunResult(
        tenant=tenant.codename,
        documents_indexed=result.documents_indexed,
        documents_skipped=result.documents_skipped,
        errors=result.errors,
        duration_s=duration,
        segment_ids=result.segment_ids,
        segment_paths=result.segment_paths,
        dry_run=args.dry_run,
    )


def _prune_segments(segments_dir: Path, keep_segment_ids: Sequence[str]) -> None:
    store = SqliteSegmentStore(segments_dir)
    keep = list(keep_segment_ids)
    if not keep:
        latest = _latest_segment_id_from_manifest(segments_dir) or store.latest_segment_id()
        if latest is None:
            return
        keep = [latest]
    store.prune_to_segment_ids(keep)


def _latest_segment_id_from_manifest(segments_dir: Path) -> str | None:
    manifest_path = segments_dir / SqliteSegmentStore.MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    latest = payload.get("latest_segment_id")
    return latest if isinstance(latest, str) and latest.strip() else None


def _print_result(result: TenantRunResult, *, changed_only: bool) -> None:
    status = "dry-run" if result.dry_run else "persisted"
    print(
        f"- {result.tenant:<20} indexed {result.documents_indexed} docs (skipped {result.documents_skipped}) "
        f"in {result.duration_s:.2f}s [{status}{', changed-only' if changed_only else ''}]"
    )
    if not result.dry_run and result.segment_paths:
        print(f"  segment: {result.segment_paths[0]}")
        if len(result.segment_paths) > 1:
            print(f"  + {len(result.segment_paths) - 1} additional segment(s)")
    if result.segment_ids:
        print(f"  active segment ids: {', '.join(result.segment_ids)}")
    if result.errors:
        preview = list(result.errors[:3])
        for entry in preview:
            print(f"  error: {entry}")
        remaining = len(result.errors) - len(preview)
        if remaining > 0:
            print(f"  ... {remaining} more error(s)")


if __name__ == "__main__":
    raise SystemExit(main())
