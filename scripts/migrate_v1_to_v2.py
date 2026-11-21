import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jobpilot.migration")

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "jobpilot.db"
BACKUP_PATH = ROOT_DIR / "data" / "jobpilot_v1_backup.db"
ANSWERS_EXAMPLE = ROOT_DIR / "data" / "answers.example.json"


def run_migration(db_path: Path = DB_PATH) -> Dict[str, Any]:
    """
    Safely migrates JobPilot v1 database to JobPilot v2 multi-source pipeline schema.
    1. Preserves existing sent history, companies, contacts, signals, cache, and usage.
    2. Extends jobs and applications with multi-routing, source tracking, and packet paths.
    3. Creates job_sources, status_history, runs, answers, and saved_searches tables.
    4. Seeds answers table with candidate profile and [FILL] chips.
    """
    if not db_path.exists():
        logger.warning("Database at %s does not exist; initializing fresh schema.", db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Create a safe backup before migration
    if db_path.exists() and db_path.stat().st_size > 0:
        shutil.copy2(db_path, BACKUP_PATH)
        logger.info("Backup created at %s (%d bytes)", BACKUP_PATH, BACKUP_PATH.stat().st_size)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF;")

    # Helper to check existing columns
    def get_existing_columns(table: str) -> set:
        cur.execute(f"PRAGMA table_info({table})")
        return {r[1] for r in cur.fetchall()}

    # 2. Upgrade jobs table
    existing_tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "jobs" in existing_tables:
        job_cols = get_existing_columns("jobs")
        new_job_columns = [
            ("canonical_key", "TEXT"),
            ("location_norm", "TEXT"),
            ("location_raw", "TEXT"),
            ("posted_at", "TIMESTAMP"),
            ("salary", "TEXT"),
            ("apply_url", "TEXT"),
            ("apply_kind", "TEXT DEFAULT 'unknown'"),
            ("easy_apply", "INTEGER DEFAULT 0"),
            ("source_names", "TEXT DEFAULT '[]'"),
            ("first_seen", "TIMESTAMP"),
            ("last_seen", "TIMESTAMP"),
            ("is_active", "INTEGER DEFAULT 1")
        ]
        for col_name, col_type in new_job_columns:
            if col_name not in job_cols:
                logger.info("Adding column jobs.%s (%s)", col_name, col_type)
                cur.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type};")

        # Backfill existing jobs
        cur.execute("""
            UPDATE jobs SET
                apply_url = COALESCE(apply_url, url),
                location_raw = COALESCE(location_raw, location),
                location_norm = COALESCE(location_norm, location),
                canonical_key = COALESCE(canonical_key, LOWER(company) || '__' || LOWER(title)),
                source_names = COALESCE(source_names, '["' || COALESCE(source, 'manual') || '"]'),
                first_seen = COALESCE(first_seen, created_at, CURRENT_TIMESTAMP),
                last_seen = COALESCE(last_seen, created_at, CURRENT_TIMESTAMP),
                apply_kind = CASE
                    WHEN apply_kind IS NOT NULL AND apply_kind != 'unknown' THEN apply_kind
                    WHEN recruiter_email IS NOT NULL AND recruiter_email != '' THEN 'email'
                    ELSE 'unknown'
                END
            WHERE apply_url IS NULL OR canonical_key IS NULL;
        """)
        conn.commit()

    # 3. Upgrade applications table
    if "applications" in existing_tables:
        app_cols = get_existing_columns("applications")
        new_app_columns = [
            ("route", "TEXT DEFAULT 'email'"),
            ("cover_note", "TEXT"),
            ("applied_at", "TIMESTAMP"),
            ("packet_path", "TEXT"),
            ("tone_score", "REAL DEFAULT 10.0"),
            ("notes", "TEXT")
        ]
        for col_name, col_type in new_app_columns:
            if col_name not in app_cols:
                logger.info("Adding column applications.%s (%s)", col_name, col_type)
                cur.execute(f"ALTER TABLE applications ADD COLUMN {col_name} {col_type};")

        # Backfill applied_at from sent_at for existing sent history
        cur.execute("""
            UPDATE applications SET
                applied_at = COALESCE(applied_at, sent_at),
                route = COALESCE(route, 'email')
            WHERE sent_at IS NOT NULL AND applied_at IS NULL;
        """)
        conn.commit()

    # 4. Create job_sources table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS job_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            source TEXT NOT NULL,
            external_id TEXT,
            url TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_job_sources_job_id ON job_sources(job_id);")

    if "jobs" in existing_tables:
        cur.execute("""
            INSERT OR IGNORE INTO job_sources (job_id, source, url)
            SELECT id, COALESCE(source, 'manual'), url FROM jobs
            WHERE id NOT IN (SELECT job_id FROM job_sources);
        """)
        conn.commit()

    # 5. Create status_history table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            note TEXT,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_status_history_app_id ON status_history(application_id);")

    if "applications" in existing_tables:
        cur.execute("""
            INSERT OR IGNORE INTO status_history (application_id, from_status, to_status, changed_at, note)
            SELECT id, 'new', status, COALESCE(sent_at, updated_at, created_at), 'Migrated from JobPilot v1'
            FROM applications
            WHERE id NOT IN (SELECT application_id FROM status_history);
        """)
        conn.commit()

    # 6. Create runs table (in-process scheduler and SSE progress)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            status TEXT DEFAULT 'running',
            counts_json TEXT DEFAULT '{}',
            error TEXT
        );
    """)

    # 7. Create answers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            needs_fill INTEGER DEFAULT 0
        );
    """)

    # Seed answers from answers.example.json if empty
    cur.execute("SELECT COUNT(*) FROM answers;")
    if cur.fetchone()[0] == 0 and ANSWERS_EXAMPLE.exists():
        with open(ANSWERS_EXAMPLE, "r", encoding="utf-8") as f:
            example_answers = json.load(f)
        for k, v in example_answers.items():
            is_fill = 1 if "[FILL]" in str(v) else 0
            cur.execute("INSERT OR REPLACE INTO answers (key, value, needs_fill) VALUES (?, ?, ?);", (k, str(v), is_fill))
        conn.commit()
        logger.info("Seeded %d answers into answers table.", len(example_answers))

    # 8. Create saved_searches table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            query_json TEXT NOT NULL,
            notify INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    cur.execute("PRAGMA foreign_keys = ON;")

    # 9. Summary stats
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [r[0] for r in cur.fetchall()]
    counts = {t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    conn.close()
    logger.info("Migration to JobPilot v2 complete. Table counts: %s", counts)
    return counts


if __name__ == "__main__":
    run_migration()
