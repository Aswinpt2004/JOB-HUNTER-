import logging
from typing import List, Dict, Any
from bs4 import BeautifulSoup
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.company_careers")


@register_source
class CompanyCareersSource(BaseSource):
    name = "company_careers"
    display_name = "Company Career Pages (QBurst, Accubits, CareStack, Zerodha, etc.)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        seed_list = settings.company_discovery_config.get("seed_companies", [])

        for comp in seed_list:
            careers_url = comp.get("careers_url")
            comp_name = comp.get("name", "Tech Company")
            city = comp.get("city", "Bangalore")

            if not careers_url:
                continue

            try:
                self.polite_delay()
                resp = self.session.get(careers_url, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", href=True)

                for a in links:
                    text = a.get_text(strip=True)
                    href = a["href"]
                    # Filter for job-like links
                    combined = f"{text} {href}".lower()
                    if any(k in combined for k in ["engineer", "developer", "machine-learning", "ai", "python", "vision", "intern"]):
                        if not href.startswith("http"):
                            from urllib.parse import urljoin
                            href = urljoin(careers_url, href)

                        jobs.append(RawJob(
                            title=text or f"Role at {comp_name}",
                            company=comp_name,
                            location=city,
                            url=href,
                            apply_url=href,
                            description=f"Direct opening at {comp_name}: {text}",
                            source="company_careers",
                            apply_kind="company_form"
                        ))
            except Exception as e:
                logger.error("Error scraping career page for %s: %s", comp_name, e)

        return jobs

