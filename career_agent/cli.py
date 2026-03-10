from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .sources.rss import load_jobs_from_rss

import typer

from .config import load_config, resolve_db_path
from .db import connect, init_db
from .scoring.engine import score_heuristic
from .sources.local_json import load_jobs

app = typer.Typer(add_completion=False)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@app.command("config")
def show_config():
    """Print the currently loaded configuration."""
    config = load_config()
    typer.echo(json.dumps(config, indent=2))


@app.command()
def init(db: Path | None = None):
    """Initialize the local database."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)
    typer.echo(f"Initialized DB at {db_path}")


@app.command()
def scan(db: Path | None = None):
    """
    Scan configured sources and store new jobs.
    Source definitions come from config.json.
    """
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    sources = config.get("sources", [])
    if not sources:
        typer.echo("No sources configured.")
        raise typer.Exit(code=1)

    total_seen = 0
    total_inserted = 0

    for source_cfg in sources:
        source_type = source_cfg.get("type")
        source_label = source_cfg.get("name") or source_cfg.get("url") or source_type or "unknown"
        started = now_iso()

        cur = conn.cursor()
        cur.execute(
            "INSERT INTO runs (started_at, source, query_json, stats_json) VALUES (?, ?, ?, ?)",
            (started, source_label or "unknown", json.dumps(source_cfg), "{}"),
        )
        run_id = cur.lastrowid

        seen = 0
        inserted = 0

        try:
            if source_type == "local_json":
                path = Path(source_cfg["path"])
                jobs = load_jobs(path)

            elif source_type == "rss":
                url = source_cfg["url"]
                jobs = load_jobs_from_rss(url)

            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            for job in jobs:
                seen += 1
                total_seen += 1
                fp = job.fingerprint()

                try:
                    conn.execute(
                        """INSERT INTO jobs
                           (source, url, company, title, location, posted_date, description, fingerprint, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            job.source,
                            job.url,
                            job.company,
                            job.title,
                            job.location,
                            job.posted_date,
                            job.description,
                            fp,
                            now_iso(),
                        ),
                    )
                    inserted += 1
                    total_inserted += 1
                except sqlite3.IntegrityError:
                    pass

            ended = now_iso()
            stats = {"seen": seen, "inserted": inserted}
            conn.execute(
                "UPDATE runs SET ended_at=?, stats_json=? WHERE id=?",
                (ended, json.dumps(stats), run_id),
            )
            conn.commit()

            typer.echo(f"{source_label}: Seen {seen}, New {inserted}")

        except Exception as e:
            ended = now_iso()
            stats = {"seen": seen, "inserted": inserted, "error": str(e)}
            conn.execute(
                "UPDATE runs SET ended_at=?, stats_json=? WHERE id=?",
                (ended, json.dumps(stats), run_id),
            )
            conn.commit()
            typer.echo(f"{source_type}: ERROR - {e}")


