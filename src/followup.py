from datetime import datetime
import logging
from typing import List, Dict, Any, Optional
from src.config import settings
from src.db import (
    get_connection,
    update_application,
    add_to_blocklist,
    log_event
)
from src.llm import generate

logger = logging.getLogger("jobpilot.followup")


def get_due_followups() -> List[Dict[str, Any]]:
    """Returns applications that were sent >= followup_days ago and haven't had a follow-up yet."""
    now_str = datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, j.title, j.company, j.url, c.email as recipient_email
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            LEFT JOIN contacts c ON j.id = c.job_id
            WHERE a.status = 'sent'
            AND a.followup_sent = 0
            AND (a.followup_due IS NOT NULL AND a.followup_due <= ?)
            ORDER BY a.followup_due ASC
        """, (now_str,))
        return [dict(row) for row in cursor.fetchall()]


def generate_followup_draft(
    company: str,
    role: str,
    original_subject: str,
    candidate_name: str
) -> Dict[str, str]:
    """Generates a concise 50-75 word polite check-in draft."""
    prompt = f"""Draft a short, 50-75 word polite follow-up email from a job applicant to a recruiter.
Role: {role}
Company: {company}
Applicant: {candidate_name}

Tone: Courteous, low-pressure, direct.
Do NOT use clichés. Check if they have had a chance to review the application and offer to answer any questions.
Include a closing and candidate contact line.
"""
    body = generate(prompt, json_mode=False)
    if "Hi" not in body and "Hello" not in body:
        body = (
            f"Hi {company} Hiring Team,\n\n"
            f"I wanted to briefly follow up on my application for the {role} position submitted last week. "
            f"I remain very interested in the team's work and would be happy to provide any additional details or work samples.\n\n"
            f"Thank you for your time and consideration.\n\n"
            f"Best regards,\n{candidate_name}"
        )

    clean_subj = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"
    return {
        "subject": clean_subj,
        "body": body.strip()
    }


def mark_as_replied(job_id: str) -> None:
    """Marks application as replied, stopping any automated follow-up."""
    update_application(job_id=job_id, status="replied")
    log_event("followup", f"Application {job_id} marked as replied.")


def opt_out_and_block(job_id: str, email: str, reason: str = "Recruiter requested no further contact") -> None:
    """Adds email to permanent blocklist and updates application to skipped."""
    add_to_blocklist(email=email, reason=reason)
    update_application(job_id=job_id, status="skipped")
    log_event("followup", f"Email {email} permanently added to blocklist. Application {job_id} set to skipped.")

