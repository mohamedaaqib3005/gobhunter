import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import is_relevant_title
from models import Job, JobStatus

DB_PATH = Path(__file__).parent / "jobs.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT NOT NULL,
            source TEXT NOT NULL,
            source_url TEXT NOT NULL UNIQUE,
            description TEXT,
            salary_range TEXT,
            posted_date TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            applied_date TEXT,
            notes TEXT,
            resume_path TEXT,
            resume_job_id TEXT,
            resume_status TEXT DEFAULT 'none',
            resume_meta TEXT,
            resume_updated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)
    """)

    # Safe column migration for existing databases
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    new_columns = {
        "resume_path": "TEXT",
        "resume_job_id": "TEXT",
        "resume_status": "TEXT DEFAULT 'none'",
        "resume_meta": "TEXT",
        "resume_updated_at": "TEXT",
    }
    for col_name, col_type in new_columns.items():
        if col_name not in existing_columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_resume_job_id ON jobs(resume_job_id)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            jobs_found INTEGER DEFAULT 0,
            jobs_saved INTEGER DEFAULT 0,
            message TEXT
        )
    """)
    conn.commit()
    conn.close()


def record_scrape_start() -> int:
    init_db()
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # Mark old 'running' runs as interrupted
    conn.execute(
        "UPDATE scrape_runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
        (now,),
    )
    cursor = conn.execute(
        "INSERT INTO scrape_runs (status, started_at) VALUES ('running', ?)",
        (now,),
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def record_scrape_finish(
    run_id: int,
    status: str = "completed",
    jobs_found: int = 0,
    jobs_saved: int = 0,
    message: str = "",
) -> None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE scrape_runs
           SET status = ?, finished_at = ?, jobs_found = ?, jobs_saved = ?, message = ?
           WHERE id = ?""",
        (status, now, jobs_found, jobs_saved, message, run_id),
    )
    conn.commit()
    conn.close()


def get_last_scrape_run() -> dict | None:
    init_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row:
        res = {
            "id": row["id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "jobs_found": row["jobs_found"],
            "jobs_saved": row["jobs_saved"],
            "message": row["message"],
        }
        conn.close()
        return res

    fallback_row = conn.execute("SELECT MAX(updated_at) as last_update FROM jobs").fetchone()
    conn.close()
    if fallback_row and fallback_row["last_update"]:
        return {
            "id": None,
            "status": "completed",
            "started_at": fallback_row["last_update"],
            "finished_at": fallback_row["last_update"],
            "jobs_found": 0,
            "jobs_saved": 0,
            "message": "Initial import",
        }
    return None


def is_scrape_running() -> bool:
    init_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT id, started_at FROM scrape_runs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return False
    try:
        started = datetime.fromisoformat(row["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed > 1800:
            return False
    except Exception:
        pass
    return True



def normalize_source_url(url: str, source: str = "") -> str:
    if source == "indeed" or (not source and "indeed.com" in url):
        qs = parse_qs(urlparse(url).query)
        if "jk" in qs:
            return f"https://in.indeed.com/viewjob?jk={qs['jk'][0]}"
    return url


def migrate_source_urls() -> int:
    conn = get_conn()
    rows = conn.execute("SELECT id, source, source_url FROM jobs ORDER BY id").fetchall()

    to_delete: list[int] = []
    normalized_map: dict[str, int] = {}
    updates: list[tuple[str, str, int]] = []

    for row in rows:
        normalized = normalize_source_url(row["source_url"], row["source"])
        if normalized == row["source_url"]:
            continue
        if normalized in normalized_map:
            to_delete.append(row["id"])
        else:
            normalized_map[normalized] = row["id"]
            now = datetime.now(timezone.utc).isoformat()
            updates.append((normalized, now, row["id"]))

    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", to_delete)

    for normalized, now, rid in updates:
        conn.execute("UPDATE jobs SET source_url = ?, updated_at = ? WHERE id = ?",
                     (normalized, now, rid))

    if to_delete or updates:
        conn.commit()
    conn.close()
    return len(updates)


def deduplicate_jobs() -> int:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, company, location, source, status FROM jobs ORDER BY id"
    ).fetchall()
    seen: dict[tuple[str, str, str, str], int] = {}
    id_status: dict[int, str] = {}
    to_delete: list[int] = []
    for row in rows:
        id_status[row["id"]] = row["status"]
        key = (row["title"].strip().lower(), row["company"].strip().lower(),
               row["location"].strip().lower(), row["source"])
        if key in seen:
            existing_id = seen[key]
            existing_status = id_status[existing_id]
            current_status = row["status"]
            if existing_status == "new" and current_status != "new":
                to_delete.append(existing_id)
                seen[key] = row["id"]
            else:
                to_delete.append(row["id"])
        else:
            seen[key] = row["id"]
    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", to_delete)
        conn.commit()
    conn.close()
    return len(to_delete)


def insert_job(job: Job) -> int | None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    job.source_url = normalize_source_url(job.source_url, job.source)
    try:
        cursor = conn.execute("""
            INSERT INTO jobs (title, company, location, source, source_url,
                              description, salary_range, posted_date, status,
                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job.title, job.company, job.location, job.source, job.source_url,
            job.description, job.salary_range, job.posted_date, job.status.value,
            now, now,
        ))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def job_exists(source_url: str, source: str = "") -> bool:
    conn = get_conn()
    normalized = normalize_source_url(source_url, source)
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE source_url = ?", (normalized,)
    ).fetchone()
    conn.close()
    return row is not None


def job_exists_by_content(title: str, company: str, location: str, source: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        """SELECT 1 FROM jobs
           WHERE LOWER(TRIM(title)) = LOWER(TRIM(?))
             AND LOWER(TRIM(company)) = LOWER(TRIM(?))
             AND LOWER(TRIM(location)) = LOWER(TRIM(?))
             AND source = ?""",
        (title, company, location, source),
    ).fetchone()
    conn.close()
    return row is not None