@app.command("list")
def list_jobs(
    top: int = 10,
    scored: bool = False,
    remote_only: bool = False,
    db: Path | None = None,
):
    """List jobs. Use --scored to include latest score if available."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    remote_filter = """
        AND (
            LOWER(j.location) LIKE '%remote%'
            OR LOWER(j.url) LIKE '%remoteok.com%'
            OR LOWER(j.url) LIKE '%weworkremotely.com%'
        )
    """ if remote_only else ""

    if not scored:
        query = f"""
            SELECT j.id, j.company, j.title, j.location, j.url, j.created_at
            FROM jobs j
            WHERE 1=1
            {remote_filter}
            ORDER BY j.id DESC
            LIMIT ?
        """

        rows = conn.execute(query, (top,)).fetchall()

        if not rows:
            if remote_only:
                typer.echo("No remote jobs found.")
            else:
                typer.echo("No jobs found.")
            return

        for (job_id, company, title, location, url, created_at) in rows:
            typer.echo(f"[{job_id}] {company} | {title} | {location}")
            typer.echo(f"     {url}")
            typer.echo(f"     saved: {created_at}")
        return

    query = f"""
        SELECT
          j.id, j.company, j.title, j.location, j.url, j.created_at,
          s.score, s.model, s.created_at
        FROM jobs j
        LEFT JOIN (
          SELECT s1.*
          FROM scores s1
          JOIN (
            SELECT job_id, MAX(id) AS max_id
            FROM scores
            GROUP BY job_id
          ) latest
          ON s1.job_id = latest.job_id AND s1.id = latest.max_id
        ) s
        ON s.job_id = j.id
        WHERE 1=1
        {remote_filter}
        ORDER BY COALESCE(s.score, -1) DESC, j.id DESC
        LIMIT ?
    """

    rows = conn.execute(query, (top,)).fetchall()

    if not rows:
        if remote_only:
            typer.echo("No remote jobs found.")
        else:
            typer.echo("No jobs found.")
        return

    for (job_id, company, title, location, url, created_at, score, model, scored_at) in rows:
        score_str = f"{score:3d}" if score is not None else "  -"
        meta = f"{model} @ {scored_at}" if score is not None else "unscored"
        typer.echo(f"[{job_id}] score={score_str} | {company} | {title} | {location}")
        typer.echo(f"     {url}")
        typer.echo(f"     saved: {created_at} | {meta}")

@app.command()
def top(
    limit: int = 10,
    min_score: int = 0,
    remote_only: bool = False,
    db: Path | None = None,
):
    """Show the top-scoring jobs using each job's latest score."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    query = """
        SELECT
          j.id,
          j.company,
          j.title,
          j.location,
          j.url,
          s.score,
          s.model,
          s.created_at
        FROM jobs j
        JOIN (
          SELECT s1.*
          FROM scores s1
          JOIN (
            SELECT job_id, MAX(id) AS max_id
            FROM scores
            GROUP BY job_id
          ) latest
          ON s1.job_id = latest.job_id AND s1.id = latest.max_id
        ) s
        ON s.job_id = j.id
        WHERE s.score >= ?
    """

    params: list[object] = [min_score]

    if remote_only:
        query += """
        AND (
            LOWER(j.location) LIKE '%remote%'
            OR LOWER(j.url) LIKE '%remoteok.com%'
            OR LOWER(j.url) LIKE '%weworkremotely.com%'
        )
        """

    query += """
        ORDER BY s.score DESC, j.id DESC
        LIMIT ?
    """

    params.append(limit)

    rows = conn.execute(query, tuple(params)).fetchall()

    if not rows:
        if remote_only:
            typer.echo(f"No remote scored jobs found with score >= {min_score}.")
        else:
            typer.echo(f"No scored jobs found with score >= {min_score}.")
        return

    for job_id, company, title, location, url, score, model, scored_at in rows:
        typer.echo(f"[{job_id}] score={score:3d} | {company} | {title} | {location}")
        typer.echo(f"     {url}")
        typer.echo(f"     {model} @ {scored_at}")

@app.command()
def show(job_id: int, db: Path | None = None):
    """Show full details for a job."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    row = conn.execute(
        """SELECT company, title, location, posted_date, url, description
           FROM jobs WHERE id=?""",
        (job_id,),
    ).fetchone()

    if not row:
        raise typer.BadParameter(f"No job with id={job_id}")

    company, title, location, posted_date, url, description = row
    typer.echo(f"{company} | {title}")
    typer.echo(f"Location: {location}")
    typer.echo(f"Posted: {posted_date or 'unknown'}")
    typer.echo(url)
    typer.echo("\n---\n")
    typer.echo(description.strip() or "(no description)")


