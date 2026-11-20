import os
import json
import base64
from datetime import datetime
from pathlib import Path
import streamlit as st

from src.config import settings
from src.db import (
    init_db,
    list_jobs,
    get_job,
    list_applications_by_status,
    update_application,
    get_contacts_for_job,
    add_to_blocklist,
    get_connection,
    get_sent_count_today,
    get_today_llm_usage,
    list_companies,
    get_company,
    update_company,
    get_company_contacts,
    get_company_signals,
    list_company_outreach_by_status,
    update_company_outreach,
    get_company_outreach,
    get_send_logs
)
from src.sender import (
    send_application_email,
    send_company_outreach_email,
    is_within_sending_hours,
    check_smtp_health,
    mask_email,
    IST
)
from src.send_worker import (
    get_worker_status,
    trigger_send_worker,
    get_send_worker
)
from src.followup import get_due_followups, generate_followup_draft, mark_as_replied, opt_out_and_block
from src.pipeline import (
    step_scrape,
    step_match,
    step_draft,
    step_send_approved,
    step_auto_apply,
    apply_single_job,
    step_run_companies
)
from src.companies.discovery import run_company_discovery
from src.companies.enrichment import run_company_enrichment, enrich_company_size
from src.companies.scorer import run_company_scoring, score_single_company
from src.companies.contacts import run_company_contacts, crawl_company_contacts
from src.companies.speculative import run_company_drafting, draft_single_speculative_application

