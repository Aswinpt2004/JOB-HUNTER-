import logging
from typing import List
from urllib.parse import urlencode
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.adzuna")


@register_source
class AdzunaSource(BaseSource):
    name = "adzuna"
    display_name = "Adzuna API (India)"
    requires_api_key = True

    def is_configured(self) -> bool:
        return bool(settings.adzuna_app_id and settings.adzuna_app_key)

    def fetch_jobs(self) -> List[RawJob]:
        if not self.is_configured():
            logger.info("Adzuna API credentials not configured; skipping.")
            return []

        jobs: List[RawJob] = []
        queries = ["AI ML Engineer", "Computer Vision", "Python Developer", "Machine Learning"]
        locations = ["Bangalore", "Kochi", "Trivandrum", "India"]

        base_url = "https://api.adzuna.com/v1/api/jobs/in/search/1"
        for q in queries:
            for loc in locations:
                params = {
                    "app_id": settings.adzuna_app_id,
                    "app_key": settings.adzuna_app_key,
                    "what": q,
                    "where": loc,
                    "results_per_page": 20,
                    "content-type": "application/json"
                }
                try:
                    self.polite_delay()
                    resp = self.session.get(base_url, params=params, timeout=12)
                    if resp.status_code != 200:
                        logger.warning("Adzuna API returned status %s for query %s in %s", resp.status_code, q, loc)
                        continue
                    data = resp.json()
                    for item in data.get("results", []):
                        title = item.get("title", "").strip()
                        company = (item.get("company", {}) or {}).get("display_name", "Unknown Company").strip()
                        url = item.get("redirect_url", "")
                        desc = self.strip_html(item.get("description", ""))
                        loc_name = (item.get("location", {}) or {}).get("display_name", loc)
                        salary_min = item.get("salary_min")
                        salary_max = item.get("salary_max")
                        salary_str = f"{salary_min} - {salary_max}" if salary_min and salary_max else None

                        if url and title:
                            jobs.append(RawJob(
                                title=title,
                                company=company,
                                location=loc_name,
                                url=url,
                                description=desc,
                                source="adzuna",
                                source_job_id=str(item.get("id")),
                                posted_date=item.get("created"),
                                salary=salary_str
                            ))
                except Exception as e:
                    logger.error("Error fetching Adzuna jobs for %s in %s: %s", q, loc, e)
        return jobs

