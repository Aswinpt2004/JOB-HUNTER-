import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlparse
import dns.resolver
from bs4 import BeautifulSoup
import requests
from src.config import settings
from src.models import RecruiterContact, Job
from src.db import is_blocked, save_contact, log_event

logger = logging.getLogger("jobpilot.contacts")

# RFC-compliant email extraction regex
EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'
)

# Obfuscated email pattern: name [at] domain [dot] com or name (at) domain (dot) com
OBFUSCATED_REGEX = re.compile(
    r'\b([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*([A-Za-z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*([A-Za-z]{2,7})\b',
    re.IGNORECASE
)

# Skip-list for automated, support, legal, accommodations, or bounce addresses
NO_REPLY_PATTERNS = [
    r'^no-?reply@',
    r'^donotreply@',
    r'^mailer-daemon@',
    r'^bounce@',
    r'^notifications?@',
    r'^support@',
    r'^help@',
    r'^privacy.*@',
    r'^legal@',
    r'^compliance@',
    r'^dpo@',
    r'^billing@',
    r'^abuse@',
    r'^security@',
    r'^press@',
    r'^media@',
    r'^investor.*@',
    r'^admin@',
    r'^webmaster@',
    r'^accommodation.*@',
    r'^info@infopark\.in',
    r'^info@technopark\.in',
    r'^info@cyberparks\.in',
]

ROLE_PREFIXES = [
    "careers@", "jobs@", "hr@", "recruiting@", "recruitment@",
    "talent@", "hiring@", "people@", "join@", "team@"
]


def decode_cloudflare_email(cf_hex: str) -> str:
    """Decodes Cloudflare data-cfemail hex-encoded strings."""
    try:
        r = int(cf_hex[:2], 16)
        email = "".join([chr(int(cf_hex[i:i+2], 16) ^ r) for i in range(2, len(cf_hex), 2)])
        return email.lower().strip()
    except Exception:
        return ""


def is_valid_email_syntax(email: str) -> bool:
    """Checks basic email syntax."""
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.fullmatch(email.strip()))


def is_no_reply_or_generic(email: str) -> bool:
    """Checks if email is a no-reply, billing, support, or compliance address."""
    email_clean = email.lower().strip()
    for pattern in NO_REPLY_PATTERNS:
        if re.search(pattern, email_clean):
            return True
    return False


def verify_mx_record(domain: str, timeout: float = 4.0) -> bool:
    """Verifies that the domain has active MX mail exchange records using dnspython."""
    for ns in [None, ['8.8.8.8', '1.1.1.1']]:
        try:
            resolver = dns.resolver.Resolver()
            if ns:
                resolver.nameservers = ns
            resolver.timeout = timeout
            resolver.lifetime = timeout * 2
            answers = resolver.resolve(domain, "MX")
            if len(answers) > 0:
                return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return False
        except Exception as e:
            logger.debug("MX lookup attempt on %s failed: %s", domain, e)
    return False


def extract_emails_from_text(text: str) -> List[str]:
    """Finds all valid syntax emails in a text block, decoding obfuscations."""
    if not text:
        return []

    discovered = []
    seen = set()

    # 1. Plain RFC emails
    matches = EMAIL_REGEX.findall(text)
    for m in matches:
        e = re.sub(r'^(?:u003[ce]|gt;|lt;)+', '', m, flags=re.IGNORECASE).lower().strip()
        if is_valid_email_syntax(e) and e not in seen and not is_no_reply_or_generic(e) and not is_blocked(e):
            seen.add(e)
            discovered.append(e)

    # 2. Obfuscated emails: name [at] domain [dot] com
    obf_matches = OBFUSCATED_REGEX.findall(text)
    for user, domain_part, tld in obf_matches:
        reconstructed = f"{user}@{domain_part}.{tld}".lower().strip()
        if is_valid_email_syntax(reconstructed) and reconstructed not in seen and not is_no_reply_or_generic(reconstructed) and not is_blocked(reconstructed):
            seen.add(reconstructed)
            discovered.append(reconstructed)

    return discovered


def score_email_priority(email: str) -> int:
    """Higher score means more preferred for job applications."""
    email_lower = email.lower()
    for i, prefix in enumerate(ROLE_PREFIXES):
        if email_lower.startswith(prefix):
            return 100 - i
    # Direct recruiter or talent address (e.g. sarah.smith@company.com)
    return 50