@app.command()
def explain(job_id: int, db: Path | None = None):
    """Explain the latest score for a job (and show match details)."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    job = conn.execute(
        """SELECT company, title, location, posted_date, url, description
           FROM jobs WHERE id=?""",
        (job_id,),
    ).fetchone()

    if not job:
        raise typer.BadParameter(f"No job with id={job_id}")

    company, title, location, posted_date, url, description = job

    score_row = conn.execute(
        """SELECT score, model, reasons_json, matched_json, missing_json, resume_emphasis_json, created_at
           FROM scores
           WHERE job_id=?
           ORDER BY id DESC
           LIMIT 1""",
        (job_id,),
    ).fetchone()

    typer.echo(f"[{job_id}] {company} | {title}")
    typer.echo(f"Location: {location}")
    typer.echo(f"Posted: {posted_date or 'unknown'}")
    typer.echo(f"URL: {url}")
    typer.echo("\n---\n")

    if not score_row:
        typer.echo("No score found for this job yet.")
        typer.echo(f"Run: career-agent score {job_id}")
        return

    score, model, reasons_json, matched_json, missing_json, resume_json, scored_at = score_row

    reasons = json.loads(reasons_json)
    matched = json.loads(matched_json)
    missing = json.loads(missing_json)
    resume_emphasis = json.loads(resume_json)

    typer.echo(f"Score: {score}/100")
    typer.echo(f"Model: {model}")
    typer.echo(f"Scored at: {scored_at}")

    typer.echo("\nReasons:")
    for r in reasons:
        typer.echo(f"  - {r}")

    typer.echo("\nMatched keywords:")
    typer.echo("  " + (", ".join(matched) if matched else "(none)"))

    typer.echo("\nMissing keywords:")
    typer.echo("  " + (", ".join(missing) if missing else "(none)"))

    typer.echo("\nResume emphasis:")
    for tip in resume_emphasis:
        typer.echo(f"  - {tip}")

    desc = (description or "").strip()
    if desc:
        excerpt = desc[:600] + ("..." if len(desc) > 600 else "")
        typer.echo("\n---\nDescription excerpt:\n")
        typer.echo(excerpt)


@app.command()
def score(job_id: int, db: Path | None = None):
    """Score a job (v1: heuristic, config-driven)."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    row = conn.execute(
        """SELECT id, company, title, location, posted_date, url, description
           FROM jobs WHERE id=?""",
        (job_id,),
    ).fetchone()

    if not row:
        raise typer.BadParameter(f"No job with id={job_id}")

    _id, company, title, location, posted_date, url, description = row
    job_text = f"""
Company: {company}
Title: {title}
Location: {location}
Posted: {posted_date or 'unknown'}
URL: {url}

Description:
{description}
""".strip()

    profile = config["profile"]

    result = score_heuristic(
        job_text,
        keyword_weights=profile["preferred_keywords"],
        negative_keywords=profile["negative_keywords"],
    )

    conn.execute(
        """INSERT INTO scores
           (job_id, model, score, reasons_json, matched_json, missing_json, resume_emphasis_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            result.model,
            result.score,
            json.dumps(result.reasons),
            json.dumps(result.matched_keywords),
            json.dumps(result.missing_keywords),
            json.dumps(result.resume_emphasis),
            now_iso(),
        ),
    )
    conn.commit()

    typer.echo(f"[{job_id}] score={result.score} ({result.model})")
    for r in result.reasons:
        typer.echo(f"  - {r}")

@app.command("score-all")
def score_all(db: Path | None = None, limit: int | None = None):
    """Score all jobs that do not yet have a score."""
    config = load_config()
    db_path = db or resolve_db_path(config)

    conn = connect(db_path)
    init_db(conn)

    profile = config["profile"]

    query = """
        SELECT j.id, j.company, j.title, j.location, j.posted_date, j.url, j.description
        FROM jobs j
        LEFT JOIN scores s ON j.id = s.job_id
        WHERE s.job_id IS NULL
        ORDER BY j.id ASC
    """

    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    rows = conn.execute(query, params).fetchall()

    if not rows:
        typer.echo("No unscored jobs found.")
        return

    scored_count = 0

    for row in rows:
        job_id, company, title, location, posted_date, url, description = row

        job_text = f"""
Company: {company}
Title: {title}
Location: {location}
Posted: {posted_date or 'unknown'}
URL: {url}

Description:
{description}
""".strip()

        result = score_heuristic(
            job_text,
            keyword_weights=profile["preferred_keywords"],
            negative_keywords=profile["negative_keywords"],
        )

        conn.execute(
            """INSERT INTO scores
               (job_id, model, score, reasons_json, matched_json, missing_json, resume_emphasis_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                result.model,
                result.score,
                json.dumps(result.reasons),
                json.dumps(result.matched_keywords),
                json.dumps(result.missing_keywords),
                json.dumps(result.resume_emphasis),
                now_iso(),
            ),
        )

        scored_count += 1
        typer.echo(f"[{job_id}] score={result.score} | {company} | {title}")

    conn.commit()
    typer.echo(f"\nScored {scored_count} job(s).")