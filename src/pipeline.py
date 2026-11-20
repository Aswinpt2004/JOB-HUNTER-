import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from src.config import settings
from src.db import (
    init_db,
    get_connection,
    save_job,
    list_jobs,
    get_job,
    list_applications_by_status,
    update_application,
    get_contacts_for_job,
    log_event,
    list_companies,
    list_company_outreach_by_status,
    backfill_jobs_to_companies
)
from src.models import MasterResume, Job
from src.scrapers.base import BaseScraper
from src.scrapers.greenhouse import GreenhouseScraper
from src.scrapers.lever import LeverScraper
from src.scrapers.remotive import RemotiveScraper
from src.scrapers.career_page import CareerPageScraper
from src.scrapers.kerala_parks import TechnoparkScraper, InfoparkScraper
from src.contacts import find_recruiter_contacts
from src.jd_parser import parse_job_description
from src.matcher import compute_match_score
from src.resume_tailor import tailor_resume
from src.pdf_builder import build_tailored_resume_files
from src.email_writer import generate_application_email
from src.sender import send_application_email
from src.followup import get_due_followups, generate_followup_draft
from src.companies.discovery import run_company_discovery
from src.companies.enrichment import run_company_enrichment
from src.companies.scorer import run_company_scoring
from src.companies.contacts import run_company_contacts
from src.companies.speculative import run_company_drafting

# Configure console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("jobpilot.pipeline")


