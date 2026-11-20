import difflib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import settings
from src.db import (
    get_connection,
    init_db,
    save_company,
    save_company_signal,
    list_companies,
    normalize_domain_key,
    clean_company_name_for_matching,
    are_company_names_similar,
    COMPANY_LEGAL_SUFFIXES
)
from src.models import Company, CompanySignal

logger = logging.getLogger("jobpilot.companies.discovery")


def normalize_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """Canonical domain normalization."""
    return normalize_domain_key(url_or_domain)


class BaseCompanyCollector:
    source_name: str = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8"
        })

    def polite_delay(self, min_s: float = 1.0, max_s: float = 2.5):
        time.sleep(min_s)

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        raise NotImplementedError


class KeralaParksCollector(BaseCompanyCollector):
    """Collects resident tech companies from Technopark (TVM), Infopark (Kochi), and Cyberpark (Kozhikode)."""
    source_name = "kerala_parks"

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        companies: List[Company] = []

        # 1. Technopark Trivandrum
        try:
            logger.info("Collecting companies from Technopark Trivandrum directory...")
            # Query pages 1 and 2 (each ~15-20 companies)
            for page in range(1, 4):
                self.polite_delay(1.0, 2.0)
                url = f"https://technopark.in/api/paginated-companies?page={page}"
                res = self.session.get(url, timeout=10)
                if res.status_code != 200:
                    break
                data = res.json()
                items = data.get("data", [])
                for it in items:
                    cname = it.get("company", "").strip()
                    if not cname:
                        continue
                    cid = it.get("id")
                    detail_url = f"https://technopark.in/company-details/{cid}"
                    primary_b = it.get("primary_building") or {}
                    building_info = primary_b.get("building") or {}
                    loc_info = building_info.get("location") or {}
                    city = loc_info.get("district") or "Thiruvananthapuram"
                    address = f"{building_info.get('building', '')}, {loc_info.get('location', 'Technopark')}"

                    comp = Company(
                        name=cname,
                        city=city,
                        address=address,
                        discovered_via="technopark_directory",
                        status="new"
                    )
                    companies.append(comp)
                    if limit and len(companies) >= limit:
                        return companies
        except Exception as e:
            logger.warning("Technopark collector error: %s", e)

        # 2. Infopark Kochi
        try:
            logger.info("Collecting companies from Infopark Kochi directory...")
            self.polite_delay(1.0, 2.0)
            res = self.session.get("https://infopark.in/companies", timeout=12)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                for card in soup.find_all(class_=lambda x: x and "company-detail" in x.lower()):
                    text = card.get_text(separator=" ", strip=True)
                    # Often "2Base Technologies Pvt Ltd www.2basetechnologies.com Domain AI..."
                    web_link = card.find("a", href=True)
                    website = web_link["href"] if web_link else None
                    # Company name is first text item or heading
                    h_elem = card.find(["h3", "h4", "h5", "h2", "strong"])
                    cname = h_elem.get_text(strip=True) if h_elem else ""
                    if not cname:
                        # Fallback extract first chunk
                        cname = text.split("www.")[0].split("http")[0].strip()
                    if cname and len(cname) > 2:
                        tags = []
                        if "ai" in text.lower() or "artificial intelligence" in text.lower():
                            tags.append("artificial_intelligence")
                        if "machine learning" in text.lower():
                            tags.append("machine_learning")
                        if "data" in text.lower():
                            tags.append("data_analytics")
                        comp = Company(
                            name=cname,
                            website=website,
                            domain=normalize_domain(website),
                            city="Kochi",
                            address="Infopark Kochi, Kerala",
                            field_tags=tags,
                            discovered_via="infopark_directory",
                            status="new"
                        )
                        companies.append(comp)
                        if limit and len(companies) >= limit:
                            return companies
        except Exception as e:
            logger.warning("Infopark collector error: %s", e)

        return companies


