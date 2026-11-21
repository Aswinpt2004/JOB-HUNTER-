import logging
from typing import List
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.jooble")


@register_source
class JoobleSource(BaseSource):
    name = "jooble"
    display_name = "Jooble API (India)"
    requires_api_key = True

    def is_configured(self) -> bool:
        return bool(settings.jooble_api_key)

    def fetch_jobs(self) -> List[RawJob]:
        if not self.is_configured():
            logger.info("Jooble API key not configured; skipping.")
            return []

        jobs: List[RawJob] = []
        url = f"https://jooble.org/api/{settings.jooble_api_key}"
        queries = ["AI Engineer", "Computer Vision", "Python Developer"]

        for q in queries:
            try:
                self.polite_delay()
                payload = {"keywords": q, "location": "India"}
                resp = self.session.post(url, json=payload, timeout=12)
                if resp.status_code != 200:
                    logger.warning("Jooble API returned status %s for query %s", resp.status_code, q)
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    company = item.get("company", "Unknown").strip()
                    link = item.get("link", "")
                    snippet = self.strip_html(item.get("snippet", ""))
                    location = item.get("location", "India")
                    salary = item.get("salary")

                    if link and title:
                        jobs.append(RawJob(
                            title=title,
                            company=company,
                            location=location,
                            url=link,
                            description=snippet,
                            source="jooble",
                            source_job_id=str(item.get("id")),
                            posted_date=item.get("updated"),
                            salary=salary
                        ))
            except Exception as e:
                logger.error("Error fetching Jooble jobs for %s: %s", q, e)
        return jobs

