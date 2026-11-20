import sqlite3
import json
import re
import difflib
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.config import settings
from src.models import Job, Application, RecruiterContact, Company, CompanySignal, CompanyOutreach


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


def clean_company_name_for_matching(name: str) -> str:
    """Strips legal suffixes, punctuation, and whitespace for fuzzy duplicate detection."""
    if not name:
        return ""
    clean = name.lower().strip()
    for suff in COMPANY_LEGAL_SUFFIXES:
        clean = re.sub(suff, '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[^a-z0-9\s]', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean or name.lower().strip()


def are_company_names_similar(name1: str, name2: str, threshold: float = 0.88) -> bool:
    """Fuzzy comparison of two company names."""
    c1 = clean_company_name_for_matching(name1)
    c2 = clean_company_name_for_matching(name2)
    if not c1 or not c2:
        return False
    if c1 == c2:
        return True

    # If both have numeric suffixes that differ (e.g. company0 vs company1), they are distinct
    m1 = re.search(r'\d+$', c1)
    m2 = re.search(r'\d+$', c2)
    if m1 and m2 and m1.group() != m2.group():
        return False

    if len(c1) >= 4 and len(c2) >= 4 and (c1 in c2 or c2 in c1):
        return True
    return difflib.SequenceMatcher(None, c1, c2).ratio() >= threshold


TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "src", "gh_src", "gh_jid", "session",
    "session_id", "sid", "fbclid", "gclid", "trk", "trackingid", "_ga",
    "mc_cid", "mc_eid"
}


