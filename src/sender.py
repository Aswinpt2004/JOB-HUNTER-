import email
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime, timedelta
import logging
from pathlib import Path
import random
import smtplib
import ssl
import time as time_module
from typing import Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo

from src.config import settings
from src.db import (
    get_connection,
    get_sent_count_today,
    has_company_or_email_been_contacted_recently,
    is_blocked,
    update_application,
    update_company_outreach,
    get_company_outreach_by_id,
    log_event
)

logger = logging.getLogger("jobpilot.sender")
IST = ZoneInfo("Asia/Kolkata")


def mask_email(email_str: str) -> str:
    """Masks email for safe logging (e.g. aswinpt2004@gmail.com -> a***4@gmail.com)."""
    if not email_str or "@" not in email_str:
        return email_str
    user, domain = email_str.split("@", 1)
    if len(user) <= 2:
        masked = user[0] + "*"
    else:
        masked = user[0] + "***" + user[-1]
    return f"{masked}@{domain}"


def is_within_sending_hours(now: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Checks if current time falls within configured sending window in IST (Asia/Kolkata).
    Default: 09:00 - 18:00 IST.
    Returns (is_allowed, explanation_message).
    """
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


def send_application_email(
    job_id: str,
    recipient_email: str,
    subject: str,
    body: str,
    pdf_attachment_path: Optional[Path] = None,
    company_name: str = "",
    ignore_hours: bool = False
) -> Tuple[bool, str]:
    """
    Sends an approved job application email via Gmail SMTP with strict honesty and guardrails:
    - Sets status to 'sending' before attempting dispatch
    - Blocklist check
    - Daily cap check (default: 15)
    - 30-day cooldown per company and recipient
    - Permitted sending hours window (Asia/Kolkata IST)
    - Constructs RFC-compliant EmailMessage with Message-ID and Date
    - Dispatches via smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
    - Retries transient failures up to 2 times; halts immediately on auth errors (535)
    - Sets status='sent' ONLY after server.send_message() succeeds
    - Persists error, smtp_response, message_id, attempted_at, sent_at
    """
    now_ist = datetime.now(IST)
    recipient_clean = recipient_email.strip().lower()

    # Set status='sending' and record attempted_at
    update_application(
        job_id=job_id,
        status="sending",
        attempted_at=now_ist,
        error=None
    )

    # 1. Guardrail: Blocklist check
    if is_blocked(recipient_clean):
        msg = f"Aborted: Recipient '{recipient_clean}' is on the blocklist."
        logger.warning(msg)
        log_event("sender", msg, level="WARNING")
        update_application(job_id=job_id, status="failed", error=msg)
        return False, msg

    # 2. Guardrail: Daily Cap
    sent_today = get_sent_count_today()
    if sent_today >= settings.daily_cap:
        msg = f"Waiting: Daily sending cap of {settings.daily_cap} reached for today ({sent_today} sent)."
        logger.warning(msg)
        log_event("sender", msg, level="WARNING")
        update_application(job_id=job_id, status="approved", error=msg)
        return False, msg

    # 3. Guardrail: 30-Day Cooldown
    if has_company_or_email_been_contacted_recently(company=company_name, email=recipient_clean, cooldown_days=settings.cooldown_days_per_company):
        msg = f"Waiting: Company '{company_name}' or email '{recipient_clean}' contacted within last {settings.cooldown_days_per_company} days."
        logger.warning(msg)
        log_event("sender", msg, level="WARNING")
        update_application(job_id=job_id, status="approved", error=msg)
        return False, msg

    # 4. Guardrail: Sending Hours (Asia/Kolkata)
    in_window, window_msg = is_within_sending_hours(now_ist)
    if not ignore_hours and not in_window:
        logger.warning(window_msg)
        update_application(job_id=job_id, status="approved", error=window_msg)
        return False, window_msg

    # 5. Check Gmail credentials
    gmail_user = settings.gmail_user.strip()
    gmail_app_pw = settings.gmail_app_password.strip().replace(" ", "")
    if not gmail_user or not gmail_app_pw or gmail_user.startswith("your_") or gmail_app_pw.startswith("your_"):
        err = "Credentials error: GMAIL_USER and GMAIL_APP_PASSWORD must be configured in .env."
        logger.error(err)
        log_event("sender", err, level="ERROR")
        update_application(job_id=job_id, status="failed", error=err)
        return False, err

    # 7. Construct RFC-compliant EmailMessage
    msg = EmailMessage()
    msg["From"] = f"{settings.candidate_name} <{gmail_user}>"
    msg["To"] = recipient_clean
    msg["Reply-To"] = settings.candidate_email or gmail_user
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg_id = make_msgid(domain="gmail.com")
    msg["Message-ID"] = msg_id
    msg.set_content(body)

    if pdf_attachment_path and Path(pdf_attachment_path).exists():
        pdf_file = Path(pdf_attachment_path)
        with open(pdf_file, "rb") as f:
            pdf_bytes = f.read()
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_file.name
        )

    # 8. Dispatch via Gmail SMTP SSL with retry
    smtp_success = False
    last_smtp_err = ""
    smtp_code_resp = ""

    for attempt in range(2):
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
                server.login(gmail_user, gmail_app_pw)
                send_errs = server.send_message(msg)
                if send_errs:
                    last_smtp_err = f"Recipients rejected: {send_errs}"
                    break
                smtp_success = True
                smtp_code_resp = "250 OK (Message accepted for delivery)"
                break
        except smtplib.SMTPAuthenticationError as auth_err:
            last_smtp_err = f"App Password invalid or 2-Step Verification off (SMTPAuthenticationError 535): {auth_err}"
            logger.error("Auth failure on SMTP: %s", last_smtp_err)
            # Do NOT retry auth errors
            break
        except Exception as e:
            last_smtp_err = f"{type(e).__name__}: {e}"
            logger.warning("SMTP attempt %d failed: %s", attempt + 1, last_smtp_err)
            if attempt == 0:
                time_module.sleep(3.0)

    if not smtp_success:
        err = f"SMTP dispatch failed: {last_smtp_err}"
        log_event("sender", err, level="ERROR")
        update_application(
            job_id=job_id,
            status="failed",
            error=last_smtp_err,
            smtp_response="FAILED"
        )
        return False, err

    # 9. Mark application as sent ONLY after send_message() succeeds
    sent_time = datetime.now(IST)
    followup_date = sent_time + timedelta(days=settings.followup_days)
    update_application(
        job_id=job_id,
        status="sent",
        sent_at=sent_time,
        followup_due=followup_date,
        followup_sent=False,
        error=None,
        smtp_response=smtp_code_resp,
        message_id=msg_id
    )

    success_msg = f"Email sent successfully to {recipient_clean} for job {job_id} (Message-ID: {msg_id})."
    log_event("sender", success_msg)
    logger.info(success_msg)
    return True, success_msg


def send_company_outreach_email(
    outreach_id: int,
    ignore_hours: bool = False
) -> Tuple[bool, str]:
    """
    Sends an approved speculative outreach email to a company with:
    - Sets status to 'sending' before attempting dispatch
    - Blocklist check
    - Daily cap check (shared)
    - 30-day cooldown check (shared)
    - Permitted sending hours window (Asia/Kolkata IST)
    - RFC-compliant EmailMessage with Message-ID and PDF attachment
    - smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
    - Sets status='sent' ONLY after server.send_message() succeeds
    """
    now_ist = datetime.now(IST)
    outreach = get_company_outreach_by_id(outreach_id)
    if not outreach:
        return False, f"Outreach record #{outreach_id} not found."

    company_name = outreach.get("company_name", "Target Company")
    recipient_email = (outreach.get("contact_email") or "").strip().lower()
    if not recipient_email:
        err = f"No recipient email found for outreach #{outreach_id} ({company_name})."
        update_company_outreach(outreach_id, {"status": "failed", "error": err})
        return False, err

    # Set status='sending'
    update_company_outreach(outreach_id, {
        "status": "sending",
        "attempted_at": now_ist,
        "error": None
    })

    # 1. Blocklist check
    if is_blocked(recipient_email):
        msg = f"Aborted: Recipient '{recipient_email}' is on the blocklist."
        log_event("sender", msg, level="WARNING")
        update_company_outreach(outreach_id, {"status": "failed", "error": msg})
        return False, msg

    # 2. Daily Cap check (shared)
    sent_today = get_sent_count_today()
    if sent_today >= settings.daily_cap:
        msg = f"Waiting: Daily sending cap of {settings.daily_cap} reached for today ({sent_today} sent)."
        log_event("sender", msg, level="WARNING")
        update_company_outreach(outreach_id, {"status": "approved", "error": msg})
        return False, msg

    # 3. 30-Day Cooldown
    if has_company_or_email_been_contacted_recently(company=company_name, email=recipient_email, cooldown_days=settings.cooldown_days_per_company):
        msg = f"Waiting: Company '{company_name}' or email '{recipient_email}' contacted within last {settings.cooldown_days_per_company} days."
        log_event("sender", msg, level="WARNING")
        update_company_outreach(outreach_id, {"status": "approved", "error": msg})
        return False, msg

    # 4. Sending hours (Asia/Kolkata)
    in_window, window_msg = is_within_sending_hours(now_ist)
    if not ignore_hours and not in_window:
        logger.warning(window_msg)
        update_company_outreach(outreach_id, {"status": "approved", "error": window_msg})
        return False, window_msg

    # 5. Credentials
    gmail_user = settings.gmail_user.strip()
    gmail_app_pw = settings.gmail_app_password.strip().replace(" ", "")
    if not gmail_user or not gmail_app_pw or gmail_user.startswith("your_"):
        err = "Credentials error: GMAIL_USER and GMAIL_APP_PASSWORD must be configured in .env."
        update_company_outreach(outreach_id, {"status": "failed", "error": err})
        return False, err

    # 7. Construct EmailMessage
    msg = EmailMessage()
    msg["From"] = f"{settings.candidate_name} <{gmail_user}>"
    msg["To"] = recipient_email
    msg["Reply-To"] = settings.candidate_email or gmail_user
    msg["Subject"] = outreach.get("email_subject") or f"Fresher AI/ML Engineer Profile - {settings.candidate_name}"
    msg["Date"] = formatdate(localtime=True)
    msg_id = make_msgid(domain="gmail.com")
    msg["Message-ID"] = msg_id
    msg.set_content(outreach.get("email_body") or "")

    pdf_path_str = outreach.get("resume_path")
    if pdf_path_str and Path(pdf_path_str).exists():
        pdf_file = Path(pdf_path_str)
        with open(pdf_file, "rb") as f:
            pdf_bytes = f.read()
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_file.name
        )

    # 8. SMTP Dispatch with retry
    smtp_success = False
    last_smtp_err = ""
    smtp_code_resp = ""

    for attempt in range(2):
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as server:
                server.login(gmail_user, gmail_app_pw)
                send_errs = server.send_message(msg)
                if send_errs:
                    last_smtp_err = f"Recipients rejected: {send_errs}"
                    break
                smtp_success = True
                smtp_code_resp = "250 OK (Message accepted for delivery)"
                break
        except smtplib.SMTPAuthenticationError as auth_err:
            last_smtp_err = f"App Password invalid or 2-Step Verification off (SMTPAuthenticationError 535): {auth_err}"
            logger.error("Auth failure on SMTP: %s", last_smtp_err)
            break
        except Exception as e:
            last_smtp_err = f"{type(e).__name__}: {e}"
            logger.warning("SMTP attempt %d failed: %s", attempt + 1, last_smtp_err)
            if attempt == 0:
                time_module.sleep(3.0)

    if not smtp_success:
        err = f"SMTP dispatch failed: {last_smtp_err}"
        log_event("sender", err, level="ERROR")
        update_company_outreach(outreach_id, {
            "status": "failed",
            "error": last_smtp_err,
            "smtp_response": "FAILED"
        })
        return False, err

    # 9. Mark status='sent'
    sent_time = datetime.now(IST)
    followup_date = sent_time + timedelta(days=settings.followup_days)
    update_company_outreach(outreach_id, {
        "status": "sent",
        "sent_at": sent_time,
        "followup_due": followup_date,
        "followup_sent": 0,
        "error": None,
        "smtp_response": smtp_code_resp,
        "message_id": msg_id
    })

    success_msg = f"Speculative email sent successfully to {recipient_email} at {company_name} (Message-ID: {msg_id})."
    log_event("sender", success_msg)
    logger.info(success_msg)
    return True, success_msg


def check_smtp_health() -> Tuple[bool, str]:
    """
    Non-destructive health check that verifies Gmail SMTP connection and authentication.
    Returns (True, success_message) or (False, error_message).
    """
    gmail_user = (settings.gmail_user or "").strip()
    gmail_app_pw = (settings.gmail_app_password or "").strip().replace(" ", "")
    if not gmail_user or not gmail_app_pw or gmail_user.startswith("your_"):
        return False, "GMAIL_USER or GMAIL_APP_PASSWORD is not configured in .env."
    if len(gmail_app_pw) != 16:
        return False, f"GMAIL_APP_PASSWORD length is {len(gmail_app_pw)} chars (expected exactly 16 chars)."

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=10) as server:
            code, resp = server.login(gmail_user, gmail_app_pw)
            if code == 235:
                return True, f"Gmail SMTP SSL connected and authenticated as {mask_email(gmail_user)}."
            return False, f"SMTP returned status {code}: {resp.decode('utf-8', errors='ignore')}"
    except Exception as e:
        return False, f"SMTP Connection/Auth Error: {e}"

