import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.config import settings
from src.contacts import EMAIL_REGEX, is_valid_email_syntax, verify_mx_record
from src.db import (
    init_db,
    save_company,
    save_company_contact,
    save_company_signal,
    get_company_by_domain,
    get_company_by_name
)
from src.models import Company, RecruiterContact, CompanySignal

logger = logging.getLogger("jobpilot.companies.importer")


def normalize_city_name(raw_city: str) -> str:
    """Standardizes Kerala / India city locations from directory strings."""
    c = raw_city.lower()
    if "trivandrum" in c or "technopark" in c or "thiruvananthapuram" in c:
        return "Thiruvananthapuram"
    if "kochi" in c or "infopark" in c or "cochin" in c:
        return "Kochi"
    if "kozhikode" in c or "calicut" in c or "cyberpark" in c:
        return "Kozhikode"
    if "bangalore" in c or "bengaluru" in c:
        return "Bangalore"
    return raw_city.strip()


def extract_field_tags(role_text: str, note_text: str) -> List[str]:
    """Extracts candidate-relevant domain tags from role description and notes."""
    combined = f"{role_text} {note_text}".lower()
    tags = set()

    if any(k in combined for k in ["computer vision", " cv ", "cv)", "yolo", "opencv", "video analytics"]):
        tags.add("computer_vision")
    if any(k in combined for k in ["nlp", "natural language"]):
        tags.add("nlp")
    if any(k in combined for k in ["llm", "large language model", "rag"]):
        tags.add("llm")
        tags.add("rag")
    if any(k in combined for k in ["genai", "generative ai"]):
        tags.add("generative_ai")
    if any(k in combined for k in ["document", "document intelligence", "idp", "report extraction"]):
        tags.add("document_ai")
    if any(k in combined for k in ["machine learning", "deep learning", "ai/ml", "ai developer", "ml engineer"]):
        tags.add("ai_ml")
        tags.add("machine_learning")
    if "python" in combined:
        tags.add("python")
    if any(k in combined for k in ["edge ai", "edge"]):
        tags.add("edge_ai")
    if "azure" in combined:
        tags.add("cloud_ai")
    if any(k in combined for k in ["pytorch", "torch"]):
        tags.add("pytorch")

    if not tags:
        tags = {"ai_ml", "python", "computer_vision", "llm"}
    return sorted(list(tags))


def parse_size_info(size_note: str) -> Tuple[int, Optional[int], Optional[int], float, str, str, str]:
    """
    Parses employee size constraints from CSV size notes.
    Returns: (employee_min, employee_max, employee_estimate, size_confidence, size_source, size_evidence, size_status)
    """
    s = (size_note or "").strip()
    s_lower = s.lower()

    if "large group" in s_lower:
        return (100, 5000, 500, 0.85, "CSV size note: Large group", s, "likely_20plus")
    if "17+ years" in s_lower:
        return (50, 500, 150, 0.80, "CSV size note: 17+ years in business", s, "likely_20plus")

    # Explicit numbers
    nums = [int(n) for n in re.findall(r'\b\d+\b', s)]
    if nums and max(nums) >= 20:
        val = max(nums)
        return (val, val * 3, val, 0.80, "CSV size note: Explicit count", s, "confirmed_20plus")

    # Default unverified
    return (0, None, None, 0.0, "CSV: Not verified", s or "Needs manual size verification before outreach", "unknown")


def calculate_fit(fresher_fit: str, field_tags: List[str]) -> Tuple[float, str]:
    """Calculates field fit score (0-100) and assigned tier from fresher fit signal and tags."""
    ff = fresher_fit.lower().strip()
    score = 75.0
    tier = "B"

    if "high" in ff and "medium" not in ff and "low" not in ff:
        score = 92.0
        tier = "A"
    elif "medium-high" in ff or "high-medium" in ff:
        score = 86.0
        tier = "A"
    elif "medium" in ff and "low" not in ff:
        score = 78.0
        tier = "B"
    elif "low-medium" in ff:
        score = 70.0
        tier = "B"
    elif "low" in ff:
        score = 60.0
        tier = "C"

    # Boost score slightly if core tags (computer_vision, document_ai, llm) match user resume strongly
    if "computer_vision" in field_tags or "document_ai" in field_tags:
        score = min(98.0, score + 4.0)
    if "rag" in field_tags or "llm" in field_tags:
        score = min(98.0, score + 3.0)

    if score >= 85.0:
        tier = "A"
    elif score >= 68.0:
        tier = "B"
    else:
        tier = "C"

    return (score, tier)