def normalize_job_url(raw_url: str) -> str:
    """Normalizes job URLs to avoid duplicate entries due to tracking tags or casing."""
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

        # Filter tracking params
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
    """Normalizes job title for duplicate detection across boards."""
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r'[/\\|\-_]', ' ', t)
    t = re.sub(r'\b(fresher|entry\s+level|junior|trainee|intern|internship|urgent|immediate\s+joiner|full\s+time|remote|hybrid)\b', ' ', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def is_job_duplicate(title: str, company: str, url: str, db_path: Optional[Path] = None) -> bool:
    """Checks if a job already exists in the database by normalized URL or (company + title)."""
    norm_url = normalize_job_url(url)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if norm_url:
            cursor.execute("SELECT id FROM jobs WHERE url = ?", (norm_url,))
            if cursor.fetchone():
                return True

        if title and company:
            clean_comp = clean_company_name_for_matching(company)
            clean_title = clean_job_title_for_dedupe(title)
            if clean_comp and clean_title:
                cursor.execute("SELECT id, title, company FROM jobs")
                for row in cursor.fetchall():
                    existing_comp = clean_company_name_for_matching(row["company"])
                    if existing_comp == clean_comp or are_company_names_similar(company, row["company"]):
                        existing_title = clean_job_title_for_dedupe(row["title"])
                        if existing_title == clean_title:
                            return True
                        if len(clean_title) >= 6 and len(existing_title) >= 6:
                            if clean_title in existing_title or existing_title in clean_title:
                                return True
    return False


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize database tables, indices, and constraints."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Jobs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                posted_date TEXT,
                source TEXT DEFAULT 'manual',
                recruiter_email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Recruiter Contacts table
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

        # Companies table (Company-first Discovery & Speculative Outreach)
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
                size_status TEXT DEFAULT 'unknown', -- confirmed_20plus | likely_20plus | unknown | under_20
                field_tags TEXT,                    -- json: ["computer_vision","llm","document_ai",...]
                field_fit_score REAL DEFAULT 0.0,
                hiring_signal_score REAL DEFAULT 0.0,
                company_score REAL DEFAULT 0.0,
                tier TEXT DEFAULT 'C',              -- A | B | C | excluded
                discovered_via TEXT,
                last_checked TIMESTAMP,
                status TEXT DEFAULT 'new',          -- new, verified, active, not_relevant, excluded
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Company Signals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                signal_type TEXT NOT NULL,          -- field_keyword | open_role | tech_blog | github | funding | team_page | park_directory
                value TEXT NOT NULL,
                source_url TEXT,
                weight REAL DEFAULT 1.0,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)

        # Company Outreach table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS company_outreach (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                contact_id INTEGER,
                mode TEXT DEFAULT 'speculative',    -- job_application | speculative
                resume_path TEXT,
                email_subject TEXT,
                email_body TEXT,
                status TEXT DEFAULT 'drafted',      -- drafted, approved, sending, sent, replied, failed, skipped
                error TEXT,
                smtp_response TEXT,
                message_id TEXT,
                attempted_at TIMESTAMP,
                sent_at TIMESTAMP,
                followup_due TIMESTAMP,
                followup_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)

        # Applications queue & state machine table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                resume_path TEXT,
                tailored_json_path TEXT,
                email_subject TEXT,
                email_body TEXT,
                status TEXT DEFAULT 'new', -- new, matched, drafted, approved, sending, sent, replied, failed, skipped, needs_manual_contact
                match_score REAL DEFAULT 0.0,
                rationale TEXT,
                error TEXT,
                smtp_response TEXT,
                message_id TEXT,
                attempted_at TIMESTAMP,
                sent_at TIMESTAMP,
                followup_due TIMESTAMP,
                followup_sent INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
        """)

        # Migration: ensure rationale, role_tier, and role_lens columns exist
        cursor.execute("PRAGMA table_info(applications);")
        columns = [row[1] for row in cursor.fetchall()]
        if "rationale" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN rationale TEXT;")
        if "role_tier" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN role_tier TEXT;")
        if "role_lens" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN role_lens TEXT;")
        if "layout_warning" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN layout_warning INTEGER DEFAULT 0;")
        if "page_fill" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN page_fill TEXT;")
        if "error" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN error TEXT;")
        if "smtp_response" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN smtp_response TEXT;")
        if "message_id" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN message_id TEXT;")
        if "attempted_at" not in columns:
            cursor.execute("ALTER TABLE applications ADD COLUMN attempted_at TIMESTAMP;")

        # Migration: ensure company_outreach columns exist
        cursor.execute("PRAGMA table_info(company_outreach);")
        co_columns = [row[1] for row in cursor.fetchall()]
        if "error" not in co_columns:
            cursor.execute("ALTER TABLE company_outreach ADD COLUMN error TEXT;")
        if "smtp_response" not in co_columns:
            cursor.execute("ALTER TABLE company_outreach ADD COLUMN smtp_response TEXT;")
        if "message_id" not in co_columns:
            cursor.execute("ALTER TABLE company_outreach ADD COLUMN message_id TEXT;")
        if "attempted_at" not in co_columns:
            cursor.execute("ALTER TABLE company_outreach ADD COLUMN attempted_at TIMESTAMP;")

        # Migration: ensure company_id exists in jobs and contacts
        cursor.execute("PRAGMA table_info(jobs);")
        job_cols = [row[1] for row in cursor.fetchall()]
        if "company_id" not in job_cols:
            cursor.execute("ALTER TABLE jobs ADD COLUMN company_id INTEGER;")

        cursor.execute("PRAGMA table_info(contacts);")
        contact_cols = [row[1] for row in cursor.fetchall()]
        if "company_id" not in contact_cols:
            cursor.execute("ALTER TABLE contacts ADD COLUMN company_id INTEGER;")

        # Blocklist for opt-outs and do-not-contact emails
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Activity and audit logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT DEFAULT 'INFO',
                module TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # LLM response cache to save quota and ensure determinism
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                prompt_hash TEXT PRIMARY KEY,
                response_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Daily LLM Token & Request tracking to prevent quota exhaustion
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

        # Indices for fast lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_followup ON applications(followup_due, followup_sent);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_tier ON companies(tier);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(company_score);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_signals_cid ON company_signals(company_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_outreach_cid ON company_outreach(company_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_company_outreach_status ON company_outreach(status);")

        conn.commit()


# --- Job Operations ---

def save_job(job: Job, db_path: Optional[Path] = None) -> bool:
    """Insert or update a job. Returns True if newly inserted, False if already existed."""
    # Normalize URL to prevent tracking query duplicate URLs
    norm_url = normalize_job_url(job.url)
    job.url = norm_url or job.url

    # Check for duplicate job by URL or (company + title)
    if is_job_duplicate(job.title, job.company, job.url, db_path=db_path):
        return False

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO jobs (id, title, company, location, url, description, posted_date, source, recruiter_email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id, job.title, job.company, job.location, job.url,
                job.description, job.posted_date, job.source, job.recruiter_email
            ))
            # Also create corresponding application row in 'new' status if not exists
            cursor.execute("""
                INSERT OR IGNORE INTO applications (job_id, status)
                VALUES (?, 'new')
            """, (job.id,))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_job(job_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_job_by_url(url: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    norm = normalize_job_url(url)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE url = ? OR url = ?", (norm, url))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_jobs(db_path: Optional[Path] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.*, a.status as app_status, a.match_score
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            ORDER BY j.created_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


# --- Contacts Operations ---

def save_contact(contact: RecruiterContact, db_path: Optional[Path] = None) -> int:
    clean_email = contact.email.lower().strip()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE job_id = ? AND LOWER(email) = ?", (contact.job_id, clean_email))
        existing = cursor.fetchone()
        if existing:
            return existing["id"]

        cursor.execute("""
            INSERT INTO contacts (job_id, email, name, role, source_type, verified, domain_mx_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            contact.job_id, clean_email, contact.name, contact.role,
            contact.source_type, int(contact.verified), int(contact.domain_mx_valid)
        ))
        conn.commit()
        return cursor.lastrowid or 0


