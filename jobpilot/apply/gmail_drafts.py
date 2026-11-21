import email
import re
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
import imaplib
import json
import logging
from pathlib import Path
import time
from typing import Dict, Any, Optional, List, Tuple

from jobpilot.core.config import settings
from jobpilot.core.db import (
    get_connection,
    is_email_blocklisted,
    update_application_status,
    save_tailored_application,
    log_event,
    start_run,
    finish_run
)
from jobpilot.core.events import event_broadcaster
from jobpilot.core.models import Job, MasterResume
from jobpilot.pipeline.prescreen import prescreen_job
from jobpilot.pipeline.match import evaluate_job_match
from jobpilot.tailor.resume_tailor import tailor_resume_for_job
from jobpilot.tailor.pdf_builder import generate_tailored_pdf
from jobpilot.tailor.email_writer import generate_tailored_email
from jobpilot.apply.email_sender import is_company_in_cooldown

logger = logging.getLogger("jobpilot.apply.gmail_drafts")


def sanitize_email(email_str: str) -> Optional[str]:
    """Extracts clean RFC email address, discarding image extensions or trailing garbage."""
    if not email_str:
        return None
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', email_str)
    if match:
        clean = match.group(0).lower().rstrip('.')
        if clean.endswith(('.jpg', '.png', '.jpeg', '.gif', '.webp')):
            # Strip trailing extension if attached to an email domain
            clean = re.sub(r'\.(jpg|png|jpeg|gif|webp)$', '', clean)
        return clean
    return None


def get_gmail_drafts_folder(mail: imaplib.IMAP4_SSL) -> str:
    """Finds the canonical Gmail Drafts folder name, handling non-English locales if needed."""
    try:
        status, folders = mail.list()
        if status == "OK":
            for f in folders:
                f_str = f.decode("utf-8", errors="ignore")
                if r"\Drafts" in f_str:
                    parts = f_str.split(' "/" ')
                    if len(parts) == 2:
                        return parts[1].strip()
    except Exception as e:
        logger.warning("Could not auto-detect Drafts folder, defaulting to '[Gmail]/Drafts': %s", e)
    return '"[Gmail]/Drafts"'


