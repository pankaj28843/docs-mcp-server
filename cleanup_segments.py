#!/usr/bin/env python3
"""Cleanup search segments and sync metadata based on deployment config."""

# ruff: noqa: T201  # CLI intentionally prints progress summary

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from itertools import chain
import json
from pathlib import Path
from typing import Any

from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore


SEGMENTS_SUBDIR_DEFAULT = "__search_segments"
SYNC_METADATA_SUBDIR_DEFAULT = "__scheduler_meta"
DOCS_METADATA_SUBDIR_DEFAULT = "__docs_metadata"


@dataclass(slots=True)
class RemovedFile:
    path: Path
    size: int


@dataclass(slots=True)
class DirectoryReport:
    directory: Path
    removed: list[RemovedFile] = field(default_factory=list)
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def bytes_reclaimed(self) -> int:
        return sum(entry.size for entry in self.removed)

    @property
    def cleaned(self) -> bool:
        return bool(self.removed)


@dataclass(slots=True)
class MetadataReport:
    directory: Path
    removed: list[RemovedFile] = field(default_factory=list)
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    entries_scanned: int = 0

    @property
    def bytes_reclaimed(self) -> int:
        return sum(entry.size for entry in self.removed)

    @property
    def cleaned(self) -> bool:
        return bool(self.removed)


@dataclass(slots=True)
class DocsMetadataReport:
    directory: Path
    removed_metadata: list[RemovedFile] = field(default_factory=list)
    removed_markdown: list[RemovedFile] = field(default_factory=list)
    scheduler_removed: list[RemovedFile] = field(default_factory=list)
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    entries_scanned: int = 0
    missing_markdown: int = 0
    disallowed_urls: int = 0
    duplicate_entries: int = 0

    @property
    def bytes_reclaimed(self) -> int:
        return sum(entry.size for entry in chain(self.removed_metadata, self.removed_markdown))

    @property
    def cleaned(self) -> bool:
        return bool(self.removed_metadata or self.removed_markdown or self.scheduler_removed)


@dataclass(slots=True)
class CleanupSummary:
    scanned: int = 0
    cleaned: int = 0
    files_removed: int = 0
    bytes_reclaimed: int = 0
    metadata_scanned: int = 0
    metadata_cleaned: int = 0
    metadata_files_removed: int = 0
    metadata_bytes_reclaimed: int = 0
    docs_metadata_scanned: int = 0
    docs_metadata_cleaned: int = 0
    docs_metadata_files_removed: int = 0
    docs_markdown_files_removed: int = 0
    docs_metadata_bytes_reclaimed: int = 0
    scheduler_entries_removed: int = 0
    errors: list[str] = field(default_factory=list)

    def record(self, report: DirectoryReport) -> None:
        self.scanned += 1
        if report.errors:
            for error in report.errors:
                self.errors.append(f"{report.directory}: {error}")
        if report.skipped_reason:
            return
        if report.cleaned:
            self.cleaned += 1
            self.files_removed += len(report.removed)
            self.bytes_reclaimed += report.bytes_reclaimed

    def record_metadata(self, report: MetadataReport) -> None:
        self.metadata_scanned += 1
        if report.errors:
            for error in report.errors:
                self.errors.append(f"{report.directory}: {error}")
        if report.skipped_reason:
            return
        if report.cleaned:
            self.metadata_cleaned += 1
            self.metadata_files_removed += len(report.removed)
            self.metadata_bytes_reclaimed += report.bytes_reclaimed

    def record_docs_metadata(self, report: DocsMetadataReport) -> None:
        self.docs_metadata_scanned += 1
        if report.errors:
            for error in report.errors:
                self.errors.append(f"{report.directory}: {error}")
        if report.skipped_reason:
            return
        if report.cleaned:
            self.docs_metadata_cleaned += 1
        self.docs_metadata_files_removed += len(report.removed_metadata)
        self.docs_markdown_files_removed += len(report.removed_markdown)
        self.scheduler_entries_removed += len(report.scheduler_removed)
        self.docs_metadata_bytes_reclaimed += report.bytes_reclaimed


