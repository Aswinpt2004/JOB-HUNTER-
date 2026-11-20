import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.db import (
    init_db,
    get_company,
    get_company_contacts,
    save_company_outreach,
    get_company_outreach,
    list_companies,
    log_event
)
from src.email_writer import (
    MANDATORY_OPTOUT,
    ROLE_LENS_HOOKS,
    BANNED_PHRASES,
    score_email_tone
)
from src.matcher import classify_role
from src.models import (
    Company,
    CompanyOutreach,
    Job,
    MasterResume,
    RecruiterContact,
    TailoredResume
)
from src.pdf_builder import build_tailored_resume_files
from src.resume_tailor import tailor_resume
from src.verifier import verify_no_fabrication

logger = logging.getLogger("jobpilot.companies.speculative")

SPECULATIVE_BANNED_EXTRA = [
    r'i\s+know\s+you\s+are\s+not\s+hiring',
    r'give\s+me\s+a\s+job',
    r'hire\s+me\b',
    r'guarantee',
    r'urgent\s+job',
    r'need\s+a\s+job\s+badly',
]


def determine_dominant_role_lens(field_tags: List[str], company_name: str) -> str:
    """Selects the best matching canonical role lens for the company domain."""
    tags_str = " ".join(field_tags).lower()
    if any(k in tags_str for k in ["computer_vision", "drone", "uav", "surveillance", "video_analytics", "yolo", "opencv"]):
        return "Computer Vision / Drone / Surveillance"
    if any(k in tags_str for k in ["llm", "rag", "agent", "generative_ai", "nlp"]):
        return "LLM / GenAI / RAG / Agents"
    if any(k in tags_str for k in ["document_ai", "healthcare_ai", "medical", "idp"]):
        return "Document AI / Healthcare AI"
    if any(k in tags_str for k in ["federated", "privacy", "graph"]):
        return "Federated / Privacy / Graph ML / Research"
    if any(k in tags_str for k in ["backend", "fastapi", "django"]):
        return "Backend / Full-stack with AI"
    return "Generic ML / Data Science"


def generate_pseudo_jd(company: Dict[str, Any]) -> Tuple[Job, str]:
    """Builds a pseudo-JD from company public metadata to feed into the tailoring engine."""
    cname = company["name"]
    city = company.get("city") or "Bangalore"
    field_tags = company.get("field_tags") or []
    dominant_lens = determine_dominant_role_lens(field_tags, cname)

    tag_desc = ", ".join([t.replace("_", " ") for t in field_tags])
    notes = company.get("notes") or ""

    synthetic_desc = f"""
    About {cname}: A technology leader located in {city}.
    Key focus areas: {tag_desc}.
    Company profile notes: {notes}.
    Core technologies & skills: Python, PyTorch, Deep Learning, Machine Learning, Computer Vision, LLMs, REST APIs.
    Candidate profile: Fresher / Junior AI/ML Engineer with strong problem-solving abilities, clean code standards, and practical experience.
    """

    pseudo_job = Job(
        id=f"speculative_{company['id']}",
        company=cname,
        title=f"AI/ML Engineer ({dominant_lens.split('/')[0].strip()})",
        location=f"{city}, India",
        url=company.get("careers_url") or company.get("website") or (f"https://{company['domain']}" if company.get("domain") else ""),
        description=synthetic_desc,
        source="speculative_engine",
        role_lens=dominant_lens,
        role_tier="Tier A"
    )

    return (pseudo_job, dominant_lens)


