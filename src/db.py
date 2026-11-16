"""Database layer — Turso (libsql) with local SQLite fallback."""

from __future__ import annotations

import os
import pathlib
import logging
from src.config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN

log = logging.getLogger(__name__)

_conn = None
_SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "schema.sql"


def get_connection():
    """Return (and cache) a connection to Turso cloud or local database."""
    global _conn
    if _conn is not None:
        return _conn

    is_remote_turso = TURSO_DATABASE_URL.startswith("libsql://") or TURSO_DATABASE_URL.startswith("https://")

    if is_remote_turso:
        try:
            import libsql_experimental as libsql
            # Connect with local replica caching and Turso remote sync
            _conn = libsql.connect(
                database="local_replica.db",
                sync_url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN,
            )
            try:
                _conn.sync()
            except Exception as se:
                log.warning("Turso sync warning: %s", se)
            return _conn
        except Exception as e:
            log.warning("Failed connecting via libsql sync, trying direct connect: %s", e)
            try:
                import libsql_experimental as libsql
                _conn = libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
                return _conn
            except Exception as e2:
                log.error("Failed connecting to Turso: %s. Falling back to local SQLite.", e2)

    # Local SQLite fallback for testing or development
    import sqlite3
    db_path = TURSO_DATABASE_URL if not is_remote_turso and TURSO_DATABASE_URL else "local.db"
    _conn = sqlite3.connect(db_path)
    _conn.execute("PRAGMA foreign_keys = ON;")
    return _conn


def init_db():
    """Create tables from schema.sql if they don't exist."""
    conn = get_connection()
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    for statement in schema_sql.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)
    conn.commit()
    if hasattr(conn, "sync"):
        try:
            conn.sync()
        except Exception as e:
            log.warning("DB sync on init_db: %s", e)


def _to_tuple(params):
    """Ensure parameters are converted to a tuple for libsql compatibility."""
    if params is None:
        return None
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return (params,)


def execute(sql: str, params=None):
    """Execute a write query and commit."""
    conn = get_connection()
    p = _to_tuple(params)
    if p is not None:
        conn.execute(sql, p)
    else:
        conn.execute(sql)
    conn.commit()
    if hasattr(conn, "sync"):
        try:
            conn.sync()
        except Exception as e:
            log.warning("DB sync on execute: %s", e)


def fetchone(sql: str, params=None) -> dict | None:
    """Fetch a single row as a dict, or None."""
    conn = get_connection()
    p = _to_tuple(params)
    if p is not None:
        cur = conn.execute(sql, p)
    else:
        cur = conn.execute(sql)
    columns = [d[0] for d in cur.description] if cur.description else []
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


def fetchall(sql: str, params=None) -> list[dict]:
    """Fetch all rows as a list of dicts."""
    conn = get_connection()
    p = _to_tuple(params)
    if p is not None:
        cur = conn.execute(sql, p)
    else:
        cur = conn.execute(sql)
    columns = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(columns, row)) for row in cur.fetchall()]



def get_bot_state(key: str) -> str | None:
    """Get a value from the bot_state key-value store."""
    row = fetchone("SELECT value FROM bot_state WHERE key = ?", (key,))
    return row["value"] if row else None


def set_bot_state(key: str, value: str):
    """Upsert a value in the bot_state key-value store."""
    execute(
        "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value),
    )

