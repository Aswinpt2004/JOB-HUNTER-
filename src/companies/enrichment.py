import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import settings
from src.db import (
    init_db,
    get_connection,
    get_company,
    update_company,
    list_companies,
    save_company_signal
)
from src.models import CompanySignal

logger = logging.getLogger("jobpilot.companies.enrichment")

# High confidence regex patterns for employee count extraction
REGEX_SIZE_PATTERNS = [
    # Range: 50-200 employees, 11-50 employees
    (re.compile(r'\b(\d{1,5})\s*(?:-|to)\s*(\d{1,5})\s+(?:employees|people|engineers|team\s+members)\b', re.IGNORECASE), "range"),
    # Team of 120+, staff of 45+
    (re.compile(r'(?:team|company|staff|workforce|crew)\s+(?:of\s+)?(?:about\s+)?(\d{2,5})\+?', re.IGNORECASE), "prefix"),
    # 200+ engineers, 50+ employees
    (re.compile(r'\b(\d{2,5})\+?\s+(?:employees|people|engineers|team\s+members|professionals|staff)\b', re.IGNORECASE), "suffix"),
    # Team of 45
    (re.compile(r'\b(?:team|crew|staff|workforce)\s+of\s+(\d{1,5})\b', re.IGNORECASE), "of_single"),
]


def extract_size_from_text(text: str) -> Optional[Tuple[int, int, int, str]]:
    """
    Extracts employee count (min, max, estimate, evidence_snippet) from raw text.
    Returns None if no credible pattern matched.
    """
    if not text:
        return None

    # Search patterns
    for pat, pat_type in REGEX_SIZE_PATTERNS:
        match = pat.search(text)
        if match:
            groups = match.groups()
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            snippet = text[start:end].replace("\n", " ").strip()

            if pat_type == "range":
                low = int(groups[0])
                high = int(groups[1])
                estimate = int((low + high) / 2)
                return (low, high, estimate, snippet)
            else:
                val = int(groups[0])
                return (val, val, val, snippet)

    return None


def fetch_wikidata_employees(company_name: str) -> Optional[Tuple[int, str]]:
    """
    Queries free public Wikidata API for organization's numberOfEmployees (P1128).
    Returns (employee_count, source_url) or None.
    """
    try:
        url = "https://www.wikidata.org/w/api.php"
        headers = {"User-Agent": settings.user_agent}
        params = {
            "action": "wbsearchentities",
            "search": company_name,
            "language": "en",
            "format": "json"
        }
        res = requests.get(url, params=params, headers=headers, timeout=2.5)
        if res.status_code != 200:
            return None
        data = res.json()
        results = data.get("search", [])
        if not results:
            return None

        # Check top result
        top = results[0]
        qid = top.get("id")
        if not qid:
            return None

        ent_url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
        ent_res = requests.get(ent_url, headers=headers, timeout=2.5)
        if ent_res.status_code != 200:
            return None

        ent_data = ent_res.json()
        claims = ent_data.get("entities", {}).get(qid, {}).get("claims", {})
        # P1128 is numberOfEmployees
        if "P1128" in claims:
            emp_claim = claims["P1128"][0]
            amount_str = emp_claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("amount", "")
            if amount_str:
                emp_val = int(float(amount_str.lstrip("+")))
                return (emp_val, f"https://www.wikidata.org/wiki/{qid}")
    except Exception as e:
        logger.debug("Wikidata lookup for %s failed: %s", company_name, e)

    return None


def extract_schema_org_employees(soup: BeautifulSoup) -> Optional[int]:
    """Parses schema.org JSON-LD or microdata for numberOfEmployees."""
    try:
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            if not s.string:
                continue
            data = json.loads(s.string)
            # Can be dict or list
            items = data if isinstance(data, list) else [data]
            for it in items:
                if isinstance(it, dict) and it.get("@type") in ("Organization", "Corporation", "LocalBusiness"):
                    num = it.get("numberOfEmployees")
                    if isinstance(num, (int, float)):
                        return int(num)
                    elif isinstance(num, dict):
                        # QuantitativeValue
                        val = num.get("value") or num.get("minValue")
                        if val:
                            return int(float(val))
    except Exception:
        pass
    return None


def get_hiring_volume_proxy(company_name: str) -> Optional[Tuple[int, float, str]]:
    """
    Computes proxy employee size based on distinct open job postings in database.
    >= 8 open roles suggests >= 50 staff (confidence 0.5)
    >= 4 open roles suggests >= 20 staff (confidence 0.5)
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT id) FROM jobs
                WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
            """, (company_name,))
            count = cursor.fetchone()[0]
            if count >= 8:
                return (50, 0.5, f"Hiring volume proxy: {count} open roles across job boards")
            elif count >= 4:
                return (20, 0.5, f"Hiring volume proxy: {count} open roles across job boards")
    except Exception:
        pass
    return None


