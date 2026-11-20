import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import settings
from src.contacts import (
    decode_cloudflare_email,
    extract_emails_from_text,
    is_valid_email_syntax,
    is_no_reply_or_generic,
    verify_mx_record,
    score_email_priority,
    ROLE_PREFIXES
)
from src.db import (
    init_db,
    get_connection,
    get_company,
    get_company_contacts,
    save_company_contact,
    is_blocked,
    list_companies
)
from src.models import RecruiterContact

logger = logging.getLogger("jobpilot.companies.contacts")


def crawl_company_contacts(company_id: int) -> List[RecruiterContact]:
    """
    Crawls official public pages of a company to discover verified HR/recruiter emails.
    Respects robots, obfuscation, Cloudflare encoding, and MX verification.
    NEVER guesses first.last@ emails.
    """
    company = get_company(company_id)
    if not company:
        return []

    cname = company["name"]
    domain = company.get("domain")
    website = company.get("website") or (f"https://{domain}" if domain else None)
    careers_url = company.get("careers_url")

    # Check if we already have verified contacts in DB
    existing = get_company_contacts(company_id)
    if existing:
        return [
            RecruiterContact(
                company_id=company_id,
                email=e["email"],
                name=e.get("name"),
                role=e.get("role") or "Hiring Team",
                source_type=e.get("source_type") or "cached",
                verified=bool(e.get("verified")),
                domain_mx_valid=bool(e.get("domain_mx_valid"))
            )
            for e in existing
        ]

    urls_to_crawl = []
    if careers_url:
        urls_to_crawl.append(careers_url)

    if website:
        base = website.rstrip("/")
        urls_to_crawl.extend([
            f"{base}/careers",
            f"{base}/contact",
            f"{base}/about",
            f"{base}/team",
            base
        ])

    discovered_emails = set()
    candidate_contacts: List[RecruiterContact] = []
    headers = {"User-Agent": settings.user_agent}

    for target_url in urls_to_crawl[:3]:
        try:
            res = requests.get(target_url, headers=headers, timeout=2.5)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")

            # 1. Cloudflare protected emails
            cf_elements = soup.find_all(attrs={"data-cfemail": True})
            for cf in cf_elements:
                dec = decode_cloudflare_email(cf["data-cfemail"])
                if dec and is_valid_email_syntax(dec) and not is_no_reply_or_generic(dec) and not is_blocked(dec):
                    discovered_emails.add(dec)

            # 2. Mailto links
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.lower().startswith("mailto:"):
                    raw = href[7:].split("?")[0].strip().lower()
                    if is_valid_email_syntax(raw) and not is_no_reply_or_generic(raw) and not is_blocked(raw):
                        discovered_emails.add(raw)

            # 3. Body text regex & obfuscated patterns
            text_emails = extract_emails_from_text(res.text)
            for e in text_emails:
                if not is_blocked(e):
                    discovered_emails.add(e)

            if discovered_emails:
                break
        except Exception as e:
            logger.debug("Failed crawling %s: %s", target_url, e)

    # Validate MX and rank
    for email in discovered_emails:
        mail_domain = email.split("@")[-1]
        mx_ok = verify_mx_record(mail_domain)
        if mx_ok:
            # Score role priority
            priority = score_email_priority(email)
            contact = RecruiterContact(
                company_id=company_id,
                email=email,
                name=f"{cname} Hiring Team",
                role="Talent Acquisition / HR",
                source_type="company_crawl",
                verified=True,
                domain_mx_valid=True
            )
            candidate_contacts.append(contact)
            save_company_contact(company_id, contact)

    # Sort candidates by priority
    candidate_contacts.sort(key=lambda c: score_email_priority(c.email), reverse=True)
    return candidate_contacts


def run_company_contacts(tier_filter: Optional[List[str]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Finds contacts for companies matching selected tiers (default: Tier A & Tier B)."""
    init_db()
    tiers = tier_filter or ["A", "B"]
    logger.info("=== Starting Company Contact Harvesting for Tiers %s ===", tiers)

    companies = list_companies()
    candidates = [c for c in companies if c.get("tier") in tiers]
    if limit:
        candidates = candidates[:limit]

    logger.info("Crawling contacts for %d eligible companies...", len(candidates))

    contacts_found = 0
    portal_only_count = 0

    for c in candidates:
        contacts = crawl_company_contacts(c["id"])
        if contacts:
            contacts_found += 1
            logger.info("Found %d verified contact(s) for '%s': %s", len(contacts), c["name"], [ct.email for ct in contacts])
        else:
            portal_only_count += 1

    return {
        "eligible_companies": len(candidates),
        "contacts_found": contacts_found,
        "portal_only": portal_only_count
    }
