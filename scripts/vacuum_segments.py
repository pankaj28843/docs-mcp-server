"""Vacuum search segment SQLite databases to reclaim disk space."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sqlite3


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _iter_segment_dbs(root: Path, tenant: str | None) -> list[Path]:
    if tenant:
        candidate = root / tenant / "__search_segments"
        if candidate.exists():
            return sorted(candidate.glob("*.db"))
        return []
    return sorted(root.rglob("__search_segments/*.db"))


def _vacuum_db(db_path: Path, *, dry_run: bool) -> None:
    if dry_run:
        logger.info("Dry run: would vacuum %s", db_path)
        return
    logger.info("Vacuuming %s", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vacuum SQLite segment files to reclaim disk space.")
    parser.add_argument("--tenant", help="Tenant codename to vacuum (optional).")
    parser.add_argument(
        "--segments-root",
        default="mcp-data",
        help="Root directory containing tenant docs (default: mcp-data).",
    )
    parser.add_argument("--dry-run", action="store_true", help="List segment DBs without modifying them.")
    args = parser.parse_args()

    root = Path(args.segments_root).expanduser()
    if not root.exists():
        logger.error("Segments root does not exist: %s", root)
        return 1

    segment_dbs = _iter_segment_dbs(root, args.tenant)
    if not segment_dbs:
        logger.info("No segment DBs found under %s", root)
        return 0

    for db_path in segment_dbs:
        _vacuum_db(db_path, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
