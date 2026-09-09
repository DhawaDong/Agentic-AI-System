"""
Memory / Knowledge Base layer. SQLite keeps this deployable on Render's
free tier with zero extra infra; swap for Postgres later by changing this
module only (keep the same function signatures).
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from core import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    objectives TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS breakthroughs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    domain_key TEXT,
    title TEXT,
    summary TEXT,
    rank_score REAL,
    novelty REAL,
    significance REAL,
    evidence_strength REAL,
    impact REAL,
    reproducibility REAL,
    long_term_importance REAL,
    dedup_hash TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    title TEXT,
    content_markdown TEXT,
    quality_score REAL,
    pdf_path TEXT,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS seen_sources (
    url TEXT PRIMARY KEY,
    title TEXT,
    first_seen_run_id INTEGER,
    first_seen_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---- runs -------------------------------------------------------------------
def create_run(objectives: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, objectives) VALUES (?, 'running', ?)",
            (_now(), json.dumps(objectives)),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str = "completed", error: str = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?",
            (_now(), status, error, run_id),
        )


def get_run(run_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None


def list_runs(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---- breakthroughs ------------------------------------------------------------
def save_breakthrough(run_id: int, b: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO breakthroughs
               (run_id, domain_key, title, summary, rank_score, novelty, significance,
                evidence_strength, impact, reproducibility, long_term_importance, dedup_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, b.get("domain_key"), b.get("title"), b.get("summary"),
             b.get("rank_score"), b.get("novelty"), b.get("significance"),
             b.get("evidence_strength"), b.get("impact"), b.get("reproducibility"),
             b.get("long_term_importance"), b.get("dedup_hash")),
        )
        return cur.lastrowid


def is_duplicate_of_known(dedup_hash: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM breakthroughs WHERE dedup_hash=? LIMIT 1", (dedup_hash,)
        ).fetchone()
        return row is not None


# ---- sources (for cross-run novelty tracking) --------------------------------
def mark_source_seen(url: str, title: str, run_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_sources (url, title, first_seen_run_id, first_seen_at) "
            "VALUES (?,?,?,?)",
            (url, title, run_id, _now()),
        )


def was_source_seen_before(url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM seen_sources WHERE url=?", (url,)).fetchone()
        return row is not None


# ---- reports ------------------------------------------------------------------
def save_report(run_id: int, title: str, content_markdown: str,
                 quality_score: float, pdf_path: str = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reports (run_id, title, content_markdown, quality_score,
               pdf_path, created_at) VALUES (?,?,?,?,?,?)""",
            (run_id, title, content_markdown, quality_score, pdf_path, _now()),
        )
        return cur.lastrowid


def get_report(report_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None


def latest_report_for_run(run_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def list_reports(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