def get_jobs(
    source: str | None = None,
    status: str | None = None,
    relevant: bool = True,
    exclude_dismissed: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> list[Job]:
    conn = get_conn()
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if status:
        query += " AND status = ?"
        params.append(status)
    elif exclude_dismissed:
        query += " AND status != 'dismissed'"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    jobs = [_row_to_job(r) for r in rows]
    if relevant:
        jobs = [j for j in jobs if is_relevant_title(j.title)]
    return jobs[offset:offset + limit]


def get_job(job_id: int) -> Job | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return _row_to_job(row) if row else None


def update_job_status(job_id: int, status: JobStatus, notes: str | None = None) -> None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
        (status.value, now, job_id),
    )
    if notes:
        conn.execute(
            "UPDATE jobs SET notes = ?, updated_at = ? WHERE id = ?",
            (notes, now, job_id),
        )
    applied_date = now if status == JobStatus.APPLIED else None
    if applied_date:
        conn.execute(
            "UPDATE jobs SET applied_date = ? WHERE id = ?",
            (applied_date, job_id),
        )
    conn.commit()
    conn.close()


def update_job_description(job_id: int, description: str) -> None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE jobs SET description = ?, updated_at = ? WHERE id = ?",
        (description, now, job_id),
    )
    conn.commit()
    conn.close()


def update_job_scraped_details(
    job_id: int,
    description: str | None = None,
    salary_range: str | None = None,
    location: str | None = None,
) -> None:
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    fields = ["updated_at = ?"]
    params = [now]
    if description is not None:
        fields.append("description = ?")
        params.append(description)
    if salary_range is not None:
        fields.append("salary_range = ?")
        params.append(salary_range)
    if location is not None:
        fields.append("location = ?")
        params.append(location)
    params.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()




def get_stats() -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT source, status, COUNT(*) as count FROM jobs GROUP BY source, status"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0]
    all_jobs = conn.execute("SELECT title FROM jobs").fetchall()
    conn.close()
    relevant = sum(1 for r in all_jobs if is_relevant_title(r["title"]))
    stats: dict[str, dict[str, int]] = {"_total": total, "_relevant": relevant, "_applied": applied}
    for row in rows:
        source = row["source"]
        if source not in stats:
            stats[source] = {}
        stats[source][row["status"]] = row["count"]
    return stats


def delete_irrelevant_jobs() -> int:
    conn = get_conn()
    rows = conn.execute("SELECT id, title FROM jobs").fetchall()
    to_delete = [row["id"] for row in rows if not is_relevant_title(row["title"])]
    if to_delete:
        placeholders = ",".join("?" * len(to_delete))
        conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", to_delete)
        conn.commit()
    conn.close()
    return len(to_delete)


RESUMES_DIR = Path(__file__).parent / "resumes"


def get_job_by_resume_job_id(resume_job_id: str) -> Job | None:
    init_db()
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE resume_job_id = ? ORDER BY id DESC LIMIT 1",
        (resume_job_id,),
    ).fetchone()
    conn.close()
    return _row_to_job(row) if row else None


def update_job_resume_status(
    job_id: int,
    resume_status: str,
    resume_job_id: str | None = None,
    resume_path: str | None = None,
    resume_meta: str | None = None,
) -> None:
    init_db()
    conn = get_conn()
    now = datetime.now(timezone.utc).isoformat()
    fields = ["resume_status = ?", "resume_updated_at = ?"]
    params = [resume_status, now]

    if resume_job_id is not None:
        fields.append("resume_job_id = ?")
        params.append(resume_job_id)
    if resume_path is not None:
        fields.append("resume_path = ?")
        params.append(resume_path)
    if resume_meta is not None:
        fields.append("resume_meta = ?")
        params.append(resume_meta)

    params.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def save_job_resume_pdf(
    job_id: int,
    pdf_bytes: bytes,
    filename: str | None = None,
    resume_job_id: str | None = None,
    meta: str | None = None,
) -> str:
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clean filename
    job = get_job(job_id)
    safe_company = "".join(c for c in (job.company if job else "company") if c.isalnum() or c in (" ", "_", "-")).strip()
    safe_title = "".join(c for c in (job.title if job else "resume") if c.isalnum() or c in (" ", "_", "-")).strip()
    
    if filename:
        save_name = f"{job_id}_{filename}"
    else:
        save_name = f"resume_{job_id}_{safe_company}_{safe_title}.pdf".replace(" ", "_")

    file_path = RESUMES_DIR / save_name
    file_path.write_bytes(pdf_bytes)

    update_job_resume_status(
        job_id=job_id,
        resume_status="succeeded",
        resume_job_id=resume_job_id,
        resume_path=str(file_path.resolve()),
        resume_meta=meta,
    )
    return str(file_path.resolve())


def _row_to_job(row: sqlite3.Row) -> Job:
    keys = row.keys() if hasattr(row, "keys") else []
    return Job(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        source=row["source"],
        source_url=row["source_url"],
        description=row["description"],
        salary_range=row["salary_range"],
        posted_date=row["posted_date"],
        status=JobStatus(row["status"]),
        notes=row["notes"],
        resume_path=row["resume_path"] if "resume_path" in keys else None,
        resume_job_id=row["resume_job_id"] if "resume_job_id" in keys else None,
        resume_status=row["resume_status"] if "resume_status" in keys else "none",
        resume_meta=row["resume_meta"] if "resume_meta" in keys else None,
        resume_updated_at=row["resume_updated_at"] if "resume_updated_at" in keys else None,
    )
