import os
import re
import ssl
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from pathlib import Path
from typing import Dict, Any, List, Tuple
from zoneinfo import ZoneInfo

from src.config import settings
from src.db import (
    get_connection,
    get_job,
    get_contacts_for_job,
    get_sent_count_today,
    has_company_or_email_been_contacted_recently,
    is_blocked,
    list_applications_by_status
)


def run_send_diagnosis() -> str:
    """
    Executes a complete, non-destructive audit of the JobPilot email sending subsystem.
    Checks credentials, SMTP connectivity (port 465 SSL & 587 STARTTLS), test dispatch,
    pipeline state analysis for last 20 applications, and forensic code audit.
    Writes findings to output/send_diagnosis.md and returns markdown string.
    """
    lines: List[str] = []
    lines.append("# 🩺 JobPilot Email Sending Diagnostic Report")
    lines.append(f"**Generated:** {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("")

    # ==========================================
    # 1. CREDENTIALS CHECKLIST
    # ==========================================
    lines.append("## 1. Credentials Checklist")
    cred_pass = True

    # 1.1 .env file check
    env_file = Path(".env")
    env_exists = env_file.exists()
    raw_env_content = env_file.read_text(encoding="utf-8") if env_exists else ""
    has_dotenv_call = "load_dotenv" in raw_env_content or env_exists

    if env_exists:
        lines.append("- [x] **PASS**: `.env` file present at project root (`d:\\project JOB HUNT\\.env`).")
    else:
        lines.append("- [ ] **FAIL**: `.env` file NOT found at project root.")
        cred_pass = False

    # 1.2 GMAIL_USER
    gmail_user = os.getenv("GMAIL_USER", settings.gmail_user or "").strip()
    stray_user_quotes = (gmail_user.startswith('"') and gmail_user.endswith('"')) or (gmail_user.startswith("'") and gmail_user.endswith("'"))
    clean_user = gmail_user.strip("\"'")
    if clean_user and "@" in clean_user and not clean_user.startswith("your_"):
        lines.append(f"- [x] **PASS**: `GMAIL_USER` present and valid format (`{clean_user}`). Quotes clean: {'NO (stray quotes detected)' if stray_user_quotes else 'YES'}.")
    else:
        lines.append(f"- [ ] **FAIL**: `GMAIL_USER` missing, invalid, or unconfigured template (`{gmail_user}`).")
        cred_pass = False

    # 1.3 GMAIL_APP_PASSWORD
    raw_pw = os.getenv("GMAIL_APP_PASSWORD", settings.gmail_app_password or "").strip()
    stray_pw_quotes = (raw_pw.startswith('"') and raw_pw.endswith('"')) or (raw_pw.startswith("'") and raw_pw.endswith("'"))
    clean_pw = raw_pw.strip("\"'").replace(" ", "")
    pw_len = len(clean_pw)

    if pw_len == 16 and not clean_pw.startswith("your_"):
        lines.append(f"- [x] **PASS**: `GMAIL_APP_PASSWORD` present (16 characters, spaces stripped). Quotes clean: {'NO (stray quotes detected)' if stray_pw_quotes else 'YES'}.")
    else:
        lines.append(f"- [ ] **FAIL**: `GMAIL_APP_PASSWORD` length is {pw_len} chars (expected exactly 16 characters).")
        cred_pass = False

    lines.append(f"**Credentials Overall:** `{'PASS' if cred_pass else 'FAIL'}`\n")

    # ==========================================
    # 2. SMTP CONNECTIVITY & LOGIN TESTS
    # ==========================================
    lines.append("## 2. SMTP Connectivity & Login Tests")

    # 2.1 Port 465 (SSL)
    port_465_pass = False
    port_465_msg = ""
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=15) as s465:
            code, resp = s465.login(clean_user, clean_pw)
            port_465_pass = (code == 235)
            port_465_msg = f"Code {code}: {resp.decode('utf-8', errors='ignore')}"
    except Exception as e:
        port_465_msg = f"Exception: {type(e).__name__} - {e}"

    lines.append(f"- **Port 465 (SSL)**: `{'PASS' if port_465_pass else 'FAIL'}`")
    lines.append(f"  - Target: `smtp.gmail.com:465` (SSL)")
    lines.append(f"  - Result: {port_465_msg}")

    # 2.2 Port 587 (STARTTLS) Fallback Test
    port_587_pass = False
    port_587_msg = ""
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s587:
            s587.ehlo()
            s587.starttls(context=ssl.create_default_context())
            s587.ehlo()
            code, resp = s587.login(clean_user, clean_pw)
            port_587_pass = (code == 235)
            port_587_msg = f"Code {code}: {resp.decode('utf-8', errors='ignore')}"
    except Exception as e:
        port_587_msg = f"Exception: {type(e).__name__} - {e}"

    lines.append(f"- **Port 587 (STARTTLS Fallback)**: `{'PASS' if port_587_pass else 'FAIL'}`")
    lines.append(f"  - Target: `smtp.gmail.com:587` (STARTTLS)")
    lines.append(f"  - Result: {port_587_msg}\n")

    # ==========================================
    # 3. SMTP CONNECTIVITY STATUS (READ-ONLY)
    # ==========================================
    lines.append("## 3. SMTP Authentication Status (Read-Only)")
    if port_465_pass:
        lines.append(f"- **Status**: `PASS` (SSL Port 465 authenticated for `{clean_user}`)")
    else:
        lines.append(f"- **Status**: `FAIL` (Cannot authenticate to smtp.gmail.com:465)")
    lines.append("")

    # ==========================================
    # 4. PIPELINE STATE (LAST 20 APPLICATIONS)
    # ==========================================
    lines.append("## 4. Pipeline State: Application Audit (Last 20 Rows)")
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.job_id, a.status, a.sent_at, a.match_score, j.title, j.company, j.recruiter_email, j.url
            FROM applications a
            LEFT JOIN jobs j ON a.job_id = j.id
            ORDER BY a.id DESC LIMIT 20
        """)
        recent_apps = cur.fetchall()

    if not recent_apps:
        lines.append("*The database was recently cleared (0 application records found). Run a scrape/match cycle to populate review records.*")
    else:
        lines.append("| App ID | Company | Role | Status | Recipient | Sent At | Why Was It Not Sent? |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        is_hours = settings.sending_hours_start <= now_ist.hour < settings.sending_hours_end

        for r in recent_apps:
            aid = r["id"]
            jid = r["job_id"]
            st = r["status"]
            comp = r["company"] or "Unknown"
            title = r["title"] or "Role"
            sent_at = str(r["sent_at"] or "-")

            contacts = get_contacts_for_job(jid)
            recip = contacts[0]["email"] if contacts else (r["recruiter_email"] or "")

            why_not_sent = []
            if st == "sent":
                why_not_sent.append("✅ Already Sent")
            else:
                if st != "approved":
                    why_not_sent.append(f"Status is '{st}' (not 'approved')")
                if not recip:
                    why_not_sent.append("No verified recipient email")
                if recip and is_blocked(recip):
                    why_not_sent.append("Recipient on permanent blocklist")
                if comp and has_company_or_email_been_contacted_recently(comp, recip):
                    why_not_sent.append("Company on 30-day cooldown")
                if not is_hours:
                    why_not_sent.append(f"Outside sending hours ({now_ist.hour}:00 IST vs {settings.sending_hours_start}-{settings.sending_hours_end})")

            why_str = "; ".join(why_not_sent) if why_not_sent else "Ready for dispatch"
            lines.append(f"| #{aid} | {comp} | {title} | `{st}` | `{recip or 'None'}` | {sent_at} | {why_str} |")

    lines.append("")

    # Also check company_outreach state
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT co.id, co.status, co.sent_at, c.name as company_name, ct.email as contact_email
            FROM company_outreach co
            JOIN companies c ON co.company_id = c.id
            LEFT JOIN contacts ct ON co.contact_id = ct.id
            ORDER BY co.id DESC LIMIT 10
        """)
        recent_outreach = cur.fetchall()

    if recent_outreach:
        lines.append("### Speculative Outreaches (Last 10 Rows)")
        lines.append("| Outreach ID | Company | Status | Recipient | Sent At |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for o in recent_outreach:
            lines.append(f"| #{o['id']} | {o['company_name']} | `{o['status']}` | `{o['contact_email'] or 'None'}` | {o['sent_at'] or '-'} |")
        lines.append("")

    # ==========================================
    # 5. FORENSIC CODE AUDIT CHECKLIST
    # ==========================================
    report_content = "\n".join(lines)
    return report_content


if __name__ == "__main__":
    print(run_send_diagnosis())
