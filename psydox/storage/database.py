"""
Psydox Persistent Storage — SQLite

Uses SQLite for single-server deployments (Railway, Heroku, etc.).
The database file is stored at PSYDOX_DB_PATH (default: ./psydox.db).

Migrations are applied automatically at startup via _MIGRATIONS list.
Each migration is a tuple (version, sql) applied in order.
Never mutate existing migration SQL — always add a new migration.

Schema covers:
  product_profiles    — ProductMemory persistence
  projects            — Project metadata
  jobs                — Persistent job records
  job_items           — Individual items within a batch job
  outputs             — Generated image metadata (not the bytes themselves)
  quality_results     — QA scores linked to outputs
  reviews             — Human review decisions
  ai_usage            — Cost and usage tracking
  audit_logs          — Security and action audit trail
  brand_profiles      — Brand configuration
  dashboard_prefs     — Per-user dashboard customization
  workflow_runs       — Workflow execution history
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_log = logging.getLogger("psydox.storage.database")

_DB_PATH  = os.environ.get("PSYDOX_DB_PATH", str(Path.cwd() / "psydox.db"))
_lock     = threading.Lock()
_conn_tls = threading.local()  # per-thread connection

# ── Migration registry ────────────────────────────────────────────────────────
# Each entry: (version_int, description, sql)
_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema", """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS product_profiles (
            product_id  TEXT PRIMARY KEY,
            data        TEXT NOT NULL,
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            owner_email TEXT NOT NULL,
            name        TEXT NOT NULL,
            status      TEXT DEFAULT 'active',
            data        TEXT NOT NULL DEFAULT '{}',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id            TEXT PRIMARY KEY,
            feature_id    TEXT NOT NULL,
            label         TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'queued',
            user_email    TEXT NOT NULL DEFAULT '',
            project_id    TEXT,
            progress      INTEGER DEFAULT 0,
            data          TEXT NOT NULL DEFAULT '{}',
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            completed_at  REAL
        );

        CREATE TABLE IF NOT EXISTS outputs (
            id          TEXT PRIMARY KEY,
            job_id      TEXT NOT NULL,
            feature_id  TEXT NOT NULL,
            label       TEXT NOT NULL,
            mime        TEXT NOT NULL DEFAULT 'image/jpeg',
            file_path   TEXT,
            quality_score INTEGER,
            quality_verdict TEXT,
            fidelity_score  REAL,
            status      TEXT DEFAULT 'pending',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quality_results (
            id          TEXT PRIMARY KEY,
            output_id   TEXT NOT NULL,
            job_id      TEXT NOT NULL,
            score       INTEGER NOT NULL,
            verdict     TEXT NOT NULL,
            data        TEXT NOT NULL DEFAULT '{}',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id          TEXT PRIMARY KEY,
            output_id   TEXT NOT NULL,
            job_id      TEXT NOT NULL,
            decision    TEXT NOT NULL,
            reviewer    TEXT NOT NULL DEFAULT '',
            notes       TEXT DEFAULT '',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_usage (
            id          TEXT PRIMARY KEY,
            job_id      TEXT,
            feature_id  TEXT NOT NULL,
            model       TEXT,
            provider    TEXT,
            cost_usd    REAL DEFAULT 0.0,
            tokens_in   INTEGER DEFAULT 0,
            tokens_out  INTEGER DEFAULT 0,
            latency_ms  INTEGER DEFAULT 0,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email  TEXT NOT NULL DEFAULT '',
            action      TEXT NOT NULL,
            resource    TEXT DEFAULT '',
            detail      TEXT DEFAULT '',
            ip_address  TEXT DEFAULT '',
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brand_profiles (
            id          TEXT PRIMARY KEY,
            owner_email TEXT NOT NULL,
            name        TEXT NOT NULL,
            data        TEXT NOT NULL DEFAULT '{}',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_prefs (
            user_email  TEXT PRIMARY KEY,
            prefs       TEXT NOT NULL DEFAULT '{}',
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workflow_runs (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'running',
            job_ids     TEXT DEFAULT '[]',
            user_email  TEXT DEFAULT '',
            data        TEXT NOT NULL DEFAULT '{}',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_user     ON jobs(user_email);
        CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_outputs_job   ON outputs(job_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_out   ON reviews(output_id);
        CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_logs(user_email);
        CREATE INDEX IF NOT EXISTS idx_audit_time    ON audit_logs(created_at);
    """),
]


# ── Connection management ─────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating it if needed."""
    if not hasattr(_conn_tls, "conn") or _conn_tls.conn is None:
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _conn_tls.conn = conn
    return _conn_tls.conn


def init_db() -> None:
    """Apply all pending migrations. Call once at startup."""
    with _lock:
        conn = _get_conn()
        # Get current version
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
        except sqlite3.OperationalError:
            current = 0

        for version, description, sql in _MIGRATIONS:
            if version > current:
                _log.info("Applying DB migration v%d: %s", version, description)
                conn.executescript(sql)
                conn.execute("INSERT OR IGNORE INTO schema_version VALUES (?)", (version,))
                conn.commit()
                current = version

    _log.info("Database ready at %s (schema v%d)", _DB_PATH, current)


def get_db() -> sqlite3.Connection:
    """Get the database connection, initializing if needed."""
    init_db()
    return _get_conn()


# ── Convenience helpers ───────────────────────────────────────────────────────

def db_execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    return get_db().execute(sql, params)


def db_commit() -> None:
    get_db().commit()