@dataclass(slots=True)
class TenantTarget:
    codename: str | None
    docs_root: Path
    segments_dir: Path
    metadata_dir: Path
    docs_metadata_dir: Path
    whitelist: tuple[str, ...]
    blacklist: tuple[str, ...]


@dataclass(slots=True)
class TenantReport:
    target: TenantTarget
    segment_report: DirectoryReport
    metadata_report: MetadataReport
    docs_metadata_report: DocsMetadataReport | None = None


def _load_deployment_payload(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid deployment config: {exc}") from exc


def _split_config_value(raw_value: Any) -> tuple[str, ...]:
    if not isinstance(raw_value, str) or not raw_value:
        return ()
    entries = [entry.strip() for entry in raw_value.split(",") if entry.strip()]
    return tuple(entries)


def collect_tenant_targets(
    *,
    root: Path | None = None,
    config_path: Path | None = None,
    extra_dirs: Sequence[Path] | None = None,
    segments_subdir: str = SEGMENTS_SUBDIR_DEFAULT,
    metadata_subdir: str = SYNC_METADATA_SUBDIR_DEFAULT,
    config_data: dict[str, Any] | None = None,
) -> list[TenantTarget]:
    """Discover tenant docs roots along with whitelist/blacklist filters."""

    if config_data is None and config_path and config_path.exists():
        config_data = _load_deployment_payload(config_path)

    targets: list[TenantTarget] = []
    seen: set[Path] = set()

    def _register(
        docs_root: Path,
        *,
        codename: str | None,
        whitelist: tuple[str, ...] = (),
        blacklist: tuple[str, ...] = (),
    ) -> None:
        resolved = docs_root.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        targets.append(
            TenantTarget(
                codename=codename,
                docs_root=resolved,
                segments_dir=resolved / segments_subdir,
                metadata_dir=resolved / metadata_subdir,
                docs_metadata_dir=resolved / DOCS_METADATA_SUBDIR_DEFAULT,
                whitelist=whitelist,
                blacklist=blacklist,
            )
        )

    if config_data:
        tenants = config_data.get("tenants", [])
        if isinstance(tenants, list):
            for tenant in tenants:
                if not isinstance(tenant, dict):
                    continue
                codename = tenant.get("codename")
                docs_root_dir = tenant.get("docs_root_dir")
                if docs_root_dir:
                    docs_root = Path(docs_root_dir)
                elif root and codename:
                    docs_root = root / codename
                else:
                    continue
                whitelist = _split_config_value(tenant.get("url_whitelist_prefixes"))
                blacklist = _split_config_value(tenant.get("url_blacklist_prefixes"))
                _register(docs_root, codename=codename, whitelist=whitelist, blacklist=blacklist)

    if root:
        normalized_root = root.expanduser()
        if normalized_root.exists():
            for child in normalized_root.iterdir():
                if child.is_dir():
                    _register(child, codename=child.name)

    if extra_dirs:
        for path in extra_dirs:
            _register(path.expanduser(), codename=path.name)

    return targets


def cleanup_directory(
    directory: Path,
    *,
    dry_run: bool = False,
) -> DirectoryReport:
    if not directory.exists():
        return DirectoryReport(directory=directory, skipped_reason="missing directory")
    if not directory.is_dir():
        return DirectoryReport(directory=directory, skipped_reason="not a directory")

    # For SQLite storage, use the store to get segment information
    try:
        store = SqliteSegmentStore(directory)
        segments = store.list_segments()
        
        if not segments:
            return DirectoryReport(directory=directory, skipped_reason="no segments found")
        
        # Keep only the most recent segments (up to MAX_SEGMENTS)
        segments.sort(key=lambda s: s["created_at"], reverse=True)
        keep_segments = segments[:SqliteSegmentStore.MAX_SEGMENTS]
        keep_segment_ids = {s["segment_id"] for s in keep_segments}
        
        removed: list[RemovedFile] = []
        errors: list[str] = []
        
        # Remove old segments
        for db_file in directory.glob(f"*{SqliteSegmentStore.DB_SUFFIX}"):
            segment_id = db_file.stem
            if segment_id not in keep_segment_ids:
                size = db_file.stat().st_size
                removed.append(RemovedFile(path=db_file, size=size))
                if not dry_run:
                    try:
                        db_file.unlink()
                    except OSError as exc:
                        errors.append(f"failed to remove {db_file.name}: {exc}")
        
        return DirectoryReport(directory=directory, removed=removed, errors=errors)
        
    except Exception as exc:
        return DirectoryReport(directory=directory, errors=[f"cleanup error: {exc}"])


def cleanup_directories(
    directories: Iterable[Path], *, dry_run: bool = False
) -> tuple[CleanupSummary, list[DirectoryReport]]:
    summary = CleanupSummary()
    reports: list[DirectoryReport] = []
    for directory in directories:
        report = cleanup_directory(directory, dry_run=dry_run)
        reports.append(report)
        summary.record(report)
    return summary, reports


def cleanup_metadata_directory(
    directory: Path,
    *,
    whitelist: Sequence[str] = (),
    blacklist: Sequence[str] = (),
    dry_run: bool = False,
) -> MetadataReport:
    if not directory.exists():
        return MetadataReport(directory=directory, skipped_reason="missing directory")
    if not directory.is_dir():
        return MetadataReport(directory=directory, skipped_reason="not a directory")

    removed: list[RemovedFile] = []
    errors: list[str] = []
    entries_scanned = 0

    for path in directory.glob("*.json"):
        if not path.name.startswith("url_"):
            continue
        entries_scanned += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        url = data.get("url") if isinstance(data, dict) else None
        allowed = _url_allowed(url, whitelist, blacklist)
        if allowed:
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:  # pragma: no cover - unlikely
            errors.append(f"failed to stat {path.name}: {exc}")
            continue
        removed.append(RemovedFile(path=path, size=size))
        if dry_run:
            continue
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"failed to remove {path.name}: {exc}")

    return MetadataReport(
        directory=directory,
        removed=removed,
        skipped_reason=None,
        errors=errors,
        entries_scanned=entries_scanned,
    )


