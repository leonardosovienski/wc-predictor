"""predictor-core.infra — helpers SQLite: WAL, busy_timeout, migração idempotente."""
import sqlite3
import pathlib
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


def connect(db_path: pathlib.Path | str, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    """Abre conexão SQLite com WAL e busy_timeout configurados."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run_migrations(conn: sqlite3.Connection, migrations: list[tuple[str, str]]) -> None:
    """Aplica lista de (nome, sql) de forma idempotente via tabela _migrations."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    applied = {row["name"] for row in conn.execute("SELECT name FROM _migrations")}
    for name, sql in migrations:
        if name in applied:
            continue
        logger.info("applying migration: %s", name)
        conn.executescript(sql)
        conn.execute("INSERT INTO _migrations(name) VALUES(?)", (name,))
        conn.commit()


def config_hash(params: dict) -> str:
    """Hash determinístico de um dict de parâmetros para detectar staleness."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
