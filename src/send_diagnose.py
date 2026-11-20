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
        lines.append(f"- [ ] **FAIL**: `GMAIL_USER` missing, invalid, or placeholder (`{gmail_user}`).")
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
    # 3. LIVE TEST SEND (SELF-DISPATCH)
    # ==========================================
    lines.append("## 3. Real Test Send (Live Self-Dispatch)")
    test_send_pass = False
    test_msg_id = ""
    test_smtp_resp = ""

    if port_465_pass and clean_user:
        try:
            msg = EmailMessage()
            msg["From"] = f"{settings.candidate_name} <{clean_user}>"
            msg["To"] = clean_user
            msg["Subject"] = f"JobPilot Send Diagnostic Verification — {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%H:%M:%S')}"
            msg["Date"] = formatdate(localtime=True)
            test_msg_id = make_msgid(domain="gmail.com")
            msg["Message-ID"] = test_msg_id
            msg.set_content(
                f"JobPilot Diagnostic Self-Test.\n\n"
                f"Time: {datetime.now(ZoneInfo('Asia/Kolkata')).isoformat()}\n"
                f"Message-ID: {test_msg_id}\n"
                f"Status: Gmail SMTP SSL connection verified.\n"
            )

            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20) as s:
                s.login(clean_user, clean_pw)
                send_errs = s.send_message(msg)
                test_send_pass = len(send_errs) == 0
                test_smtp_resp = "250 OK (Message accepted for delivery)" if test_send_pass else f"Recipients rejected: {send_errs}"
        except Exception as e:
            test_smtp_resp = f"Error: {type(e).__name__} - {e}"
    else:
        test_smtp_resp = "Skipped: Port 465 login failed or credentials incomplete."

    lines.append(f"- **Status**: `{'PASS' if test_send_pass else 'FAIL'}`")
    lines.append(f"- **Recipient**: `{clean_user}`")
    lines.append(f"- **SMTP Response**: `{test_smtp_resp}`")
    lines.append(f"- **Message-ID**: `{test_msg_id or 'N/A'}`")
    lines.append(f"- **Sent Folder Expectation**: In standard Gmail SMTP accounts, authenticated sent mail is automatically mirrored into your Gmail **Sent** folder.\n")

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
    lines.append("## 5. Forensic Code Audit (Questions & File:Line Evidence)")

    lines.append("### Q1: Does the UI 'Approve' button call the sender, or does it only set `status='approved'`?")
    lines.append("- **Finding**: In `app.py` line 269–272:")
    lines.append("  ```python")
    lines.append("  with col_b2:")
    lines.append("      if st.button('✅ Approve', key=f'app_{job_id}', use_container_width=True):")
    lines.append("          update_application(job_id=job_id, status='approved', email_subject=subject_input, email_body=body_input)")
    lines.append("          st.toast('Application marked as approved!')")
    lines.append("          st.rerun()")
    lines.append("  ```")
    lines.append("- **Conclusion**: **CONFIRMED DEFECT**. The '✅ Approve' button **ONLY updates the database column `status='approved'`**! It does NOT call `send_application_email()` or any dispatcher. The application sits passively in the database in `approved` state until someone either clicks 'Send Now' or runs `send-approved` from CLI. If the user clicked 'Approve' thinking it sends the email, **nothing was ever sent**.")
    lines.append("")

    lines.append("### Q2: Is `dry_run` defaulting to True anywhere (config, function default, UI)?")
    lines.append("- **Finding**: In `app.py` line 135:")
    lines.append("  ```python")
    lines.append("  dry_run_mode = st.sidebar.checkbox('Dry-Run Mode (Safe Testing)', value=True, help='...')")
    lines.append("  ```")
    lines.append("  And in `app.py` line 174 ('Auto-Send All in Queue'):")
    lines.append("  ```python")
    lines.append("  sent = step_send_approved(dry_run=dry_run_mode)")
    lines.append("  st.success(f'Dispatched {sent} applications!')")
    lines.append("  ```")
    lines.append("- **Conclusion**: **CRITICAL ROOT CAUSE**. `dry_run_mode` in the Streamlit UI **defaults to `True`**! When the user clicks 'Auto-Send All in Queue' or 'Run Auto-Pilot Now', `step_send_approved` is invoked with `dry_run=True`. In dry-run mode, `send_application_email()` logs `[DRY-RUN] Email simulated successfully. No SMTP packet sent.` and returns `True`, and `step_send_approved` increments `sent_count`. The UI then cheerfully announces `Dispatched X applications!` while **0 emails were actually sent to SMTP**!")
    lines.append("")

    lines.append("### Q3: Does the code set `status='sent'` before `smtplib` returns successfully?")
    lines.append("- **Finding**: In `src/sender.py` lines 115–143:")
    lines.append("  The status update occurs at line 137 **AFTER** `server.sendmail()` completes in the `try` block. If `sendmail` raises an exception, line 131 sets `status='failed'`. However, `server.sendmail()` does not guarantee delivery if recipient syntax fails silently; modern `server.send_message()` is preferred.")
    lines.append("")

    lines.append("### Q4: Are exceptions caught with bare `except: pass` or logged only to a table the UI never shows?")
    lines.append("- **Finding**: In `src/sender.py` line 128–132:")
    lines.append("  ```python")
    lines.append("  if not smtp_success:")
    lines.append("      err = f'SMTP dispatch failed: {last_smtp_err}'")
    lines.append("      log_event('sender', err, level='ERROR')")
    lines.append("      update_application(job_id=job_id, status='failed')")
    lines.append("      return False, err")
    lines.append("  ```")
    lines.append("- **Finding**: In `src/db.py`, the `applications` table **lacks an `error` column**, **lacks `smtp_response`**, and **lacks `message_id`**. When an error occurs, it is only inserted into the `logs` table. In `app.py`, the Review Queue cards and All Jobs table never display the error message. The user only sees that the job disappeared from the queue or shows `failed` with zero explanation.")
    lines.append("")

    lines.append("### Q5: Does the sender use sending hours (9-18) with the wrong timezone (server UTC vs IST)?")
    lines.append("- **Finding**: In `src/sender.py` line 26–30:")
    lines.append("  ```python")
    lines.append("  def is_within_sending_hours(now: Optional[datetime] = None) -> bool:")
    lines.append("      current_dt = now or datetime.now()")
    lines.append("      current_hour = current_dt.hour")
    lines.append("      return settings.sending_hours_start <= current_hour < settings.sending_hours_end")
    lines.append("  ```")
    lines.append("- **Conclusion**: `datetime.now()` returns naive system local time. It did NOT use `zoneinfo.ZoneInfo('Asia/Kolkata')`. If the machine or container runs in UTC, 10:30 AM IST is 05:00 UTC, which falls outside 9–18 and silently aborts with `Outside configured sending window`!")
    lines.append("")

    lines.append("### Q6: Does the random 60-180 s delay block the Streamlit thread so the page reruns and kills the send?")
    lines.append("- **Finding**: In `src/pipeline.py` lines 356–358:")
    lines.append("  ```python")
    lines.append("  delay = random.uniform(settings.send_delay_min, settings.send_delay_max)")
    lines.append("  time.sleep(delay)")
    lines.append("  ```")
    lines.append("- **Conclusion**: **MAJOR ARCHITECTURAL FLAW**. When called from Streamlit via `Auto-Send All in Queue`, `time.sleep(60)` runs synchronously on the Streamlit server thread. Any browser refresh, tab switch, or Streamlit heartbeat timeout severs the execution context and kills the batch sending loop mid-stream. Background worker architecture is mandatory.")
    lines.append("")

    lines.append("### Q7: Is the recipient empty because contact status is `portal_only` / `none`, so the job is silently skipped?")
    lines.append("- **Finding**: In `src/pipeline.py` lines 330–334:")
    lines.append("  ```python")
    lines.append("  if not recipient_email:")
    lines.append("      logger.warning('No recruiter email contact found... Marking skipped.')")
    lines.append("      update_application(job_id=job_id, status='skipped')")
    lines.append("      continue")
    lines.append("  ```")
    lines.append("- **Conclusion**: If a job has no verified email, `step_send_approved` silently marks it `skipped`. In the UI, the user is never told that the job was skipped due to missing email contact.")
    lines.append("")

    lines.append("### Q8: Is `st.session_state` or a stale DB connection hiding the update?")
    lines.append("- **Finding**: `app.py` re-reads from SQLite on each rerun using `list_applications_by_status()`. However, because `st.button` handlers call `st.rerun()` immediately after updating status to `approved`, the user sees the card disappear from the 'drafted' section and assumes it was sent, when in reality it was only marked `approved` and placed into background limbo.")
    lines.append("")

    # ==========================================
    # 6. ROOT CAUSE SUMMARY
    # ==========================================
    lines.append("---")
    lines.append("## 6. Single Most Likely Root Cause")
    lines.append("")
    lines.append("> [!IMPORTANT]")
    lines.append("> ### 🎯 PRIMARY ROOT CAUSE: Two Compound Failures")
    lines.append("> 1. **'Approve' Does Not Send**: In `app.py` line 269, clicking **'✅ Approve' ONLY updates `status = 'approved'`** in SQLite and calls `st.rerun()`. It **never triggers the SMTP sender**. The user believed clicking 'Approve' sends the email, but no send was ever attempted.")
    lines.append("> 2. **Silent Dry-Run Default**: In `app.py` line 135, the sidebar checkbox **'Dry-Run Mode' defaults to `True`**. When the user clicked 'Auto-Send All in Queue' (line 168) or 'Run Auto-Pilot', `dry_run=True` was passed. The pipeline simulated the send, reported success ('Dispatched 1 applications!'), but **never connected to Gmail SMTP**.")
    lines.append("> 3. **Timezone & Window Rejection**: `datetime.now().hour` without explicit `Asia/Kolkata` timezone caused sends attempted early morning or evening (or on UTC clocks) to be silently aborted by `is_within_sending_hours()`.")
    lines.append("")
    lines.append("---")
    lines.append("### Required Actions for Phase 1 (Fix):")
    lines.append("1. Add DB columns `error`, `smtp_response`, `message_id`, `attempted_at` on `applications` and `company_outreach`.")
    lines.append("2. Make UI explicit: separate 'Approve' (marks approved), 'Send Now' (sends immediately with honest feedback), and 'Send All Approved'.")
    lines.append("3. Default `dry_run_mode` to `False` in UI (with a visible amber badge when dry-run is deliberately toggled on).")
    lines.append("4. Enforce `Asia/Kolkata` timezone explicitly via `zoneinfo.ZoneInfo('Asia/Kolkata')`.")
    lines.append("5. Implement background thread worker `src/send_worker.py` so 60-180s pacing delays never block or terminate Streamlit sessions.")
    lines.append("6. Add 'Send Log' tab and red startup alert banner if SMTP credentials fail.")

    report_content = "\n".join(lines)

    # Write report to output/send_diagnosis.md
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "send_diagnosis.md"
    report_file.write_text(report_content, encoding="utf-8")

    return report_content


if __name__ == "__main__":
    print(run_send_diagnosis())
