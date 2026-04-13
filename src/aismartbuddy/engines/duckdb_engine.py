"""DuckDB database engine wrapper with Arrow/Polars support."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone

import duckdb
import pyarrow as pa

from aismartbuddy.engines import BaseEngine

logger = logging.getLogger("aismartbuddy.engines.duckdb")

# Formats that read_csv_auto handles (CSV, TSV, pipe-delimited, etc.)
_DELIMITED_FORMATS = {"csv", "tsv", "txt"}
_SUPPORTED_FORMATS = {"csv", "tsv", "txt", "json", "jsonl", "parquet"}


class DuckDBEngine(BaseEngine):
    """Manages a DuckDB database connection and query execution."""

    def __init__(
        self,
        db_path: str,
        max_rows: int = 1000,
        max_chars: int = 50000,
        threads: int = 0,
        memory_limit: str = "256MB",
    ) -> None:
        super().__init__(db_path, max_rows, max_chars)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._threads = threads
        self._memory_limit = memory_limit

    def connect(self) -> None:
        """Open a DuckDB connection to the database file."""
        config: dict[str, str | int] = {}
        if self._threads > 0:
            config["threads"] = self._threads
        if self._memory_limit:
            config["memory_limit"] = self._memory_limit
        # Use session dir for DuckDB temp spills
        session_dir = self._session_dir
        if session_dir:
            config["temp_directory"] = session_dir.replace("\\", "/")

        self._conn = duckdb.connect(self._db_path, config=config)
        logger.info(
            "Connected to DuckDB: %s (threads=%s, memory=%s)",
            self._db_path, self._threads, self._memory_limit,
        )

    def _require_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("Not connected")
        return self._conn

    def execute(self, sql: str) -> tuple[list[str], list[tuple]]:
        """Execute a SQL statement and return (columns, rows).

        For DDL/DML without result sets, returns ([], []).
        """
        conn = self._require_conn()
        result = conn.execute(sql)

        if result.description is None:
            return [], []

        columns = [desc[0] for desc in result.description]
        rows = result.fetchmany(self._max_rows)
        return columns, [tuple(row) for row in rows]

    def execute_arrow(self, sql: str) -> pa.Table | None:
        """Execute a SQL statement and return results as an Arrow Table.

        Returns None for DDL/DML that produces no result set.
        Uses DuckDB's native fetch_arrow_table(), sliced to max_rows to prevent OOM.
        """
        conn = self._require_conn()
        result = conn.execute(sql)

        if result.description is None:
            return None

        table = result.fetch_arrow_table()
        if table.num_rows > self._max_rows:
            table = table.slice(0, self._max_rows)
        return table

    def execute_paged(
        self, query: str, page_size: int | None = None
    ) -> tuple[str, pa.Table | None]:
        """Execute a query and return the first page via streaming Arrow reader.

        Uses DuckDB's to_arrow_reader() for memory-efficient streaming —
        the full result set is never materialized at once.

        Returns (cursor_id, first_page_table). cursor_id is "" if result fits in one page.
        """
        conn = self._require_conn()
        size = page_size or self._max_rows
        result = conn.execute(query)

        if result.description is None:
            return "", None

        reader = result.to_arrow_reader(batch_size=size)

        try:
            first_batch = reader.read_next_batch()
        except StopIteration:
            # Empty result set
            schema = reader.schema
            empty = {
                name: pa.array([], type=schema.field(name).type)
                for name in schema.names
            }
            return "", pa.table(empty)

        first_page = pa.Table.from_batches([first_batch], schema=reader.schema)

        # Check if there are more batches
        try:
            peek_batch = reader.read_next_batch()
        except StopIteration:
            # Only one batch — no cursor needed
            return "", first_page

        # More data exists — store reader with peeked batch
        cursor_id = uuid.uuid4().hex[:12]
        with self._cursor_lock:
            self._cursors[cursor_id] = (
                _PeekedReader(peek_batch, reader),
                datetime.now(timezone.utc),
            )
        return cursor_id, first_page

    def fetch_next_page(self, cursor_id: str) -> pa.Table | None:
        """Fetch the next page from a streaming Arrow reader cursor.

        Returns None when exhausted (auto-closes cursor).
        """
        with self._cursor_lock:
            entry = self._cursors.get(cursor_id)
            if entry is None:
                raise ValueError(
                    f"Cursor '{cursor_id}' not found. "
                    "It may have expired or already been exhausted."
                )
            peeked_reader, _ = entry
            self._cursors[cursor_id] = (peeked_reader, datetime.now(timezone.utc))

        batch = peeked_reader.read_next()
        if batch is None:
            self.close_cursor(cursor_id)
            return None

        # If the reader has no more data after this batch, close cursor now
        # so has_more check is accurate
        if not peeked_reader.has_more:
            self.close_cursor(cursor_id)

        return pa.Table.from_batches([batch], schema=peeked_reader.schema)

    def import_data(
        self,
        table_name: str,
        data: str,
        data_format: str = "csv",
        create_table: bool = True,
        delimiter: str | None = None,
    ) -> int:
        """Import string data into a table. Supports CSV, TSV, JSON, JSONL, Parquet.

        Args:
            table_name: Target table name.
            data: Content as a string. For parquet, this must be base64-encoded.
            data_format: One of: csv, tsv, txt, json, jsonl, parquet.
            create_table: If True, auto-creates the table from data schema.
            delimiter: Optional custom delimiter (e.g., "|", ";"). Only for delimited formats.

        Returns:
            Number of rows imported.
        """
        self._validate_identifier(table_name, "table_name")
        fmt = data_format.lower()
        if fmt not in _SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: '{data_format}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_FORMATS))}"
            )

        if delimiter is not None:
            if len(delimiter) != 1:
                raise ValueError("Delimiter must be a single character.")
            if delimiter in ("'", "\\"):
                raise ValueError(f"Invalid delimiter: {delimiter!r}")

        conn = self._require_conn()

        # Write data to temp file
        if fmt == "parquet":
            tmp_path = self._write_temp_file_binary(data)
        elif fmt == "tsv":
            tmp_path = self._write_temp_file(data, ".tsv")
        elif fmt == "txt":
            tmp_path = self._write_temp_file(data, ".txt")
        elif fmt in ("json", "jsonl"):
            tmp_path = self._write_temp_file(data, ".json")
        else:
            tmp_path = self._write_temp_file(data, ".csv")

        try:
            escaped_path = tmp_path.replace("\\", "/")
            read_func = self._build_read_function(fmt, escaped_path, delimiter)

            if create_table:
                conn.execute(
                    f"CREATE OR REPLACE TABLE {table_name} AS "
                    f"SELECT * FROM {read_func}"
                )
            else:
                before = conn.execute(
                    f"SELECT count(*) FROM {table_name}"
                ).fetchone()[0]
                conn.execute(
                    f"INSERT INTO {table_name} SELECT * FROM {read_func}"
                )
                after = conn.execute(
                    f"SELECT count(*) FROM {table_name}"
                ).fetchone()[0]
                return after - before

            row = conn.execute(
                f"SELECT count(*) FROM {table_name}"
            ).fetchone()
            return row[0] if row else 0
        finally:
            self._safe_unlink(tmp_path)

    def import_batch(
        self,
        table_name: str,
        chunks: list[str],
        data_format: str = "csv",
        delimiter: str | None = None,
    ) -> int:
        """Import multiple data chunks into a single table.

        The first chunk creates (or replaces) the table with auto-detected schema.
        Subsequent chunks append rows.

        Args:
            table_name: Target table name.
            chunks: List of data strings (each with headers for CSV/TSV).
            data_format: Format of all chunks (csv, tsv, json, etc.).
            delimiter: Optional custom delimiter.

        Returns:
            Total number of rows imported across all chunks.
        """
        if not chunks:
            return 0

        total = 0
        for i, chunk in enumerate(chunks):
            create = i == 0
            count = self.import_data(
                table_name, chunk, data_format, create_table=create, delimiter=delimiter
            )
            total += count
        return total

    def _build_read_function(
        self, fmt: str, escaped_path: str, delimiter: str | None
    ) -> str:
        """Build the DuckDB read function call for the given format."""
        if fmt in _DELIMITED_FORMATS:
            opts = ["header=true", "auto_detect=true"]
            if delimiter:
                opts.append(f"delim='{delimiter}'")
            elif fmt == "tsv":
                opts.append("delim='\\t'")
            opts_str = ", ".join(opts)
            return f"read_csv('{escaped_path}', {opts_str})"
        elif fmt in ("json", "jsonl"):
            return f"read_json_auto('{escaped_path}')"
        elif fmt == "parquet":
            return f"read_parquet('{escaped_path}')"
        else:
            return f"read_csv_auto('{escaped_path}')"

    def _write_temp_file_binary(self, base64_data: str) -> str:
        """Decode base64 data and write to a temp .parquet file."""
        import os  # noqa: F811
        import tempfile  # noqa: F811

        try:
            raw = base64.b64decode(base64_data)
        except Exception as exc:
            raise ValueError(
                "Invalid base64 data for parquet format. "
                "Ensure the parquet file is base64-encoded."
            ) from exc
        fd, path = tempfile.mkstemp(suffix=".parquet", dir=self._session_dir)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        return path

    # Keep backward-compatible aliases
    def import_csv(self, table_name: str, csv_data: str, create_table: bool = True) -> int:
        return self.import_data(table_name, csv_data, "csv", create_table)

    def import_json(self, table_name: str, json_data: str, create_table: bool = True) -> int:
        return self.import_data(table_name, json_data, "json", create_table)

    def get_tables(self) -> list[str]:
        """Return list of table names in the database."""
        conn = self._require_conn()
        result = conn.execute("SHOW TABLES")
        rows = result.fetchall()
        return [row[0] for row in rows]

    def describe_table(self, name: str) -> tuple[list[str], list[tuple]]:
        """Describe a table's schema. Returns (columns, rows) from DESCRIBE."""
        self._validate_identifier(name, "table_name")
        conn = self._require_conn()
        result = conn.execute(f"DESCRIBE {name}")
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return columns, [tuple(row) for row in rows]

    def close(self) -> None:
        """Close the database connection and all cursors."""
        self.close_all_cursors()
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("Closed DuckDB connection: %s", self._db_path)


class _PeekedReader:
    """Wrapper around RecordBatchReader with one-ahead peek for has_more detection."""

    def __init__(self, peeked: pa.RecordBatch, reader: pa.RecordBatchReader) -> None:
        self._peeked: pa.RecordBatch | None = peeked
        self._reader = reader
        self._exhausted = False

    @property
    def schema(self) -> pa.Schema:
        return self._reader.schema

    @property
    def has_more(self) -> bool:
        """True if there are more batches after the most recently returned one."""
        return not self._exhausted

    def read_next(self) -> pa.RecordBatch | None:
        if self._peeked is not None:
            batch = self._peeked
            self._peeked = None
            # Peek ahead to know if there's more after this
            try:
                self._peeked = self._reader.read_next_batch()
            except StopIteration:
                self._exhausted = True
            return batch
        if self._exhausted:
            return None
        try:
            batch = self._reader.read_next_batch()
        except StopIteration:
            self._exhausted = True
            return None
        # Peek ahead
        try:
            self._peeked = self._reader.read_next_batch()
        except StopIteration:
            self._exhausted = True
        return batch