def get_contacts_for_job(job_id: str, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE job_id = ? ORDER BY verified DESC, id ASC", (job_id,))
        return [dict(row) for row in cursor.fetchall()]


# --- Applications Operations ---

def update_application(
    job_id: str,
    status: Optional[str] = None,
    match_score: Optional[float] = None,
    rationale: Optional[str] = None,
    role_tier: Optional[str] = None,
    role_lens: Optional[str] = None,
    layout_warning: Optional[bool] = None,
    page_fill: Optional[str] = None,
    resume_path: Optional[str] = None,
    tailored_json_path: Optional[str] = None,
    email_subject: Optional[str] = None,
    email_body: Optional[str] = None,
    error: Optional[str] = None,
    smtp_response: Optional[str] = None,
    message_id: Optional[str] = None,
    attempted_at: Optional[datetime] = None,
    sent_at: Optional[datetime] = None,
    followup_due: Optional[datetime] = None,
    followup_sent: Optional[bool] = None,
    db_path: Optional[Path] = None,
) -> None:
    updates = []
    params = []

    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if match_score is not None:
        updates.append("match_score = ?")
        params.append(match_score)
    if rationale is not None:
        updates.append("rationale = ?")
        params.append(rationale)
    if role_tier is not None:
        updates.append("role_tier = ?")
        params.append(role_tier)
    if role_lens is not None:
        updates.append("role_lens = ?")
        params.append(role_lens)
    if layout_warning is not None:
        updates.append("layout_warning = ?")
        params.append(1 if layout_warning else 0)
    if page_fill is not None:
        updates.append("page_fill = ?")
        params.append(page_fill)
    if resume_path is not None:
        updates.append("resume_path = ?")
        params.append(resume_path)
    if tailored_json_path is not None:
        updates.append("tailored_json_path = ?")
        params.append(tailored_json_path)
    if email_subject is not None:
        updates.append("email_subject = ?")
        params.append(email_subject)
    if email_body is not None:
        updates.append("email_body = ?")
        params.append(email_body)
    if error is not None:
        updates.append("error = ?")
        params.append(error)
    if smtp_response is not None:
        updates.append("smtp_response = ?")
        params.append(smtp_response)
    if message_id is not None:
        updates.append("message_id = ?")
        params.append(message_id)
    if attempted_at is not None:
        updates.append("attempted_at = ?")
        params.append(attempted_at.isoformat() if isinstance(attempted_at, (datetime, date)) else str(attempted_at))
    if sent_at is not None:
        updates.append("sent_at = ?")
        params.append(sent_at.isoformat() if isinstance(sent_at, (datetime, date)) else str(sent_at))
    if followup_due is not None:
        updates.append("followup_due = ?")
        params.append(followup_due.isoformat() if isinstance(followup_due, (datetime, date)) else str(followup_due))
    if followup_sent is not None:
        updates.append("followup_sent = ?")
        params.append(1 if followup_sent else 0)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(job_id)

    query = f"UPDATE applications SET {', '.join(updates)} WHERE job_id = ?"
    with get_connection(db_path) as conn:
        conn.execute(query, params)
        conn.commit()


def get_application(job_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_applications_by_status(status: str, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, j.title, j.company, j.location, j.url, j.recruiter_email, j.description
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.status = ?
            ORDER BY a.match_score DESC, a.created_at DESC
        """, (status,))
        return [dict(row) for row in cursor.fetchall()]


def get_send_logs(limit: int = 50, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Returns combined history of email dispatch attempts across applications and speculative outreach."""
    init_db(db_path)
    query = """
        SELECT * FROM (
            SELECT
                'job_application' as dispatch_type,
                a.id as record_id,
                a.job_id as reference_id,
                j.company as company_name,
                j.title as role_title,
                COALESCE(ct.email, j.recruiter_email, '') as recipient_email,
                a.email_subject as subject,
                a.status as status,
                a.error as error,
                a.smtp_response as smtp_response,
                a.message_id as message_id,
                a.attempted_at as attempted_at,
                a.sent_at as sent_at,
                a.created_at as created_at
            FROM applications a
            LEFT JOIN jobs j ON a.job_id = j.id
            LEFT JOIN contacts ct ON ct.job_id = a.job_id
            WHERE a.status IN ('sending', 'sent', 'failed', 'approved') OR a.attempted_at IS NOT NULL OR a.sent_at IS NOT NULL
            
            UNION ALL
            
            SELECT
                'speculative' as dispatch_type,
                co.id as record_id,
                CAST(co.company_id AS TEXT) as reference_id,
                c.name as company_name,
                'Speculative Outreach' as role_title,
                COALESCE(ct2.email, '') as recipient_email,
                co.email_subject as subject,
                co.status as status,
                co.error as error,
                co.smtp_response as smtp_response,
                co.message_id as message_id,
                co.attempted_at as attempted_at,
                co.sent_at as sent_at,
                co.created_at as created_at
            FROM company_outreach co
            LEFT JOIN companies c ON co.company_id = c.id
            LEFT JOIN contacts ct2 ON co.contact_id = ct2.id
            WHERE co.status IN ('sending', 'sent', 'failed', 'approved') OR co.attempted_at IS NOT NULL OR co.sent_at IS NOT NULL
        )
        ORDER BY COALESCE(attempted_at, sent_at, created_at) DESC
        LIMIT ?
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (limit,))
        return [dict(r) for r in cursor.fetchall()]


def get_sent_count_today(db_path: Optional[Path] = None) -> int:
    today_str = date.today().isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                (SELECT COUNT(*) FROM applications WHERE status IN ('sent', 'replied') AND date(sent_at) = date(?))
                +
                (SELECT COUNT(*) FROM company_outreach WHERE status IN ('sent', 'replied') AND date(sent_at) = date(?))
        """, (today_str, today_str))
        row = cursor.fetchone()
        return row[0] if row else 0


def has_company_or_email_been_contacted_recently(
    company: str,
    email: Optional[str] = None,
    cooldown_days: int = 30,
    db_path: Optional[Path] = None,
) -> bool:
    cutoff = (datetime.now() - timedelta(days=cooldown_days)).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        # 1. Check company cooldown in job applications
        cursor.execute("""
            SELECT COUNT(*) FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE LOWER(j.company) = LOWER(?)
            AND a.sent_at >= ?
        """, (company.strip(), cutoff))
        if cursor.fetchone()[0] > 0:
            return True

        # 2. Check company cooldown in company outreach
        cursor.execute("""
            SELECT COUNT(*) FROM company_outreach co
            JOIN companies c ON co.company_id = c.id
            WHERE LOWER(c.name) = LOWER(?)
            AND co.sent_at >= ?
        """, (company.strip(), cutoff))
        if cursor.fetchone()[0] > 0:
            return True

        # 3. Check recipient email cooldown across jobs & companies
        if email:
            cursor.execute("""
                SELECT COUNT(*) FROM contacts c
                JOIN applications a ON c.job_id = a.job_id
                WHERE LOWER(c.email) = LOWER(?)
                AND a.sent_at >= ?
            """, (email.strip(), cutoff))
            if cursor.fetchone()[0] > 0:
                return True

            cursor.execute("""
                SELECT COUNT(*) FROM contacts c
                JOIN company_outreach co ON c.id = co.contact_id
                WHERE LOWER(c.email) = LOWER(?)
                AND co.sent_at >= ?
            """, (email.strip(), cutoff))
            if cursor.fetchone()[0] > 0:
                return True

    return False


# --- Blocklist Operations ---

def is_blocked(email: str, db_path: Optional[Path] = None) -> bool:
    if not email:
        return False
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM blocklist WHERE LOWER(email) = LOWER(?)", (email.strip(),))
        return cursor.fetchone() is not None


def add_to_blocklist(email: str, reason: str = "User opt-out", db_path: Optional[Path] = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO blocklist (email, reason) VALUES (?, ?)", (email.lower().strip(), reason))
        conn.commit()


# --- LLM Cache Operations ---

def get_cached_llm_response(prompt_hash: str, db_path: Optional[Path] = None) -> Optional[str]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT response_text FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,))
        row = cursor.fetchone()
        return row[0] if row else None


def set_cached_llm_response(prompt_hash: str, response_text: str, db_path: Optional[Path] = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO llm_cache (prompt_hash, response_text) VALUES (?, ?)", (prompt_hash, response_text))
        conn.commit()


# --- LLM Token & Quota Tracking ---

def record_llm_usage(prompt_tokens: int, completion_tokens: int, db_path: Optional[Path] = None) -> None:
    """Records prompt and completion token consumption for the current date."""
    today_str = date.today().isoformat()
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


def get_today_llm_usage(db_path: Optional[Path] = None) -> Dict[str, int]:
    """Returns today's total request count and token usage."""
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
                "request_count": int(row["request_count"]),
                "prompt_tokens": int(row["prompt_tokens"]),
                "completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"])
            }
        return {"request_count": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


# --- Logging Operations ---

def log_event(module: str, message: str, level: str = "INFO", db_path: Optional[Path] = None) -> None:
    try:
        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO logs (level, module, message) VALUES (?, ?, ?)", (level, module, message))
            conn.commit()
    except Exception:
        pass


# --- Company Operations ---

ATS_AND_PLATFORM_DOMAINS = {
    "greenhouse.io", "boards.greenhouse.io", "lever.co", "jobs.lever.co",
    "workable.com", "apply.workable.com", "ashbyhq.com", "jobs.ashbyhq.com",
    "smartrecruiters.com", "technopark.in", "infopark.in", "github.com",
    "duckduckgo.com", "google.com", "linkedin.com", "naukri.com", "indeed.com"
}


def normalize_domain_key(raw_domain: Optional[str]) -> Optional[str]:
    """Strips protocols, www, query params, and trailing slashes for canonical deduplication.
    Rejects generic ATS and job board platforms so they don't overwrite company domain."""
    if not raw_domain:
        return None
    d = raw_domain.lower().strip()
    d = d.split("://")[-1]
    d = d.split("/")[0]
    d = d.split("?")[0]
    d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    if d in ATS_AND_PLATFORM_DOMAINS:
        return None
    return d or None


def find_existing_company(
    name: str,
    domain: Optional[str] = None,
    website: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Finds an existing company by canonical domain, website, exact name, or fuzzy/cleaned name."""
    norm_domain = normalize_domain_key(domain) or normalize_domain_key(website)
    norm_web = normalize_domain_key(website)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 1. Match by canonical domain
        if norm_domain:
            cursor.execute("SELECT * FROM companies WHERE LOWER(domain) = LOWER(?)", (norm_domain,))
            row = cursor.fetchone()
            if row:
                return dict(row)

        # 2. Match by website domain if different
        if norm_web and norm_web != norm_domain:
            cursor.execute("SELECT * FROM companies WHERE LOWER(domain) = LOWER(?)", (norm_web,))
            row = cursor.fetchone()
            if row:
                return dict(row)

        # 3. Match by exact name (case-insensitive)
        if name and name.strip():
            cursor.execute("SELECT * FROM companies WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name.strip(),))
            row = cursor.fetchone()
            if row:
                return dict(row)

        # 4. Match by cleaned/fuzzy company name
        if name and name.strip():
            clean_target = clean_company_name_for_matching(name)
            if clean_target:
                cursor.execute("SELECT * FROM companies")
                for row in cursor.fetchall():
                    row_name = row["name"]
                    if clean_company_name_for_matching(row_name) == clean_target:
                        return dict(row)
                    if are_company_names_similar(name, row_name, threshold=0.85):
                        return dict(row)

    return None


def save_company(company: Company, company_id: Optional[int] = None, db_path: Optional[Path] = None) -> int:
    """Inserts or merges a company record by canonical domain or company name. Returns company id."""
    norm_domain = normalize_domain_key(company.domain) or normalize_domain_key(company.website)
    tags_json = json.dumps(company.field_tags) if company.field_tags else "[]"
    now_str = datetime.now().isoformat()

    existing_row = None
    if company_id:
        existing_row = get_company(company_id, db_path)
    if not existing_row:
        existing_row = find_existing_company(company.name, company.domain, company.website, db_path)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        if existing_row:
            cid = existing_row["id"]
            # Merge discovered_via
            old_via = existing_row.get("discovered_via") or ""
            new_via = company.discovered_via or ""
            merged_via_parts = set([p.strip() for p in (old_via + "," + new_via).split(",") if p.strip()])
            merged_via = ", ".join(sorted(merged_via_parts))

            # Merge field_tags
            old_tags = []
            if existing_row.get("field_tags"):
                try:
                    old_tags = json.loads(existing_row["field_tags"]) if isinstance(existing_row["field_tags"], str) else existing_row["field_tags"]
                except Exception:
                    old_tags = []
            merged_tags = sorted(list(set(old_tags + (company.field_tags or []))))

            # Keep higher confidence size estimation
            old_conf = existing_row.get("size_confidence") or 0.0
            new_conf = company.size_confidence or 0.0
            best_size_status = company.size_status if new_conf >= old_conf else existing_row.get("size_status")
            best_min = company.employee_min if new_conf >= old_conf and company.employee_min else existing_row.get("employee_min")
            best_max = company.employee_max if new_conf >= old_conf and company.employee_max else existing_row.get("employee_max")
            best_est = company.employee_estimate if new_conf >= old_conf and company.employee_estimate else existing_row.get("employee_estimate")
            best_conf = max(old_conf, new_conf)
            best_source = company.size_source if new_conf >= old_conf and company.size_source else existing_row.get("size_source")
            best_evidence = company.size_evidence if new_conf >= old_conf and company.size_evidence else existing_row.get("size_evidence")

            # Determine update domain without colliding with another company
            update_domain = norm_domain or existing_row.get("domain")
            if update_domain:
                cursor.execute("SELECT id FROM companies WHERE LOWER(domain) = LOWER(?) AND id != ?", (update_domain, cid))
                if cursor.fetchone():
                    # Domain already belongs to a different company row; retain existing domain
                    update_domain = existing_row.get("domain")

            cursor.execute("""
                UPDATE companies SET
                    domain = ?,
                    website = COALESCE(?, website),
                    careers_url = COALESCE(?, careers_url),
                    city = COALESCE(?, city),
                    address = COALESCE(?, address),
                    hq_country = COALESCE(?, hq_country),
                    employee_min = ?,
                    employee_max = ?,
                    employee_estimate = ?,
                    size_confidence = ?,
                    size_source = ?,
                    size_evidence = ?,
                    size_status = ?,
                    field_tags = ?,
                    field_fit_score = MAX(COALESCE(field_fit_score, 0.0), ?),
                    hiring_signal_score = MAX(COALESCE(hiring_signal_score, 0.0), ?),
                    company_score = MAX(COALESCE(company_score, 0.0), ?),
                    tier = CASE WHEN ? = 'A' THEN 'A' WHEN tier = 'A' THEN 'A' WHEN ? = 'B' THEN 'B' ELSE tier END,
                    discovered_via = ?,
                    last_checked = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                update_domain,
                company.website,
                company.careers_url,
                company.city,
                company.address,
                company.hq_country,
                best_min,
                best_max,
                best_est,
                best_conf,
                best_source,
                best_evidence,
                best_size_status,
                json.dumps(merged_tags),
                company.field_fit_score,
                company.hiring_signal_score,
                company.company_score,
                company.tier,
                company.tier,
                merged_via,
                now_str,
                cid
            ))
            conn.commit()
            return cid

        # New insert with collision handling
        try:
            cursor.execute("""
                INSERT INTO companies (
                    name, domain, website, careers_url, city, address, hq_country,
                    employee_min, employee_max, employee_estimate, size_confidence,
                    size_source, size_evidence, size_status, field_tags,
                    field_fit_score, hiring_signal_score, company_score, tier,
                    discovered_via, last_checked, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company.name.strip(),
                norm_domain,
                company.website,
                company.careers_url,
                company.city,
                company.address,
                company.hq_country or "India",
                company.employee_min,
                company.employee_max,
                company.employee_estimate,
                company.size_confidence,
                company.size_source,
                company.size_evidence,
                company.size_status or "unknown",
                tags_json,
                company.field_fit_score,
                company.hiring_signal_score,
                company.company_score,
                company.tier or "C",
                company.discovered_via or "manual",
                now_str,
                company.status or "new",
                company.notes
            ))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError as err:
            logger.warning("Collision on inserting company '%s' (domain: %s): %s. Merging into existing record.", company.name, norm_domain, err)
            conflicting_row = None
            if norm_domain:
                cursor.execute("SELECT * FROM companies WHERE LOWER(domain) = LOWER(?)", (norm_domain,))
                r = cursor.fetchone()
                if r:
                    conflicting_row = dict(r)
            if not conflicting_row and company.name:
                cursor.execute("SELECT * FROM companies WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (company.name.strip(),))
                r = cursor.fetchone()
                if r:
                    conflicting_row = dict(r)

            if conflicting_row:
                cid = conflicting_row["id"]
                cursor.execute("""
                    UPDATE companies SET
                        website = COALESCE(?, website),
                        careers_url = COALESCE(?, careers_url),
                        city = COALESCE(?, city),
                        address = COALESCE(?, address),
                        field_fit_score = MAX(COALESCE(field_fit_score, 0.0), ?),
                        hiring_signal_score = MAX(COALESCE(hiring_signal_score, 0.0), ?),
                        company_score = MAX(COALESCE(company_score, 0.0), ?),
                        last_checked = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    company.website,
                    company.careers_url,
                    company.city,
                    company.address,
                    company.field_fit_score,
                    company.hiring_signal_score,
                    company.company_score,
                    now_str,
                    cid
                ))
                conn.commit()
                return cid
            else:
                # Fallback: insert with domain=NULL so record is not lost
                cursor.execute("""
                    INSERT INTO companies (
                        name, domain, website, careers_url, city, address, hq_country,
                        employee_min, employee_max, employee_estimate, size_confidence,
                        size_source, size_evidence, size_status, field_tags,
                        field_fit_score, hiring_signal_score, company_score, tier,
                        discovered_via, last_checked, status, notes
                    ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    company.name.strip(),
                    company.website,
                    company.careers_url,
                    company.city,
                    company.address,
                    company.hq_country or "India",
                    company.employee_min,
                    company.employee_max,
                    company.employee_estimate,
                    company.size_confidence,
                    company.size_source,
                    company.size_evidence,
                    company.size_status or "unknown",
                    tags_json,
                    company.field_fit_score,
                    company.hiring_signal_score,
                    company.company_score,
                    company.tier or "C",
                    company.discovered_via or "manual",
                    now_str,
                    company.status or "new",
                    company.notes
                ))
                conn.commit()
                return cursor.lastrowid


def get_company(company_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("field_tags"):
            try:
                d["field_tags"] = json.loads(d["field_tags"])
            except Exception:
                d["field_tags"] = []
        else:
            d["field_tags"] = []
        return d


def get_company_by_domain(domain: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    norm = normalize_domain_key(domain)
    if not norm:
        return None
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE LOWER(domain) = LOWER(?)", (norm,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("field_tags"):
            try:
                d["field_tags"] = json.loads(d["field_tags"])
            except Exception:
                d["field_tags"] = []
        return d


def get_company_by_name(name: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (name,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("field_tags"):
            try:
                d["field_tags"] = json.loads(d["field_tags"])
            except Exception:
                d["field_tags"] = []
        return d


def list_companies(
    filter_dict: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    filter_dict = filter_dict or {}
    query = "SELECT * FROM companies WHERE 1=1"
    params = []

    if "tier" in filter_dict and filter_dict["tier"]:
        query += " AND tier = ?"
        params.append(filter_dict["tier"])

    if "city" in filter_dict and filter_dict["city"]:
        query += " AND LOWER(city) LIKE ?"
        params.append(f"%{filter_dict['city'].lower()}%")

    if "size_status" in filter_dict and filter_dict["size_status"]:
        query += " AND size_status = ?"
        params.append(filter_dict["size_status"])

    if "status" in filter_dict and filter_dict["status"]:
        query += " AND status = ?"
        params.append(filter_dict["status"])

    if "min_score" in filter_dict and filter_dict["min_score"] is not None:
        query += " AND company_score >= ?"
        params.append(float(filter_dict["min_score"]))

    query += " ORDER BY company_score DESC, id ASC"

    if "limit" in filter_dict and filter_dict["limit"]:
        query += " LIMIT ?"
        params.append(int(filter_dict["limit"]))

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("field_tags"):
                try:
                    d["field_tags"] = json.loads(d["field_tags"])
                except Exception:
                    d["field_tags"] = []
            else:
                d["field_tags"] = []
            result.append(d)
        return result


def update_company(company_id: int, updates: Dict[str, Any], db_path: Optional[Path] = None) -> None:
    if not updates:
        return
    fields = []
    params = []
    for k, v in updates.items():
        if k == "field_tags" and isinstance(v, list):
            fields.append("field_tags = ?")
            params.append(json.dumps(v))
        else:
            fields.append(f"{k} = ?")
            params.append(v)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(company_id)

    query = f"UPDATE companies SET {', '.join(fields)} WHERE id = ?"
    with get_connection(db_path) as conn:
        conn.execute(query, params)
        conn.commit()


def save_company_signal(signal: CompanySignal, db_path: Optional[Path] = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO company_signals (company_id, signal_type, value, source_url, weight)
            VALUES (?, ?, ?, ?, ?)
        """, (
            signal.company_id,
            signal.signal_type,
            signal.value,
            signal.source_url,
            signal.weight
        ))
        conn.commit()
        return cursor.lastrowid