def cleanup_docs_metadata_directory(
    directory: Path,
    *,
    docs_root: Path,
    whitelist: Sequence[str] = (),
    blacklist: Sequence[str] = (),
    scheduler_dir: Path | None = None,
    dry_run: bool = False,
) -> DocsMetadataReport:
    if not directory.exists():
        return DocsMetadataReport(directory=directory, skipped_reason="missing directory")
    if not directory.is_dir():
        return DocsMetadataReport(directory=directory, skipped_reason="not a directory")

    report = DocsMetadataReport(directory=directory)
    seen_markdown: set[Path] = set()

    for meta_path in directory.rglob("*.meta.json"):
        report.entries_scanned += 1
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.errors.append(f"{meta_path.name}: {exc}")
            continue

        url = payload.get("url") if isinstance(payload, dict) else None
        metadata_payload = payload.get("metadata") if isinstance(payload, dict) else None
        if not isinstance(metadata_payload, dict):
            metadata_payload = {}

        markdown_path = _resolve_markdown_path_from_metadata(meta_path, docs_root, metadata_payload)
        markdown_exists = markdown_path.exists()
        duplicate = markdown_path in seen_markdown if markdown_path else False
        allowed = _url_allowed(url or "", whitelist, blacklist)
        remove_reason: str | None = None

        if not allowed:
            remove_reason = "disallowed"
            report.disallowed_urls += 1
        elif not markdown_exists:
            remove_reason = "missing_markdown"
            report.missing_markdown += 1
        elif duplicate:
            remove_reason = "duplicate"
            report.duplicate_entries += 1

        if not remove_reason:
            if markdown_path:
                seen_markdown.add(markdown_path)
            continue

        _remove_file(meta_path, report.removed_metadata, report.errors, dry_run)

        if remove_reason == "disallowed" and markdown_exists:
            _remove_file(markdown_path, report.removed_markdown, report.errors, dry_run)

        if scheduler_dir is not None:
            scheduler_removed = _remove_scheduler_entry(url, scheduler_dir, report.errors, dry_run)
            if scheduler_removed:
                report.scheduler_removed.append(scheduler_removed)

    return report


