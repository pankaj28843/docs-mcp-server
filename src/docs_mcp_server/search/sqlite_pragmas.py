"""Shared SQLite PRAGMA helpers for consistent performance tuning."""

from __future__ import annotations

import sqlite3


def apply_read_pragmas(
    conn: sqlite3.Connection,
    *,
    cache_size_kb: int = -64000,
    mmap_size_bytes: int = 268435456,
    temp_store: str = "MEMORY",
    query_only: bool = True,
    threads: int | None = None,
    busy_timeout_ms: int | None = None,
) -> None:
    """Apply read-optimized PRAGMAs with optional overrides."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA cache_size = {cache_size_kb}")
    conn.execute(f"PRAGMA mmap_size = {mmap_size_bytes}")
    conn.execute(f"PRAGMA temp_store = {temp_store}")
    if busy_timeout_ms is not None:
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    if threads is not None:
        conn.execute(f"PRAGMA threads = {threads}")
    if query_only:
        conn.execute("PRAGMA query_only = 1")


def apply_write_pragmas(
    conn: sqlite3.Connection,
    *,
    cache_size_kb: int = -64000,
    mmap_size_bytes: int = 268435456,
    temp_store: str = "MEMORY",
    page_size: int = 4096,
    cache_spill: bool = False,
) -> None:
    """Apply write-optimized PRAGMAs for segment creation."""
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA cache_size = {cache_size_kb}")
    conn.execute(f"PRAGMA mmap_size = {mmap_size_bytes}")
    conn.execute(f"PRAGMA temp_store = {temp_store}")
    conn.execute(f"PRAGMA page_size = {page_size}")
    conn.execute(f"PRAGMA cache_spill = {'TRUE' if cache_spill else 'FALSE'}")
