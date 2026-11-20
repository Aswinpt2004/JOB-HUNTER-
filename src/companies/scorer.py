import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

from src.config import settings
from src.db import (
    init_db,
    get_connection,
    get_company,
    update_company,
    list_companies,
    save_company_signal,
    has_company_or_email_been_contacted_recently
)
from src.models import CompanySignal

logger = logging.getLogger("jobpilot.companies.scorer")

# Field Fit Keywords with weights
FIELD_KEYWORDS_WEIGHT_3 = [
    "computer vision", "video analytics", "object detection", "drone", "uav",
    "surveillance", "llm", "rag", "agentic", "agents", "deep learning",
    "pytorch", "yolo", "opencv"
]

FIELD_KEYWORDS_WEIGHT_2 = [
    "document ai", "intelligent document processing", "idp", "healthcare ai",
    "medical imaging", "federated learning", "privacy preserving", "graph neural network",
    "graph ml", "fastapi", "mlops", "ml platform"
]

FIELD_KEYWORDS_WEIGHT_1 = [
    "machine learning", "data science", "ai platform", "artificial intelligence",
    "backend", "data analytics", "data engineering", "nlp"
]


def extract_field_tags_and_score(text: str) -> Tuple[List[str], float]:
    """
    Deterministically computes field fit score (0-100) and extracts matching field tags.
    Weight 3.0: Core CV, Drone, LLM/RAG, PyTorch
    Weight 2.0: Document AI, Medical AI, Federated/Graph ML, FastAPI/MLOps
    Weight 1.0: General ML, Data Science, AI platform
    """
    if not text:
        return ([], 0.0)

    t_low = text.lower()
    matched_tags: Set[str] = set()
    total_points = 0.0

    for kw in FIELD_KEYWORDS_WEIGHT_3:
        if kw in t_low:
            matched_tags.add(kw.replace(" ", "_"))
            total_points += 18.0

    for kw in FIELD_KEYWORDS_WEIGHT_2:
        if kw in t_low:
            matched_tags.add(kw.replace(" ", "_"))
            total_points += 12.0

    for kw in FIELD_KEYWORDS_WEIGHT_1:
        if kw in t_low:
            matched_tags.add(kw.replace(" ", "_"))
            total_points += 6.0

    # Normalize to 0-100
    field_fit_score = min(100.0, total_points)
    return (sorted(list(matched_tags)), round(field_fit_score, 1))


