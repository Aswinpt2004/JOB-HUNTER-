import logging
from typing import List
from src.config import settings
from src.models import Job
from src.scrapers.base import BaseScraper
from src.db import log_event

logger = logging.getLogger("jobpilot.scraper.greenhouse")


class GreenhouseScraper(BaseScraper):
    def __init__(self, boards: List[str] = None):
        super().__init__(source_name="greenhouse")
        if isinstance(boards, str):
            boards = [boards]
        self.boards = boards or settings.greenhouse_boards

    def fetch_jobs(self) -> List[Job]:
        all_jobs: List[Job] = []

        for board in self.boards:
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
            logger.info("Checking Greenhouse board: %s", board)

            if not self.is_allowed_by_robots(api_url, is_api=True):
                logger.warning("Robots.txt disallowed access to Greenhouse board: %s", board)
                continue

            try:
                self.polite_delay()
                response = self.session.get(api_url, timeout=12)
                if response.status_code != 200:
                    logger.warning("Greenhouse board '%s' returned status %d", board, response.status_code)
                    continue

                data = response.json()
                jobs_data = data.get("jobs", [])

                for item in jobs_data:
                    title = item.get("title", "")
                    job_url = item.get("absolute_url", "")
                    if not job_url or self.is_duplicate(job_url):
                        continue

                    # Filter by keywords
                    combined_text = f"{title} {item.get('content', '')}".lower()
                    if settings.keywords and not any(kw.lower() in combined_text for kw in settings.keywords):
                        continue

                    location_obj = item.get("location", {})
                    location_name = location_obj.get("name", "Remote") if isinstance(location_obj, dict) else str(location_obj)

                    if not self.matches_preferred_location(location_name):
                        continue

                    clean_description = self.strip_html(item.get("content", ""))

                    job = Job(
                        id=self.generate_id(board, job_url),
                        title=title,
                        company=board.capitalize(),
                        location=location_name or "Remote",
                        url=job_url,
                        description=clean_description or title,
                        posted_date=item.get("updated_at"),
                        source="greenhouse"
                    )
                    all_jobs.append(job)

                log_event("scraper.greenhouse", f"Found {len(all_jobs)} candidate jobs on board '{board}'")

            except Exception as e:
                logger.error("Error scraping Greenhouse board '%s': %s", board, e)

        return all_jobs
