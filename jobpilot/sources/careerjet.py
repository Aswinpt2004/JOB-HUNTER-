import logging
from typing import List
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.careerjet")


@register_source
class CareerjetSource(BaseSource):
    name = "careerjet"
    display_name = "Careerjet API (India)"
    requires_api_key = True

    def is_configured(self) -> bool:
        return bool(settings.careerjet_affiliate_id)

    def fetch_jobs(self) -> List[RawJob]:
        if not self.is_configured():
            logger.info("Careerjet affiliate ID not configured; skipping.")
            return []

        jobs: List[RawJob] = []
        url = "http://public.api.careerjet.net/search"
        queries = ["Machine Learning", "Computer Vision", "Python"]

        for q in queries:
            try:
                self.polite_delay()
                params = {
                    "affid": settings.careerjet_affiliate_id,
                    "user_ip": "127.0.0.1",
                    "user_agent": self.session.headers["User-Agent"],
                    "keywords": q,
                    "location": "India",
                    "locale_code": "en_IN",
                    "pagesize": 25
                }
                resp = self.session.get(url, params=params, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    company = item.get("company", "Unknown").strip()
                    link = item.get("url", "")
                    desc = self.strip_html(item.get("description", ""))
                    loc = item.get("locations", "India")
                    salary = item.get("salary")

                    if link and title:
                        jobs.append(RawJob(
                            title=title,
                            company=company,
                            location=loc,
                            url=link,
                            description=desc,
                            source="careerjet",
                            salary=salary,
                            posted_date=item.get("date")
                        ))
            except Exception as e:
                logger.error("Error fetching Careerjet jobs: %s", e)
        return jobs

