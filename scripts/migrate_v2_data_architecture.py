import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jobpilot.migration")

DB_PATH = Path("data/jobpilot.db")


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower().strip()
    # Strip location / remote tags in parentheses or after dashes
    t = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', t)
    t = re.sub(r'\s*-\s*(remote|bangalore|kochi|trivandrum|thiruvananthapuram|calicut|kozhikode|india).*$', '', t)
    # Seniority and standard abbreviations
    t = re.sub(r'\bartificial\s+intelligence\b', 'ai', t)
    t = re.sub(r'\bmachine\s+learning\b', 'ml', t)
    t = re.sub(r'\bsr\.?\b', 'senior', t)
    t = re.sub(r'\bjr\.?\b', 'junior', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_city(city: str) -> str:
    if not city:
        return "remote"
    c = city.lower().strip()
    if any(k in c for k in ["bangalore", "bengaluru"]):
        return "bangalore"
    if any(k in c for k in ["trivandrum", "thiruvananthapuram"]):
        return "thiruvananthapuram"
    if any(k in c for k in ["kochi", "cochin", "ernakulam"]):
        return "kochi"
    if any(k in c for k in ["kozhikode", "calicut"]):
        return "kozhikode"
    if "remote" in c:
        return "remote"
    return re.sub(r'\s+', ' ', c)


def normalize_company(company: str) -> str:
    if not company:
        return ""
    c = company.lower().strip()
    c = re.sub(r'\b(pvt|ltd|limited|private|inc|corp|technologies|solutions|services|infotech|software)\b', '', c)
    c = re.sub(r'[\(\)\.,\-\_]', ' ', c)
    return re.sub(r'\s+', ' ', c).strip()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        clean_scheme = parsed.scheme.lower() or "https"
        clean_netloc = parsed.netloc.lower()
        # Filter out tracking query params
        keep_params = []
        tracking_keys = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "ref", "source", "fbclid", "gclid", "msclkid", "origin"
        }
        for k, v in parse_qsl(parsed.query, keep_blank_values=False):
            if k.lower() not in tracking_keys:
                keep_params.append((k, v))
        clean_query = urlencode(sorted(keep_params))
        clean_path = parsed.path.rstrip('/')
        return urlunparse((clean_scheme, clean_netloc, clean_path, "", clean_query, ""))
    except Exception:
        return url.strip().lower()


