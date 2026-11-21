import email
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime, date, timedelta
import logging
from pathlib import Path
import random
import smtplib
import ssl
import time as time_module
from typing import Dict, Any, Optional, Tuple, List
from zoneinfo import ZoneInfo

from jobpilot.core.config import settings
from jobpilot.core.db import (
    get_connection,
    is_email_blocklisted,
    update_application_status,
    log_event
)

logger = logging.getLogger("jobpilot.apply.email_sender")
IST = ZoneInfo("Asia/Kolkata")


def mask_email(email_str: str) -> str:
    if not email_str or "@" not in email_str:
        return email_str
    user, domain = email_str.split("@", 1)
    if len(user) <= 2:
        masked = user[0] + "*"
    else:
        masked = user[0] + "***" + user[-1]
    return f"{masked}@{domain}"


def is_within_sending_hours(now: Optional[datetime] = None) -> Tuple[bool, str]:
    current_dt = now or datetime.now(IST)
    if current_dt.tzinfo is None:
        current_dt = current_dt.replace(tzinfo=IST)
    else:
        current_dt = current_dt.astimezone(IST)

    current_hour = current_dt.hour
    now_str = current_dt.strftime("%H:%M")

    if settings.sending_hours_start <= current_hour < settings.sending_hours_end:
        return True, f"Within sending window ({settings.sending_hours_start}:00 - {settings.sending_hours_end}:00 IST, currently {now_str} IST)"
    else:
        return False, f"Waiting: sending hours are {settings.sending_hours_start}:00 - {settings.sending_hours_end}:00 IST (now {now_str} IST)"


def get_sent_count_today(db_path: Optional[Path] = None) -> int:
    today_str = date.today().isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE status IN ('sent', 'emailed', 'followed_up')
              AND (date(sent_at) = ? OR date(applied_at) = ?)
        """, (today_str, today_str))
        count = cursor.fetchone()[0]
        return count


def is_company_in_cooldown(company: str, db_path: Optional[Path] = None) -> Tuple[bool, Optional[str]]:
    if not company:
        return False, None
    cooldown_cutoff = (datetime.now() - timedelta(days=settings.cooldown_days_per_company)).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.sent_at, j.company
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE LOWER(j.company) = LOWER(?)
              AND a.status IN ('sent', 'emailed')
              AND a.sent_at >= ?
            LIMIT 1
        """, (company.strip(), cooldown_cutoff))
        row = cursor.fetchone()
        if row:
            return True, f"Company '{company}' contacted within last {settings.cooldown_days_per_company} days (sent at {row['sent_at']})"
    return False, None