def import_companies_from_csv(
    csv_path: Path = Path("data/ai_hr_contacts.csv"),
    check_mx: bool = True
) -> Dict[str, Any]:
    """
    Imports real companies and HR contacts from ai_hr_contacts.csv into SQLite.
    Performs DNS MX checks, assigns size status, field tags, and stores signals.
    """
    init_db()
    if not csv_path.exists():
        raise FileNotFoundError(f"Contacts CSV not found at {csv_path.resolve()}")

    logger.info("=== Importing Production Companies & Contacts from %s ===", csv_path)

    imported_companies = 0
    updated_companies = 0
    imported_contacts = 0
    mx_valid_count = 0
    mx_failed_count = 0

    mx_cache: Dict[str, bool] = {}

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_cname = row.get("Company", "").strip()
            if not raw_cname:
                continue

            city_raw = row.get("City", "").strip()
            city = normalize_city_name(city_raw)
            email_field = row.get("HR / careers email", "").strip()
            role_seen = row.get("Role seen", "").strip()
            exp_asked = row.get("Experience asked", "").strip()
            fresher_fit = row.get("Fresher fit", "Medium").strip()
            size_note = row.get("Size note", "").strip()
            source_url = row.get("Source (official listing)", "").strip()
            notes = row.get("Note", "").strip()

            # Find all emails in the email field
            emails = EMAIL_REGEX.findall(email_field)
            if not emails:
                logger.warning("No valid email found in row for '%s' ('%s')", raw_cname, email_field)
                continue

            primary_email = emails[0].lower().strip()
            domain = primary_email.split("@")[1].lower().strip()

            emp_min, emp_max, emp_est, size_conf, size_source, size_evidence, size_status = parse_size_info(size_note)
            field_tags = extract_field_tags(role_seen, notes)
            fit_score, tier = calculate_fit(fresher_fit, field_tags)

            website = f"https://{domain}"
            if "technopark.org" in source_url or "infopark.in" in source_url:
                careers_url = source_url
            else:
                careers_url = source_url or f"https://{domain}/careers"

            company_obj = Company(
                name=raw_cname,
                domain=domain,
                website=website,
                careers_url=careers_url,
                city=city,
                address=city_raw,
                hq_country="India",
                employee_min=emp_min,
                employee_max=emp_max,
                employee_estimate=emp_est,
                size_confidence=size_conf,
                size_source=size_source,
                size_evidence=size_evidence,
                size_status=size_status,
                field_tags=field_tags,
                field_fit_score=fit_score,
                hiring_signal_score=80.0 if "fresh" in exp_asked.lower() else 65.0,
                company_score=fit_score,
                tier=tier,
                discovered_via="csv_official_listing",
                status="active",
                notes=f"{role_seen} | Exp: {exp_asked} | {notes}".strip(" |")
            )

            cid = save_company(company_obj)
            imported_companies += 1

            # Store rich company signals
            signals = [
                CompanySignal(company_id=cid, signal_type="open_role", value=f"{role_seen} (Req: {exp_asked})", source_url=source_url, weight=2.0),
                CompanySignal(company_id=cid, signal_type="park_directory", value=city_raw, source_url=source_url, weight=1.0),
                CompanySignal(company_id=cid, signal_type="fresher_fit", value=f"Fit: {fresher_fit}", source_url=source_url, weight=1.5)
            ]
            if notes:
                signals.append(CompanySignal(company_id=cid, signal_type="tech_blog", value=notes, source_url=source_url, weight=1.0))
            for s in signals:
                save_company_signal(s)

            # Populate contacts table
            for email in emails:
                clean_email = email.lower().strip()
                mail_domain = clean_email.split("@")[1]

                if check_mx:
                    if mail_domain not in mx_cache:
                        mx_cache[mail_domain] = verify_mx_record(mail_domain, timeout=2.5)
                    mx_valid = mx_cache[mail_domain]
                else:
                    mx_valid = True

                if mx_valid:
                    mx_valid_count += 1
                else:
                    mx_failed_count += 1
                    logger.warning("MX validation failed for contact %s at %s", clean_email, raw_cname)

                # Identify if generic inbox
                is_generic = any(clean_email.startswith(p) for p in [
                    "careers@", "hr@", "jobs@", "info@", "career@", "infopark@", "talent@"
                ])
                contact_name = "Talent Acquisition Team" if is_generic else "HR Recruiter"

                contact_obj = RecruiterContact(
                    job_id="",
                    company_id=cid,
                    email=clean_email,
                    name=contact_name,
                    role="Talent Acquisition / HR",
                    source_type="official_listing",
                    verified=is_valid_email_syntax(clean_email),
                    domain_mx_valid=mx_valid
                )
                save_company_contact(cid, contact_obj)
                imported_contacts += 1

    summary = {
        "companies_imported": imported_companies,
        "contacts_imported": imported_contacts,
        "mx_valid_contacts": mx_valid_count,
        "mx_failed_contacts": mx_failed_count
    }
    logger.info("Import summary: %s", summary)
    return summary
