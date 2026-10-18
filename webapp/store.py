"""Connections for local SQLite and hosted PostgreSQL persistence.

The clinical repository uses a deliberately small SQL subset: unquoted ``?``
parameter markers and single-row inserts into known tables. This adapter keeps
that existing API (including ``lastrowid`` and indexed/named rows) on PostgreSQL;
it is not a general SQLite-to-PostgreSQL SQL translator.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "outputs" / "review.db"

# Join tables have composite keys and intentionally do not request RETURNING id.
_IDENTITY_TABLES = frozenset({
    "organisations", "users", "invitations", "medication_documents",
    "document_versions", "regimens", "assignments", "usage_reports",
    "ai_assessments", "assessment_reviews", "document_suggestions",
    "clarification_requests", "audit_events",
})
_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+([a-z_][a-z_0-9]*)\b", re.IGNORECASE)


class _PostgresRow(dict):
    """Match the named/indexed access used from sqlite3.Row, including duplicates."""

    def __init__(self, names, values):
        super().__init__()
        self._values = tuple(values)
        for name, value in zip(names, self._values):
            # sqlite3.Row resolves duplicate column names to the first value.
            self.setdefault(name, value)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return super().__getitem__(key)


def _postgres_row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: _PostgresRow(names, values)


class _PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


class Connection:
    """Commit or roll back on context exit and always release the connection."""

    def __init__(self, raw, dialect):
        self._raw = raw
        self.dialect = dialect
        self.closed = False

    def execute(self, sql, parameters=()):
        if self.dialect == "sqlite":
            return self._raw.execute(sql, parameters)

        # Repository SQL contains ? only as a parameter marker. Values, including
        # user text containing ? or %, remain bound parameters throughout.
        translated = sql.replace("?", "%s")
        inserted_table = _INSERT_TABLE.match(sql)
        wants_id = (
            inserted_table is not None
            and inserted_table.group(1).lower() in _IDENTITY_TABLES
            and "RETURNING" not in sql.upper()
        )
        if wants_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._raw.execute(translated, parameters or None)
        lastrowid = cursor.fetchone()[0] if wants_id else None
        return _PostgresCursor(cursor, lastrowid)

    def executescript(self, script):
        # Only the static schema calls this; it contains no semicolons inside
        # strings or functions. Unlike sqlite3.executescript, preserve the active
        # transaction so schema creation and seeding stay under the same lock.
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def _connect() -> Connection:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        import psycopg

        raw = psycopg.connect(
            database_url,
            row_factory=_postgres_row_factory,
            prepare_threshold=None,  # Compatible with transaction-pooling URLs.
            connect_timeout=10,
        )
        return Connection(raw, "postgres")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(DB_PATH, timeout=30)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return Connection(raw, "sqlite")
