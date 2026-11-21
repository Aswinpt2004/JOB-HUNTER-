import logging
from typing import List
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.jsearch")


@register_source
class JSearchSource(BaseSource):
    name = "jsearch"
    display_name = "JSearch (RapidAPI Google-for-Jobs Aggregator)"
    requires_api_key = True

    def is_configured(self) -> bool:
        return bool(settings.rapidapi_key)

    def fetch_jobs(self) -> List[RawJob]:
        if not self.is_configured():
            logger.info("RapidAPI key not configured; skipping JSearch.")
            return []

        jobs: List[RawJob] = []
        url = "https://jsearch.p.rapidapi.com/search"
        headers = {
            "x-rapidapi-key": settings.rapidapi_key,
            "x-rapidapi-host": "jsearch.p.rapidapi.com"
        }
        queries = ["AI ML Engineer in Bangalore", "Computer Vision Engineer India", "Python Developer Fresher India"]

        for q in queries:
            try:
                self.polite_delay()
                params = {
                    "query": q,
                    "page": "1",
                    "num_pages": "1",
                    "date_posted": "week"
                }
                resp = self.session.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code != 200:
                    logger.warning("JSearch returned status %s for %s", resp.status_code, q)
                    continue
                data = resp.json()
                for item in data.get("data", []):
                    title = item.get("job_title", "").strip()
                    company = item.get("employer_name", "Unknown").strip()
                    apply_link = item.get("job_apply_link", "") or item.get("job_google_link", "")
                    desc = item.get("job_description", "")
                    city = item.get("job_city", "")
                    country = item.get("job_country", "India")
                    location = f"{city}, {country}" if city else country
                    is_direct = item.get("job_apply_is_direct", False)

                    if apply_link and title:
                        jobs.append(RawJob(
                            title=title,
                            company=company,
                            location=location,
                            url=apply_link,
                            apply_url=apply_link,
                            description=desc,
                            source="jsearch",
                            source_job_id=item.get("job_id"),
                            posted_date=item.get("job_posted_at_datetime_utc"),
                            easy_apply=bool(is_direct)
                        ))
            except Exception as e:
                logger.error("Error fetching JSearch jobs: %s", e)
        return jobs

