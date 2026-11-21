import re
import logging
from urllib.parse import urlparse
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("jobpilot.pipeline.route")

EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

IGNORED_EMAIL_DOMAINS = {
    "example.com", "sentry.io", "wixpress.com", "gravatar.com",
    "github.com", "google.com", "facebook.com", "twitter.com"
}


def extract_emails_from_text(text: str) -> list[str]:
    if not text:
        return []
    matches = EMAIL_REGEX.findall(text)
    clean = []
    for m in matches:
        m_lower = m.lower()
        dom = m_lower.split("@")[-1]
        if dom not in IGNORED_EMAIL_DOMAINS and not m_lower.endswith(".png") and not m_lower.endswith(".jpg"):
            clean.append(m_lower)
    return list(dict.fromkeys(clean))


def classify_url_domain(url: str) -> str:
    if not url:
        return "unknown"
    u = url.lower()
    if "greenhouse.io" in u:
        return "ats_greenhouse"
    if "lever.co" in u:
        return "ats_lever"
    if "ashbyhq.com" in u:
        return "ats_ashby"
    if "workable.com" in u:
        return "ats_workable"
    if "smartrecruiters.com" in u:
        return "ats_smartrecruiters"
    if "linkedin.com" in u:
        return "linkedin"
    if "naukri.com" in u:
        return "naukri"
    if "indeed.com" in u:
        return "indeed"
    if "keka.com" in u or "zohorecruit.com" in u or "darwinbox.in" in u:
        return "company_form"
    if u.startswith("mailto:"):
        return "email"
    return "company_form"


def resolve_apply_target(
    url: str,
    apply_url: Optional[str] = None,
    description: str = "",
    follow_redirects: bool = False
) -> Dict[str, Any]:
    """
    Resolves the canonical apply URL, identifies the application channel,
    extracts potential recruiter email, and assigns the best apply route.
    """
    target = (apply_url or url or "").strip()
    recruiter_email: Optional[str] = None
    easy_apply = False

    # Check for mailto
    if target.startswith("mailto:"):
        recruiter_email = target.replace("mailto:", "").split("?")[0].strip()

    # Check description for emails if none found
    if not recruiter_email and description:
        emails = extract_emails_from_text(description)
        # Prioritize hr/careers/jobs emails
        for em in emails:
            if any(term in em for term in ["hr", "career", "job", "talent", "recruit", "hiring"]):
                recruiter_email = em
                break
        if not recruiter_email and emails:
            recruiter_email = emails[0]

    # Follow redirects for short links or aggregators if requested
    if follow_redirects and target and not target.startswith("mailto:"):
        try:
            resp = requests.head(target, allow_redirects=True, timeout=5)
            target = resp.url
        except Exception:
            pass

    # Check Easy Apply indicators
    desc_lower = (description or "").lower()
    if "easy apply" in desc_lower or "easily apply" in desc_lower:
        easy_apply = True

    apply_kind = classify_url_domain(target)
    if recruiter_email and apply_kind in ["unknown", "company_form"]:
        apply_kind = "email"

    # Assign route: email | ats_assist | packet
    if recruiter_email or apply_kind == "email":
        route = "email"
    elif apply_kind.startswith("ats_"):
        route = "ats_assist"
    else:
        route = "packet"

    return {
        "apply_url": target,
        "apply_kind": apply_kind,
        "easy_apply": easy_apply,
        "recruiter_email": recruiter_email,
        "route": route
    }