def generate_speculative_email(
    company: Dict[str, Any],
    contact: Optional[RecruiterContact],
    role_lens: str
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Drafts a polite, humble, genuine cold speculative outreach email (90-150 words).
    Respects mandatory opt-out footer, lens hook, and no empty flattery.
    """
    cname = company["name"]
    candidate_name = settings.candidate_name
    candidate_email = settings.candidate_email
    candidate_phone = settings.user_profile.get("phone", "+91 88913 81713")

    # Recipient greeting
    if contact and contact.name and "team" not in contact.name.lower():
        first_name = contact.name.split()[0].title()
        greeting = f"Dear {first_name},"
    else:
        greeting = f"Dear Hiring Team at {cname},"

    # Specific reference to company domain
    field_tags = company.get("field_tags") or []
    domain_mention = "work in machine learning and software engineering"
    if "computer_vision" in field_tags or "surveillance" in field_tags or "drone" in field_tags:
        domain_mention = f"innovations in computer vision and intelligent video analytics at {cname}"
    elif "generative_ai" in field_tags or "llm" in field_tags or "rag" in field_tags:
        domain_mention = f"applications in generative AI and intelligent agents at {cname}"
    elif "healthcare_ai" in field_tags or "document_ai" in field_tags:
        domain_mention = f"initiatives in document intelligence and applied AI systems at {cname}"

    hook = ROLE_LENS_HOOKS.get(role_lens, ROLE_LENS_HOOKS["Generic ML / Data Science"])

    subject = f"Fresher AI/ML Engineer interested in opportunities at {cname} | {candidate_name}"

    body = f"""{greeting}

I have been following {domain_mention}. As an M.Sc. Machine Intelligence graduate with practical AI/ML experience, I am writing to respectfully express interest in junior engineering roles.

{hook}

I recognize you may not have an active posting open right now. If there is any current or upcoming opening where my profile could be useful, I would be grateful if you could consider it; I would also be glad to be kept in mind for future roles.

I have attached my 2-page tailored resume for your review. Thank you sincerely for your time.

Best regards,
{candidate_name}
{candidate_phone} | {candidate_email}

{MANDATORY_OPTOUT}"""

    # Run tone critic
    tone_report = score_email_tone(body)

    # Check additional speculative banned phrases
    for bad_pat in SPECULATIVE_BANNED_EXTRA:
        if re.search(bad_pat, body, re.IGNORECASE):
            tone_report["score"] = max(0.0, tone_report["score"] - 3.0)
            tone_report.setdefault("banned_phrases", []).append(bad_pat)

    return (subject, body, tone_report)


def draft_single_speculative_application(company_id: int, master: MasterResume) -> Optional[int]:
    """Generates tailored pseudo-JD resume and cold email for an eligible company."""
    company = get_company(company_id)
    if not company:
        return None

    # Check eligibility: Tier A or B, not under 20, not excluded
    tier = company.get("tier")
    size_st = company.get("size_status")
    if tier not in ("A", "B"):
        logger.info("Company '%s' is Tier %s; skipping speculative draft.", company["name"], tier)
        return None

    if size_st == "under_20":
        logger.info("Company '%s' is under 20 employees; skipping speculative draft.", company["name"])
        return None

    # Get contacts and enforce require_contact_email
    contacts = get_company_contacts(company_id)
    if settings.require_contact_email and not contacts:
        logger.info("Company '%s' has NO contact email in DB (require_contact_email=True); rejecting draft.", company["name"])
        return None

    top_contact = None
    contact_id = None
    if contacts:
        top_contact_dict = contacts[0]
        contact_id = top_contact_dict["id"]
        top_contact = RecruiterContact(
            company_id=company_id,
            email=top_contact_dict["email"],
            name=top_contact_dict.get("name"),
            role=top_contact_dict.get("role")
        )

    # 1. Generate Pseudo JD and dominant role lens
    pseudo_job, dominant_lens = generate_pseudo_jd(company)

    from src.models import JDParsed
    tag_desc = ", ".join([t.replace("_", " ") for t in (company.get("field_tags") or [])])
    jd_parsed = JDParsed(
        role=f"AI/ML Engineer ({dominant_lens.split('/')[0].strip()})",
        seniority="Fresher",
        must_have_skills=["Python", "PyTorch", "Machine Learning", "Deep Learning"],
        nice_to_have_skills=["Computer Vision", "LLMs", "FastAPI"],
        keywords=company.get("field_tags") or [],
        responsibilities=[f"Applied AI/ML development in {tag_desc or 'data and machine intelligence'}."],
        location=company.get("city") or "Bangalore"
    )

    # 2. Tailor resume using exact-format 2-page engine
    tailored = tailor_resume(master, jd_parsed)
    # Verification check against master
    is_valid, violations = verify_no_fabrication(tailored, master)
    if not is_valid:
        from src.verifier import sanitize_tailored_resume
        tailored = sanitize_tailored_resume(tailored, master)

    pdf_path, json_path = build_tailored_resume_files(tailored, company["name"], jd_parsed.role)

    # 3. Draft Speculative cold outreach email
    subject, body, tone_report = generate_speculative_email(company, top_contact, dominant_lens)

    # 4. Save to company_outreach table (mark 'needs_review' if size unknown until confirmed)
    outreach_status = "needs_review" if size_st == "unknown" else "drafted"

    outreach = CompanyOutreach(
        company_id=company_id,
        contact_id=contact_id,
        mode="speculative",
        resume_path=str(pdf_path),
        email_subject=subject,
        email_body=body,
        status=outreach_status
    )

    outreach_id = save_company_outreach(outreach)
    logger.info("Drafted speculative outreach #%d for '%s' (Lens: %s, Tone: %.1f/10)",
                outreach_id, company["name"], dominant_lens, tone_report["score"])

    return outreach_id


def run_company_drafting(limit: Optional[int] = None) -> Dict[str, Any]:
    """Drafts speculative applications for eligible Tier A & B companies with verified contacts."""
    init_db()
    logger.info("=== Starting Speculative Application Drafting ===")

    from src.pipeline import load_master_resume
    master = load_master_resume()

    eligible = list_companies({"tier": "A"}) + list_companies({"tier": "B"})
    # Deduplicate
    seen_ids = set()
    candidates = []
    for c in eligible:
        if c["id"] not in seen_ids:
            seen_ids.add(c["id"])
            candidates.append(c)

    if limit:
        candidates = candidates[:limit]

    logger.info("Evaluating %d Tier A/B companies for speculative drafting...", len(candidates))

    drafted_count = 0
    skipped_unverified_size = 0
    skipped_existing = 0

    for c in candidates:
        cid = c["id"]
        # Check if already drafted
        existing = get_company_outreach(cid)
        if existing and existing.get("status") in ("drafted", "approved", "sent"):
            skipped_existing += 1
            continue

        if c.get("size_status") == "under_20":
            skipped_unverified_size += 1
            continue

        oid = draft_single_speculative_application(cid, master)
        if oid:
            drafted_count += 1

    logger.info("Speculative drafting complete: %d drafted, %d skipped unverified size, %d already drafted.",
                drafted_count, skipped_unverified_size, skipped_existing)

    return {
        "candidates": len(candidates),
        "drafted": drafted_count,
        "skipped_unverified_size": skipped_unverified_size,
        "skipped_existing": skipped_existing
    }
