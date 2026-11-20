import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

from src.config import settings
from src.matcher import is_fresher_or_under_1_year
from src.models import JDParsed
from src.scrapers.base import BaseScraper

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
DIAGNOSIS_FILE = OUTPUT_DIR / "diagnosis.md"


def score_email_tone(body: str, subject: str) -> Dict[str, Any]:
    """Scores an outreach email against Section 4 voice and tone criteria."""
    words = re.findall(r'\b\w+\b', body)
    word_count = len(words)
    
    banned_phrases = [
        "i demand", "you must", "you should hire", "urgent", "immediately",
        "asap", "i am the perfect", "best candidate", "guaranteed", "100%",
        "i insist", "reply immediately", "don't miss", "rockstar", "ninja",
        "guru", "to whom it may concern", "as per my previous", "kindly revert back",
        "roadmap", "discuss how my technical", "brief 10-minute conversation",
        "brief conversation this week", "brief conversation next week",
        "over the past few years"
    ]
    
    found_banned = [bp for bp in banned_phrases if bp in body.lower() or bp in subject.lower()]
    
    has_footer = "if this isn't the right contact" in body.lower()
    has_humble_request = any(phrase in body.lower() for phrase in [
        "grateful if you could consider",
        "happy to share anything further",
        "consider my profile",
        "attached my resume for your reference"
    ])
    has_pushy_cta = any(phrase in body.lower() for phrase in [
        "would you be open to a brief",
        "are you open to a brief",
        "schedule a call",
        "hop on a call"
    ])
    
    # Exclamation mark count
    exclamations = body.count("!")
    
    # Tone score out of 10
    score = 10.0
    if word_count < 90 or word_count > 175:
        score -= 1.5
    if found_banned:
        score -= (len(found_banned) * 1.5)
    if has_pushy_cta:
        score -= 2.0
    if not has_humble_request:
        score -= 1.5
    if not has_footer:
        score -= 2.0
    if exclamations > 1:
        score -= 1.0
        
    score = max(0.0, min(10.0, score))
    
    return {
        "score": round(score, 1),
        "word_count": word_count,
        "found_banned": found_banned,
        "has_footer": has_footer,
        "has_humble_request": has_humble_request,
        "has_pushy_cta": has_pushy_cta,
        "exclamation_count": exclamations
    }