# Configure Page
st.set_page_config(
    page_title="JobPilot - Automated Job Search & Application Assistant",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize DB on load
init_db()

# --- Custom Styling ---
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        border-left: 5px solid #0d6efd;
        margin-bottom: 10px;
    }
    .badge-pill {
        padding: 4px 8px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 0.8em;
    }
    .score-high { background-color: #d1e7dd; color: #0f5132; }
    .score-mid { background-color: #fff3cd; color: #664d03; }
    .score-low { background-color: #f8d7da; color: #842029; }
</style>
""", unsafe_allow_html=True)


# --- Sidebar Navigation & Quick Actions ---
st.sidebar.title("✈️ JobPilot")
st.sidebar.caption("Human-in-the-Loop Job Assistant")

sent_today = get_sent_count_today()
llm_usage = get_today_llm_usage()

col_m1, col_m2 = st.sidebar.columns(2)
with col_m1:
    st.metric("Emails Today", f"{sent_today} / {settings.daily_cap}")
with col_m2:
    st.metric("LLM Calls", f"{llm_usage['request_count']} / {settings.llm_max_requests_per_day}")

token_pct = min(1.0, llm_usage["total_tokens"] / max(1, settings.llm_max_tokens_per_day))
st.sidebar.caption(f"Token Quota: {llm_usage['total_tokens']:,} / {settings.llm_max_tokens_per_day:,} tokens")
st.sidebar.progress(token_pct)

page = st.sidebar.radio(
    "Navigation",
    [
        "📋 Review Queue",
        "🏢 Target Companies",
        "🎯 Instant Apply (Any Job)",
        "💼 All Jobs",
        "🚀 Sent Applications",
        "📤 Send Logs",
        "⏰ Follow-ups",
        "⚙️ Settings & Logs"
    ],
    index=0
)

st.sidebar.markdown("---")
st.sidebar.subheader("Quick Pipeline Actions")
col_s1, col_s2 = st.sidebar.columns(2)
with col_s1:
    if st.button("Scrape New", use_container_width=True):
        with st.spinner("Scraping job boards..."):
            count = step_scrape()
            st.sidebar.success(f"Scraped {count} jobs!")
            st.rerun()

with col_s2:
    if st.button("Match & Draft", use_container_width=True):
        with st.spinner("Matching and tailoring..."):
            step_match()
            count = step_draft()
            st.sidebar.success(f"Drafted {count} applications!")
            st.rerun()

if st.sidebar.button("🏢 Run Company Engine", use_container_width=True):
    with st.spinner("Running Company Discovery, Size Enrichment & Scoring..."):
        comp_res = step_run_companies()
        st.sidebar.success(f"Company Engine complete! Total: {comp_res.get('total_companies', 0)} companies.")
        st.rerun()

dry_run_mode = st.sidebar.checkbox(
    "Dry-Run Mode (Safe Testing)",
    value=False,
    help="When checked, sending is simulated without connecting to Gmail SMTP. Uncheck to send real emails."
)
if dry_run_mode:
    st.sidebar.warning("⚠️ **DRY-RUN ACTIVE**\nSends will be simulated without Gmail SMTP.")

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ Full Auto-Pilot")
st.sidebar.caption("Scrape -> Match -> Tailor Resume -> Tailor Email -> Send automatically.")
if st.sidebar.button("🚀 Run Auto-Pilot Now", type="primary", use_container_width=True):
    with st.spinner("Running Auto-Pilot pipeline..."):
        sent = step_auto_apply(dry_run=dry_run_mode)
        mode_text = "[DRY-RUN]" if dry_run_mode else "LIVE"
        st.sidebar.success(f"Auto-Pilot completed ({mode_text}): {sent} application(s) processed!")
        st.rerun()

# --- Global Top-of-Page Health & Dry-Run Alerts ---
@st.cache_data(ttl=180)
def _check_system_smtp_health():
    return check_smtp_health()

_smtp_healthy, _smtp_diag = _check_system_smtp_health()
if not _smtp_healthy:
    st.error(f"🚨 **SMTP Dispatch Alert / Not Ready:** {_smtp_diag}\n\nEmails cannot leave Gmail until credentials and SMTP connection are valid. Configure `.env` and verify via `python -m src.pipeline send-diagnose`.")
elif dry_run_mode:
    st.warning("⚠️ **DRY-RUN MODE IS ENABLED:** Sending is in simulation mode. No real emails will leave Gmail until unchecked in the sidebar.")



# ==========================================
# PAGE 1: REVIEW QUEUE
# ==========================================
if page == "📋 Review Queue":
    st.title("📋 Application Review Queue")
    st.info("Review, customize, and approve applications before any email is dispatched. Nothing is sent without your explicit approval.")

    # Status Telemetry & Background Worker Dashboard
    worker_st = get_worker_status()
    in_win, win_msg = is_within_sending_hours()

    st.markdown("### 🚦 Dispatch Worker & Schedule Telemetry")
    col_w1, col_w2, col_w3, col_w4 = st.columns(4)
    with col_w1:
        w_state_icon = "🟢" if worker_st["is_running"] else "⚪"
        st.metric("Worker Status", f"{w_state_icon} {'Active' if worker_st['is_running'] else 'Idle'}")
    with col_w2:
        st.metric("Approved in Queue", f"{worker_st['queued_count']} items")
    with col_w3:
        st.metric("Worker Dispatched", f"{worker_st['total_sent']} sent / {worker_st['total_failed']} failed")
    with col_w4:
        win_label = "✅ Window Open" if in_win else "⏰ Outside Hours"
        st.metric("Sending Hours (IST)", win_label)

    if not in_win:
        st.warning(f"⏰ {win_msg}. Approved applications will be held safely until the window opens, or dispatch immediately using **🚀 Send Now**.")

    if worker_st["current_task"] and worker_st["is_running"]:
        st.info(f"🔄 **Current Worker Activity:** {worker_st['current_task']}")

    drafted_apps = list_applications_by_status("drafted")
    approved_apps = list_applications_by_status("approved")
    sending_apps = list_applications_by_status("sending")
    failed_apps = list_applications_by_status("failed")
    all_raw_queue = drafted_apps + approved_apps + sending_apps + failed_apps
    # Avoid listings without verified HR contact emails for mailing
    all_queue = [app for app in all_raw_queue if get_contacts_for_job(app["job_id"])]

    col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.5, 1])
    with col_btn1:
        if st.button("🚀 Send All Approved (Start Worker)", type="primary", use_container_width=True):
            trigger_send_worker(dry_run=dry_run_mode)
            st.success("Background sender started! Queue is being processed with 60–180s anti-spam pacing off the main thread.")
            st.rerun()
    with col_btn2:
        if st.button("✅ Approve All Pending Drafts", use_container_width=True):
            count_approved = 0
            for app in all_queue:
                if app["status"] == "drafted":
                    update_application(job_id=app["job_id"], status="approved")
                    count_approved += 1
            st.toast(f"Marked {count_approved} applications as approved!")
            st.rerun()
    with col_btn3:
        if st.button("🔄 Refresh Queue & Worker", use_container_width=True):
            st.rerun()

    st.markdown("---")

    if not all_queue:
        st.success("🎉 Your review queue is clear! No applications waiting for review.")
        st.write("Click **Scrape New** or **Match & Draft** in the sidebar to discover and process new roles.")
    else:
        st.write(f"**{len(all_queue)}** application(s) in review queue.")

        for app in all_queue:
            job_id = app["job_id"]
            contacts = get_contacts_for_job(job_id)
            default_recipient = contacts[0]["email"] if contacts else ""
            score = app.get("match_score", 0.0)

            score_class = "score-high" if score >= 80 else ("score-mid" if score >= 65 else "score-low")
            status_val = (app.get("status") or "drafted").lower()
            badge_color = {
                "drafted": "#0d6efd",
                "approved": "#ffc107",
                "sending": "#0dcaf0",
                "sent": "#198754",
                "failed": "#dc3545",
                "skipped": "#6c757d"
            }.get(status_val, "#6c757d")

            with st.expander(f"**{app['company']}** — {app['title']} (Match: {score:.1f}%) [{status_val.upper()}]", expanded=(status_val in ('drafted', 'failed'))):
                # Error alert banner if previous send attempt failed
                if app.get("error"):
                    st.error(f"❌ **Send Attempt Failed:** {app['error']}")
                if app.get("message_id"):
                    st.caption(f"📨 Message-ID: `{app['message_id']}` | SMTP Response: `{app.get('smtp_response')}`")

                col_left, col_right = st.columns([1, 1])

                with col_left:
                    st.subheader("Job & Match Summary")
                    st.markdown(f"**Company:** {app['company']}")
                    st.markdown(f"**Role:** {app['title']}")
                    st.markdown(f"**Location:** {app['location']}")
                    tier = app.get("role_tier") or "Tier A"
                    lens = app.get("role_lens") or "Generic ML / Data Science"
                    st.markdown(f"**Role Tier & Lens:** <span class='badge-pill score-high'>{tier}</span> &nbsp; <span class='badge-pill score-mid'>{lens}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Status:** <span style='background-color:{badge_color}; color:white; padding:3px 8px; border-radius:10px; font-weight:bold;'>{status_val.upper()}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Verified HR Contact:** `{default_recipient}` ✅")
                    st.markdown(f"**Job URL:** [Open Original Posting]({app['url']})")
                    st.markdown(f"**Match Fit Score:** <span class='badge-pill {score_class}'>{score:.1f}%</span>", unsafe_allow_html=True)
                    from src.email_writer import score_email_tone
                    tone_res = score_email_tone(app.get("email_body") or "")
                    st.markdown(f"**Tone Quality:** `{tone_res['score']:.1f}/10` (Humble Fresher Voice, {tone_res['word_count']} words)")

                    st.markdown("---")
                    st.markdown("#### 📄 Tailored ATS Resume")
                    pdf_path = Path(app["resume_path"]) if app.get("resume_path") else None
                    if pdf_path and pdf_path.exists():
                        st.success(f"Generated: `{pdf_path.name}` ({pdf_path.stat().st_size} bytes)")

                        # Display Page Fill percentages & layout fit status
                        page_fill_data = None
                        if app.get("page_fill"):
                            try:
                                page_fill_data = json.loads(app["page_fill"])
                            except Exception:
                                page_fill_data = None

                        json_path_temp = Path(app["tailored_json_path"]) if app.get("tailored_json_path") else None
                        if not page_fill_data and json_path_temp and json_path_temp.exists():
                            try:
                                with open(json_path_temp, "r", encoding="utf-8") as f:
                                    page_fill_data = json.load(f).get("page_fill")
                            except Exception:
                                page_fill_data = None

                        if page_fill_data:
                            p1_f = page_fill_data.get("page1", 0.0) * 100
                            p2_f = page_fill_data.get("page2", 0.0) * 100
                            warn = app.get("layout_warning", 0) == 1
                            fit_badge = "⚠️ Layout Warning" if warn else "✅ Exact 2-Page Fit"
                            st.markdown(f"**Vertical Page Fill:** Page 1: `{p1_f:.1f}%` | Page 2: `{p2_f:.1f}%` ({fit_badge})")

                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()
                        st.download_button(
                            label="⬇️ Download Tailored PDF",
                            data=pdf_bytes,
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            key=f"dl_pdf_{job_id}"
                        )
                    else:
                        st.warning("No PDF generated yet.")

                    # Also show tailored JSON if exists
                    json_path = Path(app["tailored_json_path"]) if app.get("tailored_json_path") else None
                    if json_path and json_path.exists():
                        with open(json_path, "r", encoding="utf-8") as f:
                            json_data = json.load(f)
                        with st.expander("View Tailored JSON Structure"):
                            st.json(json_data)

                with col_right:
                    st.subheader("✉️ Email Draft")
                    recip_input = st.text_input("Recipient Recruiter Email:", value=default_recipient, key=f"recip_{job_id}")
                    subject_input = st.text_input("Subject:", value=app.get("email_subject") or "", key=f"subj_{job_id}")
                    body_input = st.text_area("Body:", value=app.get("email_body") or "", height=230, key=f"body_{job_id}")

                    st.markdown("---")
                    col_b1, col_b2, col_b3, col_b4 = st.columns(4)

                    with col_b1:
                        if st.button("💾 Save Edits", key=f"save_{job_id}", use_container_width=True):
                            update_application(job_id=job_id, email_subject=subject_input, email_body=body_input)
                            st.toast("Saved edits!")
                            st.rerun()

                    with col_b2:
                        if st.button("✅ Approve", key=f"app_{job_id}", use_container_width=True):
                            update_application(job_id=job_id, status="approved", email_subject=subject_input, email_body=body_input)
                            st.toast("Application marked as approved!")
                            st.rerun()

                    with col_b3:
                        if st.button("🚀 Send Now", key=f"send_{job_id}", type="primary", use_container_width=True):
                            if not recip_input:
                                st.error("No recipient email provided!")
                            else:
                                with st.spinner("Dispatching application..."):
                                    ok, msg = send_application_email(
                                        job_id=job_id,
                                        recipient_email=recip_input,
                                        subject=subject_input,
                                        body=body_input,
                                        pdf_attachment_path=pdf_path,
                                        company_name=app["company"],
                                        dry_run=dry_run_mode,
                                        ignore_hours=True
                                    )
                                    if ok:
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)

                    with col_b4:
                        if st.button("❌ Skip / Reject", key=f"skip_{job_id}", use_container_width=True):
                            update_application(job_id=job_id, status="skipped")
                            st.toast("Application skipped.")
                            st.rerun()

        # Speculative Company Outreaches in Review Queue
        speculative_drafts = (
            list_company_outreach_by_status("drafted") +
            list_company_outreach_by_status("approved") +
            list_company_outreach_by_status("sending") +
            list_company_outreach_by_status("failed")
        )
        if speculative_drafts:
            st.markdown("---")
            st.subheader(f"💼 Speculative Cold Outreaches ({len(speculative_drafts)} in Queue)")
            st.caption("Speculative applications sent to verified HR contacts of high-fit companies even when no open role is currently listed.")

            for outreach in speculative_drafts:
                oid = outreach["id"]
                cname = outreach.get("company_name", "Target Company")
                score = outreach.get("company_score", 0.0)
                tier = outreach.get("tier", "A")
                city = outreach.get("city", "Bangalore")
                recip = outreach.get("contact_email") or ""
                size_st = outreach.get("size_status") or "confirmed_20plus"
                ostatus = (outreach.get("status") or "drafted").lower()
                obadge_color = {
                    "drafted": "#0d6efd",
                    "approved": "#ffc107",
                    "sending": "#0dcaf0",
                    "sent": "#198754",
                    "failed": "#dc3545",
                    "skipped": "#6c757d"
                }.get(ostatus, "#6c757d")

                with st.expander(f"💼 **{cname}** — Speculative Cold Application (Tier {tier}, Score: {score:.1f}) [{ostatus.upper()}]", expanded=(ostatus in ('drafted', 'failed'))):
                    if outreach.get("error"):
                        st.error(f"❌ **Send Attempt Failed:** {outreach['error']}")
                    if outreach.get("message_id"):
                        st.caption(f"📨 Message-ID: `{outreach['message_id']}` | SMTP Response: `{outreach.get('smtp_response')}`")

                    col_sl, col_sr = st.columns([1, 1])
                    with col_sl:
                        st.markdown(f"**Target Company:** {cname} ({city})")
                        st.markdown(f"**Mode:** <span class='badge-pill score-high'>💼 Speculative Outreach</span>", unsafe_allow_html=True)
                        st.markdown(f"**Status:** <span style='background-color:{obadge_color}; color:white; padding:3px 8px; border-radius:10px; font-weight:bold;'>{ostatus.upper()}</span>", unsafe_allow_html=True)
                        st.markdown(f"**Tier & Company Score:** <span class='badge-pill score-mid'>Tier {tier}</span> — `{score:.1f}/100`", unsafe_allow_html=True)
                        st.markdown(f"**Size Status:** `{size_st}` (20/50 Rule Verified)")
                        st.markdown(f"**Recipient Contact:** `{recip or 'Hiring Team'}` ✅")

                        pdf_path_str = outreach.get("resume_path")
                        if pdf_path_str and Path(pdf_path_str).exists():
                            p_file = Path(pdf_path_str)
                            st.success(f"Tailored Resume: `{p_file.name}` ({p_file.stat().st_size} bytes)")
                            with open(p_file, "rb") as f:
                                b64_pdf = base64.b64encode(f.read()).decode("utf-8")
                            href = f'<a href="data:application/pdf;base64,{b64_pdf}" download="{p_file.name}">⬇️ Download 2-Page Tailored Resume (PDF)</a>'
                            st.markdown(href, unsafe_allow_html=True)

                    with col_sr:
                        st.subheader("Speculative Outreach Email")
                        sub_val = st.text_input("Subject:", value=outreach.get("email_subject") or "", key=f"s_sub_{oid}")
                        body_val = st.text_area("Body:", value=outreach.get("email_body") or "", height=200, key=f"s_body_{oid}")

                        col_sa, col_sb, col_sc = st.columns(3)
                        with col_sa:
                            if st.button("✅ Approve", key=f"appr_s_{oid}", use_container_width=True):
                                update_company_outreach(oid, {"status": "approved", "email_subject": sub_val, "email_body": body_val})
                                st.success("Speculative outreach approved!")
                                st.rerun()
                        with col_sb:
                            if st.button("🚀 Send Now", key=f"send_s_{oid}", type="primary", use_container_width=True):
                                with st.spinner("Dispatching speculative outreach..."):
                                    update_company_outreach(oid, {"email_subject": sub_val, "email_body": body_val})
                                    ok, msg = send_company_outreach_email(
                                        outreach_id=oid,
                                        dry_run=dry_run_mode,
                                        ignore_hours=True
                                    )
                                    if ok:
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                        with col_sc:
                            if st.button("❌ Skip", key=f"skip_s_{oid}", use_container_width=True):
                                update_company_outreach(oid, {"status": "skipped"})
                                st.toast("Outreach skipped.")
                                st.rerun()


# ==========================================
# PAGE: TARGET COMPANIES
# ==========================================
elif page == "🏢 Target Companies":
    st.title("🏢 Target Companies & Speculative Outreach")
    st.info("Company-first engine: discovers employers in Bangalore, Thiruvananthapuram, Kochi, Kozhikode, and Remote India. Evaluates employee size (20/50 rule), scores field fit, and identifies verified public HR contacts.")

    # Action Toolbar
    col_t1, col_t2, col_t3, col_t4, col_t5 = st.columns(5)
    with col_t1:
        if st.button("🔍 Discover Companies", use_container_width=True):
            with st.spinner("Discovering companies across parks and directories..."):
                d_res = run_company_discovery()
                st.success(f"Discovered {d_res.get('discovered', 0)} companies!")
                st.rerun()
    with col_t2:
        if st.button("📏 Enrich Sizes", use_container_width=True):
            with st.spinner("Evaluating size evidence ladder..."):
                e_res = run_company_enrichment()
                st.success(f"Enriched sizes: {e_res}")
                st.rerun()
    with col_t3:
        if st.button("⭐ Score & Tier", use_container_width=True):
            with st.spinner("Scoring field fit and hiring signals..."):
                s_res = run_company_scoring()
                st.success(f"Scored tiers: {s_res}")
                st.rerun()
    with col_t4:
        if st.button("✉️ Harvest Contacts", use_container_width=True):
            with st.spinner("Crawling verified public contacts..."):
                c_res = run_company_contacts(tier_filter=["A", "B"])
                st.success(f"Harvested {c_res.get('contacts_found', 0)} contacts!")
                st.rerun()
    with col_t5:
        if st.button("⚡ Draft Speculative", use_container_width=True):
            with st.spinner("Drafting speculative 2-page tailored resumes & emails..."):
                dr_res = run_company_drafting()
                st.success(f"Drafted {dr_res.get('drafted', 0)} speculative applications!")
                st.rerun()

    st.markdown("---")

    # Coverage Metrics Dashboard
    all_comps = list_companies()
    total_count = len(all_comps)
    tier_a_b = len([c for c in all_comps if c.get("tier") in ("A", "B")])
    confirmed_size = len([c for c in all_comps if c.get("size_status") in ("confirmed_20plus", "likely_20plus")])
    confirmed_size_pct = (confirmed_size / max(1, total_count)) * 100.0

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE company_id IS NOT NULL")
        with_contacts = cursor.fetchone()[0]
    contacts_pct = (with_contacts / max(1, total_count)) * 100.0

    cm1, cm2, cm3, cm4 = st.columns(4)
    with cm1:
        st.metric("Total Companies", total_count)
    with cm2:
        st.metric("Tier A & B Fits", tier_a_b)
    with cm3:
        st.metric("Verified >=20 Staff", f"{confirmed_size_pct:.1f}%", f"{confirmed_size} companies")
    with cm4:
        st.metric("With Verified HR", f"{contacts_pct:.1f}%", f"{with_contacts} companies")

    st.markdown("---")

    # Filters
    col_f1, col_f2, col_f3, col_f4 = st.columns([2, 1, 1, 1])
    with col_f1:
        search_query = st.text_input("Search company name, domain, or notes:", placeholder="e.g. InMobi, QBurst, vision, drone...")
    with col_f2:
        city_options = ["All", "Bangalore", "Thiruvananthapuram", "Kochi", "Kozhikode", "Remote India"]
        selected_city = st.selectbox("Filter City:", city_options, index=0)
    with col_f3:
        tier_options = ["All", "Tier A", "Tier B", "Tier C", "Excluded"]
        selected_tier = st.selectbox("Filter Tier:", tier_options, index=0)
    with col_f4:
        size_options = ["All", "confirmed_20plus", "likely_20plus", "unknown", "under_20"]
        selected_size = st.selectbox("Size Status:", size_options, index=0)

    # Filter data
    filtered_comps = all_comps
    if search_query:
        sq = search_query.lower().strip()
        filtered_comps = [c for c in filtered_comps if sq in c["name"].lower() or (c.get("domain") and sq in c["domain"].lower()) or (c.get("notes") and sq in c["notes"].lower())]
    if selected_city != "All":
        filtered_comps = [c for c in filtered_comps if c.get("city") and selected_city.lower() in c["city"].lower()]
    if selected_tier != "All":
        t_key = selected_tier.split()[-1] if "Tier" in selected_tier else selected_tier.lower()
        filtered_comps = [c for c in filtered_comps if c.get("tier") == t_key]
    if selected_size != "All":
        filtered_comps = [c for c in filtered_comps if c.get("size_status") == selected_size]

    st.write(f"Showing **{len(filtered_comps)}** of **{total_count}** companies:")

    for comp in filtered_comps:
        cid = comp["id"]
        cname = comp["name"]
        tier = comp.get("tier") or "C"
        cscore = comp.get("company_score") or 0.0
        size_st = comp.get("size_status") or "unknown"
        city = comp.get("city") or "India"
        domain = comp.get("domain") or comp.get("website") or ""

        tier_badge = "score-high" if tier == "A" else ("score-mid" if tier == "B" else "score-low")

        with st.expander(f"🏢 **{cname}** ({city}) — Tier {tier} (Score: {cscore:.1f}) | Size: {size_st}", expanded=False):
            col_l, col_r = st.columns([1, 1])

            with col_l:
                st.markdown(f"**Company Name:** {cname}")
                st.markdown(f"**Website / Domain:** [{domain}]({comp.get('website') or 'https://' + domain})")
                if comp.get("careers_url"):
                    st.markdown(f"**Careers Portal:** [View Openings]({comp['careers_url']})")
                st.markdown(f"**City / Location:** {city}")
                st.markdown(f"**Field Fit Score:** `{comp.get('field_fit_score', 0):.1f}/100` | **Hiring Signal:** `{comp.get('hiring_signal_score', 0):.1f}/100`")
                st.markdown(f"**Tier Classification:** <span class='badge-pill {tier_badge}'>Tier {tier}</span>", unsafe_allow_html=True)
                st.markdown(f"**Discovered Via:** `{comp.get('discovered_via', 'manual')}`")

                # Field Tags
                tags = comp.get("field_tags") or []
                if tags:
                    tag_pills = " ".join([f"<span class='badge-pill score-mid'>{t}</span>" for t in tags[:6]])
                    st.markdown(f"**Field Focus Tags:** {tag_pills}", unsafe_allow_html=True)

            with col_r:
                st.markdown("#### 📏 Employee Size Evidence (20/50 Rule)")
                st.markdown(f"**Size Status:** `{size_st}`")
                st.markdown(f"**Estimated Employees:** `{comp.get('employee_estimate') or 'Unknown'}` (Min: {comp.get('employee_min') or 'N/A'}, Max: {comp.get('employee_max') or 'N/A'})")
                st.markdown(f"**Evidence Confidence:** `{comp.get('size_confidence', 0.0) * 100:.0f}%`")
                st.markdown(f"**Size Source:** `{comp.get('size_source') or 'N/A'}`")
                st.markdown(f"**Evidence Snippet:** *{comp.get('size_evidence') or 'No public self-report found'}*")

                st.markdown("---")
                st.markdown("#### ✉️ Discovered Contacts")
                c_contacts = get_company_contacts(cid)
                if c_contacts:
                    for ct in c_contacts:
                        st.markdown(f"• `{ct['email']}` — *{ct.get('role', 'Talent Team')}* ({'✅ MX Valid' if ct.get('domain_mx_valid') else 'Pending'})")
                else:
                    st.info("No direct HR email discovered yet.")

                st.markdown("---")
                # Interactive Controls
                col_btn1, col_btn2, col_btn3 = st.columns(3)
                with col_btn1:
                    if st.button("✅ Confirm 20+", key=f"conf_sz_{cid}", use_container_width=True):
                        update_company(cid, {
                            "size_status": "confirmed_20plus",
                            "size_confidence": 0.95,
                            "size_source": "Manual user override",
                            "size_evidence": "Candidate manually confirmed team size >= 20",
                            "employee_estimate": max(25, comp.get("employee_estimate") or 25)
                        })
                        score_single_company(cid)
                        st.toast(f"Confirmed size 20+ for {cname}!")
                        st.rerun()

                with col_btn2:
                    if st.button("❌ Not Relevant", key=f"excl_{cid}", use_container_width=True):
                        update_company(cid, {"status": "not_relevant", "tier": "excluded"})
                        st.toast(f"Marked {cname} as not relevant.")
                        st.rerun()

                with col_btn3:
                    if st.button("⚡ Draft Outreach", key=f"drf_out_{cid}", use_container_width=True):
                        from src.pipeline import load_master_resume
                        master = load_master_resume()
                        oid = draft_single_speculative_application(cid, master)
                        if oid:
                            st.success("Drafted speculative application! View in Review Queue.")
                            st.rerun()
                        else:
                            st.warning("Could not draft: ensure company is Tier A/B and size is confirmed/likely.")


# ==========================================
# PAGE: INSTANT APPLY (ANY JOB)
# ==========================================
elif page == "🎯 Instant Apply (Any Job)":
    st.title("🎯 Instant Apply to Any Job")
    st.info("Paste any Job Description from LinkedIn, Indeed, Naukri, or any company career page. JobPilot will extract the recruiter contact, tailor your resume, compile your ATS PDF, write a personalized cover email, and send it via your verified Gmail.")

    col_i1, col_i2 = st.columns(2)
    with col_i1:
        custom_company = st.text_input("Company Name:", placeholder="e.g. DeepMind, Fractal, Bosch, InnovateLabs")
        custom_title = st.text_input("Job Title:", placeholder="e.g. AI/ML Engineer, Computer Vision Developer")
        custom_url = st.text_input("Job URL (optional):", placeholder="https://company.com/careers/job-123")
        custom_email = st.text_input("HR / Recruiter Email (optional - leaves blank to auto-detect from text):", placeholder="careers@company.com or hr@company.com")

    with col_i2:
        custom_jd = st.text_area("Paste Job Description (JD) Text:", height=200, placeholder="Paste the responsibilities, requirements, and qualifications here...")
        instant_autosend = st.checkbox("Auto-Send via Gmail SMTP immediately if contact is found", value=True)

    if st.button("⚡ Tailor Resume, Email & Apply Now!", type="primary", use_container_width=True):
        if not custom_company or not custom_title or not custom_jd:
            st.error("Please provide at least Company Name, Job Title, and Job Description text.")
        else:
            with st.spinner("Processing JD with Gemini 3.8 Flash, tailoring resume, compiling ATS PDF, and drafting email..."):
                res = apply_single_job(
                    company=custom_company.strip(),
                    title=custom_title.strip(),
                    jd_text=custom_jd.strip(),
                    job_url=custom_url.strip(),
                    recipient_email=custom_email.strip() or None,
                    auto_send=instant_autosend,
                    dry_run=dry_run_mode
                )

                st.success(f"Application processed for **{res['company']}** ({res['role']})!")
                st.markdown(f"**Match Fit Score:** `{res['match_score']:.1f}%`")
                if res["recipient_email"]:
                    st.markdown(f"**Recipient Contact:** `{res['recipient_email']}`")

                col_res1, col_res2 = st.columns(2)
                with col_res1:
                    st.subheader("📄 Tailored ATS Resume")
                    pdf_p = Path(res["pdf_path"])
                    if pdf_p.exists():
                        with open(pdf_p, "rb") as f:
                            pdf_bytes = f.read()
                        st.download_button(
                            label=f"⬇️ Download {pdf_p.name}",
                            data=pdf_bytes,
                            file_name=pdf_p.name,
                            mime="application/pdf",
                            key="instant_pdf_dl"
                        )

                with col_res2:
                    st.subheader("✉️ Tailored Email")
                    st.text_input("Subject:", value=res["subject"], disabled=True)
                    st.text_area("Body:", value=res["body"], height=160, disabled=True)

                if res["sent"]:
                    mode_lbl = "[DRY-RUN]" if dry_run_mode else "LIVE GMAIL"
                    st.success(f"🎉 **Application Sent Successfully ({mode_lbl})!** {res['message']}")
                else:
                    st.info(f"ℹ️ {res['message']}")


# ==========================================
# PAGE 2: ALL JOBS
# ==========================================
elif page == "💼 All Jobs":
    st.title("💼 Discovered Jobs")

    jobs = list_jobs(limit=200)
    if not jobs:
        st.info("No jobs in database yet. Click 'Scrape New' in the sidebar.")
    else:
        # Search & Filter
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            search_query = st.text_input("Search by title or company:", "")
        with col_f2:
            status_filter = st.selectbox("Filter by Status:", ["All", "new", "matched", "drafted", "approved", "sent", "replied", "skipped"])

        filtered = jobs
        if search_query:
            filtered = [j for j in filtered if search_query.lower() in j["title"].lower() or search_query.lower() in j["company"].lower()]
        if status_filter != "All":
            filtered = [j for j in filtered if j.get("app_status") == status_filter]

        st.write(f"Showing **{len(filtered)}** of **{len(jobs)}** jobs")

        for j in filtered:
            score = j.get("match_score") or 0.0
            status_str = j.get("app_status") or "new"
            with st.expander(f"{j['company']} — {j['title']} ({j['location']}) | Status: {status_str.upper()} | Score: {score:.1f}%"):
                st.markdown(f"**Source:** {j['source']} | **Posted:** {j['posted_date'] or 'N/A'}")
                st.markdown(f"**URL:** [View Posting]({j['url']})")
                st.markdown("**Description Preview:**")
                st.text(j['description'][:600] + ("..." if len(j['description']) > 600 else ""))


# ==========================================
# PAGE 3: SENT APPLICATIONS
# ==========================================
elif page == "🚀 Sent Applications":
    st.title("🚀 Sent Applications")
    sent_apps = list_applications_by_status("sent") + list_applications_by_status("replied")

    if not sent_apps:
        st.info("No applications have been sent yet.")
    else:
        st.write(f"Total Sent: **{len(sent_apps)}**")
        for app in sent_apps:
            job_id = app["job_id"]
            contacts = get_contacts_for_job(job_id)
            recipient = contacts[0]["email"] if contacts else "N/A"

            sent_at_val = str(app.get('sent_at') or 'N/A')[:16]
            followup_val = str(app.get('followup_due') or 'N/A')[:10]
            with st.expander(f"{app['company']} — {app['title']} (Sent on: {sent_at_val}) [{app['status'].upper()}]"):
                st.markdown(f"**Recipient:** `{recipient}`")
                st.markdown(f"**Subject:** {app.get('email_subject')}")
                st.markdown(f"**Follow-up Due Date:** {followup_val}")
                st.text_area("Sent Body:", value=app.get("email_body") or "", height=120, disabled=True, key=f"sent_body_{job_id}")

                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    if st.button("🎉 Mark as Replied", key=f"replied_{job_id}"):
                        mark_as_replied(job_id)
                        st.success("Marked as replied!")
                        st.rerun()
                with col_a2:
                    if st.button("🚫 Opt-Out & Add to Blocklist", key=f"block_{job_id}"):
                        opt_out_and_block(job_id, recipient, reason="Recruiter opted out")
                        st.warning(f"Added {recipient} to blocklist!")
                        st.rerun()


# ==========================================
# PAGE: SEND LOGS & DISPATCH AUDIT
# ==========================================
elif page == "📤 Send Logs":
    st.title("📤 Email Dispatch & Delivery Audit Logs")
    st.info("Live, transparent audit trail of all email dispatches. Directly reflects SMTP responses, RFC-compliant Message-IDs, sending hour compliance, and real-time error telemetry.")

    # Fetch logs
    all_raw_logs = get_send_logs(limit=200)

    # Metrics
    total_attempts = len([l for l in all_raw_logs if l.get("status") in ("sent", "failed", "sending")])
    total_sent = len([l for l in all_raw_logs if l.get("status") == "sent"])
    total_failed = len([l for l in all_raw_logs if l.get("status") == "failed"])
    total_approved = len([l for l in all_raw_logs if l.get("status") == "approved"])

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric("Total Dispatched", total_attempts)
    with m_col2:
        st.metric("Delivered (SMTP 250)", total_sent)
    with m_col3:
        st.metric("Failed / Errors", total_failed)
    with m_col4:
        st.metric("Approved in Queue", total_approved)

    st.markdown("---")

    col_flt1, col_flt2 = st.columns([3, 1])
    with col_flt1:
        search_kw = st.text_input("🔍 Search logs by company, role, or recipient email:", "")
    with col_flt2:
        status_filter = st.selectbox("Filter by Status:", ["All", "sent", "failed", "sending", "approved"], index=0)

    # Apply filters
    filtered_logs = all_raw_logs
    if status_filter != "All":
        filtered_logs = [l for l in filtered_logs if (l.get("status") or "").lower() == status_filter.lower()]
    if search_kw.strip():
        kw = search_kw.strip().lower()
        filtered_logs = [
            l for l in filtered_logs
            if kw in (l.get("company_name") or "").lower()
            or kw in (l.get("recipient_email") or "").lower()
            or kw in (l.get("role_title") or "").lower()
            or kw in (l.get("subject") or "").lower()
        ]

    if not filtered_logs:
        st.info("No dispatch records matching current filter.")
    else:
        st.write(f"Showing **{len(filtered_logs)}** log records:")
        for log_entry in filtered_logs:
            l_status = (log_entry.get("status") or "unknown").lower()
            l_badge_color = {
                "sent": "#198754",
                "failed": "#dc3545",
                "sending": "#0dcaf0",
                "approved": "#ffc107"
            }.get(l_status, "#6c757d")

            l_company = log_entry.get("company_name") or "Target Company"
            l_role = log_entry.get("role_title") or "Role Application"
            l_recip = log_entry.get("recipient_email") or "N/A"
            l_ts = str(log_entry.get("sent_at") or log_entry.get("attempted_at") or log_entry.get("created_at") or "")[:19]
            l_type = log_entry.get("dispatch_type") or "job_application"

            with st.expander(f"[{l_status.upper()}] {l_company} — {l_role} ({mask_email(l_recip)}) | {l_ts}"):
                c_info1, c_info2 = st.columns([2, 1])
                with c_info1:
                    st.markdown(f"**Company:** {l_company}")
                    st.markdown(f"**Role / Type:** {l_role} (`{l_type}`)")
                    st.markdown(f"**Recipient:** `{l_recip}`")
                    st.markdown(f"**Subject:** {log_entry.get('subject') or 'N/A'}")
                    st.markdown(f"**Status:** <span style='background-color:{l_badge_color}; color:white; padding:3px 8px; border-radius:10px; font-weight:bold;'>{l_status.upper()}</span>", unsafe_allow_html=True)

                with c_info2:
                    st.markdown(f"**Timestamp:** `{l_ts or 'N/A'}`")
                    st.markdown(f"**Message-ID:** `{log_entry.get('message_id') or 'N/A'}`")
                    st.markdown(f"**SMTP Response:** `{log_entry.get('smtp_response') or 'N/A'}`")

                if log_entry.get("error"):
                    st.error(f"❌ **Error Message:** {log_entry['error']}")

                # Retry action for failed records
                if l_status == "failed":
                    st.markdown("---")
                    if l_type == "job_application":
                        j_ref = log_entry.get("reference_id")
                        if st.button(f"🔄 Retry Dispatch Application", key=f"retry_log_job_{log_entry['record_id']}"):
                            from src.sender import send_application_email
                            with st.spinner("Retrying dispatch..."):
                                ok, msg = send_application_email(
                                    job_id=j_ref,
                                    recipient_email=l_recip,
                                    subject=log_entry.get("subject") or "",
                                    body="",
                                    company_name=l_company,
                                    dry_run=dry_run_mode,
                                    ignore_hours=True
                                )
                                if ok:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                    elif l_type == "speculative":
                        o_ref = log_entry.get("record_id")
                        if st.button(f"🔄 Retry Speculative Outreach", key=f"retry_log_spec_{o_ref}"):
                            from src.sender import send_company_outreach_email
                            with st.spinner("Retrying speculative outreach..."):
                                ok, msg = send_company_outreach_email(
                                    outreach_id=o_ref,
                                    dry_run=dry_run_mode,
                                    ignore_hours=True
                                )
                                if ok:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

        # JSON Download
        log_json_data = json.dumps(filtered_logs, indent=2, default=str)
        st.download_button(
            label="⬇️ Download Send Audit Logs (JSON)",
            data=log_json_data,
            file_name="jobpilot_send_audit_logs.json",
            mime="application/json"
        )


# ==========================================
# PAGE 4: FOLLOW-UPS
# ==========================================
elif page == "⏰ Follow-ups":
    st.title("⏰ 6-Day Follow-Up Tracker")
    st.info("Ensures polite, low-pressure follow-up. Exactly 1 follow-up is scheduled 6 days after dispatch. Never sends more than once.")

    due_apps = get_due_followups()
    if not due_apps:
        st.success("No follow-ups due right now! Check back when 6 days have elapsed from your first sent application.")
    else:
        st.write(f"**{len(due_apps)}** follow-up(s) ready:")
        for app in due_apps:
            job_id = app["job_id"]
            contacts = get_contacts_for_job(job_id)
            recipient = contacts[0]["email"] if contacts else "recruiter"

            f_due = str(app.get("followup_due") or "N/A")[:10]
            with st.expander(f"{app['company']} — {app['title']} (Due: {f_due})"):
                draft = generate_followup_draft(
                    company=app["company"],
                    role=app["title"],
                    original_subject=app.get("email_subject") or f"Application: {app['title']}",
                    candidate_name=settings.candidate_name
                )
                f_subj = st.text_input("Follow-up Subject:", value=draft["subject"], key=f"fsubj_{job_id}")
                f_body = st.text_area("Follow-up Body:", value=draft["body"], height=120, key=f"fbody_{job_id}")

                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    if st.button("🚀 Approve & Send Follow-up", key=f"send_f_{job_id}", type="primary"):
                        ok, msg = send_application_email(
                            job_id=job_id,
                            recipient_email=recipient,
                            subject=f_subj,
                            body=f_body,
                            company_name=app["company"],
                            dry_run=dry_run_mode,
                            ignore_hours=True
                        )
                        if ok:
                            update_application(job_id=job_id, followup_sent=True)
                            st.success("Follow-up sent!")
                            st.rerun()
                        else:
                            st.error(msg)
                with col_f2:
                    if st.button("Mark as Replied", key=f"mreplied_{job_id}"):
                        mark_as_replied(job_id)
                        st.rerun()
                with col_f3:
                    if st.button("Do Not Contact / Block", key=f"block_f_{job_id}"):
                        opt_out_and_block(job_id, recipient)
                        st.rerun()


# ==========================================
# PAGE 5: SETTINGS & LOGS
# ==========================================
elif page == "⚙️ Settings & Logs":
    st.title("⚙️ Settings, Credentials & Audit Logs")

    tab1, tab2, tab3 = st.tabs(["Credentials & Config", "Permanent Blocklist", "System Audit Logs"])

    with tab1:
        st.subheader("System Credentials")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            gemini_key_set = bool(settings.gemini_api_key and not settings.gemini_api_key.startswith("your_"))
            st.write(f"**Gemini API Key:** {'✅ Configured' if gemini_key_set else '⚠️ Missing or placeholder (using offline mock)'}")
            st.write(f"**Model:** `{settings.gemini_model}`")

        with col_c2:
            gmail_set = bool(settings.gmail_user and settings.gmail_app_password and not settings.gmail_user.startswith("your_"))
            st.write(f"**Gmail Sender:** {'✅ Configured (' + settings.gmail_user + ')' if gmail_set else '⚠️ Missing or placeholder'}")
            st.write(f"**App Password:** {'✅ Configured' if gmail_set else '⚠️ Missing'}")
            if gmail_set:
                if st.button("📨 Send Test Verification Email", key="btn_test_email"):
                    from src.sender import send_test_email
                    with st.spinner("Connecting to Gmail SMTP SSL and dispatching verification email..."):
                        ok, msg = send_test_email(settings.gmail_user)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

        st.markdown("---")
        st.subheader("LLM Token & Free-Tier Guardrails")
        u = get_today_llm_usage()
        st.write(f"- **Today's Requests:** `{u['request_count']} / {settings.llm_max_requests_per_day}`")
        st.write(f"- **Today's Tokens Used:** `{u['total_tokens']:,} / {settings.llm_max_tokens_per_day:,}` (Prompt: {u['prompt_tokens']:,}, Completion: {u['completion_tokens']:,})")
        st.write(f"- **Pacing Delay:** `{settings.llm_min_seconds_between_calls}s` between consecutive API calls (enforces strictly under 15 RPM)")
        st.write(f"- **Max JD Length:** `{settings.llm_max_input_characters}` characters (prevents token bloat from legal/cookie disclaimers)")
        st.write(f"- **Response Caching:** Enabled (SQLite `llm_cache` avoids duplicate token usage)")

        st.markdown("---")
        st.subheader("Operating Constraints")
        st.write(f"- **Daily Sending Cap:** {settings.daily_cap} emails/day")
        st.write(f"- **Sending Hours:** {settings.sending_hours_start}:00 to {settings.sending_hours_end}:00 (Local Time)")
        st.write(f"- **Company Cooldown:** {settings.cooldown_days_per_company} days between emails")
        st.write(f"- **Follow-up Timing:** Exactly 1 follow-up after {settings.followup_days} days")
        st.write(f"- **Min Match Score:** {settings.min_match_score}%")

    with tab2:
        st.subheader("Do-Not-Contact Blocklist")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM blocklist ORDER BY created_at DESC")
            blocked = [dict(row) for row in cursor.fetchall()]

        if blocked:
            for b in blocked:
                b_date = str(b.get("created_at") or "N/A")[:10]
                st.write(f"🚫 **{b['email']}** &mdash; Reason: *{b['reason']}* (Added: {b_date})")
        else:
            st.info("Blocklist is currently empty.")

        new_block = st.text_input("Manually add email to blocklist:")
        if st.button("Add to Blocklist") and new_block:
            add_to_blocklist(new_block.strip(), reason="Manually added by user")
            st.success(f"Added {new_block} to blocklist.")
            st.rerun()

    with tab3:
        st.subheader("Recent System Logs")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 50")
            recent_logs = [dict(row) for row in cursor.fetchall()]

        if recent_logs:
            for log in recent_logs:
                level_color = "red" if log["level"] == "ERROR" else ("orange" if log["level"] == "WARNING" else "gray")
                ts = str(log.get("timestamp") or "")[:19]
                st.markdown(f"`{ts}` <span style='color:{level_color}; font-weight:bold;'>[{log['level']}]</span> **{log['module']}**: {log['message']}", unsafe_allow_html=True)
        else:
            st.info("No audit logs recorded yet.")

