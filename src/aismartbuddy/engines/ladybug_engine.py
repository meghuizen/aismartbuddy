"""LadybugDB graph database engine wrapper with Arrow/Polars support."""

from __future__ import annotations

import logging

import ladybug as lb
import pyarrow as pa

from aismartbuddy.engines import BaseEngine, tuples_to_arrow

logger = logging.getLogger("aismartbuddy.engines.ladybug")


class LadybugEngine(BaseEngine):
    """Manages a LadybugDB graph database connection and query execution."""

    def __init__(
        self,
        db_path: str,
        max_rows: int = 1000,
        max_chars: int = 50000,
        buffer_pool_size: int = 256 * 1024 * 1024,
        max_threads: int = 0,
    ) -> None:
        super().__init__(db_path, max_rows, max_chars)
        self._db: lb.Database | None = None
        self._conn: lb.Connection | None = None
        self._buffer_pool_size = buffer_pool_size
        self._max_threads = max_threads

    def connect(self) -> None:
        """Open a LadybugDB connection with configured buffer pool."""
        db_kwargs: dict = {"database_path": self._db_path}
        if self._buffer_pool_size > 0:
            db_kwargs["buffer_pool_size"] = self._buffer_pool_size
        if self._max_threads > 0:
            db_kwargs["max_num_threads"] = self._max_threads

        try:
            self._db = lb.Database(**db_kwargs)
        except TypeError:
            # Compatibility fallback for LadybugDB builds without tuning kwargs.
            self._db = lb.Database(self._db_path)
            logger.debug("LadybugDB Database() does not accept buffer/thread config")

        self._conn = lb.Connection(self._db)

        # Install JSON extension for JSON support
        try:
            self._conn.execute("INSTALL json; LOAD json;")
        except Exception:
            logger.debug("JSON extension not available or already loaded")

        logger.info(
            "Connected to LadybugDB: %s (buffer=%dMB, threads=%d)",
            self._db_path,
            self._buffer_pool_size // (1024 * 1024),
            self._max_threads,
        )

    def _require_conn(self) -> lb.Connection:
        if self._conn is None:
            raise RuntimeError("Not connected")
        return self._conn

    def _extract_result(
        self,
        result: lb.QueryResult | list[lb.QueryResult],
    ) -> lb.QueryResult | None:
        """Normalize LadybugDB result (handles list for multi-statement queries)."""
        if isinstance(result, list):
            return result[-1] if result else None
        return result

    @staticmethod
    def _next_row(result: lb.QueryResult, columns: list[str] | None = None) -> tuple:
        """Normalize LadybugDB's list/dict row representations to a tuple."""
        row = result.get_next()
        if isinstance(row, dict):
            names = columns or result.get_column_names()
            return tuple(row.get(name) for name in names)
        return tuple(row)

    def execute(self, query: str) -> tuple[list[str], list[tuple]]:
        """Execute a Cypher query and return (columns, rows).

        For mutations without result sets, returns ([], []).
        """
        conn = self._require_conn()
        raw = conn.execute(query)
        result = self._extract_result(raw)
        if result is None:
            return [], []

        # Try to extract column names — DDL results may lack column metadata
        try:
            columns = result.get_column_names()
        except (AttributeError, RuntimeError):
            return [], []

        rows: list[tuple] = []
        count = 0
        while result.has_next() and count < self._max_rows:
            rows.append(self._next_row(result, columns))
            count += 1

        return columns, rows

    def execute_arrow(self, query: str) -> pa.Table | None:
        """Execute a Cypher query and return results as an Arrow Table.

        Returns None for DDL/DML that produces no result set.
        Uses LadybugDB's native get_as_arrow(), sliced to max_rows to prevent OOM.
        """
        conn = self._require_conn()
        raw = conn.execute(query)
        result = self._extract_result(raw)
        if result is None:
            return None

        try:
            if not result.get_column_names():
                return None
            table = result.get_as_arrow()
        except (AttributeError, RuntimeError, ZeroDivisionError):
            return None
        if table.num_rows > self._max_rows:
            table = table.slice(0, self._max_rows)
        return table

    def execute_windowed(
        self,
        query: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[pa.Table | None, bool]:
        """Execute a Cypher query and return only the requested result window.

        LadybugDB does not expose a streaming Arrow reader, so this uses the
        row iterator (`has_next` / `get_next`) to skip the requested offset,
        collect only the requested rows, and detect `has_more` with one
        additional row read.
        """
        conn = self._require_conn()
        raw = conn.execute(query)
        result = self._extract_result(raw)
        if result is None:
            return None, False

        try:
            columns = result.get_column_names()
        except (AttributeError, RuntimeError):
            return None, False

        remaining_offset = max(0, offset)
        remaining_limit = max(0, limit or self._max_rows)

        while remaining_offset > 0 and result.has_next():
            result.get_next()
            remaining_offset -= 1

        if remaining_limit == 0:
            return tuples_to_arrow(columns, []), result.has_next()

        rows: list[tuple] = []
        while result.has_next() and len(rows) < remaining_limit:
            rows.append(self._next_row(result, columns))

        has_more = result.has_next()
        return tuples_to_arrow(columns, rows), has_more

    # Pagination: LadybugDB uses inherited BaseEngine.execute_paged() and
    # BaseEngine.fetch_next_page() which materialize via Polars iter_slices.
    # No streaming Arrow reader available, so the base implementation is optimal.

    def import_csv(
        self,
        table_name: str,
        csv_data: str,
        table_type: str = "node",
        schema: str | None = None,
        from_table: str | None = None,
        to_table: str | None = None,
    ) -> int:
        """Import CSV data into a graph table.

        Args:
            table_name: Table name for the node or relationship.
            csv_data: CSV content as a string (with header row).
            table_type: "node" or "relationship".
            schema: Column definitions, e.g. "id INT64 PRIMARY KEY, name STRING".
            from_table: Source node table (required for relationships).
            to_table: Target node table (required for relationships).

        Returns:
            Number of rows imported.
        """
        self._validate_identifier(table_name, "table_name")
        conn = self._require_conn()
        tmp_path = self._write_temp_file(csv_data, ".csv")
        escaped_path = tmp_path.replace("\\", "/")

        try:
            if schema:
                if table_type == "node":
                    conn.execute(f"CREATE NODE TABLE {table_name} ({schema});")
                elif table_type == "relationship":
                    if not from_table or not to_table:
                        raise ValueError(
                            "from_table and to_table required for relationship imports"
                        )
                    self._validate_identifier(from_table, "from_table")
                    self._validate_identifier(to_table, "to_table")
                    conn.execute(
                        f"CREATE REL TABLE {table_name} "
                        f"(FROM {from_table} TO {to_table}, {schema});"
                    )

            conn.execute(f"COPY {table_name} FROM '{escaped_path}';")

            # Count rows
            result = conn.execute(
                f"MATCH (n:{table_name}) RETURN count(n);"
                if table_type == "node"
                else f"MATCH ()-[r:{table_name}]->() RETURN count(r);"
            )
            if isinstance(result, list):
                result = result[-1] if result else None
            if result and result.has_next():
                return self._next_row(result)[0]
            return 0
        finally:
            self._safe_unlink(tmp_path)

    def get_schema(self) -> tuple[list[str], list[tuple]]:
        """Get the database schema. Returns (columns, rows) from show_tables."""
        conn = self._require_conn()
        result = conn.execute("CALL show_tables() RETURN *;")
        if isinstance(result, list):
            result = result[-1] if result else None
        if result is None:
            return [], []

        try:
            columns = result.get_column_names()
        except Exception:
            return [], []

        rows: list[tuple] = []
        while result.has_next():
            rows.append(self._next_row(result, columns))

        return columns, rows

    def get_statistics(self) -> dict:
        """Get graph statistics: node/edge counts per table type."""
        conn = self._require_conn()
        schema_cols, schema_rows = self.get_schema()
        if not schema_rows:
            return {"node_tables": {}, "rel_tables": {}, "total_nodes": 0, "total_edges": 0}

        # Ladybug's show_tables() currently returns:
        #   (id, name, type, database name, comment)
        # but older/alternate builds may omit the leading id column. Resolve
        # by column name first so counting logic does not accidentally treat
        # the numeric id as a table label.
        col_lookup = {str(name).strip().lower(): idx for idx, name in enumerate(schema_cols)}
        name_idx = col_lookup.get("name", 0)
        type_idx = col_lookup.get("type", 1 if len(schema_cols) > 1 else 0)

        node_tables: dict[str, int] = {}
        rel_tables: dict[str, int] = {}

        for row in schema_rows:
            table_name = str(row[name_idx]) if len(row) > name_idx else ""
            table_type = str(row[type_idx]) if len(row) > type_idx else ""

            if not table_name:
                continue

            try:
                if "NODE" in table_type.upper() or "node" in table_type.lower():
                    count_result = conn.execute(
                        f"MATCH (n:{table_name}) RETURN count(n);"
                    )
                    if isinstance(count_result, list):
                        count_result = count_result[-1] if count_result else None
                    if count_result and count_result.has_next():
                        node_tables[table_name] = self._next_row(count_result)[0]
                elif "REL" in table_type.upper() or "rel" in table_type.lower():
                    count_result = conn.execute(
                        f"MATCH ()-[r:{table_name}]->() RETURN count(r);"
                    )
                    if isinstance(count_result, list):
                        count_result = count_result[-1] if count_result else None
                    if count_result and count_result.has_next():
                        rel_tables[table_name] = self._next_row(count_result)[0]
            except Exception:
                logger.warning("Could not count table %s", table_name, exc_info=True)

        return {
            "node_tables": node_tables,
            "rel_tables": rel_tables,
            "total_nodes": sum(node_tables.values()),
            "total_edges": sum(rel_tables.values()),
        }

    def close(self) -> None:
        """Close the database connection and all cursors."""
        self.close_all_cursors()
        self._conn = None
        self._db = None
        logger.info("Closed LadybugDB connection: %s", self._db_path)
