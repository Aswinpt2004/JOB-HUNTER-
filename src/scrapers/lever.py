import logging
from typing import List
from src.config import settings
from src.models import Job
from src.scrapers.base import BaseScraper
from src.db import log_event

logger = logging.getLogger("jobpilot.scraper.lever")


class LeverScraper(BaseScraper):
    def __init__(self, boards: List[str] = None):
        super().__init__(source_name="lever")
        if isinstance(boards, str):
            boards = [boards]
        self.boards = boards or settings.lever_boards

    def fetch_jobs(self) -> List[Job]:
        all_jobs: List[Job] = []

        for board in self.boards:
            api_url = f"https://api.lever.co/v0/postings/{board}?mode=json"
            logger.info("Checking Lever board: %s", board)

            if not self.is_allowed_by_robots(api_url, is_api=True):
                logger.warning("Robots.txt disallowed access to Lever board: %s", board)
                continue

            try:
                self.polite_delay()
                response = self.session.get(api_url, timeout=12)
                if response.status_code != 200:
                    logger.warning("Lever board '%s' returned status %d", board, response.status_code)
                    continue

                jobs_data = response.json()
                if not isinstance(jobs_data, list):
                    continue

                for item in jobs_data:
                    title = item.get("text", "")
                    job_url = item.get("hostedUrl", "")
                    if not job_url or self.is_duplicate(job_url):
                        continue

                    desc_plain = item.get("descriptionPlain", "") or ""
                    additional_plain = item.get("additionalPlain", "") or ""
                    full_text = f"{desc_plain}\n{additional_plain}"

                    # Filter by keywords
                    check_text = f"{title} {full_text}".lower()
                    if settings.keywords and not any(kw.lower() in check_text for kw in settings.keywords):
                        continue

                    categories = item.get("categories", {})
                    location = categories.get("location", "Remote")

                    if not self.matches_preferred_location(location):
                        continue

                    job = Job(
                        id=self.generate_id(board, job_url),
                        title=title,
                        company=board.capitalize(),
                        location=location or "Remote",
                        url=job_url,
                        description=full_text or title,
                        posted_date=str(item.get("createdAt")),
                        source="lever"
                    )
                    all_jobs.append(job)

                log_event("scraper.lever", f"Found {len(all_jobs)} candidate jobs on Lever board '{board}'")

            except Exception as e:
                logger.error("Error scraping Lever board '%s': %s", board, e)

        return all_jobs