def save_draft_to_gmail(
    recipient_email: str,
    subject: str,
    body: str,
    pdf_attachment_path: Optional[Path] = None,
    mail_client: Optional[imaplib.IMAP4_SSL] = None
) -> Dict[str, Any]:
    """
    Connects to Gmail via IMAP SSL (993) and appends a formatted email message
    directly to the user's Gmail Drafts folder with the '\\Draft' flag.
    Does NOT send any email.
    """
    user_email = settings.smtp_user or settings.user_email
    user_password = settings.smtp_password

    if not user_email or not user_password:
        return {
            "success": False,
            "error": "Gmail credentials (GMAIL_USER & GMAIL_APP_PASSWORD) not configured in .env"
        }

    own_connection = False
    mail = mail_client
    try:
        if mail is None:
            own_connection = True
            mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
            mail.login(user_email, user_password)

        drafts_folder = get_gmail_drafts_folder(mail)

        # Build MIME Message
        msg = EmailMessage()
        msg["From"] = user_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        msg["X-Unsent"] = "1"
        msg.set_content(body)

        # Attach 2-page tailored PDF if provided
        if pdf_attachment_path and Path(pdf_attachment_path).exists():
            with open(pdf_attachment_path, "rb") as f:
                pdf_data = f.read()
            filename = Path(pdf_attachment_path).name
            msg.add_attachment(
                pdf_data,
                maintype="application",
                subtype="pdf",
                filename=filename
            )

        # Append to Drafts folder with \Draft flag
        now_time = time.time()
        res_status, res_data = mail.append(
            drafts_folder,
            r"(\Draft)",
            imaplib.Time2Internaldate(now_time),
            msg.as_bytes()
        )

        if res_status != "OK":
            return {
                "success": False,
                "error": f"IMAP append to {drafts_folder} returned: {res_status} {res_data}"
            }

        return {
            "success": True,
            "draft_folder": drafts_folder,
            "recipient": recipient_email,
            "subject": subject
        }

    except Exception as e:
        logger.error("Failed to append draft to Gmail: %s", e)
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        if own_connection and mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def draft_all_qualified_jobs_to_gmail(
    min_score: float = 75.0,
    max_jobs: int = 50
) -> Dict[str, Any]:
    """
    1-Click Automation:
    1. Finds all unapplied jobs with verified HR email and match_score >= min_score (default 75).
    2. Tailors exact 2-page resume & builds PDF.
    3. Generates humble cold email with mandatory opt-out.
    4. Appends each drafted message directly into candidate's Gmail Drafts dashboard via IMAP.
    5. Updates application records to status 'drafted_gmail' for pipeline tracking.
    """
    user_email = settings.smtp_user or settings.user_email
    user_password = settings.smtp_password

    if not user_email or not user_password:
        return {
            "success": False,
            "error": "Gmail credentials (GMAIL_USER & GMAIL_APP_PASSWORD) not configured in .env",
            "drafted_count": 0,
            "jobs": []
        }

    run_id = start_run(run_type="gmail_drafts_batch")
    event_broadcaster.broadcast_sync("gmail_drafting_started", {"min_score": min_score, "run_id": run_id})

    # Load master resume skills
    master_skills = set()
    try:
        with open(settings.master_resume_path, "r", encoding="utf-8") as f:
            m_data = json.load(f)
        for cat_skills in m_data.get("skills", {}).values():
            for s in cat_skills:
                master_skills.add(s.lower())
    except Exception as e:
        logger.error("Failed to load master resume skills: %s", e)

    # 1. Fetch eligible jobs from DB
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.id, j.title, j.company, j.location, j.description, j.apply_url, j.url,
                   j.apply_kind, j.recruiter_email, a.id as application_id, a.status as app_status,
                   a.match_score, a.resume_path, a.email_subject, a.email_body
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            WHERE j.recruiter_email IS NOT NULL AND j.recruiter_email != ''
              AND (a.status IS NULL OR a.status IN ('new', 'drafted', 'skipped'))
            ORDER BY j.created_at DESC
        """)
        candidates = [dict(r) for r in cursor.fetchall()]

    # Connect to IMAP once for batch efficiency
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
        mail.login(user_email, user_password)
    except Exception as e:
        finish_run(run_id, status="failed", counts={}, error=f"IMAP login failed: {e}")
        return {
            "success": False,
            "error": f"Failed connecting to Gmail IMAP: {e}",
            "drafted_count": 0,
            "jobs": []
        }

    drafted_jobs = []
    skipped_count = 0

    try:
        for job_dict in candidates:
            if len(drafted_jobs) >= max_jobs:
                break

            title = job_dict.get("title", "")
            desc = job_dict.get("description", "")
            company = job_dict.get("company", "")
            raw_email = job_dict.get("recruiter_email", "").strip()
            recruiter_email = sanitize_email(raw_email)
            if not recruiter_email or "@" not in recruiter_email:
                continue

            # Safeguard: Blocklist check
            if is_email_blocklisted(recruiter_email):
                continue

            # Safeguard: Cooldown check
            in_cooldown, _ = is_company_in_cooldown(company)
            if in_cooldown:
                continue

            # Pre-screen experience/seniority
            ps = prescreen_job(title, desc)
            if not ps["eligible"]:
                continue

            # Evaluate role tier & match score
            match_res = evaluate_job_match(title, desc, master_skills)
            if match_res.role_tier == "reject" or match_res.match_score < min_score:
                skipped_count += 1
                continue

            logger.info("Drafting to Gmail: %s at %s (Score: %.1f)", title, company, match_res.match_score)

            # Reconstruct Job model
            job_obj = Job(
                id=job_dict["id"],
                title=title,
                company=company,
                location=job_dict.get("location", "Bangalore"),
                description=desc,
                url=job_dict.get("url") or job_dict.get("apply_url") or "",
                apply_url=job_dict.get("apply_url"),
                apply_kind="email",
                source="aggregator",
                recruiter_email=recruiter_email
            )

            # 1. Tailor Resume
            tailored = tailor_resume_for_job(job_obj)

            # 2. Build 2-Page PDF
            pdf_path, fill_ratio = generate_tailored_pdf(tailored, job_obj.id, job_obj.company)

            # 3. Generate Humble Cold Email
            email_sub, email_bod, email_tone = generate_tailored_email(job_obj, tailored)

            # 4. Save to Gmail Drafts folder
            draft_res = save_draft_to_gmail(
                recipient_email=recruiter_email,
                subject=email_sub,
                body=email_bod,
                pdf_attachment_path=Path(pdf_path) if pdf_path else None,
                mail_client=mail
            )

            if not draft_res["success"]:
                logger.error("Failed drafting %s to Gmail: %s", job_obj.company, draft_res.get("error"))
                continue

            # 5. Persist to SQLite
            tailored_json_path = str(settings.resume_output_dir / f"tailored_{job_obj.id}.json")
            with open(tailored_json_path, "w", encoding="utf-8") as f:
                json.dump(tailored.model_dump(), f, indent=2, default=str)

            app_id = save_tailored_application(
                job_id=job_obj.id,
                match_score=tailored.match_score or match_res.match_score,
                resume_path=pdf_path,
                tailored_json_path=tailored_json_path,
                role_lens=tailored.lens or match_res.role_lens,
                role_tier=tailored.target_tier or match_res.role_tier,
                rationale=f"Auto-drafted to Gmail (Score: {tailored.match_score or match_res.match_score:.1f}%). 2-page fit: {fill_ratio*100:.1f}%.",
                route="email",
                email_subject=email_sub,
                email_body=email_bod,
                cover_note=f"Application for {title} at {company}",
                tone_score=email_tone
            )

            # Update status to drafted_gmail
            update_application_status(
                app_id,
                to_status="drafted_gmail",
                note=f"Saved directly to Gmail Drafts folder for {recruiter_email}"
            )

            # Log to applications recipient_email
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("UPDATE applications SET recipient_email = ? WHERE id = ?", (recruiter_email, app_id))
                conn.commit()

            drafted_jobs.append({
                "job_id": job_obj.id,
                "application_id": app_id,
                "title": title,
                "company": company,
                "recruiter_email": recruiter_email,
                "match_score": tailored.match_score or match_res.match_score,
                "subject": email_sub
            })

            event_broadcaster.broadcast_sync("gmail_draft_created", {
                "company": company,
                "title": title,
                "recipient": recruiter_email,
                "count": len(drafted_jobs)
            })

            # Polite pacing between IMAP appends
            time.sleep(1.0)

        finish_run(
            run_id,
            status="success",
            counts={"drafted_to_gmail": len(drafted_jobs), "skipped": skipped_count}
        )

        return {
            "success": True,
            "drafted_count": len(drafted_jobs),
            "skipped_count": skipped_count,
            "jobs": drafted_jobs
        }

    except Exception as e:
        logger.error("Error during batch Gmail drafting: %s", e)
        finish_run(run_id, status="failed", counts={"drafted_to_gmail": len(drafted_jobs)}, error=str(e))
        return {
            "success": False,
            "error": str(e),
            "drafted_count": len(drafted_jobs),
            "jobs": drafted_jobs
        }
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