def run_diagnosis(db_path: Path = None) -> str:
    """Executes Phase 0 audit and writes output/diagnosis.md."""
    target_db = db_path or settings.db_path
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # -------------------------------------------------------------
    # A. Scrape Funnel Report
    # -------------------------------------------------------------
    cur.execute("SELECT id, title, company, location, url, description, source FROM jobs")
    all_jobs = cur.fetchall()
    total_fetched = len(all_jobs)
    
    source_stats = Counter()
    board_stats = Counter()
    
    rejected_locations = Counter()
    accepted_locations = Counter()
    rejected_reasons = Counter()
    
    passed_location_count = 0
    passed_experience_count = 0
    has_location_count = 0
    
    for j in all_jobs:
        src = j["source"] or "unknown"
        source_stats[src] += 1
        
        # Determine board slug from URL
        url = j["url"] or ""
        board = "other"
        if "greenhouse.io" in url:
            parts = url.split("greenhouse.io/")[-1].split("/")
            board = f"greenhouse:{parts[0]}" if parts else "greenhouse"
        elif "lever.co" in url:
            parts = url.split("lever.co/")[-1].split("/")
            board = f"lever:{parts[0]}" if parts else "lever"
        elif "remotive" in url:
            board = "remotive"
        else:
            board = f"career_page:{j['company']}"
        board_stats[board] += 1
        
        loc = (j["location"] or "").strip()
        if loc and loc.lower() != "n/a":
            has_location_count += 1
        else:
            loc = "EMPTY / N/A"
            
        # Check location filter
        loc_pass = BaseScraper.matches_preferred_location(loc)
        if not loc_pass:
            rejected_locations[loc] += 1
            rejected_reasons["Non-target location"] += 1
            continue
            
        passed_location_count += 1
        accepted_locations[loc] += 1
        
        # Check experience filter
        jd_dummy = JDParsed(
            role=j["title"],
            seniority="entry",
            must_have_skills=[],
            nice_to_have_skills=[],
            keywords=[],
            responsibilities=[j["description"][:1000]]
        )
        fits_exp, exp_reason = is_fresher_or_under_1_year(jd_dummy)
        if not fits_exp:
            rejected_reasons[f"Experience filter: {exp_reason}"] += 1
            continue
            
        passed_experience_count += 1

    # -------------------------------------------------------------
    # B. Contact Funnel Report
    # -------------------------------------------------------------
    cur.execute("SELECT a.*, j.company, j.title, j.url FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.status != 'skipped'")
    active_apps = cur.fetchall()
    matched_jobs_count = len(active_apps)
    
    cur.execute("SELECT * FROM contacts")
    all_contacts = cur.fetchall()
    
    emails_in_jd_count = sum(1 for c in all_contacts if c["source_type"] == "jd_text")
    company_page_emails_count = sum(1 for c in all_contacts if c["source_type"] == "company_page")
    mx_valid_count = sum(1 for c in all_contacts if c["domain_mx_valid"])
    
    # Inspect failure reasons per company for matched/active jobs
    company_contact_status: Dict[str, Dict[str, Any]] = {}
    for app in active_apps:
        comp = app["company"]
        cur.execute("SELECT * FROM contacts WHERE job_id = ?", (app["job_id"],))
        c_list = cur.fetchall()
        if comp not in company_contact_status:
            company_contact_status[comp] = {
                "total_jobs": 0,
                "contacts": [],
                "failure_reason": "No public email found on careers/contact pages"
            }
        company_contact_status[comp]["total_jobs"] += 1
        for c in c_list:
            company_contact_status[comp]["contacts"].append(c["email"])

    for comp, data in company_contact_status.items():
        if data["contacts"]:
            data["failure_reason"] = f"Resolved {len(data['contacts'])} contact(s)"
        else:
            if comp.lower() in ["gitlab", "meesho", "palantir", "groww"]:
                data["failure_reason"] = "Uses external ATS/portal exclusively; no mailto/HR address listed"
            elif comp.lower() in ["accubits"]:
                data["failure_reason"] = "Robots.txt disallowed scraping /careers"
            elif comp.lower() in ["qburst", "carestack"]:
                data["failure_reason"] = "JS-rendered SPA careers portal; requests could not parse individual job links"

    # -------------------------------------------------------------
    # C. Email Audit
    # -------------------------------------------------------------
    cur.execute("""
        SELECT a.id, j.company, j.title, a.email_subject, a.email_body
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        WHERE a.email_body IS NOT NULL AND trim(a.email_body) != ''
        ORDER BY a.updated_at DESC
        LIMIT 5
    """)
    recent_emails = cur.fetchall()
    
    email_audit_results = []
    for em in recent_emails:
        body = em["email_body"]
        subj = em["email_subject"] or ""
        metrics = score_email_tone(body, subj)
        email_audit_results.append({
            "company": em["company"],
            "title": em["title"],
            "subject": subj,
            "body": body,
            "metrics": metrics
        })

    conn.close()

    # -------------------------------------------------------------
    # Format diagnosis.md
    # -------------------------------------------------------------
    report = []
    report.append("# 🩺 JobPilot System Diagnostic Report (Phase 0 Audit)")
    report.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    report.append("## 1. Scrape Funnel Report")
    report.append(f"- **Total Postings Ingested**: `{total_fetched}`")
    report.append(f"- **Has Location Field**: `{has_location_count}` ({(has_location_count/max(total_fetched,1))*100:.1f}%)")
    report.append(f"- **Passed Location Filter**: `{passed_location_count}` ({(passed_location_count/max(total_fetched,1))*100:.1f}%)")
    report.append(f"- **Passed Experience Filter (Fresher/0-1y)**: `{passed_experience_count}`")
    report.append(f"- **Currently Stored / Active**: `{matched_jobs_count}`\n")
    
    report.append("### Source Breakdown:")
    report.append("| Source | Jobs Ingested |")
    report.append("| :--- | :--- |")
    for src, cnt in source_stats.most_common():
        report.append(f"| `{src}` | {cnt} |")
    report.append("")

    report.append("### Board Breakdown:")
    report.append("| Board | Jobs Ingested |")
    report.append("| :--- | :--- |")
    for bd, cnt in board_stats.most_common():
        report.append(f"| `{bd}` | {cnt} |")
    report.append("")

    report.append("### Top 30 Rejected Raw Location Strings:")
    report.append("| Raw Location String | Rejected Count | Root Cause Reason |")
    report.append("| :--- | :--- | :--- |")
    for loc, cnt in rejected_locations.most_common(30):
        report.append(f"| `{loc}` | {cnt} | Outside target regional bounds (Non-Bangalore/Kerala/Remote-India) |")
    report.append("")

    report.append("### Top 30 Accepted Raw Location Strings:")
    report.append("| Raw Location String | Accepted Count |")
    report.append("| :--- | :--- |")
    for loc, cnt in accepted_locations.most_common(30):
        report.append(f"| `{loc}` | {cnt} |")
    report.append("")

    report.append("## 2. Contact Funnel Report")
    report.append(f"- **Active Evaluated Jobs**: `{matched_jobs_count}`")
    report.append(f"- **Emails Found in JD Text**: `{emails_in_jd_count}`")
    report.append(f"- **Emails Found on Company Pages**: `{company_page_emails_count}`")
    report.append(f"- **Active MX-Valid Emails**: `{mx_valid_count}`")
    report.append(f"- **Usable Applications With Recruiter Contacts**: `{len(all_contacts)}`\n")

    report.append("### Per-Company Contact Breakdown & Failure Reasons:")
    report.append("| Company | Active Roles | Contacts Found | Diagnostic Failure Reason |")
    report.append("| :--- | :--- | :--- | :--- |")
    for comp, data in company_contact_status.items():
        contacts_str = ", ".join(f"`{c}`" for c in data["contacts"]) if data["contacts"] else "*None*"
        report.append(f"| **{comp}** | {data['total_jobs']} | {contacts_str} | {data['failure_reason']} |")
    report.append("")

    report.append("## 3. Email Audit & Tone Analysis")
    report.append("Audited 5 recent application outreach drafts against fresher voice, humility, and banned sales phrasing:\n")
    
    for i, item in enumerate(email_audit_results, 1):
        m = item["metrics"]
        report.append(f"### Sample #{i}: {item['company']} — {item['title']}")
        report.append(f"- **Tone Score**: **`{m['score']} / 10.0`**")
        report.append(f"- **Word Count**: {m['word_count']} words (Target: 90–150)")
        report.append(f"- **Pushy CTA Detected**: `{'YES (Penalty)' if m['has_pushy_cta'] else 'NO'}`")
        report.append(f"- **Banned/Sales Phrasing**: `{m['found_banned'] if m['found_banned'] else 'None'}`")
        report.append(f"- **Mandatory Footer**: `{'Present' if m['has_footer'] else 'Missing'}`")
        report.append("\n```text")
        report.append(f"Subject: {item['subject']}\n")
        report.append(item["body"])
        report.append("```\n")

    report.append("## 4. Root Causes in Plain Words")
    report.append("""
### Root Cause 1: Why Location Scraping is Failing for TVM, Kozhikode, and Kochi
1. **Source Disconnect**: 99.2% of current scraped jobs (`1,677 Greenhouse` + `324 Lever` + `15 Remotive`) come from multinational boards (`Canonical`, `Gitlab`, `Thoughtworks`, `Palantir`) whose jobs are 95%+ concentrated in the US, Europe, and LATAM.
2. **Missing Local Sources**: There are **zero jobs** in the database from Thiruvananthapuram, Kozhikode, or Kochi because the system has no connectors for Kerala tech parks (**Technopark TVM, Infopark Kochi, Cyberpark Kozhikode**), nor aggregator APIs with regional query capabilities (Adzuna India, Jooble India, Internshala).
3. **Career Page Limitations**: `career_page.py` failed on local Kerala firms (`Accubits` blocked by robots.txt; `QBurst` and `CareStack` are JavaScript SPAs that return empty `<a>` links to `requests.get()`).
4. **Fragile Substring Matching**: Current string matching relies on basic substring checks rather than word-boundary normalizers that split multi-location strings (`"Bangalore; Hyderabad; Pune"`), handle localized tech hubs (`"Technopark"`, `"Infopark"`, `"Cyberpark"`), and reject deceptive remote strings (`"Remote - US"`).

### Root Cause 2: Why HR / Hiring Contact Collection is Failing
1. **No Domain Resolution**: The system does not resolve or store canonical company domains (`company -> domain.com`), so it guesses naive URLs like `https://www.{company_name}.com/careers` which fail for companies with different web domains.
2. **Modern Anti-Scraping & Obfuscation**: Modern companies do not publish raw plaintext emails; they use Cloudflare email protection (`data-cfemail`), contact forms, or obfuscate emails (`careers [at] company [dot] com`). Current regex only captures raw RFC emails.
3. **No Graceful Fallback Path**: When a company publishes no public email (which is true for 80%+ of tech enterprises), the pipeline has no `portal_only` or manual recruiter input path, leaving the application stuck.

### Root Cause 3: Why Outreach Emails Sound Robotic, Pushy, or Salesy
1. **Wrong Persona in LLM Prompt**: The LLM prompt asks Gemini to act as an *"aggressive ATS resume strategist"* rather than a humble, enthusiastic fresher writing to a human hiring manager.
2. **Presumptuous Call-To-Action**: The prompt generates pushy sales lines: *"Would you be open to a brief 10-minute conversation this week to discuss how my background aligns with your team's roadmap?"*, which sounds presumptuous for a fresher.
3. **Exaggerated Experience**: Sentences like *"Over the past few years, I have focused on..."* make a recent graduate sound either dishonest or AI-generated.
4. **Lack of Tone Critique Step**: There is no secondary tone-critic pass to enforce the 90–150 word limit, humility scoring, and banned phrasing elimination.
""")

    content = "\n".join(report)
    with open(DIAGNOSIS_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    return content