def load_master_resume() -> MasterResume:
    """Loads and validates candidate master resume."""
    with open(settings.master_resume_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return MasterResume.model_validate(data)


def step_scrape(dry_run: bool = False) -> int:
    """Discovers new job postings across Greenhouse, Lever, Remotive, and Career pages."""
    init_db()
    logger.info("=== Starting Job Discovery Scrapers ===")
    scrapers = [
        TechnoparkScraper(),
        InfoparkScraper(),
        GreenhouseScraper(),
        LeverScraper(),
        RemotiveScraper(),
        CareerPageScraper()
    ]

    total_new = 0
    for scraper in scrapers:
        try:
            jobs = scraper.fetch_jobs()
            for job in jobs:
                if dry_run:
                    logger.info("[DRY-RUN] Scraped: %s at %s (%s)", job.title, job.company, job.url)
                    total_new += 1
                else:
                    inserted = save_job(job)
                    if inserted:
                        total_new += 1
                        logger.info("Saved new job: %s at %s", job.title, job.company)
        except Exception as e:
            logger.error("Scraper '%s' encountered error: %s", scraper.source_name, e)

    logger.info("Job discovery completed. %d new jobs saved.", total_new)
    log_event("pipeline", f"Scraped {total_new} new jobs (dry_run={dry_run})")
    return total_new


def step_match(threshold: Optional[float] = None, limit: Optional[int] = 10, dry_run: bool = False) -> int:
    """Parses new JDs and computes match score against master resume."""
    init_db()
    min_score = threshold if threshold is not None else settings.min_match_score
    master = load_master_resume()
    new_apps = list_applications_by_status("new")
    logger.info("Found %d unprocessed jobs to scan for target locations and match against threshold (%.1f)...", len(new_apps), min_score)

    # Prioritize engineering, AI/ML, and fresher/intern positions
    def get_job_priority(app):
        jdata = get_job(app["job_id"])
        if not jdata:
            return 99
        t = jdata.get("title", "").lower()
        if any(w in t for w in ["intern", "fresher", "junior", "trainee"]):
            return 0
        if any(w in t for w in ["software engineer", "backend", "machine learning", "ai engineer", "python", "developer", "data scientist"]):
            return 1
        return 10

    new_apps.sort(key=get_job_priority)

    matched_count = 0
    evaluated_count = 0
    for app in new_apps:
        if limit and evaluated_count >= limit:
            break

        job_id = app["job_id"]
        job_data = get_job(job_id)
        if not job_data:
            continue

        try:
            # 1. Location check: strictly Bangalore, Kochi, TVM, KKD, Remote India
            loc = job_data.get("location") or ""
            if not BaseScraper.matches_preferred_location(loc):
                if not dry_run:
                    update_application(job_id=job_id, status="skipped", match_score=0.0)
                continue

            # 2. Fast check: Disqualify Senior / Lead / Manager / Multi-year roles without wasting LLM tokens
            title_lower = job_data["title"].lower()
            senior_kw = ["senior", "sr.", "sr ", "lead", "staff", "principal", "architect", "manager", "director", "head of", "vp", "vice president", "3+", "4+", "5+", "6+", "7+", "8+"]
            is_senior = any(sk in title_lower for sk in senior_kw) and not any(ok in title_lower for ok in ["junior", "intern", "associate", "trainee"])
            if is_senior:
                logger.info("Job '%s' title indicates senior/lead tier. Skipping without LLM call.", job_data["title"])
                if not dry_run:
                    update_application(job_id=job_id, status="skipped", match_score=0.0)
                continue

            # 3. Pre-screen: check if title or description matches any technical keyword
            check_text = f"{job_data['title']} {job_data['description']}".lower()
            if settings.keywords and not any(kw.lower() in check_text for kw in settings.keywords):
                logger.info("Job '%s' has 0 matching technical keywords. Skipping without LLM call.", job_data["title"])
                if not dry_run:
                    update_application(job_id=job_id, status="skipped", match_score=0.0)
                continue

            evaluated_count += 1
            logger.info("Parsing JD for '%s' at %s...", job_data["title"], job_data["company"])
            jd_parsed = parse_job_description(job_data["description"])
            if not jd_parsed:
                logger.warning("Could not parse JD for job %s. Skipping.", job_id)
                continue

            # Compute match score
            match_res = compute_match_score(jd_parsed, master, threshold=min_score)
            logger.info("Job '%s' score: %.1f (Threshold: %.1f, Met: %s)", job_data["title"], match_res.match_score, min_score, match_res.meets_threshold)

            # Extract recruiter contacts
            job_obj = Job(**job_data)
            contacts = find_recruiter_contacts(job_obj, check_mx=True)

            # USER PREFERENCE: Avoid any listing that lacks a verified HR contact email for outreach
            if not contacts:
                logger.info("Job '%s' at %s has NO verified HR contact email. Avoiding listing for mailing.", job_data["title"], job_data["company"])
                if not dry_run:
                    update_application(
                        job_id=job_id,
                        status="skipped",
                        match_score=match_res.match_score,
                        rationale="Skipped: No verified HR / recruiter contact email available for outreach"
                    )
                continue

            if not dry_run:
                next_status = "matched" if match_res.meets_threshold else "skipped"
                update_application(
                    job_id=job_id,
                    status=next_status,
                    match_score=match_res.match_score,
                    rationale=match_res.rationale,
                    role_tier=match_res.role_tier,
                    role_lens=match_res.role_lens
                )
                if match_res.meets_threshold:
                    matched_count += 1
            else:
                if match_res.meets_threshold:
                    matched_count += 1
                logger.info("[DRY-RUN] Qualified for mailing with HR contact! Would set status=%s, match_score=%.1f (Tier: %s, Lens: %s)", "matched" if match_res.meets_threshold else "skipped", match_res.match_score, match_res.role_tier, match_res.role_lens)

        except Exception as e:
            logger.error("Error evaluating job %s: %s", job_id, e)

    logger.info("Matching complete. %d jobs qualified above threshold.", matched_count)
    log_event("pipeline", f"Matched {matched_count} jobs above {min_score}")
    return matched_count


def step_draft(limit: Optional[int] = 10, dry_run: bool = False) -> int:
    """Tailors ATS resume, compiles PDF, and generates personalized application email drafts."""
    init_db()
    master = load_master_resume()
    matched_apps = list_applications_by_status("matched")
    if limit and len(matched_apps) > limit:
        matched_apps = matched_apps[:limit]
    logger.info("Drafting resumes and emails for %d matched applications...", len(matched_apps))

    drafted_count = 0
    for app in matched_apps:
        job_id = app["job_id"]
        job_data = get_job(job_id)
        if not job_data:
            continue

        try:
            job_obj = Job(**job_data)
            jd_parsed = parse_job_description(job_data["description"])
            if not jd_parsed:
                continue

            logger.info("Tailoring resume for '%s' at %s...", job_data["title"], job_data["company"])
            tailored = tailor_resume(master, jd_parsed)

            # Build PDF and tailored JSON
            pdf_path, json_path = build_tailored_resume_files(
                tailored=tailored,
                company=job_data["company"],
                role=jd_parsed.role
            )

            # Identify recipient recruiter name if available
            contacts = get_contacts_for_job(job_id)
            if not contacts:
                logger.info("Application for job %s has no verified HR email. Skipping drafting per user preference.", job_id)
                if not dry_run:
                    update_application(
                        job_id=job_id,
                        status="skipped",
                        rationale="Skipped: No verified HR contact email for outreach"
                    )
                continue

            recruiter_name = contacts[0]["name"] if contacts and contacts[0].get("name") else None

            # Generate tailored application email
            subject, body = generate_application_email(
                job=job_obj,
                jd_parsed=jd_parsed,
                tailored_resume=tailored,
                master_resume=master,
                recruiter_name=recruiter_name
            )

            if not dry_run:
                page_fill_str = json.dumps(tailored.page_fill) if getattr(tailored, "page_fill", None) else None
                update_application(
                    job_id=job_id,
                    status="drafted",
                    resume_path=str(pdf_path),
                    tailored_json_path=str(json_path),
                    email_subject=subject,
                    email_body=body,
                    layout_warning=getattr(tailored, "layout_warning", False),
                    page_fill=page_fill_str
                )
                drafted_count += 1
                fill_info = f" (P1: {tailored.page_fill['page1']*100:.1f}%, P2: {tailored.page_fill['page2']*100:.1f}%)" if getattr(tailored, "page_fill", None) else ""
                logger.info("Drafted application for '%s'. Resume: %s%s", job_data["company"], pdf_path.name, fill_info)
            else:
                drafted_count += 1
                fill_info = f" (P1: {tailored.page_fill['page1']*100:.1f}%, P2: {tailored.page_fill['page2']*100:.1f}%)" if getattr(tailored, "page_fill", None) else ""
                logger.info("[DRY-RUN] Tailored resume & drafted email for %s at %s%s", job_data["title"], job_data["company"], fill_info)

        except Exception as e:
            logger.error("Failed drafting application for %s: %s", job_id, e)

    logger.info("Drafting complete. %d applications ready in Review Queue.", drafted_count)
    log_event("pipeline", f"Drafted {drafted_count} applications ready for human review")
    return drafted_count


def step_send_approved(dry_run: bool = False, ignore_hours: bool = False) -> int:
    """Dispatches human-approved applications and speculative outreaches with anti-spam delays and daily limits."""
    init_db()
    approved_apps = list_applications_by_status("approved")
    logger.info("Found %d approved applications queued for sending...", len(approved_apps))

    sent_count = 0
    for app in approved_apps:
        job_id = app["job_id"]
        job_data = get_job(job_id)
        if not job_data:
            continue

        contacts = get_contacts_for_job(job_id)
        recipient_email = None
        if contacts:
            recipient_email = contacts[0]["email"]
        elif job_data.get("recruiter_email"):
            recipient_email = job_data["recruiter_email"]
        else:
            # Fallback 1: Check if any contact exists for this company
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT c.email FROM contacts c
                    JOIN jobs j ON c.job_id = j.id
                    WHERE LOWER(j.company) = LOWER(?)
                    ORDER BY c.verified DESC, c.id DESC LIMIT 1
                """, (job_data["company"],))
                row = cur.fetchone()
                if row:
                    recipient_email = row[0]

            # Fallback 2: Try scraping company site on-the-fly
            if not recipient_email:
                new_contacts = find_recruiter_contacts(Job(**job_data), check_mx=True)
                if new_contacts:
                    recipient_email = new_contacts[0].email

        if not recipient_email:
            logger.warning("No recruiter email contact found for job %s (%s). Marking 'skipped'.", job_id, job_data["company"])
            if not dry_run:
                update_application(job_id=job_id, status="skipped")
            continue
        subject = app["email_subject"] or f"Application: {job_data['title']} - {settings.candidate_name}"
        body = app["email_body"] or "Please find my attached resume."
        pdf_path = Path(app["resume_path"]) if app["resume_path"] else None

        logger.info("Dispatching approved email to %s for %s at %s...", recipient_email, job_data["title"], job_data["company"])

        ok, msg = send_application_email(
            job_id=job_id,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            pdf_attachment_path=pdf_path,
            company_name=job_data["company"],
            dry_run=dry_run,
            ignore_hours=ignore_hours or dry_run
        )

        if ok:
            sent_count += 1
            if not dry_run:
                # Anti-spam delay between sends
                delay = random.uniform(settings.send_delay_min, settings.send_delay_max)
                logger.info("Waiting %.1f seconds before next dispatch (anti-spam cooldown)...", delay)
                time.sleep(delay)
        else:
            logger.warning("Dispatch halted: %s", msg)
            break

    # Also dispatch approved speculative outreach
    from src.db import list_company_outreach_by_status
    from src.sender import send_company_outreach_email
    approved_outreach = list_company_outreach_by_status("approved")
    if approved_outreach:
        logger.info("Found %d approved speculative outreaches queued for sending...", len(approved_outreach))
        for outreach in approved_outreach:
            oid = outreach["id"]
            cname = outreach.get("company_name", "Target Company")
            logger.info("Dispatching approved speculative outreach #%d for %s...", oid, cname)
            ok, msg = send_company_outreach_email(
                outreach_id=oid,
                dry_run=dry_run,
                ignore_hours=ignore_hours or dry_run
            )
            if ok:
                sent_count += 1
                if not dry_run:
                    delay = random.uniform(settings.send_delay_min, settings.send_delay_max)
                    logger.info("Waiting %.1f seconds before next dispatch (anti-spam cooldown)...", delay)
                    time.sleep(delay)
            else:
                logger.warning("Speculative dispatch halted: %s", msg)
                break

    logger.info("Send step complete. %d total emails sent.", sent_count)
    log_event("pipeline", f"Sent {sent_count} approved applications & outreaches (dry_run={dry_run})")
    return sent_count


def step_followups(dry_run: bool = False) -> int:
    """Identifies applications due for 6-day follow-up and creates drafts."""
    init_db()
    due = get_due_followups()
    logger.info("Found %d applications due for 6-day follow-up.", len(due))

    drafted = 0
    for app in due:
        job_id = app["job_id"]
        draft = generate_followup_draft(
            company=app["company"],
            role=app["title"],
            original_subject=app.get("email_subject") or f"Application: {app['title']}",
            candidate_name=settings.candidate_name
        )
        if not dry_run:
            update_application(
                job_id=job_id,
                email_subject=draft["subject"],
                email_body=draft["body"],
                status="approved"  # Ready in queue for human approval
            )
            drafted += 1
        else:
            drafted += 1
            logger.info("[DRY-RUN] Prepared follow-up for %s: %s", app["company"], draft["subject"])

    logger.info("Follow-ups processed: %d queued for review.", drafted)
    return drafted


def step_discover_companies(city: Optional[str] = None, limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Phase A: Discovers companies across Kerala Parks, Bangalore lists, ATS boards, GitHub, and seed config."""
    if dry_run:
        logger.info("[DRY-RUN] Simulating company discovery...")
        return {"discovered": 0, "processed": 0}
    return run_company_discovery(city=city, limit=limit)


def step_enrich_companies(limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Phase B: Evaluates employee size evidence ladder (20/50 rule)."""
    if dry_run:
        logger.info("[DRY-RUN] Simulating company size enrichment...")
        return {}
    return run_company_enrichment(limit=limit)


def step_score_companies(dry_run: bool = False) -> Dict[str, Any]:
    """Phase C: Scores field fit and hiring likelihood, assigning Tiers A, B, C, or excluded."""
    if dry_run:
        logger.info("[DRY-RUN] Simulating company scoring...")
        return {}
    return run_company_scoring()


def step_company_contacts(tier_filter: Optional[List[str]] = None, limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Phase D: Crawls official pages for public HR/careers contacts and validates MX records."""
    if dry_run:
        logger.info("[DRY-RUN] Simulating company contact discovery...")
        return {}
    return run_company_contacts(tier_filter=tier_filter, limit=limit)


def step_draft_companies(limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Phase E: Drafts speculative applications with pseudo-JD tailored 2-page resume and cold email."""
    if dry_run:
        logger.info("[DRY-RUN] Simulating company speculative drafting...")
        return {}
    return run_company_drafting(limit=limit)


def step_run_companies(city: Optional[str] = None, limit: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Executes the full company discovery & speculative outreach pipeline and prints the funnel."""
    logger.info("=== STARTING COMPANY-FIRST ENGINE (Discovery -> Size -> Scoring -> Contacts -> Drafting) ===")
    
    # Ensure existing jobs are linked
    backfill_jobs_to_companies()

    # 1. Discovery
    disc_res = step_discover_companies(city=city, limit=limit, dry_run=dry_run)
    # 2. Size Enrichment
    enrich_res = step_enrich_companies(limit=limit, dry_run=dry_run)
    # 3. Scoring & Tiers
    score_res = step_score_companies(dry_run=dry_run)
    # 4. Contacts
    contact_res = step_company_contacts(tier_filter=["A", "B"], limit=limit, dry_run=dry_run)
    # 5. Speculative Drafting
    draft_res = step_draft_companies(limit=limit, dry_run=dry_run)

    # Compute comprehensive company funnel
    companies = list_companies()
    total_stored = len(companies)
    on_field_count = len([c for c in companies if (c.get("field_fit_score") or 0.0) >= 20.0])

    size_counts = {"confirmed_20plus": 0, "likely_20plus": 0, "unknown": 0, "under_20": 0}
    tier_counts = {"A": 0, "B": 0, "C": 0, "excluded": 0}
    city_counts: Dict[str, int] = {}

    for c in companies:
        st = c.get("size_status") or "unknown"
        size_counts[st] = size_counts.get(st, 0) + 1

        tr = c.get("tier") or "C"
        tier_counts[tr] = tier_counts.get(tr, 0) + 1

        ct = c.get("city") or "Other"
        city_counts[ct] = city_counts.get(ct, 0) + 1

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE company_id IS NOT NULL")
        companies_with_contacts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM company_outreach WHERE status = 'drafted'")
        drafted_outreach = cursor.fetchone()[0]

    funnel_report = (
        f"\n======================================================\n"
        f"🏢 JOBPILOT COMPANY DISCOVERY & SPECULATIVE FUNNEL\n"
        f"======================================================\n"
        f"  1. Total Candidates Discovered : {disc_res.get('discovered', 0)}\n"
        f"  2. Deduplicated & In Database  : {total_stored}\n"
        f"  3. On-Field Companies (Fit>=20): {on_field_count}\n"
        f"  4. Size Status (20/50 Rule)    :\n"
        f"     • Confirmed 20+ : {size_counts.get('confirmed_20plus', 0)}\n"
        f"     • Likely 20+    : {size_counts.get('likely_20plus', 0)}\n"
        f"     • Unknown (Hold): {size_counts.get('unknown', 0)}\n"
        f"     • Under 20 (X)  : {size_counts.get('under_20', 0)}\n"
        f"  5. Company Tiers               :\n"
        f"     • Tier A (Core) : {tier_counts.get('A', 0)}\n"
        f"     • Tier B (Fit)  : {tier_counts.get('B', 0)}\n"
        f"     • Tier C        : {tier_counts.get('C', 0)}\n"
        f"     • Excluded      : {tier_counts.get('excluded', 0)}\n"
        f"  6. Verified Contacts Harvested : {companies_with_contacts}\n"
        f"  7. Speculative Outreaches Ready: {drafted_outreach}\n"
        f"------------------------------------------------------\n"
        f"  City Breakdown:\n"
    )
    for cty, cnt in sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:8]:
        funnel_report += f"     • {cty:20}: {cnt}\n"
    funnel_report += f"======================================================\n"

    print(funnel_report)
    logger.info(funnel_report)

    return {
        "total_companies": total_stored,
        "on_field": on_field_count,
        "size_counts": size_counts,
        "tier_counts": tier_counts,
        "contacts_found": companies_with_contacts,
        "drafted_outreach": drafted_outreach
    }


def step_run_all(threshold: Optional[float] = None, limit: Optional[int] = 10, dry_run: bool = False, auto_send: bool = False) -> None:
    """Executes both engines: Jobs Engine + Companies Engine, with shared daily cap and combined funnel."""
    logger.info("=== RUNNING FULL PIPELINE (Jobs Engine + Companies Engine) ===")
    
    # 1. Jobs Engine
    logger.info(">>> Stage 1: Running Jobs Engine...")
    scraped_count = step_scrape(dry_run=dry_run)
    matched_count = step_match(threshold=threshold, limit=limit, dry_run=dry_run)
    drafted_count = step_draft(limit=limit, dry_run=dry_run)

    # 2. Companies Engine
    logger.info(">>> Stage 2: Running Company Discovery & Speculative Engine...")
    comp_funnel = step_run_companies(limit=limit, dry_run=dry_run)

    # Combined Funnel Summary
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs")
        total_ingested = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM applications WHERE match_score >= 65.0")
        scored_65 = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM applications WHERE status IN ('drafted', 'approved', 'sent')")
        total_drafted_jobs = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM company_outreach WHERE status IN ('drafted', 'approved', 'sent')")
        total_drafted_comp = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM applications WHERE status IN ('sent', 'replied')")
        jobs_sent = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM company_outreach WHERE status IN ('sent', 'replied')")
        comp_sent = cur.fetchone()[0]

    combined_summary = (
        f"\n======================================================\n"
        f"🎯 JOBPILOT COMBINED FUNNEL REPORT (Jobs + Companies)\n"
        f"======================================================\n"
        f"  • Total Job Postings Ingested : {total_ingested}\n"
        f"  • Target Qualified Jobs (>=65): {scored_65}\n"
        f"  • Drafted Job Applications    : {total_drafted_jobs}\n"
        f"  ----------------------------------------------------\n"
        f"  • Companies Discovered/Stored : {comp_funnel.get('total_companies', 0)}\n"
        f"  • Tier A & B Target Companies : {comp_funnel.get('tier_counts', {}).get('A', 0) + comp_funnel.get('tier_counts', {}).get('B', 0)}\n"
        f"  • Drafted Speculative Mails   : {total_drafted_comp}\n"
        f"  ----------------------------------------------------\n"
        f"  • Total Sends All-Time        : Jobs: {jobs_sent} | Speculative: {comp_sent}\n"
        f"  • Shared Daily Send Limit     : {settings.sending.get('daily_cap', 15)} / day\n"
        f"======================================================\n"
    )
    print(combined_summary)
    logger.info(combined_summary)

    if auto_send:
        logger.info("=== Auto-send enabled: dispatching approved emails ===")
        drafted = list_applications_by_status("drafted")
        for app in drafted:
            contacts = get_contacts_for_job(app["job_id"])
            if contacts:
                update_application(job_id=app["job_id"], status="approved")
        step_send_approved(dry_run=dry_run)
    else:
        logger.info("=== Pipeline Complete. Applications queued in Review Queue & Companies tab. ===")


def step_auto_apply(threshold: Optional[float] = None, limit: Optional[int] = 10, dry_run: bool = False) -> int:
    """
    AUTONOMOUS END-TO-END PIPELINE:
    1. Scrapes latest job openings.
    2. Scores fit against candidate's master resume.
    3. Tailors resume and builds ATS PDF for every matched role.
    4. Generates tailored cold email matching JD requirements.
    5. Automatically dispatches emails to public recruiter contacts via Gmail SMTP.
    """
    logger.info("=== STARTING AUTONOMOUS AUTO-APPLY PIPELINE ===")
    step_scrape(dry_run=dry_run)
    step_match(threshold=threshold, limit=limit, dry_run=dry_run)
    drafted_count = step_draft(limit=limit, dry_run=dry_run)

    # Auto-approve applications that have valid contacts
    drafted_apps = list_applications_by_status("drafted")
    for app in drafted_apps:
        contacts = get_contacts_for_job(app["job_id"])
        if contacts:
            update_application(job_id=app["job_id"], status="approved")

    sent_count = step_send_approved(dry_run=dry_run)
    logger.info("=== AUTO-APPLY FINISHED: %d tailored applications dispatched ===", sent_count)
    return sent_count


def apply_single_job(
    company: str,
    title: str,
    jd_text: str,
    job_url: str = "",
    recipient_email: Optional[str] = None,
    auto_send: bool = True,
    dry_run: bool = False
) -> dict:
    """
    Directly processes any job posting from text or URL:
    1. Parses JD with Gemini 3.8 Flash
    2. Scores fit against master resume
    3. Finds or uses provided HR/recruiter contact email (with MX validation)
    4. Tailors master resume (0 fabrication) and compiles single-column ATS PDF
    5. Writes personalized cold email tailored to the JD
    6. Automatically dispatches via Gmail SMTP if auto_send is True
    """
    init_db()
    master = load_master_resume()

    import hashlib
    clean_url = job_url or f"manual://{company.lower()}-{int(time.time())}"
    job_id = hashlib.sha256(f"{company}_{title}_{clean_url}".encode()).hexdigest()[:16]

    job = Job(
        id=job_id,
        title=title,
        company=company,
        location="Remote / Given",
        url=clean_url,
        description=jd_text,
        source="manual_or_instant",
        recruiter_email=recipient_email
    )
    save_job(job)

    # 1. Parse JD
    logger.info("Parsing JD for '%s' at '%s'...", title, company)
    jd_parsed = parse_job_description(jd_text)
    if not jd_parsed:
        from src.jd_parser import _rule_based_fallback
        jd_parsed = _rule_based_fallback(jd_text)

    # 2. Match Score
    match_res = compute_match_score(jd_parsed, master)

    # 3. Recruiter contact
    final_email = recipient_email
    if not final_email:
        contacts = find_recruiter_contacts(job, check_mx=True)
        if contacts:
            final_email = contacts[0].email

    # 4. Tailor Resume & Compile PDF
    logger.info("Tailoring resume for '%s' at '%s'...", title, company)
    tailored = tailor_resume(master, jd_parsed)
    pdf_path, json_path = build_tailored_resume_files(tailored, company, jd_parsed.role)

    # 5. Generate Tailored Email
    logger.info("Drafting personalized cold email...")
    subject, body = generate_application_email(
        job=job,
        jd_parsed=jd_parsed,
        tailored_resume=tailored,
        master_resume=master,
        recruiter_name=None
    )

    result = {
        "job_id": job_id,
        "company": company,
        "role": jd_parsed.role,
        "match_score": match_res.match_score,
        "recipient_email": final_email,
        "pdf_path": str(pdf_path),
        "json_path": str(json_path),
        "subject": subject,
        "body": body,
        "sent": False,
        "message": ""
    }

    update_application(
        job_id=job_id,
        status="approved" if final_email else "drafted",
        match_score=match_res.match_score,
        resume_path=str(pdf_path),
        tailored_json_path=str(json_path),
        email_subject=subject,
        email_body=body,
        layout_warning=getattr(tailored, "layout_warning", False),
        page_fill=json.dumps(tailored.page_fill) if getattr(tailored, "page_fill", None) else None
    )

    # 6. Send if enabled and contact exists
    if auto_send and final_email:
        logger.info("Auto-sending application email to %s...", final_email)
        ok, msg = send_application_email(
            job_id=job_id,
            recipient_email=final_email,
            subject=subject,
            body=body,
            pdf_attachment_path=pdf_path,
            company_name=company,
            dry_run=dry_run,
            ignore_hours=dry_run
        )
        result["sent"] = ok
        result["message"] = msg
    elif not final_email:
        result["message"] = "No recruiter email found in JD text. Saved to Review Queue (marked 'apply via link')."
    else:
        result["message"] = "Application drafted and queued in Review Queue."

    return result


def step_contacts(limit: Optional[int] = 10, dry_run: bool = False) -> int:
    """Discovers and verifies public HR/recruiter contacts for applications."""
    init_db()
    apps = list_applications_by_status("matched") + list_applications_by_status("drafted") + list_applications_by_status("approved")
    if limit and len(apps) > limit:
        apps = apps[:limit]

    logger.info("Discovering recruiter contacts for %d applications...", len(apps))
    found_count = 0
    for app in apps:
        job_id = app["job_id"]
        job_data = get_job(job_id)
        if not job_data:
            continue
        job_obj = Job(**job_data)
        contacts = find_recruiter_contacts(job_obj, check_mx=True)
        if contacts:
            logger.info("Found %d verified contact(s) for %s (%s)", len(contacts), job_data["company"], contacts[0].email)
            found_count += len(contacts)
        else:
            logger.info("No public contact found for %s (%s). Marking 'needs_manual_contact'", job_data["company"], job_data["title"])
            if not dry_run and app["status"] in ("matched", "drafted"):
                update_application(job_id=job_id, status="needs_manual_contact")
    logger.info("Contact discovery complete. %d contacts verified.", found_count)
    return found_count


def main():
    parser = argparse.ArgumentParser(description="JobPilot: Autonomous Job Discovery & Tailored Application Pipeline")
    parser.add_argument(
        "command",
        choices=[
            "diagnose", "scrape", "match", "contacts", "draft", "send-approved",
            "send-worker", "followups", "run-all", "auto-apply", "apply-job",
            "discover-companies", "enrich-companies", "score-companies",
            "company-contacts", "draft-companies", "run-companies", "clear-db",
            "test-email", "send-diagnose"
        ],
        help="Pipeline stage to execute"
    )
    parser.add_argument("--threshold", type=float, default=None, help="Minimum match score threshold (0-100)")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of items to process per batch")
    parser.add_argument("--city", type=str, default=None, help="Target city filter (e.g. Bangalore, Kochi, Trivandrum)")
    parser.add_argument("--tier", type=str, default="A,B", help="Comma-separated tiers for company contacts (e.g. 'A,B')")
    parser.add_argument("--match-limit", type=int, default=None, help="Match limit for run-all")
    parser.add_argument("--draft-limit", type=int, default=None, help="Draft limit for run-all")
    parser.add_argument("--company", type=str, default="Target Company", help="Company name (for apply-job)")
    parser.add_argument("--title", type=str, default="AI/ML Engineer", help="Job title (for apply-job)")
    parser.add_argument("--jd", type=str, default="", help="Job description text (for apply-job)")
    parser.add_argument("--url", type=str, default="", help="Job posting URL (for apply-job)")
    parser.add_argument("--email", type=str, default="", help="HR/Recruiter email (for apply-job)")
    parser.add_argument("--auto-send", action="store_true", help="Automatically dispatch emails after drafting")
    parser.add_argument("--ignore-hours", action="store_true", help="Bypass the 9:00 - 18:00 sending window")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying DB or sending emails")

    args = parser.parse_args()

    if args.command == "diagnose":
        from src.diagnose import run_diagnosis
        print("Running JobPilot system diagnosis and audit...")
        report = run_diagnosis()
        print(f"Audit complete! Diagnostic report written to output/diagnosis.md")
        print("\n=== Audit Summary ===")
        print("\n".join(report.split("\n")[:40]))
    elif args.command == "scrape":
        step_scrape(dry_run=args.dry_run)
    elif args.command == "match":
        step_match(threshold=args.threshold, limit=args.limit, dry_run=args.dry_run)
    elif args.command == "contacts":
        step_contacts(limit=args.limit, dry_run=args.dry_run)
    elif args.command == "draft":
        step_draft(limit=args.limit, dry_run=args.dry_run)
    elif args.command == "send-approved":
        step_send_approved(dry_run=args.dry_run, ignore_hours=args.ignore_hours)
    elif args.command == "send-worker":
        from src.send_worker import get_send_worker, IST
        print("=== JobPilot Background Send Worker Started ===")
        print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}")
        print(f"Ignore Hours: {args.ignore_hours}")
        print("Press Ctrl+C to terminate.")
        worker = get_send_worker()
        worker.start(dry_run=args.dry_run, ignore_hours=args.ignore_hours)
        try:
            while True:
                st_info = worker.get_status()
                print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] Queued: {st_info['queued_count']} | Sent: {st_info['total_sent']} | Failed: {st_info['total_failed']} | Task: {st_info['current_task']}")
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopping send worker...")
            worker.stop()
            print("Send worker stopped.")
    elif args.command == "send-diagnose":
        from src.send_diagnose import run_send_diagnosis
        print("Running JobPilot Send Diagnostic Subsystem...")
        report = run_send_diagnosis()
        print(report)
    elif args.command == "test-email":
        from src.sender import send_test_email
        target = args.email or settings.candidate_email or settings.gmail_user
        print(f"Sending live verification test email to: {target}...")
        ok, msg = send_test_email(to_email=target)
        if ok:
            print(f"SUCCESS: {msg}")
        else:
            print(f"FAILED: {msg}")
    elif args.command == "followups":
        step_followups(dry_run=args.dry_run)
    elif args.command == "run-all":
        m_limit = args.match_limit or args.limit
        step_run_all(threshold=args.threshold, limit=m_limit, dry_run=args.dry_run, auto_send=args.auto_send)
    elif args.command == "auto-apply":
        step_auto_apply(threshold=args.threshold, limit=args.limit, dry_run=args.dry_run)
    elif args.command == "apply-job":
        if not args.jd and not args.url:
            print("Error: Please provide --jd '...' or --url '...' to apply.")
            return
        res = apply_single_job(
            company=args.company,
            title=args.title,
            jd_text=args.jd or f"Job opening at {args.company} for {args.title}. Apply at {args.url}",
            job_url=args.url,
            recipient_email=args.email or None,
            auto_send=args.auto_send,
            dry_run=args.dry_run
        )
        print("\n=== Application Result ===")
        print(f"Company: {res['company']} | Role: {res['role']}")
        print(f"Match Score: {res['match_score']:.1f}%")
        print(f"Recipient: {res['recipient_email']}")
        print(f"Tailored PDF: {res['pdf_path']}")
        print(f"Status: {'SENT' if res['sent'] else 'SAVED'}")
        print(f"Message: {res['message']}")
    elif args.command == "discover-companies":
        res = step_discover_companies(city=args.city, limit=args.limit, dry_run=args.dry_run)
        print(f"Discovered: {res.get('discovered', 0)} | Stored/Updated: {res.get('processed', 0)}")
    elif args.command == "enrich-companies":
        res = step_enrich_companies(limit=args.limit, dry_run=args.dry_run)
        print(f"Enrichment Complete: {res}")
    elif args.command == "score-companies":
        res = step_score_companies(dry_run=args.dry_run)
        print(f"Scoring Complete: {res}")
    elif args.command == "company-contacts":
        tiers = [t.strip().upper() for t in args.tier.split(",") if t.strip()]
        res = step_company_contacts(tier_filter=tiers, limit=args.limit, dry_run=args.dry_run)
        print(f"Contacts Harvested: {res}")
    elif args.command == "draft-companies":
        res = step_draft_companies(limit=args.limit, dry_run=args.dry_run)
        print(f"Speculative Drafts Complete: {res}")
    elif args.command == "run-companies":
        step_run_companies(city=args.city, limit=args.limit, dry_run=args.dry_run)
    elif args.command == "clear-db":
        from src.db import clear_database
        print("Clearing database records...")
        deleted = clear_database()
        print("Database cleared successfully!")
        for tbl, cnt in deleted.items():
            print(f"  • {tbl}: {cnt} rows deleted")


if __name__ == "__main__":
    main()