def _url_allowed(url: str | None, whitelist: Sequence[str], blacklist: Sequence[str]) -> bool:
    normalized = url.strip() if isinstance(url, str) else ""
    if whitelist:
        if not normalized:
            return False
        if not any(normalized.startswith(prefix) for prefix in whitelist):
            return False
    if not normalized:
        return True
    if blacklist and any(normalized.startswith(prefix) for prefix in blacklist):
        return False
    return True


def _resolve_markdown_path_from_metadata(meta_path: Path, docs_root: Path, meta_info: dict[str, Any]) -> Path:
    rel_path = meta_info.get("markdown_rel_path") if isinstance(meta_info, dict) else None
    candidate: Path
    if isinstance(rel_path, str) and rel_path.strip():
        candidate = Path(rel_path)
        if not candidate.is_absolute():
            candidate = docs_root / candidate
        return candidate.resolve()

    metadata_root = docs_root / DOCS_METADATA_SUBDIR_DEFAULT
    try:
        relative = meta_path.relative_to(metadata_root)
    except ValueError:
        relative = Path(meta_path.name)
    relative_str = str(relative)
    if relative_str.endswith(".meta.json"):
        relative_str = relative_str[: -len(".meta.json")] + ".md"
    return (docs_root / relative_str).resolve()


def _remove_file(path: Path, sink: list[RemovedFile], errors: list[str], dry_run: bool) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    sink.append(RemovedFile(path=path, size=size))
    if dry_run:
        return
    try:
        path.unlink()
    except OSError as exc:
        errors.append(f"failed to remove {path}: {exc}")


def _remove_scheduler_entry(
    url: str | None,
    directory: Path,
    errors: list[str],
    dry_run: bool,
) -> RemovedFile | None:
    normalized = url.strip() if isinstance(url, str) else ""
    if not normalized or not directory.exists():
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    candidate = directory / f"url_{digest}.json"
    if not candidate.exists():
        return None
    try:
        size = candidate.stat().st_size
    except OSError:
        size = 0
    if not dry_run:
        try:
            candidate.unlink()
        except OSError as exc:
            errors.append(f"failed to remove {candidate}: {exc}")
            return None
    return RemovedFile(path=candidate, size=size)


def cleanup_tenants(
    targets: Sequence[TenantTarget], *, dry_run: bool = False, docs_metadata: bool = True
) -> tuple[CleanupSummary, list[TenantReport]]:
    summary = CleanupSummary()
    reports: list[TenantReport] = []
    for target in targets:
        seg_report = cleanup_directory(target.segments_dir, dry_run=dry_run)
        summary.record(seg_report)
        metadata_report = cleanup_metadata_directory(
            target.metadata_dir,
            whitelist=target.whitelist,
            blacklist=target.blacklist,
            dry_run=dry_run,
        )
        summary.record_metadata(metadata_report)
        docs_meta_report: DocsMetadataReport | None = None
        if docs_metadata:
            docs_meta_report = cleanup_docs_metadata_directory(
                target.docs_metadata_dir,
                docs_root=target.docs_root,
                whitelist=target.whitelist,
                blacklist=target.blacklist,
                scheduler_dir=target.metadata_dir,
                dry_run=dry_run,
            )
            summary.record_docs_metadata(docs_meta_report)
        reports.append(
            TenantReport(
                target=target,
                segment_report=seg_report,
                metadata_report=metadata_report,
                docs_metadata_report=docs_meta_report,
            )
        )
    return summary, reports