def send_application_email(
    app_id: int,
    recipient_email: str,
    subject: str,
    body: str,
    pdf_attachment_path: Optional[Path] = None,
    company_name: str = "",
    ignore_hours: bool = False,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Sends cold application email through Gmail SMTP SSL on port 465 with strict guardrails."""
    # 1. Fail-fast check SMTP credentials
    settings.fail_fast_check_smtp()

    # 2. Blocklist check
    if is_email_blocklisted(recipient_email, db_path=db_path):
        msg = f"Email {mask_email(recipient_email)} is blocklisted. Send aborted."
        logger.error(msg)
        return {"success": False, "error": msg, "reason": "blocklisted"}

    # 3. Sending hours check (IST)
    if not ignore_hours:
        in_hours, reason = is_within_sending_hours()
        if not in_hours:
            logger.info("Outside sending hours: %s", reason)
            return {"success": False, "error": reason, "reason": "outside_hours"}

    # 4. Daily cap check
    sent_today = get_sent_count_today(db_path=db_path)
    if sent_today >= settings.daily_send_cap:
        msg = f"Daily send cap ({settings.daily_send_cap}) reached for today ({sent_today} sent). Aborting send."
        logger.warning(msg)
        return {"success": False, "error": msg, "reason": "daily_cap_reached"}

    # 5. Cooldown check
    if company_name:
        in_cool, cool_msg = is_company_in_cooldown(company_name, db_path=db_path)
        if in_cool:
            logger.warning(cool_msg)
            return {"success": False, "error": cool_msg, "reason": "company_cooldown"}

    # 6. Attachment check
    if pdf_attachment_path and not Path(pdf_attachment_path).exists():
        msg = f"Resume PDF not found at {pdf_attachment_path}. Aborting send to prevent unattached outreach."
        logger.error(msg)
        return {"success": False, "error": msg, "reason": "missing_attachment"}

    # 7. Update status to 'sending' before attempting network call
    update_application_status(app_id, "sending", note=f"Attempting SMTP dispatch to {mask_email(recipient_email)}", db_path=db_path)

    # 8. Build RFC 5322 EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = recipient_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg.set_content(body)

    if pdf_attachment_path:
        with open(pdf_attachment_path, "rb") as f:
            file_data = f.read()
            msg.add_attachment(
                file_data,
                maintype="application",
                subtype="pdf",
                filename=Path(pdf_attachment_path).name
            )

    # 9. Dispatch via smtplib SMTP_SSL (port 465)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=25.0) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        now = datetime.now()
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE applications SET
                    status = 'emailed',
                    sent_at = ?,
                    applied_at = ?,
                    recipient_email = ?,
                    updated_at = ?
                WHERE id = ?
            """, (now, now, recipient_email, now, app_id))
            cursor.execute("""
                INSERT INTO status_history (application_id, from_status, to_status, note)
                VALUES (?, 'sending', 'emailed', ?)
            """, (app_id, f"Sent via Gmail SMTP (Message-ID: {msg['Message-ID']})"))
            conn.commit()

        log_event("email.sent", f"Sent application #{app_id} to {mask_email(recipient_email)} at {company_name}", db_path=db_path)
        logger.info("Successfully sent email application #%d to %s", app_id, mask_email(recipient_email))

        return {
            "success": True,
            "message_id": msg["Message-ID"],
            "sent_at": now.isoformat(),
            "recipient": mask_email(recipient_email)
        }

    except Exception as e:
        logger.exception("SMTP dispatch failed for app #%d: %s", app_id, e)
        update_application_status(app_id, "approved", note=f"Send failed: {str(e)}", db_path=db_path)
        log_event("email.failed", f"Failed sending app #{app_id}: {str(e)}", level="ERROR", db_path=db_path)
        return {"success": False, "error": str(e), "reason": "smtp_error"}


def process_approved_queue(limit: int = 5, db_path: Optional[Path] = None, force: bool = False) -> int:
    """Processes pending 'approved' applications only when explicitly triggered.
    If auto_send is false and force is false, halts and keeps all applications in draft."""
    if not settings.auto_send and not force:
        logger.info("Auto-send is disabled in config (auto_send: false). Applications remain drafted.")
        return 0

    in_hours, reason = is_within_sending_hours()
    if not in_hours:
        logger.info("Cannot process approved queue: %s", reason)
        return 0

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.recipient_email, a.email_subject, a.email_body, a.resume_path,
                   j.company, j.recruiter_email as job_email
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.status = 'approved' AND a.route = 'email'
            LIMIT ?
        """, (limit,))
        pending = [dict(r) for r in cursor.fetchall()]

    sent_count = 0
    for app in pending:
        sent_today = get_sent_count_today(db_path=db_path)
        if sent_today >= settings.daily_send_cap:
            logger.info("Daily send cap reached; pausing queue.")
            break

        recipient = app["recipient_email"] or app["job_email"]
        if not recipient:
            continue

        res = send_application_email(
            app_id=app["id"],
            recipient_email=recipient,
            subject=app["email_subject"],
            body=app["email_body"],
            pdf_attachment_path=Path(app["resume_path"]) if app["resume_path"] else None,
            company_name=app["company"],
            db_path=db_path
        )

        if res["success"]:
            sent_count += 1
            # Pacing delay between sends
            delay = random.uniform(settings.send_delay_min_seconds, settings.send_delay_max_seconds)
            logger.info("Pacing next email: waiting %.1fs...", delay)
            time_module.sleep(min(delay, 10.0))  # Capped if testing

    return sent_count


def get_due_followups(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    cutoff = (datetime.now() - timedelta(days=settings.followup_days)).isoformat()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.recipient_email, a.sent_at, j.title, j.company
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.status IN ('emailed', 'sent')
              AND a.followup_sent_at IS NULL
              AND a.sent_at <= ?
        """, (cutoff,))
        return [dict(r) for r in cursor.fetchall()]

