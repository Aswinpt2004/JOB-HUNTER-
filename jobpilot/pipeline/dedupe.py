import difflib
import re
from typing import Optional
from jobpilot.core.db import (
    clean_company_name_for_matching,
    clean_job_title_for_dedupe,
    normalize_job_url
)


def compute_canonical_key(company: str, title: str) -> str:
    c = clean_company_name_for_matching(company)
    t = clean_job_title_for_dedupe(title)
    return f"{c}__{t}"


def are_jobs_duplicate(
    title1: str, company1: str, url1: str,
    title2: str, company2: str, url2: str,
    threshold: float = 0.85
) -> bool:
    if url1 and url2 and normalize_job_url(url1) == normalize_job_url(url2):
        return True

    c1 = clean_company_name_for_matching(company1)
    c2 = clean_company_name_for_matching(company2)
    if not c1 or not c2:
        return False
    if c1 != c2 and difflib.SequenceMatcher(None, c1, c2).ratio() < 0.85:
        return False

    t1 = clean_job_title_for_dedupe(title1)
    t2 = clean_job_title_for_dedupe(title2)
    if t1 == t2:
        return True

    return difflib.SequenceMatcher(None, t1, t2).ratio() >= threshold