class ATSBoardsCollector(BaseCompanyCollector):
    """Harvests company records from ATS boards (Greenhouse, Lever, etc.) and existing jobs."""
    source_name = "ats_boards"

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        companies: List[Company] = []
        # From existing jobs table
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT company, location, url, source
                    FROM jobs
                    WHERE company IS NOT NULL AND TRIM(company) != ''
                """)
                rows = cursor.fetchall()

            for r in rows:
                cname = r["company"].strip()
                loc = (r["location"] or "").lower()
                city = "Bangalore"
                if "trivandrum" in loc or "thiruvananthapuram" in loc or "technopark" in loc:
                    city = "Thiruvananthapuram"
                elif "kochi" in loc or "cochin" in loc or "infopark" in loc:
                    city = "Kochi"
                elif "kozhikode" in loc or "calicut" in loc or "cyberpark" in loc:
                    city = "Kozhikode"
                elif "remote" in loc:
                    city = "Remote India"

                url = r["url"] or ""
                domain = None
                try:
                    netloc = urlparse(url).netloc
                    if not any(b in netloc for b in ["greenhouse.io", "lever.co", "remotive.com", "ashbyhq.com"]):
                        domain = normalize_domain(netloc)
                except Exception:
                    pass

                comp = Company(
                    name=cname,
                    domain=domain,
                    city=city,
                    discovered_via=f"job_board_{r['source']}",
                    status="active"
                )
                companies.append(comp)
                if limit and len(companies) >= limit:
                    break
        except Exception as e:
            logger.warning("ATS collector error: %s", e)

        return companies


class GitHubOrgsCollector(BaseCompanyCollector):
    """Finds engineering organizations located in target cities with ML/CV/Python topics."""
    source_name = "github_orgs"

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        companies: List[Company] = []
        target_queries = [
            ("Bangalore", "location:Bangalore+type:org"),
            ("Kochi", "location:Kochi+type:org"),
            ("Thiruvananthapuram", "location:Trivandrum+type:org"),
            ("Kozhikode", "location:Calicut+type:org"),
        ]

        for city, q in target_queries:
            try:
                self.polite_delay(1.5, 3.0)
                url = f"https://api.github.com/search/users?q={q}&per_page=15"
                res = self.session.get(url, timeout=10)
                if res.status_code == 200:
                    items = res.json().get("items", [])
                    for it in items:
                        login = it.get("login")
                        if not login or "hack" in login.lower() or "study" in login.lower():
                            continue
                        # Fetch org details
                        self.polite_delay(0.5, 1.0)
                        org_res = self.session.get(f"https://api.github.com/orgs/{login}", timeout=8)
                        if org_res.status_code == 200:
                            org_data = org_res.json()
                            name = org_data.get("name") or login
                            blog = org_data.get("blog") or ""
                            desc = org_data.get("description") or ""

                            # Check for field keywords
                            desc_low = desc.lower()
                            field_tags = []
                            if any(k in desc_low for k in ["computer vision", "vision", "yolo", "opencv", "camera"]):
                                field_tags.append("computer_vision")
                            if any(k in desc_low for k in ["llm", "rag", "generative ai", "agent"]):
                                field_tags.append("llm_agents")
                            if any(k in desc_low for k in ["machine learning", "deep learning", "ai", "pytorch"]):
                                field_tags.append("machine_learning")

                            comp = Company(
                                name=name,
                                website=blog if blog.startswith("http") else (f"https://{blog}" if blog else None),
                                domain=normalize_domain(blog),
                                city=city,
                                field_tags=field_tags,
                                discovered_via="github_org_search",
                                notes=f"GitHub: https://github.com/{login} - {desc[:120]}"
                            )
                            companies.append(comp)
                            if limit and len(companies) >= limit:
                                return companies
            except Exception as e:
                logger.debug("GitHub org collector query for %s failed: %s", city, e)

        return companies


class SearchQueriesCollector(BaseCompanyCollector):
    """Runs targeted field x city queries on DuckDuckGo HTML endpoint."""
    source_name = "search_queries"

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        companies: List[Company] = []
        queries = [
            ("computer vision company Bangalore", "Bangalore", ["computer_vision", "video_analytics"]),
            ("drone AI analytics startup Bangalore", "Bangalore", ["drone_uav", "surveillance"]),
            ("AI startup Technopark Trivandrum", "Thiruvananthapuram", ["machine_learning", "ai_platform"]),
            ("computer vision startup Infopark Kochi", "Kochi", ["computer_vision", "deep_learning"]),
            ("AI ML tech companies Kozhikode Calicut", "Kozhikode", ["machine_learning", "data_science"]),
        ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        }

        for q_text, city, tags in queries:
            try:
                self.polite_delay(2.0, 3.5)
                res = self.session.post("https://html.duckduckgo.com/html/", data={"q": q_text}, headers=headers, timeout=10)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    links = soup.find_all("a", class_="result__url")
                    titles = soup.find_all("a", class_="result__snippet")
                    for a_url, a_desc in zip(links[:6], titles[:6]):
                        raw_url = a_url.get("href") or a_url.get_text(strip=True)
                        desc_text = a_desc.get_text(strip=True)
                        netloc = normalize_domain(raw_url)
                        if not netloc or any(bad in netloc for bad in ["linkedin", "naukri", "glassdoor", "indeed", "wikipedia", "youtube", "quora", "medium"]):
                            continue

                        # Extract probable company name from domain root
                        name_candidate = netloc.split(".")[0].capitalize()
                        comp = Company(
                            name=name_candidate,
                            domain=netloc,
                            website=f"https://{netloc}",
                            city=city,
                            field_tags=tags,
                            discovered_via="search_grounding",
                            notes=f"Search Snippet: {desc_text[:140]}"
                        )
                        companies.append(comp)
                        if limit and len(companies) >= limit:
                            return companies
            except Exception as e:
                logger.debug("Search query '%s' failed: %s", q_text, e)

        return companies


class SeedListCollector(BaseCompanyCollector):
    """Resolves and validates seed employers configured in config.yaml."""
    source_name = "seed_list"

    def collect(self, limit: Optional[int] = None) -> List[Company]:
        companies: List[Company] = []
        seed_data = settings.seed_companies
        for s in seed_data:
            cname = s.get("name")
            domain = normalize_domain(s.get("domain") or s.get("website"))
            website = s.get("website") or (f"https://{domain}" if domain else None)
            careers_url = s.get("careers_url")
            city = s.get("city", "Bangalore")
            tags = s.get("field_tags", [])

            comp = Company(
                name=cname,
                domain=domain,
                website=website,
                careers_url=careers_url,
                city=city,
                field_tags=tags,
                discovered_via="seed_config",
                status="new"
            )
            companies.append(comp)
            if limit and len(companies) >= limit:
                break
        return companies


def run_company_discovery(city: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Orchestrates all enabled company collectors, deduplicates by domain & fuzzy name, and saves records."""
    init_db()
    logger.info("=== Starting Company Discovery ===")

    enabled = settings.company_enabled_sources
    collectors: List[BaseCompanyCollector] = []

    if enabled.get("seed_list", True):
        collectors.append(SeedListCollector())
    if enabled.get("ats_boards", True):
        collectors.append(ATSBoardsCollector())
    if enabled.get("kerala_parks", True):
        collectors.append(KeralaParksCollector())
    if enabled.get("github_orgs", True):
        collectors.append(GitHubOrgsCollector())
    if enabled.get("search_queries", True):
        collectors.append(SearchQueriesCollector())

    per_source_counts: Dict[str, int] = {}
    total_discovered = 0
    all_raw_candidates: List[Company] = []

    for col in collectors:
        try:
            items = col.collect(limit=limit)
            per_source_counts[col.source_name] = len(items)
            total_discovered += len(items)
            all_raw_candidates.extend(items)
            logger.info("Collector '%s' discovered %d candidate companies.", col.source_name, len(items))
        except Exception as e:
            logger.error("Collector '%s' encountered error: %s", col.source_name, e)
            per_source_counts[col.source_name] = 0

    # Deduplicate against database and in-memory list
    existing_companies = list_companies()
    existing_domains: Dict[str, int] = {}
    existing_names: List[Tuple[str, int]] = []

    for ec in existing_companies:
        cid = ec["id"]
        if ec.get("domain"):
            existing_domains[ec["domain"].lower().strip()] = cid
        if ec.get("name"):
            existing_names.append((ec["name"], cid))

    saved_count = 0
    for cand in all_raw_candidates:
        if city and cand.city and city.lower() not in cand.city.lower():
            continue

        cand_domain = normalize_domain(cand.domain) or normalize_domain(cand.website)
        matched_cid = None

        if cand_domain and cand_domain in existing_domains:
            matched_cid = existing_domains[cand_domain]
        else:
            # Check fuzzy name against existing names
            for ex_name, ex_cid in existing_names:
                if are_company_names_similar(cand.name, ex_name):
                    matched_cid = ex_cid
                    break

        try:
            cid = save_company(cand, company_id=matched_cid)
            if cand_domain:
                existing_domains[cand_domain] = cid
            existing_names.append((cand.name, cid))
            saved_count += 1
        except Exception as e:
            logger.warning("Error saving discovered company candidate '%s' (domain: %s): %s", cand.name, cand.domain, e)

    final_total = len(list_companies())
    logger.info("Company discovery complete. Discovered: %d, Deduplicated and Stored/Updated: %d. Total database companies: %d",
                total_discovered, saved_count, final_total)

    return {
        "discovered": total_discovered,
        "processed": saved_count,
        "total_database_companies": final_total,
        "per_source_counts": per_source_counts
    }
