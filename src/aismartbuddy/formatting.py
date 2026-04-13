"""Token-optimized output formatting for query results.

CSV format is 2-3x more token-efficient than JSON for tabular data.
Arrow/Polars path is 10-100x faster than csv.writer for large datasets.
"""

from __future__ import annotations

import csv
import io

import polars as pl
import pyarrow as pa
from tabulate import tabulate

# ── Arrow/Polars-based formatters (preferred path) ──────────────


def format_arrow_as_csv(
    table: pa.Table,
    max_rows: int = 1000,
    max_chars: int = 50000,
) -> str:
    """Format an Arrow Table as CSV using Polars (fast path).

    Returns a string with a metadata comment, header row, and data rows.
    Truncates at max_rows and max_chars.
    """
    total_rows = table.num_rows
    num_cols = table.num_columns
    df = pl.from_arrow(table)

    if total_rows > max_rows:
        df = df.head(max_rows)

    csv_str = df.write_csv()

    # Character truncation
    truncated_by_chars = False
    if len(csv_str) > max_chars:
        csv_str = csv_str[:max_chars]
        last_newline = csv_str.rfind("\n")
        if last_newline > 0:
            csv_str = csv_str[: last_newline + 1]
        truncated_by_chars = True

    # Metadata header
    meta = f"# {total_rows} rows x {num_cols} columns"
    if total_rows > max_rows:
        meta += f" (showing first {max_rows})"
    elif truncated_by_chars:
        meta += " (truncated by size)"

    return meta + "\n" + csv_str


def format_arrow_as_table(
    table: pa.Table,
    max_rows: int = 1000,
    max_chars: int = 50000,
) -> str:
    """Format an Arrow Table as a compact ASCII table."""
    total_rows = table.num_rows
    num_cols = table.num_columns
    df = pl.from_arrow(table)

    if total_rows > max_rows:
        df = df.head(max_rows)

    # Convert to rows for tabulate
    columns = df.columns
    rows = df.rows()
    result = tabulate(rows, headers=columns, tablefmt="simple")

    # Character truncation
    truncated_by_chars = False
    if len(result) > max_chars:
        result = result[:max_chars]
        last_newline = result.rfind("\n")
        if last_newline > 0:
            result = result[: last_newline + 1]
        truncated_by_chars = True

    meta = f"# {total_rows} rows x {num_cols} columns"
    if total_rows > max_rows:
        meta += f" (showing first {max_rows})"
    elif truncated_by_chars:
        meta += " (truncated by size)"

    return meta + "\n" + result


def format_arrow_result(
    table: pa.Table | None,
    max_rows: int = 1000,
    max_chars: int = 50000,
    output_format: str = "csv",
    pagination_meta: str | None = None,
) -> str:
    """Format an Arrow Table result in the specified format.

    Args:
        table: Arrow Table, or None for DDL/DML with no result set.
        max_rows: Maximum rows to include.
        max_chars: Maximum characters in output.
        output_format: "csv" or "table".
        pagination_meta: Optional pagination footer (cursor info).
    """
    # DDL/DML — no result set
    if table is None:
        return "OK"

    # Empty result set
    if table.num_rows == 0:
        col_list = ", ".join(table.column_names)
        return f"No results\nColumns: {col_list}"

    if output_format == "table":
        result = format_arrow_as_table(table, max_rows, max_chars)
    else:
        result = format_arrow_as_csv(table, max_rows, max_chars)

    if pagination_meta:
        result += "\n" + pagination_meta

    return result


# ── Legacy tuple-based formatters (fallback path) ───────────────


def format_as_csv(
    columns: list[str],
    rows: list[tuple],
    max_rows: int = 1000,
    max_chars: int = 50000,
) -> str:
    """Format query results as CSV — the most token-efficient tabular format.

    Returns a string with a metadata comment, header row, and data rows.
    Truncates at max_rows and max_chars.
    """
    total_rows = len(rows)
    display_rows = rows[:max_rows]

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Header
    writer.writerow(columns)

    # Data rows
    for row in display_rows:
        writer.writerow(_normalize_row(row))

    result = output.getvalue()

    # Character truncation
    truncated_by_chars = False
    if len(result) > max_chars:
        result = result[:max_chars]
        # Trim to last complete line
        last_newline = result.rfind("\n")
        if last_newline > 0:
            result = result[: last_newline + 1]
        truncated_by_chars = True

    # Metadata header
    meta = f"# {total_rows} rows x {len(columns)} columns"
    if total_rows > max_rows:
        meta += f" (showing first {max_rows})"
    elif truncated_by_chars:
        meta += " (truncated by size)"

    return meta + "\n" + result


def format_as_table(
    columns: list[str],
    rows: list[tuple],
    max_rows: int = 1000,
    max_chars: int = 50000,
) -> str:
    """Format query results as a compact ASCII table using tabulate."""
    total_rows = len(rows)
    display_rows = rows[:max_rows]
    normalized = [_normalize_row(row) for row in display_rows]

    result = tabulate(normalized, headers=columns, tablefmt="simple")

    # Character truncation
    truncated_by_chars = False
    if len(result) > max_chars:
        result = result[:max_chars]
        last_newline = result.rfind("\n")
        if last_newline > 0:
            result = result[: last_newline + 1]
        truncated_by_chars = True

    meta = f"# {total_rows} rows x {len(columns)} columns"
    if total_rows > max_rows:
        meta += f" (showing first {max_rows})"
    elif truncated_by_chars:
        meta += " (truncated by size)"

    return meta + "\n" + result


def format_result(
    columns: list[str],
    rows: list[tuple],
    max_rows: int = 1000,
    max_chars: int = 50000,
    output_format: str = "csv",
) -> str:
    """Format query results in the specified format (legacy tuple path).

    Args:
        columns: Column names.
        rows: Result rows.
        max_rows: Maximum rows to include.
        max_chars: Maximum characters in output.
        output_format: "csv" or "table".
    """
    # No result set (DDL/DML)
    if not columns:
        if rows:
            return f"OK, {len(rows)} rows affected"
        return "OK"

    # Empty result set
    if not rows:
        col_list = ", ".join(columns)
        return f"No results\nColumns: {col_list}"

    if output_format == "table":
        return format_as_table(columns, rows, max_rows, max_chars)
    return format_as_csv(columns, rows, max_rows, max_chars)


def format_schema_compact(tables: list[dict]) -> str:
    """Format table schema info compactly, one line per table.

    Each dict should have 'name' and 'columns' (list of (name, type) tuples).
    """
    if not tables:
        return "No tables in database"

    lines = []
    for table in tables:
        cols = ", ".join(f"{c[0]} {c[1]}" for c in table["columns"])
        lines.append(f"{table['name']} ({cols})")
    return "\n".join(lines)


def _normalize_row(row: tuple) -> list:
    """Convert row values to clean string representations."""
    result = []
    for val in row:
        if val is None:
            result.append("")
        elif isinstance(val, (list, dict)):
            result.append(str(val))
        else:
            result.append(val)
    return result
