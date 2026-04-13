"""AISmartBuddy database engine modules."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa

logger = logging.getLogger("aismartbuddy.engines")


class BaseEngine(ABC):
    """Shared base for database engines."""

    def __init__(self, db_path: str, max_rows: int = 1000, max_chars: int = 50000) -> None:
        self._db_path = db_path
        self._max_rows = max_rows
        self._max_chars = max_chars
        self._cursors: dict[str, tuple[Any, datetime]] = {}
        self._cursor_lock = threading.Lock()

    @property
    def _session_dir(self) -> str:
        return str(Path(self._db_path).parent)

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def execute(self, query: str) -> tuple[list[str], list[tuple]]: ...

    @abstractmethod
    def close(self) -> None: ...

    def execute_arrow(self, query: str) -> pa.Table | None:
        """Execute a query and return results as an Arrow Table.

        Returns None for DDL/DML that produces no result set.
        Default implementation converts from execute() — subclasses should override
        with native Arrow support for better performance.
        """
        columns, rows = self.execute(query)
        if not columns:
            return None
        return tuples_to_arrow(columns, rows)

    def execute_paged(
        self, query: str, page_size: int | None = None
    ) -> tuple[str, pa.Table | None]:
        """Execute a query and return the first page with a cursor ID for subsequent pages.

        Returns (cursor_id, first_page_table). first_page_table is None for DDL/DML.
        Default implementation materializes full result and slices — subclasses should
        override with streaming support (e.g. DuckDB's RecordBatchReader).
        """
        size = page_size or self._max_rows
        table = self.execute_arrow(query)
        if table is None:
            return "", None

        cursor_id = uuid.uuid4().hex[:12]
        if table.num_rows <= size:
            # Entire result fits in one page — no cursor needed
            return "", table

        # Materialize and store remaining rows for paging
        import polars as pl

        df = pl.from_arrow(table)
        first_page = df.head(size).to_arrow()
        remaining = df.slice(size)
        iterator = remaining.iter_slices(size)
        with self._cursor_lock:
            self._cursors[cursor_id] = (iterator, datetime.now(timezone.utc))
        return cursor_id, first_page

    def fetch_next_page(self, cursor_id: str) -> pa.Table | None:
        """Fetch the next page from a stored cursor.

        Returns None when the cursor is exhausted (auto-closes).
        """
        with self._cursor_lock:
            entry = self._cursors.get(cursor_id)
            if entry is None:
                raise ValueError(
                    f"Cursor '{cursor_id}' not found. "
                    "It may have expired or already been exhausted."
                )
            iterator, _ = entry
            self._cursors[cursor_id] = (iterator, datetime.now(timezone.utc))
        try:
            batch = next(iterator)
            return batch.to_arrow()
        except StopIteration:
            self.close_cursor(cursor_id)
            return None

    def cursor_exists(self, cursor_id: str) -> bool:
        """Check if a cursor is still active (thread-safe)."""
        with self._cursor_lock:
            return cursor_id in self._cursors

    def close_cursor(self, cursor_id: str) -> None:
        """Close and remove a cursor."""
        with self._cursor_lock:
            self._cursors.pop(cursor_id, None)

    def cleanup_expired_cursors(self, timeout: int = 300) -> int:
        """Remove cursors that have been idle longer than timeout seconds."""
        now = datetime.now(timezone.utc)
        with self._cursor_lock:
            expired = [
                cid
                for cid, (_, last_accessed) in self._cursors.items()
                if (now - last_accessed).total_seconds() > timeout
            ]
            for cid in expired:
                self._cursors.pop(cid, None)
        return len(expired)

    def close_all_cursors(self) -> None:
        """Close all active cursors. Called during session cleanup."""
        with self._cursor_lock:
            self._cursors.clear()

    def _write_temp_file(self, data: str, suffix: str) -> str:
        """Write data to a temp file in the session directory."""
        fd, path = tempfile.mkstemp(suffix=suffix, dir=self._session_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        return path

    _IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @staticmethod
    def _validate_identifier(name: str, label: str = "identifier") -> str:
        """Validate a SQL/Cypher identifier to prevent injection."""
        if not BaseEngine._IDENT_RE.match(name):
            raise ValueError(
                f"Invalid {label}: {name!r}. "
                "Must contain only letters, digits, underscores, and start with a letter."
            )
        return name

    @staticmethod
    def _safe_unlink(path: str) -> None:
        """Delete a temp file, logging on failure instead of raising."""
        try:
            os.unlink(path)
        except OSError:
            logger.warning("Could not delete temp file: %s", path)


def _disambiguate_columns(columns: list[str]) -> list[str]:
    """Make column names unique by appending _1, _2, etc. for duplicates."""
    seen: dict[str, int] = {}
    result = []
    for name in columns:
        if name in seen:
            seen[name] += 1
            result.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            result.append(name)
    return result


def tuples_to_arrow(columns: list[str], rows: list[tuple]) -> pa.Table:
    """Convert (columns, rows) tuples into a PyArrow Table.

    Handles duplicate column names (e.g. from JOINs) by disambiguating.
    """
    unique_cols = _disambiguate_columns(columns)
    if not rows:
        arrays = [pa.array([], type=pa.string()) for _ in unique_cols]
        return pa.table(dict(zip(unique_cols, arrays)))
    col_data = list(zip(*rows))
    arrays = [pa.array(list(col)) for col in col_data]
    return pa.table(dict(zip(unique_cols, arrays)))