def enrich_company_size(company_id: int) -> Dict[str, Any]:
    """
    Runs the layered Evidence Ladder on a company to estimate employee count and size status.
    """
    company = get_company(company_id)
    if not company:
        return {}

    cname = company["name"]
    website = company.get("website") or (f"https://{company['domain']}" if company.get("domain") else None)
    headers = {"User-Agent": settings.user_agent}

    # Best evidence accumulators
    best_min: Optional[int] = None
    best_max: Optional[int] = None
    best_est: Optional[int] = None
    best_conf: float = 0.0
    best_source: Optional[str] = None
    best_evidence: Optional[str] = None

    # Ladder Level 1: Official website pages (/about, homepage)
    pages_to_check = []
    if website:
        base_clean = website.rstrip("/")
        pages_to_check = [base_clean, f"{base_clean}/about"]

    for page_url in pages_to_check:
        try:
            res = requests.get(page_url, headers=headers, timeout=2.5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")

                # Check Schema.org structured data (Ladder Level 3: conf 0.8)
                schema_num = extract_schema_org_employees(soup)
                if schema_num and schema_num > 0 and 0.8 > best_conf:
                    best_min = schema_num
                    best_max = schema_num
                    best_est = schema_num
                    best_conf = 0.8
                    best_source = page_url
                    best_evidence = f"schema.org numberOfEmployees: {schema_num}"

                # Text regexes (Ladder Level 1: conf 0.85)
                text = soup.get_text(separator=" ", strip=True)
                size_match = extract_size_from_text(text)
                if size_match and 0.85 > best_conf:
                    low, high, est, snip = size_match
                    best_min = low
                    best_max = high
                    best_est = est
                    best_conf = 0.85
                    best_source = page_url
                    best_evidence = f"Official page text: '{snip}' ({page_url})"
                    break  # Found high confidence self-report
        except Exception:
            pass

    # Ladder Level 3: Wikidata API (conf 0.8)
    if best_conf < 0.8:
        wiki_res = fetch_wikidata_employees(cname)
        if wiki_res:
            emp_val, wiki_url = wiki_res
            best_min = emp_val
            best_max = emp_val
            best_est = emp_val
            best_conf = 0.8
            best_source = wiki_url
            best_evidence = f"Wikidata property P1128: {emp_val} employees ({wiki_url})"

    # Ladder Level 4: Hiring volume proxy (conf 0.5)
    if best_conf < 0.5:
        hiring_proxy = get_hiring_volume_proxy(cname)
        if hiring_proxy:
            proxy_est, proxy_conf, proxy_ev = hiring_proxy
            best_min = proxy_est
            best_max = proxy_est
            best_est = proxy_est
            best_conf = proxy_conf
            best_source = "ats_job_counts"
            best_evidence = proxy_ev

    # Decision Rule:
    # confirmed_20plus: evidence (1-3) gives >= 20.
    # likely_20plus: proxies (4-6) combine to >= 20 with confidence >= 0.5.
    # under_20: evidence says < 20.
    # unknown: no reliable evidence.
    size_status = "unknown"
    if best_est is not None:
        if best_est < 20 and best_conf >= 0.5:
            size_status = "under_20"
        elif best_est >= 20:
            if best_conf >= 0.75:
                size_status = "confirmed_20plus"
            elif best_conf >= 0.45:
                size_status = "likely_20plus"
            else:
                size_status = "unknown"

    # Flag large organizations (10,000+ employees)
    if best_est and best_est >= 10000:
        notes_str = (company.get("notes") or "") + " [large_org]"
    else:
        notes_str = company.get("notes")

    updates = {
        "employee_min": best_min,
        "employee_max": best_max,
        "employee_estimate": best_est,
        "size_confidence": best_conf,
        "size_source": best_source,
        "size_evidence": best_evidence,
        "size_status": size_status,
        "notes": notes_str
    }
    update_company(company_id, updates)

    # Save company signal if credible evidence found
    if best_evidence:
        save_company_signal(CompanySignal(
            company_id=company_id,
            signal_type="team_page" if "Official" in (best_evidence or "") else "open_role",
            value=f"Size: {best_est} ({size_status})",
            source_url=best_source,
            weight=best_conf
        ))

    return updates


def run_company_enrichment(limit: Optional[int] = None) -> Dict[str, Any]:
    """Runs size enrichment across all new or unknown companies."""
    init_db()
    logger.info("=== Starting Company Size Enrichment ===")

    companies = list_companies()
    candidates = [c for c in companies if c.get("size_status") in ("unknown", None) or c.get("size_confidence", 0) < 0.5]
    if limit:
        candidates = candidates[:limit]

    logger.info("Evaluating size evidence ladder for %d companies...", len(candidates))

    counts = {"confirmed_20plus": 0, "likely_20plus": 0, "unknown": 0, "under_20": 0}
    for c in candidates:
        res = enrich_company_size(c["id"])
        st = res.get("size_status", "unknown")
        counts[st] = counts.get(st, 0) + 1

    logger.info("Size enrichment complete: %s", counts)
    return counts