def _scrape_company_contact_page(job: Job) -> List[str]:
    """Scrapes company job posting URL or career/contact pages for public HR/recruiter emails."""
    discovered = []
    headers = {"User-Agent": settings.user_agent}

    urls_to_check = []
    if job.url:
        urls_to_check.append(job.url)

    parsed = urlparse(job.url) if job.url else None
    if parsed and parsed.netloc:
        domain = parsed.netloc
        if any(b in domain for b in ["greenhouse.io", "lever.co", "remotive.com", "ashbyhq.com"]):
            comp_slug = re.sub(r'[^a-zA-Z0-9]', '', job.company.lower())
            if comp_slug:
                urls_to_check.extend([
                    f"https://www.{comp_slug}.com/careers",
                    f"https://www.{comp_slug}.com/contact",
                    f"https://www.{comp_slug}.com/about",
                    f"https://{comp_slug}.com"
                ])
        else:
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            urls_to_check.extend([
                f"{base_url}/careers",
                f"{base_url}/contact",
                f"{base_url}/about"
            ])

    for target_url in urls_to_check[:4]:
        try:
            res = requests.get(target_url, headers=headers, timeout=6)
            if res.status_code == 200:
                # Check for Cloudflare protected emails in HTML
                soup = BeautifulSoup(res.text, "html.parser")
                cf_elements = soup.find_all(attrs={"data-cfemail": True})
                for cf in cf_elements:
                    decoded = decode_cloudflare_email(cf["data-cfemail"])
                    if decoded and is_valid_email_syntax(decoded) and not is_no_reply_or_generic(decoded):
                        if decoded not in discovered:
                            discovered.append(decoded)

                # Check mailto links
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if href.lower().startswith("mailto:"):
                        raw_mail = href[7:].split("?")[0].strip().lower()
                        if is_valid_email_syntax(raw_mail) and not is_no_reply_or_generic(raw_mail):
                            if raw_mail not in discovered:
                                discovered.append(raw_mail)

                # Check text body
                emails = extract_emails_from_text(res.text)
                for e in emails:
                    if e not in discovered:
                        discovered.append(e)

            if discovered:
                break
        except Exception as e:
            logger.debug("Failed checking URL %s for HR emails: %s", target_url, e)

    return discovered


def find_recruiter_contacts(
    job: Job,
    check_mx: bool = True
) -> List[RecruiterContact]:
    """
    Extracts public recruiter emails from:
    1. Direct recruiter email attached to the Job model (e.g. Technopark / Infopark listings).
    2. Job description text and mailto links.
    3. Company career/contact/about pages (if accessible).
    Verifies MX record, filters non-recruiting addresses, and sorts by priority.
    """
    found_contacts: List[RecruiterContact] = []
    seen_emails: Set[str] = set()

    # 1. Check direct recruiter_email on Job object
    if job.recruiter_email:
        raw_em = job.recruiter_email.lower().strip()
        if is_valid_email_syntax(raw_em) and not is_no_reply_or_generic(raw_em) and not is_blocked(raw_em):
            domain = raw_em.split("@")[-1]
            mx_valid = verify_mx_record(domain) if check_mx else True
            if mx_valid or not check_mx:
                seen_emails.add(raw_em)
                role = "HR / Recruiter"
                for p in ROLE_PREFIXES:
                    if raw_em.startswith(p):
                        role = "Careers / Talent Acquisition"
                        break
                found_contacts.append(RecruiterContact(
                    job_id=job.id,
                    email=raw_em,
                    name=None,
                    role=role,
                    source_type="portal_listing",
                    verified=mx_valid,
                    domain_mx_valid=mx_valid
                ))

    # 2. Check Job description text
    text_candidates = extract_emails_from_text(job.description)
    for email in text_candidates:
        domain = email.split("@")[-1].lower()
        if domain in ["example.com", "example.org", "example.net", "sample.com", "domain.com"]:
            continue
        if email in seen_emails or is_blocked(email) or is_no_reply_or_generic(email):
            continue

        mx_valid = verify_mx_record(domain) if check_mx else True
        if not mx_valid and check_mx:
            logger.info("Skipping invalid MX domain email: %s", email)
            continue

        seen_emails.add(email)
        role = "HR / Recruiting"
        for p in ROLE_PREFIXES:
            if email.startswith(p):
                role = "Careers / Recruiting"
                break

        contact = RecruiterContact(
            job_id=job.id,
            email=email,
            name=None,
            role=role,
            source_type="jd_text",
            verified=mx_valid,
            domain_mx_valid=mx_valid
        )
        found_contacts.append(contact)

    # 3. If no email found yet, check company career/contact web pages
    if not found_contacts:
        page_candidates = _scrape_company_contact_page(job)
        for email in page_candidates:
            domain = email.split("@")[-1].lower()
            if domain in ["example.com", "example.org", "example.net", "sample.com", "domain.com"]:
                continue
            if email in seen_emails or is_blocked(email) or is_no_reply_or_generic(email):
                continue

            mx_valid = verify_mx_record(domain) if check_mx else True
            if not mx_valid and check_mx:
                continue

            seen_emails.add(email)
            role = "HR / Talent Acquisition"
            for p in ROLE_PREFIXES:
                if email.startswith(p):
                    role = "Careers / Recruiting"
                    break

            contact = RecruiterContact(
                job_id=job.id,
                email=email,
                name=None,
                role=role,
                source_type="company_page",
                verified=mx_valid,
                domain_mx_valid=mx_valid
            )
            found_contacts.append(contact)

    # 4. Sort by priority score (careers@, jobs@, hr@, then direct names)
    found_contacts.sort(key=lambda c: score_email_priority(c.email), reverse=True)

    for c in found_contacts:
        try:
            save_contact(c)
        except Exception as e:
            logger.debug("Could not persist contact to DB: %s", e)

    log_event("contacts", f"Found {len(found_contacts)} contacts for job {job.id} at {job.company}")
    return found_contacts
