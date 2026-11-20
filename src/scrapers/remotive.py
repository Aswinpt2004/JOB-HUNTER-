import logging
from typing import List
from src.config import settings
from src.models import Job
from src.scrapers.base import BaseScraper
from src.db import log_event

logger = logging.getLogger("jobpilot.scraper.remotive")


class RemotiveScraper(BaseScraper):
    def __init__(self, categories: List[str] = None):
        super().__init__(source_name="remotive")
        self.categories = categories or settings.remotive_categories

    def fetch_jobs(self) -> List[Job]:
        all_jobs: List[Job] = []

        for cat in self.categories:
            api_url = f"https://remotive.com/api/remote-jobs?category={cat}&limit=25"
            logger.info("Checking Remotive category: %s", cat)

            if not self.is_allowed_by_robots(api_url, is_api=True):
                logger.warning("Robots.txt disallowed access to Remotive API: %s", api_url)
                continue

            try:
                self.polite_delay()
                response = self.session.get(api_url, timeout=12)
                if response.status_code != 200:
                    logger.warning("Remotive API returned status %d", response.status_code)
                    continue

                data = response.json()
                jobs_data = data.get("jobs", [])

                for item in jobs_data:
                    title = item.get("title", "")
                    job_url = item.get("url", "")
                    company = item.get("company_name", "Unknown")
                    if not job_url or self.is_duplicate(job_url):
                        continue

                    description_html = item.get("description", "")
                    clean_desc = self.strip_html(description_html)

                    # Filter by keywords
                    check_text = f"{title} {clean_desc}".lower()
                    if settings.keywords and not any(kw.lower() in check_text for kw in settings.keywords):
                        continue

                    location = item.get("candidate_required_location", "Remote")

                    if not self.matches_preferred_location(location):
                        continue

                    job = Job(
                        id=self.generate_id(company, job_url),
                        title=title,
                        company=company,
                        location=location or "Remote",
                        url=job_url,
                        description=clean_desc or title,
                        posted_date=item.get("publication_date"),
                        source="remotive"
                    )
                    all_jobs.append(job)

                log_event("scraper.remotive", f"Found {len(all_jobs)} jobs for Remotive category '{cat}'")

            except Exception as e:
                logger.error("Error scraping Remotive: %s", e)

        return all_jobs
