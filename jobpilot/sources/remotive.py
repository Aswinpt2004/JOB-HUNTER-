import logging
from typing import List
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.remotive")


@register_source
class RemotiveSource(BaseSource):
    name = "remotive"
    display_name = "Remotive (Remote Dev & AI)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        categories = ["software-dev", "data"]

        for cat in categories:
            url = f"https://remotive.com/api/remote-jobs?category={cat}&limit=50"
            try:
                self.polite_delay()
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200:
                    logger.warning("Remotive returned status %s for category %s", resp.status_code, cat)
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    company = item.get("company_name", "Unknown").strip()
                    url_link = item.get("url", "")
                    cand_loc = (item.get("candidate_required_location") or "").lower()

                    # Only keep jobs that permit India or Worldwide / Anywhere
                    allowed_markers = ["india", "worldwide", "anywhere", "apac", "global", "all"]
                    disallowed = ["us only", "usa only", "uk only", "europe only", "americas only", "latam", "canada only"]
                    if any(d in cand_loc for d in disallowed):
                        continue
                    if cand_loc and not any(a in cand_loc for a in allowed_markers):
                        continue

                    desc = self.strip_html(item.get("description", ""))
                    salary = item.get("salary")

                    if url_link and title:
                        jobs.append(RawJob(
                            title=title,
                            company=company,
                            location=item.get("candidate_required_location") or "Remote India",
                            url=url_link,
                            description=desc,
                            source="remotive",
                            source_job_id=str(item.get("id")),
                            posted_date=item.get("publication_date"),
                            salary=salary
                        ))
            except Exception as e:
                logger.error("Error fetching Remotive jobs for %s: %s", cat, e)
        return jobs

