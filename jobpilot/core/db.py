import sqlite3
import json
import logging
import difflib
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from jobpilot.core.config import settings
from jobpilot.core.models import (
    Job, Application, RecruiterContact, Company, CompanySignal,
    CompanyOutreach, RawJob
)

logger = logging.getLogger("jobpilot.db")

COMPANY_LEGAL_SUFFIXES = [
    r'\bpvt\.?\s*ltd\.?\b',
    r'\bprivate\s+limited\b',
    r'\bltd\.?\b',
    r'\blimited\b',
    r'\binc\.?\b',
    r'\bincorporated\b',
    r'\bcorp\.?\b',
    r'\bcorporation\b',
    r'\bllc\b',
    r'\btechnologies\b',
    r'\btechnology\b',
    r'\bsolutions\b',
    r'\bsoftware\b',
    r'\bsystems\b',
    r'\blabs\b',
    r'\bservices\b',
    r'\bindia\b',
]

TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "src", "gh_src", "gh_jid", "session",
    "session_id", "sid", "fbclid", "gclid", "trk", "trackingid", "_ga",
    "mc_cid", "mc_eid"
}


def clean_company_name_for_matching(name: str) -> str:
    if not name:
        return ""
    clean = name.lower().strip()
    for suff in COMPANY_LEGAL_SUFFIXES:
        clean = re.sub(suff, '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[^a-z0-9\s]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean or name.lower().strip()


def normalize_job_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    u = raw_url.strip()
    try:
        parsed = urlparse(u)
        scheme = (parsed.scheme or "https").lower()
        netloc = parsed.netloc.lower()
        if netloc.endswith(":80"):
            netloc = netloc[:-3]
        elif netloc.endswith(":443"):
            netloc = netloc[:-4]

        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path[:-1]

        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        clean_pairs = [
            (k, v) for k, v in query_pairs
            if k.lower() not in TRACKING_QUERY_PARAMS
        ]
        clean_pairs.sort()
        clean_query = urlencode(clean_pairs)

        return urlunparse((scheme, netloc, path, "", clean_query, ""))
    except Exception:
        return u


def clean_job_title_for_dedupe(title: str) -> str:
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r'[/\\|\-_]', ' ', t)
    t = re.sub(r'\b(fresher|entry\s+level|junior|trainee|intern|internship|urgent|immediate\s+joiner|full\s+time|remote|hybrid)\b', ' ', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT DEFAULT 'Remote',
                url TEXT NOT NULL,
                description TEXT NOT NULL,
                posted_date TEXT,
                source TEXT DEFAULT 'manual',
                recruiter_email TEXT,
                role_tier TEXT,
                role_lens TEXT,
                company_id INTEGER,
                canonical_key TEXT UNIQUE,
                title_norm TEXT,
                city_norm TEXT,
                apply_url_canon TEXT,
                description_hash TEXT,
                location_norm TEXT,
                location_raw TEXT,
                posted_at TIMESTAMP,
                salary TEXT,
                apply_url TEXT,
                apply_kind TEXT DEFAULT 'unknown',
                easy_apply INTEGER DEFAULT 0,
                source_names TEXT DEFAULT '[]',
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_key);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_kind ON jobs(apply_kind);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                source TEXT NOT NULL,
                external_id TEXT,
                url TEXT,
                payload_json TEXT,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_jobs_src_ext ON raw_jobs(source, external_id);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                url TEXT,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_sources_src_ext ON job_sources(source, external_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_sources_job_id ON job_sources(job_id);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                company_id INTEGER,
                contact_email TEXT NOT NULL,
                mode TEXT DEFAULT 'job_application',
                idempotency_key TEXT UNIQUE NOT NULL,
                score REAL,
                score_basis TEXT DEFAULT 'rules',
                status TEXT NOT NULL DEFAULT 'new',
                resume_path TEXT,
                email_subject TEXT,
                email_body TEXT,
                gmail_message_id TEXT,
                gmail_uid INTEGER,
                drafted_at TIMESTAMP,
                sent_at TIMESTAMP,
                replied_at TIMESTAMP,
                followup_due TIMESTAMP,
                followup_sent TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            );
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_idempotency ON outreach(idempotency_key);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_outreach_contact_email ON outreach(contact_email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_ledger (
                email TEXT PRIMARY KEY,
                domain TEXT,
                company_id INTEGER,
                first_contacted_at TIMESTAMP,
                last_contacted_at TIMESTAMP,
                times_contacted INTEGER DEFAULT 0,
                last_outreach_id INTEGER,
                opted_out INTEGER DEFAULT 0,
                bounced INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contact_ledger_domain ON contact_ledger(domain);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_ledger (
                company_id INTEGER PRIMARY KEY,
                last_contacted_at TIMESTAMP,
                total_outreach INTEGER DEFAULT 0,
                cooldown_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_budget (
                day TEXT NOT NULL,
                model TEXT NOT NULL,
                requests INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0,
                blocked_calls INTEGER DEFAULT 0,
                PRIMARY KEY (day, model)
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                outreach_id INTEGER,
                stage TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens INTEGER DEFAULT 0,
                cached INTEGER DEFAULT 0,
                at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_run ON llm_calls(run_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_outreach ON llm_calls(outreach_id);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                match_score REAL,
                resume_path TEXT,
                tailored_json_path TEXT,
                email_subject TEXT,
                email_body TEXT,
                sent_at TIMESTAMP,
                applied_at TIMESTAMP,
                followup_sent_at TIMESTAMP,
                recipient_email TEXT,
                rationale TEXT,
                role_tier TEXT,
                role_lens TEXT,
                route TEXT DEFAULT 'email',
                cover_note TEXT,
                packet_path TEXT,
                tone_score REAL DEFAULT 10.0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outreach_id INTEGER,
                application_id INTEGER,
                from_status TEXT,
                to_status TEXT NOT NULL,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
                FOREIGN KEY (outreach_id) REFERENCES outreach(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_history_app_id ON status_history(application_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_history_outreach_id ON status_history(outreach_id);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                counts_json TEXT DEFAULT '{}',
                error TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                needs_fill INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                query_json TEXT NOT NULL,
                notify INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                company_id INTEGER,
                email TEXT NOT NULL,
                name TEXT,
                role TEXT,
                source_type TEXT DEFAULT 'jd_text',
                verified INTEGER DEFAULT 0,
                domain_mx_valid INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                domain TEXT UNIQUE,
                website TEXT,
                careers_url TEXT,
                city TEXT,
                address TEXT,
                hq_country TEXT DEFAULT 'India',
                employee_min INTEGER,
                employee_max INTEGER,
                employee_estimate INTEGER,
                size_confidence REAL DEFAULT 0.0,
                size_source TEXT,
                size_evidence TEXT,
                size_status TEXT DEFAULT 'unknown',
                field_tags TEXT,
                field_fit_score REAL DEFAULT 0.0,
                hiring_signal_score REAL DEFAULT 0.0,
                company_score REAL DEFAULT 0.0,
                tier TEXT DEFAULT 'C',
                discovered_via TEXT,
                last_checked TIMESTAMP,
                status TEXT DEFAULT 'new',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                signal_type TEXT NOT NULL,
                value TEXT NOT NULL,
                source_url TEXT,
                weight REAL DEFAULT 1.0,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                contact_id INTEGER,
                mode TEXT DEFAULT 'speculative',
                resume_path TEXT,
                email_subject TEXT,
                email_body TEXT,
                status TEXT DEFAULT 'drafted',
                sent_at TIMESTAMP,
                followup_due TIMESTAMP,
                followup_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                prompt_hash TEXT PRIMARY KEY,
                response_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                call_type TEXT NOT NULL,
                tokens_used INTEGER NOT NULL,
                cost_estimate REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT DEFAULT 'INFO',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                reason TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# --- Jobs Functions ---

def is_job_duplicate(title: str, company: str, url: str, db_path: Optional[Path] = None) -> bool:
    norm_url = normalize_job_url(url)
    c_clean = clean_company_name_for_matching(company)
    t_clean = clean_job_title_for_dedupe(title)
    canonical = f"{c_clean}__{t_clean}"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # Direct URL match
        cursor.execute("SELECT id FROM jobs WHERE url = ? OR apply_url = ?", (norm_url, norm_url))
        if cursor.fetchone():
            return True

        # Canonical key match
        cursor.execute("SELECT id FROM jobs WHERE canonical_key = ?", (canonical,))
        if cursor.fetchone():
            return True

        # Check existing jobs for same company with similar title
        cursor.execute("SELECT title, company FROM jobs WHERE LOWER(company) = LOWER(?)", (company,))
        for row in cursor.fetchall():
            row_t = clean_job_title_for_dedupe(row["title"])
            if t_clean and row_t:
                ratio = difflib.SequenceMatcher(None, t_clean, row_t).ratio()
                if ratio >= 0.85:
                    return True
    return False


def save_job(job: RawJob, db_path: Optional[Path] = None) -> str:
    norm_url = normalize_job_url(job.url)
    c_clean = clean_company_name_for_matching(job.company)
    t_clean = clean_job_title_for_dedupe(job.title)
    canonical = f"{c_clean}__{t_clean}"
    job_id = f"job_{abs(hash(canonical + norm_url)) % 100000000:08d}"

    sources_json = json.dumps([job.source])

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # Check if canonical exists
        cursor.execute("SELECT id, source_names FROM jobs WHERE canonical_key = ? OR url = ?", (canonical, norm_url))
        existing = cursor.fetchone()
        if existing:
            existing_id = existing["id"]
            existing_sources = json.loads(existing["source_names"] or "[]")
            if job.source not in existing_sources:
                existing_sources.append(job.source)
            cursor.execute("""
                UPDATE jobs SET
                    last_seen = CURRENT_TIMESTAMP,
                    source_names = ?,
                    apply_url = COALESCE(apply_url, ?),
                    apply_kind = CASE WHEN apply_kind = 'unknown' THEN ? ELSE apply_kind END
                WHERE id = ?
            """, (json.dumps(existing_sources), job.apply_url or norm_url, job.apply_kind, existing_id))

            cursor.execute("""
                INSERT OR IGNORE INTO job_sources (job_id, source, external_id, url)
                VALUES (?, ?, ?, ?)
            """, (existing_id, job.source, job.source_job_id, norm_url))
            conn.commit()
            return existing_id

        # Insert fresh job
        cursor.execute("""
            INSERT INTO jobs (
                id, title, company, location, url, description, posted_date,
                source, recruiter_email, canonical_key, location_norm,
                location_raw, salary, apply_url, apply_kind, easy_apply,
                source_names, first_seen, last_seen, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
        """, (
            job_id, job.title, job.company, job.location, norm_url,
            job.description, job.posted_date, job.source, job.recruiter_email,
            canonical, job.location, job.location, job.salary,
            job.apply_url or norm_url, job.apply_kind, 1 if job.easy_apply else 0,
            sources_json
        ))

        cursor.execute("""
            INSERT INTO job_sources (job_id, source, external_id, url)
            VALUES (?, ?, ?, ?)
        """, (job_id, job.source, job.source_job_id, norm_url))

        # Also initialize an application record for this job
        cursor.execute("""
            INSERT INTO applications (job_id, status, route)
            VALUES (?, 'new', CASE WHEN ? = 'email' THEN 'email' WHEN ? LIKE 'ats%' THEN 'ats_assist' ELSE 'packet' END)
        """, (job_id, job.apply_kind, job.apply_kind))

        conn.commit()
    return job_id


def get_job(job_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.*, a.id as application_id, a.status as app_status, a.match_score,
                   a.route, a.cover_note, a.email_subject, a.email_body, a.resume_path,
                   a.applied_at, a.sent_at, a.packet_path, a.tone_score
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            WHERE j.id = ?
        """, (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_jobs(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    apply_kind: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    min_score: Optional[float] = None,
    db_path: Optional[Path] = None
) -> Tuple[List[Dict[str, Any]], int]:
    query = """
        SELECT j.*, a.id as application_id, a.status as app_status, a.match_score,
               a.route, a.applied_at, a.sent_at, a.cover_note
        FROM jobs j
        LEFT JOIN applications a ON j.id = a.job_id
        WHERE 1=1
    """
    params: List[Any] = []

    if status:
        query += " AND a.status = ?"
        params.append(status)
    if apply_kind:
        query += " AND j.apply_kind = ?"
        params.append(apply_kind)
    if source:
        query += " AND j.source_names LIKE ?"
        params.append(f'%"{source}"%')
    if min_score is not None:
        query += " AND a.match_score >= ?"
        params.append(min_score)
    if search:
        query += " AND (j.title LIKE ? OR j.company LIKE ? OR j.description LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])

    # Get total count
    count_query = f"SELECT COUNT(*) FROM ({query}) AS sub"
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        query += " ORDER BY j.first_seen DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return rows, total


# --- Application & Status History ---

def update_application_status(
    app_id: int,
    to_status: str,
    note: Optional[str] = None,
    db_path: Optional[Path] = None
):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM applications WHERE id = ?", (app_id,))
        row = cursor.fetchone()
        from_status = row["status"] if row else "unknown"

        now = datetime.now()
        cursor.execute("""
            UPDATE applications SET
                status = ?,
                updated_at = ?,
                applied_at = CASE WHEN ? IN ('sent', 'emailed', 'applied') AND applied_at IS NULL THEN ? ELSE applied_at END
            WHERE id = ?
        """, (to_status, now, to_status, now, app_id))

        cursor.execute("""
            INSERT INTO status_history (application_id, from_status, to_status, note)
            VALUES (?, ?, ?, ?)
        """, (app_id, from_status, to_status, note))
        conn.commit()


def save_tailored_application(
    job_id: str,
    match_score: float,
    resume_path: str,
    tailored_json_path: str,
    role_lens: str,
    role_tier: str,
    rationale: str,
    route: str,
    email_subject: Optional[str] = None,
    email_body: Optional[str] = None,
    cover_note: Optional[str] = None,
    packet_path: Optional[str] = None,
    tone_score: float = 10.0,
    db_path: Optional[Path] = None
) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM applications WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        now = datetime.now()
        if row:
            app_id = row["id"]
            cursor.execute("""
                UPDATE applications SET
                    match_score = ?,
                    resume_path = ?,
                    tailored_json_path = ?,
                    role_lens = ?,
                    role_tier = ?,
                    rationale = ?,
                    route = ?,
                    email_subject = ?,
                    email_body = ?,
                    cover_note = ?,
                    packet_path = ?,
                    tone_score = ?,
                    status = 'drafted',
                    updated_at = ?
                WHERE id = ?
            """, (
                match_score, resume_path, tailored_json_path, role_lens,
                role_tier, rationale, route, email_subject, email_body,
                cover_note, packet_path, tone_score, now, app_id
            ))
            cursor.execute("""
                INSERT INTO status_history (application_id, from_status, to_status, note)
                VALUES (?, ?, 'drafted', 'Tailored resume and apply packet created')
            """, (app_id, row["status"]))
        else:
            cursor.execute("""
                INSERT INTO applications (
                    job_id, status, match_score, resume_path, tailored_json_path,
                    role_lens, role_tier, rationale, route, email_subject, email_body,
                    cover_note, packet_path, tone_score, created_at, updated_at
                ) VALUES (?, 'drafted', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, match_score, resume_path, tailored_json_path, role_lens,
                role_tier, rationale, route, email_subject, email_body,
                cover_note, packet_path, tone_score, now, now
            ))
            app_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO status_history (application_id, from_status, to_status, note)
                VALUES (?, 'new', 'drafted', 'Initial tailoring drafted')
            """, (app_id,))
        conn.commit()
        return app_id


def get_pipeline_counts(db_path: Optional[Path] = None) -> Dict[str, int]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as c FROM applications GROUP BY status")
        counts = {r["status"]: r["c"] for r in cursor.fetchall()}
        return counts


# --- Answers CRUD ---

def get_all_answers(db_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value, needs_fill FROM answers ORDER BY key")
        return {r["key"]: {"value": r["value"], "needs_fill": bool(r["needs_fill"])} for r in cursor.fetchall()}


def update_answer(key: str, value: str, db_path: Optional[Path] = None):
    needs_fill = 1 if "[FILL]" in value or not value.strip() else 0
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO answers (key, value, needs_fill)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, needs_fill = excluded.needs_fill
        """, (key, value, needs_fill))
        conn.commit()


def get_missing_answers_count(db_path: Optional[Path] = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM answers WHERE needs_fill = 1")
        return cursor.fetchone()[0]


# --- Runs & Events CRUD ---

def start_run(run_type: str, db_path: Optional[Path] = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO runs (type, started_at, status)
            VALUES (?, CURRENT_TIMESTAMP, 'running')
        """, (run_type,))
        conn.commit()
        return cursor.lastrowid


def finish_run(run_id: int, status: str, counts: Dict[str, Any], error: Optional[str] = None, db_path: Optional[Path] = None):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE runs SET
                finished_at = CURRENT_TIMESTAMP,
                status = ?,
                counts_json = ?,
                error = ?
            WHERE id = ?
        """, (status, json.dumps(counts), error, run_id))
        conn.commit()


def get_recent_runs(limit: int = 20, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]


# --- LLM Cache & Usage ---

def get_cached_llm_response(prompt_hash: str, db_path: Optional[Path] = None) -> Optional[str]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT response_text FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,))
        row = cursor.fetchone()
        return row["response_text"] if row else None


def set_cached_llm_response(prompt_hash: str, response_text: str, db_path: Optional[Path] = None):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO llm_cache (prompt_hash, response_text, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (prompt_hash, response_text))
        conn.commit()


def record_llm_usage(prompt_tokens: int = 0, completion_tokens: int = 0, tokens_used: int = 0, call_type: str = "generate", db_path: Optional[Path] = None):
    today_str = date.today().isoformat()
    if tokens_used and not (prompt_tokens or completion_tokens):
        prompt_tokens = int(tokens_used * 0.7)
        completion_tokens = int(tokens_used * 0.3)
    total_tokens = prompt_tokens + completion_tokens
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                usage_date TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            INSERT INTO llm_usage (usage_date, request_count, prompt_tokens, completion_tokens, total_tokens, updated_at)
            VALUES (?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(usage_date) DO UPDATE SET
                request_count = request_count + 1,
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                total_tokens = total_tokens + excluded.total_tokens,
                updated_at = CURRENT_TIMESTAMP
        """, (today_str, prompt_tokens, completion_tokens, total_tokens))
        conn.commit()


def get_today_llm_usage(db_path: Optional[Path] = None) -> Dict[str, Any]:
    today_str = date.today().isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                usage_date TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            SELECT request_count, prompt_tokens, completion_tokens, total_tokens
            FROM llm_usage WHERE usage_date = ?
        """, (today_str,))
        row = cursor.fetchone()
        if row:
            return {
                "date": today_str,
                "request_count": int(row["request_count"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"])
            }
        return {"date": today_str, "request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}



def log_event(event_type: str, message: str, level: str = "INFO", db_path: Optional[Path] = None):
    try:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cols = {c[1] for c in cursor.execute("PRAGMA table_info(logs)").fetchall()}
            if "event_type" in cols:
                cursor.execute("""
                    INSERT INTO logs (event_type, message, level, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (event_type, message, level))
            else:
                cursor.execute("""
                    INSERT INTO logs (level, module, message, timestamp)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (level, event_type, message))
            conn.commit()
    except Exception:
        pass


# --- Blocklist ---

def is_email_blocklisted(email: str, db_path: Optional[Path] = None) -> bool:
    if not email:
        return False
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM blocklist WHERE LOWER(email) = LOWER(?)", (email.strip(),))
        return cursor.fetchone() is not None


def add_to_blocklist(email: str, reason: str = "Manual opt-out", db_path: Optional[Path] = None):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO blocklist (email, reason, added_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (email.strip().lower(), reason))
        # Also mark opted_out in contact_ledger
        cursor.execute("""
            INSERT INTO contact_ledger (email, domain, opted_out, updated_at)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET opted_out = 1, updated_at = CURRENT_TIMESTAMP
        """, (email.strip().lower(), email.strip().lower().split("@")[-1] if "@" in email else ""))
        conn.commit()


# --- Ledger & Duplicate Protection ---

def is_recipient_in_cooldown(email: str, cooldown_days: int = 30, db_path: Optional[Path] = None) -> Tuple[bool, Optional[str]]:
    if not email:
        return False, None
    clean_email = email.lower().strip()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT last_contacted_at, opted_out, bounced
            FROM contact_ledger
            WHERE email = ?
        """, (clean_email,))
        row = cursor.fetchone()
        if not row:
            return False, None

        if row["opted_out"]:
            return True, f"Recipient {clean_email} previously opted out"
        if row["bounced"]:
            return True, f"Recipient {clean_email} bounced on prior outreach"

        if row["last_contacted_at"]:
            try:
                last_dt = datetime.fromisoformat(str(row["last_contacted_at"])[:19])
                cutoff = datetime.now() - timedelta(days=cooldown_days)
                if last_dt >= cutoff:
                    days_ago = (datetime.now() - last_dt).days
                    return True, f"Recipient contacted {days_ago} days ago (cooldown is {cooldown_days} days)"
            except Exception:
                pass
    return False, None


def is_company_in_cooldown_ledger(company_id: int, cooldown_days: int = 30, db_path: Optional[Path] = None) -> Tuple[bool, Optional[str]]:
    if not company_id:
        return False, None
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cooldown_until, last_contacted_at
            FROM company_ledger
            WHERE company_id = ?
        """, (company_id,))
        row = cursor.fetchone()
        if not row:
            return False, None

        if row["cooldown_until"]:
            try:
                cooldown_dt = datetime.fromisoformat(str(row["cooldown_until"])[:19])
                if datetime.now() < cooldown_dt:
                    return True, f"Company under cooldown until {row['cooldown_until']}"
            except Exception:
                pass

        if row["last_contacted_at"]:
            try:
                last_dt = datetime.fromisoformat(str(row["last_contacted_at"])[:19])
                cutoff = datetime.now() - timedelta(days=cooldown_days)
                if last_dt >= cutoff:
                    return True, f"Company contacted within last {cooldown_days} days"
            except Exception:
                pass
    return False, None


def create_or_get_outreach(
    job_id: Optional[str],
    company_id: Optional[int],
    contact_email: str,
    idempotency_key: str,
    score: float = 0.0,
    score_basis: str = "rules",
    status: str = "new",
    resume_path: Optional[str] = None,
    email_subject: Optional[str] = None,
    email_body: Optional[str] = None,
    gmail_message_id: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Tuple[int, bool]:
    """
    Inserts an outreach row with hard idempotency constraint.
    Returns (outreach_id, is_new).
    """
    clean_email = contact_email.lower().strip()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if company_id:
            cursor.execute("SELECT id FROM companies WHERE id = ?", (company_id,))
            if not cursor.fetchone():
                company_id = None

        try:
            cursor.execute("""
                INSERT INTO outreach (
                    job_id, company_id, contact_email, mode, idempotency_key,
                    score, score_basis, status, resume_path, email_subject, email_body,
                    gmail_message_id, created_at, updated_at
                ) VALUES (?, ?, ?, 'job_application', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                job_id, company_id, clean_email, idempotency_key,
                score, score_basis, status, resume_path, email_subject, email_body,
                gmail_message_id
            ))
            conn.commit()
            return cursor.lastrowid, True
        except sqlite3.IntegrityError:
            # Already exists - fetch existing row id
            cursor.execute("SELECT id FROM outreach WHERE idempotency_key = ?", (idempotency_key,))
            existing = cursor.fetchone()
            return (existing["id"] if existing else 0), False


def update_outreach_status(
    outreach_id: int,
    to_status: str,
    note: Optional[str] = None,
    gmail_message_id: Optional[str] = None,
    db_path: Optional[Path] = None
):
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, contact_email, company_id FROM outreach WHERE id = ?", (outreach_id,))
        row = cursor.fetchone()
        from_status = row["status"] if row else "unknown"

        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [to_status]

        if to_status == "drafted_gmail":
            updates.append("drafted_at = CURRENT_TIMESTAMP")
        elif to_status in ["sent", "sent_detected"]:
            updates.append("sent_at = CURRENT_TIMESTAMP")
            updates.append("followup_due = datetime('now', '+6 days')")
        elif to_status == "replied":
            updates.append("replied_at = CURRENT_TIMESTAMP")

        if gmail_message_id:
            updates.append("gmail_message_id = ?")
            params.append(gmail_message_id)

        params.append(outreach_id)
        cursor.execute(f"UPDATE outreach SET {', '.join(updates)} WHERE id = ?", params)

        # Record status history
        hist_cols = {c[1] for c in cursor.execute("PRAGMA table_info(status_history)").fetchall()}
        if "outreach_id" in hist_cols and "application_id" in hist_cols:
            cursor.execute("""
                INSERT INTO status_history (outreach_id, application_id, from_status, to_status, changed_at, note)
                VALUES (?, NULL, ?, ?, CURRENT_TIMESTAMP, ?)
            """, (outreach_id, from_status, to_status, note))
        elif "outreach_id" in hist_cols:
            cursor.execute("""
                INSERT INTO status_history (outreach_id, from_status, to_status, changed_at, note)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            """, (outreach_id, from_status, to_status, note))
        else:
            cursor.execute("""
                INSERT INTO status_history (application_id, from_status, to_status, changed_at, note)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
            """, (outreach_id, from_status, to_status, note))

        # Update ledgers if sent
        if to_status in ["sent", "sent_detected"] and row:
            clean_email = row["contact_email"]
            comp_id = row["company_id"]
            cursor.execute("""
                INSERT INTO contact_ledger (email, domain, company_id, last_contacted_at, times_contacted, last_outreach_id)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1, ?)
                ON CONFLICT(email) DO UPDATE SET
                    last_contacted_at = CURRENT_TIMESTAMP,
                    times_contacted = contact_ledger.times_contacted + 1,
                    last_outreach_id = excluded.last_outreach_id,
                    updated_at = CURRENT_TIMESTAMP
            """, (clean_email, clean_email.split("@")[-1] if "@" in clean_email else "", comp_id, outreach_id))

            if comp_id:
                cursor.execute("""
                    INSERT INTO company_ledger (company_id, last_contacted_at, total_outreach, cooldown_until)
                    VALUES (?, CURRENT_TIMESTAMP, 1, datetime('now', '+30 days'))
                    ON CONFLICT(company_id) DO UPDATE SET
                        last_contacted_at = CURRENT_TIMESTAMP,
                        total_outreach = company_ledger.total_outreach + 1,
                        cooldown_until = datetime('now', '+30 days'),
                        updated_at = CURRENT_TIMESTAMP
                """, (comp_id,))

        conn.commit()


def save_raw_job(
    run_id: Optional[int],
    source: str,
    external_id: Optional[str],
    url: Optional[str],
    payload_json: str,
    db_path: Optional[Path] = None
) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO raw_jobs (run_id, source, external_id, url, payload_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (run_id, source, external_id, url, payload_json))
        conn.commit()
        return cursor.lastrowid

