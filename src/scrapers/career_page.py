import logging
from typing import List, Dict
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from src.config import settings
from src.models import Job
from src.scrapers.base import BaseScraper
from src.db import log_event

logger = logging.getLogger("jobpilot.scraper.career_page")


class CareerPageScraper(BaseScraper):
    def __init__(self, target_pages: List[Dict[str, str]] = None):
        super().__init__(source_name="career_page")
        self.target_pages = target_pages or settings.career_pages

    def fetch_jobs(self) -> List[Job]:
        all_jobs: List[Job] = []

        for target in self.target_pages:
            url = target.get("url")
            company = target.get("company", "Company")
            if not url:
                continue

            logger.info("Scanning career page for %s: %s", company, url)

            if not self.is_allowed_by_robots(url):
                logger.warning("Robots.txt blocks %s", url)
                continue

            html = ""
            try:
                self.polite_delay()
                res = self.session.get(url, timeout=15)
                if res.status_code == 200:
                    html = res.text
            except Exception as e:
                logger.warning("Requests fetch failed for %s: %s", url, e)

            # If HTML is minimal (JS-heavy page), try Playwright fallback
            if len(html) < 800:
                html = self._fetch_with_playwright(url)

            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            # Extract links likely to be jobs
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                full_url = urljoin(url, href)

                # Keyword check in title/text
                if settings.keywords and not any(kw.lower() in text.lower() for kw in settings.keywords):
                    continue

                if self.is_duplicate(full_url):
                    continue

                # Filter obvious navigation links
                if len(text) < 4 or any(skip in href.lower() for skip in ["login", "privacy", "terms", "facebook", "twitter"]):
                    continue

                job = Job(
                    id=self.generate_id(company, full_url),
                    title=text,
                    company=company,
                    location="Remote / Check Link",
                    url=full_url,
                    description=f"Job posting found at {full_url}. Title: {text}",
                    source="career_page"
                )
                all_jobs.append(job)

        log_event("scraper.career_page", f"Found {len(all_jobs)} jobs across career pages")
        return all_jobs

    def _fetch_with_playwright(self, url: str) -> str:
        """Playwright fallback for client-side JavaScript rendered pages."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=settings.user_agent)
                page.goto(url, timeout=20000, wait_until="networkidle")
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            logger.debug("Playwright headless fetch not available or failed: %s", e)
            return ""

