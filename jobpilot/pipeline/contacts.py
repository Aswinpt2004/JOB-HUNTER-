import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlparse
import dns.resolver
from bs4 import BeautifulSoup
import requests
from jobpilot.core.config import settings
from jobpilot.core.models import RecruiterContact
from jobpilot.core.db import get_connection, log_event

logger = logging.getLogger("jobpilot.pipeline.contacts")

EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'
)

OBFUSCATED_REGEX = re.compile(
    r'\b([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*([A-Za-z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\s+dot\s+)\s*([A-Za-z]{2,7})\b',
    re.IGNORECASE
)

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
    try:
        r = int(cf_hex[:2], 16)
        email = "".join([chr(int(cf_hex[i:i+2], 16) ^ r) for i in range(2, len(cf_hex), 2)])
        return email.lower().strip()
    except Exception:
        return ""


def is_valid_email_syntax(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.fullmatch(email.strip()))


def is_no_reply_or_generic(email: str) -> bool:
    if not email:
        return True
    email = email.lower().strip()
    for pattern in NO_REPLY_PATTERNS:
        if re.search(pattern, email):
            return True
    return False


def is_blocked(email: str) -> bool:
    from jobpilot.core.db import is_email_blocklisted
    return is_email_blocklisted(email)


def validate_domain_mx(domain: str) -> bool:
    """Verifies that the target email domain has active Mail Exchange (MX) DNS records."""
    if not domain:
        return False
    try:
        answers = dns.resolver.resolve(domain, 'MX', lifetime=5.0)
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, Exception) as e:
        logger.warning("DNS MX check failed for domain %s: %s", domain, e)
        return False


def extract_contacts_from_text(text: str, source_type: str = "jd_text") -> List[RecruiterContact]:
    """Finds emails in text, including obfuscated emails and mailto links."""
    if not text:
        return []

    contacts: List[RecruiterContact] = []
    seen_emails: Set[str] = set()

    # 1. Plain regex search
    for email in EMAIL_REGEX.findall(text):
        clean = email.lower().strip()
        if clean not in seen_emails and not is_no_reply_or_generic(clean):
            seen_emails.add(clean)
            contacts.append(RecruiterContact(
                email=clean,
                source_type=source_type,
                verified=False,
                domain_mx_valid=False
            ))

    # 2. De-obfuscate patterns
    for match in OBFUSCATED_REGEX.findall(text):
        user, domain, tld = match
        reconstructed = f"{user}@{domain}.{tld}".lower().strip()
        if reconstructed not in seen_emails and not is_no_reply_or_generic(reconstructed):
            seen_emails.add(reconstructed)
            contacts.append(RecruiterContact(
                email=reconstructed,
                source_type=f"{source_type}_obfuscated",
                verified=False,
                domain_mx_valid=False
            ))

    return contacts


def score_contact_priority(contact: RecruiterContact) -> int:
    score = 0
    em = contact.email.lower()
    for prefix in ROLE_PREFIXES:
        if em.startswith(prefix):
            score += 50
            break
    if contact.name and "hr" in contact.name.lower():
        score += 30
    if contact.domain_mx_valid:
        score += 40
    return score


def save_contact(contact: RecruiterContact, db_path=None) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO contacts (job_id, company_id, email, name, role, source_type, verified, domain_mx_valid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            contact.job_id or "", contact.company_id, contact.email,
            contact.name, contact.role, contact.source_type,
            1 if contact.verified else 0,
            1 if contact.domain_mx_valid else 0
        ))
        conn.commit()
        return cursor.lastrowid

