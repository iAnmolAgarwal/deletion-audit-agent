"""Load untrusted SQL text into an in-memory sqlite3 database, under limits.

* An authorizer denies ATTACH and DETACH (which also blocks ``VACUUM INTO``), virtual
  tables, every PRAGMA other than ``foreign_keys``, and the file / extension functions.
  Extension loading is also switched off on the connection.
* A step cap counts SQLite virtual-machine instructions through
  ``set_progress_handler``; when it is exceeded the running statement is interrupted.
* A row cap bounds the total number of rows the loaded tables may hold.

Any breach raises :class:`SqlSafetyError`, which the caller records as status ``ERROR``.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_MAX_STEPS = 50_000_000      # VM instructions for loading and reading one file
DEFAULT_MAX_ROWS = 200_000          # rows across all tables of one file
PROGRESS_EVERY = 1_000              # VM instructions between progress-handler calls

_DENIED_ACTIONS = {
    sqlite3.SQLITE_ATTACH: "ATTACH",
    sqlite3.SQLITE_DETACH: "DETACH",
    sqlite3.SQLITE_CREATE_VTABLE: "CREATE VIRTUAL TABLE",
}
_ALLOWED_PRAGMAS = frozenset({"foreign_keys"})
_DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"})


class SqlSafetyError(Exception):
    """The SQL text breached the sandbox: a denied statement, the step cap or the row cap."""


@dataclass(frozen=True)
class SqlTable:
    """One loaded table: its name, column names and rows as ``(rowid, values)``."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[int, tuple[object, ...]], ...]


def _make_authorizer(denials: list[str]) -> Callable[..., int]:
    """Build an authorizer that records why it denied an action."""

    def authorizer(action: int, arg1: str | None, arg2: str | None, _db: str | None,
                   _src: str | None) -> int:
        if action in _DENIED_ACTIONS:
            denials.append(_DENIED_ACTIONS[action])
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA and (arg1 or "").lower() not in _ALLOWED_PRAGMAS:
            denials.append("PRAGMA")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _DENIED_FUNCTIONS:
            denials.append("function " + (arg2 or "").lower())
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorizer


def _make_progress(max_steps: int, state: dict[str, int]) -> Callable[[], int]:
    """Build a progress handler that interrupts once ``max_steps`` is passed."""

    def progress() -> int:
        state["steps"] += PROGRESS_EVERY
        return 1 if state["steps"] > max_steps else 0

    return progress


def load_tables(
    sql_text: str,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> tuple[SqlTable, ...]:
    """Execute ``sql_text`` in a fresh in-memory database and return every table.

    Tables come in creation order and rows in rowid order. Raises
    :class:`SqlSafetyError` on a sandbox breach and ``sqlite3.Error`` on invalid SQL.
    """
    denials: list[str] = []
    state = {"steps": 0}
    con = sqlite3.connect(":memory:")
    try:
        if hasattr(con, "enable_load_extension"):
            con.enable_load_extension(False)
        con.set_authorizer(_make_authorizer(denials))
        con.set_progress_handler(_make_progress(max_steps, state), PROGRESS_EVERY)
        _run(con, sql_text, denials, state, max_steps)
        return _read_all(con, denials, state, max_steps, max_rows)
    finally:
        con.close()


def _run(con: sqlite3.Connection, sql_text: str, denials: list[str], state: dict[str, int],
         max_steps: int) -> None:
    """Execute the script, turning sandbox interruptions into SqlSafetyError."""
    try:
        con.executescript(sql_text)
    except sqlite3.Error:
        _raise_if_breach(denials, state, max_steps)
        raise


def _raise_if_breach(denials: list[str], state: dict[str, int], max_steps: int) -> None:
    """Raise SqlSafetyError when a recorded denial or the step cap explains a failure."""
    if denials:
        raise SqlSafetyError("statement denied by authorizer: " + denials[0])
    if state["steps"] > max_steps:
        raise SqlSafetyError(f"step cap exceeded ({max_steps} VM steps)")


def _read_all(con: sqlite3.Connection, denials: list[str], state: dict[str, int],
              max_steps: int, max_rows: int) -> tuple[SqlTable, ...]:
    """Read every table under the row cap."""
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY rowid")]
        total = 0
        for name in names:
            total += con.execute(f'SELECT count(*) FROM "{_quote(name)}"').fetchone()[0]
        if total > max_rows:
            raise SqlSafetyError(f"row cap exceeded ({total} rows > {max_rows})")
        return tuple(_read_table(con, name) for name in names)
    except sqlite3.Error:
        _raise_if_breach(denials, state, max_steps)
        raise


def _read_table(con: sqlite3.Connection, name: str) -> SqlTable:
    """Read one table with its rowids."""
    cursor = con.execute(f'SELECT rowid, * FROM "{_quote(name)}" ORDER BY rowid')
    columns = tuple(d[0] for d in cursor.description[1:])
    rows = tuple((int(r[0]), tuple(r[1:])) for r in cursor.fetchall())
    return SqlTable(name=name, columns=columns, rows=rows)


def _quote(name: str) -> str:
    """Escape a table name for use inside double quotes."""
    return name.replace('"', '""')


def raw_value(value: object) -> str:
    """A SQLite value as a raw string: NULL -> ``"null"``, numbers via ``str``."""
    if value is None:
        return "null"
    if isinstance(value, bytes):
        raise SqlSafetyError("BLOB values are not supported")
    return str(value)
