import logging
from typing import List
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.arbeitnow")


@register_source
class ArbeitnowSource(BaseSource):
    name = "arbeitnow"
    display_name = "Arbeitnow (Remote Jobs)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        url = "https://www.arbeitnow.com/api/job-board-api"
        try:
            self.polite_delay()
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                company = item.get("company_name", "Unknown").strip()
                job_url = item.get("url", "")
                is_remote = item.get("remote", False)
                location = item.get("location", "Remote")

                # Filter for AI/Python/Dev roles
                combined = f"{title} {' '.join(item.get('tags', []))}".lower()
                if not any(k in combined for k in ["python", "ai", "machine learning", "data", "developer", "backend"]):
                    continue

                desc = self.strip_html(item.get("description", ""))
                if job_url and title:
                    jobs.append(RawJob(
                        title=title,
                        company=company,
                        location="Remote India" if is_remote else location,
                        url=job_url,
                        description=desc,
                        source="arbeitnow",
                        source_job_id=item.get("slug"),
                        posted_date=str(item.get("created_at"))
                    ))
        except Exception as e:
            logger.error("Error fetching Arbeitnow jobs: %s", e)
        return jobs