def compute_hiring_likelihood(company: Dict[str, Any]) -> float:
    """
    Computes hiring likelihood score (0-100) based on real signals:
    - Open AI/ML roles now (+40)
    - Any engineering roles open (+15)
    - Roles posted in the last 30 days (+10)
    - Recent funding/expansion news (+10)
    - Fresher/intern programs or 'we are hiring' (+15)
    - Park-resident growth signals (+5)
    - Previously cooldown-clear (+5)
    """
    score = 0.0
    cname = company["name"]

    # 1. Check open roles in jobs table
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT title, description, posted_date FROM jobs
            WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
        """, (cname,))
        comp_jobs = cursor.fetchall()

    has_ai_ml_role = False
    has_eng_role = False

    for j in comp_jobs:
        title_low = j["title"].lower()
        has_eng_role = True
        if any(k in title_low for k in ["ai", "ml", "machine learning", "computer vision", "vision", "data", "deep learning", "python", "developer", "engineer"]):
            has_ai_ml_role = True

    if has_ai_ml_role:
        score += 40.0
    elif has_eng_role:
        score += 15.0

    if len(comp_jobs) > 0:
        score += 10.0  # Has active postings

    # 2. Check careers text on website
    careers_url = company.get("careers_url") or company.get("website")
    if careers_url:
        try:
            res = requests.get(careers_url, headers={"User-Agent": settings.user_agent}, timeout=5)
            if res.status_code == 200:
                text_low = res.text.lower()
                if any(phrase in text_low for phrase in ["we are hiring", "join our team", "open positions", "current openings", "careers at"]):
                    score += 15.0
                if any(phrase in text_low for phrase in ["fresher", "intern", "internship", "graduate", "entry level"]):
                    score += 10.0
        except Exception:
            pass

    # 3. Park resident signal
    via = (company.get("discovered_via") or "").lower()
    if any(p in via for p in ["technopark", "infopark", "cyberpark", "kerala"]):
        score += 5.0

    # 4. Cooldown clear
    is_on_cooldown = has_company_or_email_been_contacted_recently(cname)
    if not is_on_cooldown:
        score += 5.0

    return min(100.0, round(score, 1))


def compute_company_overall_score(
    field_fit: float,
    hiring_likelihood: float,
    size_est: Optional[int],
    size_status: str,
    city: Optional[str]
) -> float:
    """
    company_score = 0.5*field_fit + 0.3*hiring_likelihood + 0.1*size_bonus + 0.1*city_priority
    """
    # Size bonus: >= 50: 100, 20-49: 75, unknown: 35, under_20: 0
    if size_status == "under_20" or (size_est is not None and size_est < 20):
        size_bonus = 0.0
    elif size_est and size_est >= 50:
        size_bonus = 100.0
    elif size_status in ("confirmed_20plus", "likely_20plus"):
        size_bonus = 75.0
    else:
        size_bonus = 35.0

    # City priority
    city_low = (city or "").lower()
    if any(t in city_low for t in ["bangalore", "bengaluru", "thiruvananthapuram", "trivandrum", "kochi", "cochin", "kozhikode", "calicut"]):
        city_priority = 100.0
    elif "remote" in city_low:
        city_priority = 80.0
    else:
        city_priority = 40.0

    score = 0.5 * field_fit + 0.3 * hiring_likelihood + 0.1 * size_bonus + 0.1 * city_priority
    return round(score, 1)


def assign_tier(company_score: float, size_status: str, field_fit: float, is_on_cooldown: bool) -> str:
    """
    Tier assignment:
    Tier A: >= 70 and size >= 20 confirmed/likely
    Tier B: 50-69 and size not under_20
    Tier C: 35-49
    excluded: < 35, under_20, off-field (< 25 field fit), or blocked/cooldown
    """
    if is_on_cooldown or size_status == "under_20" or field_fit < 20.0 or company_score < 35.0:
        return "excluded"
    if company_score >= 70.0 and size_status in ("confirmed_20plus", "likely_20plus"):
        return "A"
    if company_score >= 50.0:
        return "B"
    return "C"


def score_single_company(company_id: int) -> Dict[str, Any]:
    company = get_company(company_id)
    if not company:
        return {}

    cname = company["name"]
    website = company.get("website") or (f"https://{company['domain']}" if company.get("domain") else None)

    # Gather text footprint from website and database jobs
    page_texts = []
    if website:
        for u in [website]:
            try:
                r = requests.get(u, headers={"User-Agent": settings.user_agent}, timeout=2.0)
                if r.status_code == 200:
                    page_texts.append(r.text[:3000])
            except Exception:
                pass

    # Gather JD texts from jobs table
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT description, title FROM jobs WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))", (cname,))
        for row in cursor.fetchall():
            page_texts.append(f"{row['title']} {row['description']}")

    combined_text = " ".join(page_texts)

    # Merge existing field_tags with newly extracted ones
    new_tags, field_fit = extract_field_tags_and_score(combined_text)
    existing_tags = company.get("field_tags") or []
    if existing_tags and field_fit < 25.0:
        # Boost field fit if known seed tags were configured
        tag_text = " ".join(existing_tags)
        _, seed_fit = extract_field_tags_and_score(tag_text)
        field_fit = max(field_fit, seed_fit)

    merged_tags = sorted(list(set(existing_tags + new_tags)))
    hiring_likelihood = compute_hiring_likelihood(company)
    company_score = compute_company_overall_score(
        field_fit,
        hiring_likelihood,
        company.get("employee_estimate"),
        company.get("size_status") or "unknown",
        company.get("city")
    )
    is_on_cooldown = has_company_or_email_been_contacted_recently(cname)
    tier = assign_tier(company_score, company.get("size_status") or "unknown", field_fit, is_on_cooldown)

    updates = {
        "field_tags": merged_tags,
        "field_fit_score": field_fit,
        "hiring_signal_score": hiring_likelihood,
        "company_score": company_score,
        "tier": tier
    }
    update_company(company_id, updates)

    # Save company signal
    save_company_signal(CompanySignal(
        company_id=company_id,
        signal_type="field_keyword",
        value=f"FieldFit: {field_fit}, Score: {company_score}, Tier: {tier}",
        weight=1.0
    ))

    return updates


def run_company_scoring() -> Dict[str, Any]:
    """Scores all companies in database and assigns tiers."""
    init_db()
    logger.info("=== Starting Company Field-Fit and Hiring Scoring ===")

    companies = list_companies()
    tier_counts = {"A": 0, "B": 0, "C": 0, "excluded": 0}

    for c in companies:
        res = score_single_company(c["id"])
        tier = res.get("tier", "C")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    logger.info("Scoring complete. Tier distribution: %s", tier_counts)
    return tier_counts