def _format_bytes(num: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{num}B"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "Cleanup SQLite search segments")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("mcp-data"),
        help="Root directory containing tenant data (default: mcp-data)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("deployment.json"),
        help="Deployment config used to discover tenant docs_root_dir entries",
    )
    parser.add_argument(
        "--segments-subdir",
        default=SEGMENTS_SUBDIR_DEFAULT,
        help="Subdirectory name that stores search segments (default: __search_segments)",
    )
    parser.add_argument(
        "--metadata-subdir",
        default=SYNC_METADATA_SUBDIR_DEFAULT,
        help="Subdirectory name for sync metadata (default: __scheduler_meta)",
    )
    parser.add_argument(
        "--extra-dir",
        action="append",
        dest="extra_dirs",
        type=Path,
        help="Additional docs_root_dir paths to scan (repeatable)",
    )
    parser.add_argument(
        "--docs-metadata",
        dest="docs_metadata",
        action="store_true",
        default=True,
        help="Also scan __docs_metadata for stale files (default: enabled)",
    )
    parser.add_argument(
        "--no-docs-metadata",
        dest="docs_metadata",
        action="store_false",
        help="Skip __docs_metadata cleanup",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report deletions without removing files",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print summary output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:  # noqa: PLR0912 - CLI argument handling
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    config_payload: dict[str, object] | None = None
    if args.config and args.config.exists():
        try:
            config_payload = _load_deployment_payload(args.config)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

    try:
        targets = collect_tenant_targets(
            root=args.root,
            config_path=args.config if args.config.exists() else None,
            extra_dirs=args.extra_dirs,
            segments_subdir=args.segments_subdir,
            metadata_subdir=args.metadata_subdir,
            config_data=config_payload,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if not targets:
        print("No tenant directories found; nothing to do.")
        return 0

    summary, reports = cleanup_tenants(targets, dry_run=args.dry_run, docs_metadata=args.docs_metadata)

    if not args.quiet:
        action = "Would remove" if args.dry_run else "Removed"
        for report in reports:
            label = report.target.codename or str(report.target.docs_root)
            print(f"- {label}")
            seg = report.segment_report
            if seg.skipped_reason:
                print(f"  segments: skipped ({seg.skipped_reason})")
            elif seg.errors:
                print(f"  segments: errors -> {', '.join(seg.errors)}")
            elif seg.cleaned:
                for entry in seg.removed:
                    print(f"    {action} segment {entry.path} ({entry.size} bytes)")
            else:
                print("  segments: clean")

            meta = report.metadata_report
            if meta.skipped_reason:
                print(f"  metadata: skipped ({meta.skipped_reason})")
            elif meta.errors:
                print(f"  metadata: errors -> {', '.join(meta.errors)}")
            elif meta.cleaned:
                for entry in meta.removed:
                    print(f"    {action} metadata {entry.path} ({entry.size} bytes)")
            else:
                print("  metadata: clean")

            docs_meta = report.docs_metadata_report
            if docs_meta is not None:
                if docs_meta.skipped_reason:
                    print(f"  docs-metadata: skipped ({docs_meta.skipped_reason})")
                elif docs_meta.errors:
                    print(f"  docs-metadata: errors -> {', '.join(docs_meta.errors)}")
                elif docs_meta.cleaned:
                    for entry in docs_meta.removed_metadata:
                        print(f"    {action} doc metadata {entry.path} ({entry.size} bytes)")
                    for entry in docs_meta.removed_markdown:
                        print(f"    {action} markdown {entry.path} ({entry.size} bytes)")
                    if docs_meta.scheduler_removed:
                        for entry in docs_meta.scheduler_removed:
                            print(f"    {action} scheduler entry {entry.path} ({entry.size} bytes)")
                else:
                    print("  docs-metadata: clean")

    if args.dry_run:
        print("Dry run; no files were removed.")

    seg_total = _format_bytes(summary.bytes_reclaimed)
    print(
        f"Segments: scanned {summary.scanned}; {summary.cleaned} cleaned; "
        f"{summary.files_removed} files {'scheduled' if args.dry_run else 'removed'}; reclaimed {seg_total}."
    )

    meta_total = _format_bytes(summary.metadata_bytes_reclaimed)
    print(
        f"Metadata: scanned {summary.metadata_scanned}; {summary.metadata_cleaned} directories cleaned; "
        f"{summary.metadata_files_removed} entries {'scheduled' if args.dry_run else 'removed'}; reclaimed {meta_total}."
    )

    docs_meta_total = _format_bytes(summary.docs_metadata_bytes_reclaimed)
    print(
        f"Docs metadata: scanned {summary.docs_metadata_scanned}; {summary.docs_metadata_cleaned} directories cleaned; "
        f"{summary.docs_metadata_files_removed} metadata + {summary.docs_markdown_files_removed} markdown files {'scheduled' if args.dry_run else 'removed'}; "
        f"{summary.scheduler_entries_removed} scheduler entries purged; reclaimed {docs_meta_total}."
    )

    if summary.errors:
        for line in summary.errors:
            print(f"Error: {line}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