def compute_description_hash(desc: str) -> str:
    if not desc:
        return ""
    clean = re.sub(r'\s+', ' ', desc.lower().strip())[:1500]
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def compute_canonical_key(company_norm: str, title_norm: str, city_norm: str) -> str:
    raw = f"{company_norm}|{title_norm}|{city_norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_idempotency_key(contact_email: str, company_id: any, canonical_key_or_spec: str, version: str = "v2") -> str:
    c_email = contact_email.lower().strip()
    comp = str(company_id or "0")
    raw = f"{c_email}|{comp}|{canonical_key_or_spec}|{version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_migration(db_path: Path = DB_PATH):
    logger.info("Starting Data Architecture Migration on %s", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Create raw_jobs
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

    # 2. Add new columns to jobs if they don't exist
    cursor.execute("PRAGMA table_info(jobs)")
    existing_job_cols = {r["name"] for r in cursor.fetchall()}

    for col, col_type in [
        ("title_norm", "TEXT"),
        ("city_norm", "TEXT"),
        ("apply_url_canon", "TEXT"),
        ("description_hash", "TEXT"),
    ]:
        if col not in existing_job_cols:
            logger.info("Adding column %s to jobs table", col)
            cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")

    # 3. Create outreach table
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

    # 4. Create contact_ledger
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

    # 5. Create company_ledger
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

    # 6. Create llm_budget & llm_calls
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

    # 7. Update status_history table if needed
    cursor.execute("PRAGMA table_info(status_history)")
    existing_hist_cols = {r["name"] for r in cursor.fetchall()}
    if "outreach_id" not in existing_hist_cols:
        cursor.execute("ALTER TABLE status_history ADD COLUMN outreach_id INTEGER")

    conn.commit()
    logger.info("All new tables and columns created successfully.")

    # 8. Backfill normalization and canonical keys on jobs table
    cursor.execute("SELECT id, title, company, location, url, apply_url, description FROM jobs")
    all_jobs = cursor.fetchall()

    logger.info("Backfilling normalization for %d jobs...", len(all_jobs))
    for j in all_jobs:
        t_norm = normalize_title(j["title"])
        comp_norm = normalize_company(j["company"])
        city_norm = normalize_city(j["location"])
        apply_canon = canonicalize_url(j["apply_url"] or j["url"])
        desc_hash = compute_description_hash(j["description"])
        canon_key = compute_canonical_key(comp_norm, t_norm, city_norm)

        cursor.execute("""
            UPDATE jobs
            SET title_norm = ?, city_norm = ?, apply_url_canon = ?, description_hash = ?, canonical_key = ?
            WHERE id = ?
        """, (t_norm, city_norm, apply_canon, desc_hash, canon_key, j["id"]))

    # Enforce UNIQUE index on canonical_key
    # Deduplicate any collision first if multiple rows share the same canonical_key
    cursor.execute("SELECT canonical_key, COUNT(*) as cnt FROM jobs GROUP BY canonical_key HAVING cnt > 1")
    collisions = cursor.fetchall()
    if collisions:
        logger.info("Found %d canonical_key collisions. Merging...", len(collisions))
        for col in collisions:
            c_key = col["canonical_key"]
            cursor.execute("SELECT id FROM jobs WHERE canonical_key = ? ORDER BY created_at ASC", (c_key,))
            dup_ids = [r["id"] for r in cursor.fetchall()]
            keep_id = dup_ids[0]
            remove_ids = dup_ids[1:]
            for rem_id in remove_ids:
                # Merge sources and applications
                cursor.execute("UPDATE job_sources SET job_id = ? WHERE job_id = ?", (keep_id, rem_id))
                cursor.execute("UPDATE applications SET job_id = ? WHERE job_id = ?", (keep_id, rem_id))
                cursor.execute("DELETE FROM jobs WHERE id = ?", (rem_id,))
    
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_key);")

    # 9. Clean up and dedupe job_sources before adding unique index
    cursor.execute("""
        UPDATE job_sources
        SET external_id = job_id
        WHERE external_id IS NULL OR external_id = ''
    """)
    # Delete any duplicate (source, external_id)
    cursor.execute("""
        DELETE FROM job_sources
        WHERE id NOT IN (
            SELECT MIN(id) FROM job_sources GROUP BY source, external_id
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_sources_src_ext ON job_sources(source, external_id);")

    # 10. Backfill outreach table from existing applications
    cursor.execute("""
        SELECT a.*, j.company_id as job_comp_id, j.canonical_key, j.company as job_company
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        WHERE a.recipient_email IS NOT NULL AND a.recipient_email != ''
    """)
    email_apps = cursor.fetchall()
    logger.info("Backfilling %d email applications into outreach table...", len(email_apps))

    migrated_outreach = 0
    for a in email_apps:
        rec_email = a["recipient_email"].lower().strip()
        comp_id = a["job_comp_id"] or 0
        c_key = a["canonical_key"] or a["job_id"]
        idemp = compute_idempotency_key(rec_email, comp_id, c_key)

        status = a["status"] or "new"
        # Map old statuses to new clean state machine
        if status in ["drafted", "drafted_gmail"]:
            outreach_status = "drafted_gmail"
        elif status in ["sent", "emailed"]:
            outreach_status = "sent_detected"
        elif status in ["replied", "interview"]:
            outreach_status = "replied"
        elif status in ["rejected", "skipped"]:
            outreach_status = "closed"
        else:
            outreach_status = "queued"

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO outreach (
                    job_id, company_id, contact_email, mode, idempotency_key,
                    score, score_basis, status, resume_path, email_subject, email_body,
                    gmail_message_id, drafted_at, sent_at, replied_at, followup_due,
                    followup_sent, created_at, updated_at
                ) VALUES (?, ?, ?, 'job_application', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                a["job_id"], comp_id, rec_email, idemp,
                a["match_score"] or 0.0, "rules+llm" if a["match_score"] else "rules",
                outreach_status, a["resume_path"], a["email_subject"], a["email_body"],
                a["message_id"],
                a["created_at"] if outreach_status == "drafted_gmail" else None,
                a["sent_at"], a["updated_at"] if outreach_status == "replied" else None,
                a["followup_due"], a["followup_sent_at"],
                a["created_at"], a["updated_at"]
            ))
            if cursor.rowcount > 0:
                migrated_outreach += 1
        except Exception as e:
            logger.warning("Could not backfill application %s to outreach: %s", a["id"], e)

    # 11. Seed contact_ledger from outreach, contacts, and blocklist
    cursor.execute("SELECT contact_email, company_id, sent_at, created_at, status, id FROM outreach")
    outreach_records = cursor.fetchall()
    logger.info("Seeding contact_ledger from %d outreach entries...", len(outreach_records))

    for o in outreach_records:
        email_str = o["contact_email"]
        domain = email_str.split("@")[-1] if "@" in email_str else ""
        c_at = o["sent_at"] or o["created_at"]
        was_sent = o["status"] in ["sent_detected", "replied"]

        cursor.execute("""
            INSERT INTO contact_ledger (
                email, domain, company_id, first_contacted_at, last_contacted_at,
                times_contacted, last_outreach_id, opted_out, bounced
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            ON CONFLICT(email) DO UPDATE SET
                last_contacted_at = COALESCE(excluded.last_contacted_at, contact_ledger.last_contacted_at),
                times_contacted = contact_ledger.times_contacted + excluded.times_contacted,
                last_outreach_id = excluded.last_outreach_id,
                updated_at = CURRENT_TIMESTAMP
        """, (
            email_str, domain, o["company_id"], c_at, c_at,
            1 if was_sent else 0, o["id"]
        ))

    # Mark blocklisted emails as opted_out in contact_ledger
    cursor.execute("SELECT email FROM blocklist")
    for row in cursor.fetchall():
        b_email = row["email"].lower().strip()
        cursor.execute("""
            INSERT INTO contact_ledger (email, opted_out, updated_at)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(email) DO UPDATE SET opted_out = 1, updated_at = CURRENT_TIMESTAMP
        """, (b_email,))

    # 12. Seed company_ledger from outreach and companies
    cursor.execute("SELECT company_id, sent_at, created_at, status FROM outreach WHERE company_id IS NOT NULL AND company_id != 0")
    for o in cursor.fetchall():
        comp_id = o["company_id"]
        c_at = o["sent_at"] or o["created_at"]
        was_sent = o["status"] in ["sent_detected", "replied"]
        cooldown = None
        if c_at and was_sent:
            try:
                dt = datetime.fromisoformat(c_at[:19])
                cooldown = (dt + timedelta(days=30)).isoformat()
            except Exception:
                pass

        cursor.execute("""
            INSERT INTO company_ledger (
                company_id, last_contacted_at, total_outreach, cooldown_until
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                last_contacted_at = COALESCE(excluded.last_contacted_at, company_ledger.last_contacted_at),
                total_outreach = company_ledger.total_outreach + excluded.total_outreach,
                cooldown_until = COALESCE(excluded.cooldown_until, company_ledger.cooldown_until),
                updated_at = CURRENT_TIMESTAMP
        """, (
            comp_id, c_at, 1 if was_sent else 0, cooldown
        ))

    conn.commit()
    conn.close()
    logger.info("Step 1 Data Architecture Migration COMPLETED.")


if __name__ == "__main__":
    run_migration()
