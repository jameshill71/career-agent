from __future__ import annotations

import sqlite3
from pathlib import Path

# 1) DATABASE LOCATION
# We keep DB-path logic out of db.py in v1. Your config.py will define DEFAULT_DB.
# db.py should only accept a Path passed in by the caller.

# 2) SQLITE SCHEMA
# This schema is idempotent: you can run it repeatedly and it won't destroy data.
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Track scan runs (helpful for debugging and basic analytics)
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  source TEXT NOT NULL,
  query_json TEXT,
  stats_json TEXT
);

-- Core job storage (normalized fields plus a dedupe fingerprint)
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL,
  posted_date TEXT,
  description TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);

-- Scoring history: allow multiple scores per job as you tune and re-score
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL,
  model TEXT NOT NULL,
  score INTEGER NOT NULL CHECK(score >= 0 AND score <= 100),
  reasons_json TEXT NOT NULL,
  matched_json TEXT NOT NULL,
  missing_json TEXT NOT NULL,
  resume_emphasis_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scores_job_id ON scores(job_id);
"""

def connect(db_path: Path) -> sqlite3.Connection:
    """
    Open a SQLite connection (creating parent directories if needed).

    Why: CLI tools should be able to run from anywhere and still find/store state.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    # We'll still set foreign_keys here for safety (even though SCHEMA does too).
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    Initialize the database schema if it doesn't already exist.

    Why: avoids a separate "migration system" for v1.
    """
    conn.executescript(SCHEMA)
    conn.commit()