def get_company_signals(company_id: int, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM company_signals WHERE company_id = ? ORDER BY captured_at DESC
        """, (company_id,))
        return [dict(r) for r in cursor.fetchall()]


def save_company_outreach(outreach: CompanyOutreach, db_path: Optional[Path] = None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO company_outreach (
                company_id, contact_id, mode, resume_path, email_subject, email_body,
                status, sent_at, followup_due, followup_sent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            outreach.company_id,
            outreach.contact_id,
            outreach.mode,
            outreach.resume_path,
            outreach.email_subject,
            outreach.email_body,
            outreach.status,
            outreach.sent_at.isoformat() if outreach.sent_at else None,
            outreach.followup_due.isoformat() if outreach.followup_due else None,
            outreach.followup_sent
        ))
        conn.commit()
        return cursor.lastrowid


def get_company_outreach(company_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM company_outreach WHERE company_id = ? ORDER BY id DESC LIMIT 1
        """, (company_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_company_outreach_by_id(outreach_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT co.*, c.name as company_name, c.domain, c.website, c.city,
                   ct.email as contact_email, ct.name as contact_name
            FROM company_outreach co
            JOIN companies c ON co.company_id = c.id
            LEFT JOIN contacts ct ON co.contact_id = ct.id
            WHERE co.id = ?
        """, (outreach_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_company_outreach(outreach_id: int, updates: Dict[str, Any], db_path: Optional[Path] = None) -> None:
    if not updates:
        return
    fields = []
    params = []
    for k, v in updates.items():
        if isinstance(v, (datetime, date)):
            fields.append(f"{k} = ?")
            params.append(v.isoformat())
        else:
            fields.append(f"{k} = ?")
            params.append(v)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(outreach_id)

    query = f"UPDATE company_outreach SET {', '.join(fields)} WHERE id = ?"
    with get_connection(db_path) as conn:
        conn.execute(query, params)
        conn.commit()


def list_company_outreach_by_status(status: Optional[str] = None, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    query = """
        SELECT co.*, c.name as company_name, c.domain, c.website, c.city, c.tier, c.company_score, c.size_status,
               ct.email as contact_email, ct.name as contact_name
        FROM company_outreach co
        JOIN companies c ON co.company_id = c.id
        LEFT JOIN contacts ct ON co.contact_id = ct.id
    """
    params = []
    if status:
        query += " WHERE co.status = ?"
        params.append(status)
    query += " ORDER BY c.company_score DESC, co.created_at DESC"

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_company_contacts(company_id: int, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM contacts WHERE company_id = ? ORDER BY verified DESC, id ASC
        """, (company_id,))
        return [dict(r) for r in cursor.fetchall()]


def save_company_contact(company_id: int, contact: RecruiterContact, db_path: Optional[Path] = None) -> int:
    clean_email = contact.email.lower().strip()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Check if contact email already exists for this company
        cursor.execute("SELECT id FROM contacts WHERE company_id = ? AND LOWER(email) = ?", (company_id, clean_email))
        existing = cursor.fetchone()
        if existing:
            return existing["id"]

        # Ensure a valid job_id exists for the foreign key
        job_id = contact.job_id
        valid_job = False
        if job_id:
            cursor.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,))
            valid_job = cursor.fetchone() is not None

        if not valid_job:
            # Check if this company already has an associated job in jobs
            cursor.execute("SELECT id FROM jobs WHERE company_id = ? LIMIT 1", (company_id,))
            j_row = cursor.fetchone()
            if j_row:
                job_id = j_row["id"]
            else:
                # Create an inquiry profile record in jobs for relational linkage
                cursor.execute("SELECT name, website, city FROM companies WHERE id = ?", (company_id,))
                c_row = cursor.fetchone()
                cname = c_row["name"] if c_row else f"Company_{company_id}"
                cweb = c_row["website"] if c_row and c_row["website"] else f"https://company_{company_id}.com"
                ccity = c_row["city"] if c_row and c_row["city"] else "India"
                job_id = f"company_profile_{company_id}"
                cursor.execute("""
                    INSERT OR IGNORE INTO jobs (id, title, company, location, url, description, source, company_id)
                    VALUES (?, ?, ?, ?, ?, ?, 'company_profile', ?)
                """, (
                    job_id,
                    "General / Speculative Inquiry",
                    cname,
                    ccity,
                    cweb,
                    f"Speculative company profile for {cname}.",
                    company_id
                ))

        cursor.execute("""
            INSERT INTO contacts (job_id, company_id, email, name, role, source_type, verified, domain_mx_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            company_id,
            clean_email,
            contact.name,
            contact.role,
            contact.source_type,
            1 if contact.verified else 0,
            1 if contact.domain_mx_valid else 0
        ))
        conn.commit()
        return cursor.lastrowid


def clear_database(db_path: Optional[Path] = None, keep_cache: bool = True) -> Dict[str, int]:
    """Clears all jobs, applications, contacts, companies, company_signals, company_outreach, and logs."""
    deleted_counts = {}
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")
        tables = [
            "company_outreach",
            "company_signals",
            "applications",
            "contacts",
            "jobs",
            "companies",
            "logs"
        ]
        if not keep_cache:
            tables.extend(["llm_cache", "llm_usage"])

        for tbl in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
                count = cursor.fetchone()[0]
                cursor.execute(f"DELETE FROM {tbl}")
                deleted_counts[tbl] = count
            except sqlite3.OperationalError:
                pass

        try:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('companies', 'company_signals', 'company_outreach', 'applications', 'contacts')")
        except Exception:
            pass

        conn.commit()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("VACUUM;")
        conn.commit()
    return deleted_counts


def backfill_jobs_to_companies(db_path: Optional[Path] = None) -> int:
    """Migrates existing jobs to link to shared company records."""
    init_db(db_path)
    count = 0
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, company, location, url FROM jobs WHERE company_id IS NULL")
        jobs_to_link = cursor.fetchall()

    for j in jobs_to_link:
        jid = j["id"]
        cname = j["company"].strip()
        location = j["location"] or ""
        url = j["url"] or ""

        # Extract domain from job URL if possible
        domain = None
        try:
            from urllib.parse import urlparse
            netloc = urlparse(url).netloc
            if not any(b in netloc for b in ["greenhouse.io", "lever.co", "remotive.com", "ashbyhq.com"]):
                domain = netloc
        except Exception:
            pass

        # City inference
        city = "Bangalore"
        loc_low = location.lower()
        if "trivandrum" in loc_low or "thiruvananthapuram" in loc_low or "technopark" in loc_low:
            city = "Thiruvananthapuram"
        elif "kochi" in loc_low or "cochin" in loc_low or "infopark" in loc_low:
            city = "Kochi"
        elif "kozhikode" in loc_low or "calicut" in loc_low or "cyberpark" in loc_low:
            city = "Kozhikode"
        elif "remote" in loc_low:
            city = "Remote India"

        company = Company(
            name=cname,
            domain=domain,
            city=city,
            discovered_via="jobs_table",
            status="active"
        )
        cid = save_company(company, db_path=db_path)
        with get_connection(db_path) as conn:
            conn.execute("UPDATE jobs SET company_id = ? WHERE id = ?", (cid, jid))
            conn.commit()
        count += 1

    return count

