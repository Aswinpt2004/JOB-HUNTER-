import abc
import hashlib
import logging
import random
import time
import urllib.robotparser
from typing import List, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from src.config import settings
from src.models import Job
from src.db import get_job_by_url, log_event

logger = logging.getLogger("jobpilot.scraper.base")


class BaseScraper(abc.ABC):
    def __init__(self, source_name: str):
        self.source_name = source_name
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept": "application/json, text/html, */*",
        })
        self._robot_parsers = {}

    def is_allowed_by_robots(self, target_url: str, is_api: bool = False) -> bool:
        """Checks target domain's robots.txt for compliance (applied to web crawlers; official APIs exempted)."""
        if is_api:
            return True
        try:
            parsed = urlparse(target_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            if base_url not in self._robot_parsers:
                rp = urllib.robotparser.RobotFileParser()
                robots_url = f"{base_url}/robots.txt"
                rp.set_url(robots_url)
                rp.read()
                self._robot_parsers[base_url] = rp
            else:
                rp = self._robot_parsers[base_url]

            allowed = rp.can_fetch(settings.user_agent, target_url)
            return allowed if allowed is not None else True
        except Exception:
            return True

    def polite_delay(self) -> None:
        """Injects a random delay between 2 and 5 seconds."""
        delay = random.uniform(settings.request_delay_min, settings.request_delay_max)
        time.sleep(delay)

    @staticmethod
    def matches_preferred_location(job_location: str, jd_text: str = "", title: str = "") -> bool:
        """Checks if a job location strictly matches user's preferred target locations
        (Bangalore, TVM, Kozhikode, Kochi, Remote India) using the robust location normalizer."""
        from src.location import normalize_location
        res = normalize_location(raw_location=job_location, jd_text=jd_text, title=title)
        return res["matched"]

    def is_duplicate(self, url: str, title: str = "", company: str = "") -> bool:
        """Checks database to avoid scraping duplicate URLs or already recorded jobs."""
        from src.db import is_job_duplicate, normalize_job_url, get_job_by_url
        norm = normalize_job_url(url)
        if get_job_by_url(norm) is not None:
            return True
        if title and company:
            return is_job_duplicate(title, company, norm)
        return False

    def strip_html(self, html_text: str) -> str:
        """Extracts clean human-readable text from HTML descriptions."""
        if not html_text:
            return ""
        soup = BeautifulSoup(html_text, "html.parser")
        return soup.get_text(separator="\n").strip()

    def generate_id(self, company: str, url: str) -> str:
        """Generates deterministic unique job ID based on cleaned company name and normalized URL."""
        from src.db import clean_company_name_for_matching, normalize_job_url
        clean_comp = clean_company_name_for_matching(company)
        norm_url = normalize_job_url(url)
        raw = f"{clean_comp}_{norm_url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @abc.abstractmethod
    def fetch_jobs(self) -> List[Job]:
        """Fetch and return list of normalized Job objects."""
        pass
