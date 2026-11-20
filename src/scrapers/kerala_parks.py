import logging
import re
from typing import List
from bs4 import BeautifulSoup
import requests
from src.scrapers.base import BaseScraper
from src.models import Job
from src.config import settings

logger = logging.getLogger("jobpilot.scraper.kerala_parks")


class TechnoparkScraper(BaseScraper):
    """Scrapes job listings and direct HR emails from the Technopark Trivandrum (TVM) portal."""

    def __init__(self):
        super().__init__("technopark")
        self.api_base = "https://technopark.in/api/paginated-jobs"
        self.detail_base = "https://technopark.in/job-details"

    def fetch_jobs(self, max_pages: int = 5) -> List[Job]:
        logger.info("Fetching jobs from Technopark Trivandrum API...")
        jobs: List[Job] = []

        for page in range(1, max_pages + 1):
            try:
                self.polite_delay()
                url = f"{self.api_base}?page={page}&search=&type="
                res = self.session.get(url, timeout=12)
                if res.status_code != 200:
                    logger.warning("Technopark API returned status %s for page %d", res.status_code, page)
                    break

                data = res.json()
                page_jobs = data.get("data", [])
                if not page_jobs:
                    break

                for item in page_jobs:
                    job_id_num = item.get("id")
                    title = item.get("job_title", "").strip()
                    company_data = item.get("company") or {}
                    company_name = company_data.get("company", "Technopark Company").strip()
                    detail_url = f"{self.detail_base}/{job_id_num}"

                    if self.is_duplicate(detail_url):
                        continue

                    # Fetch job detail to extract description and direct HR contact email
                    try:
                        self.polite_delay()
                        det_res = self.session.get(detail_url, timeout=10)
                        if det_res.status_code != 200:
                            continue

                        # Extract Inertia data-page
                        soup = BeautifulSoup(det_res.text, "html.parser")
                        app_div = soup.find(id="app")
                        hr_email = None
                        description = ""

                        if app_div and app_div.has_attr("data-page"):
                            import json
                            page_data = json.loads(app_div["data-page"])
                            listing = page_data.get("props", {}).get("jobListing", {})
                            hr_email = listing.get("contact_email")
                            raw_desc = listing.get("job_description", "")
                            raw_skills = listing.get("preferred_skills", "")
                            description = self.strip_html(f"{raw_desc}\n\nKey Skills: {raw_skills}")

                        if not description:
                            description = self.strip_html(det_res.text)

                        # Clean HR email
                        if hr_email:
                            hr_email = hr_email.strip().lower()

                        job = Job(
                            id=self.generate_id(company_name, detail_url),
                            company=company_name,
                            title=title,
                            location="Thiruvananthapuram, Kerala, India",
                            url=detail_url,
                            description=description,
                            source="technopark_tvm",
                            recruiter_email=hr_email
                        )
                        jobs.append(job)

                    except Exception as e:
                        logger.debug("Failed fetching Technopark job detail %s: %s", detail_url, e)

                current_page = data.get("current_page", 1)
                last_page = data.get("last_page", 1)
                if current_page >= last_page:
                    break

            except Exception as e:
                logger.error("Error scraping Technopark page %d: %s", page, e)
                break

        logger.info("Technopark Trivandrum scraper collected %d jobs.", len(jobs))
        return jobs


class InfoparkScraper(BaseScraper):
    """Scrapes job listings and direct HR emails from the Infopark Kochi portal."""

    def __init__(self):
        super().__init__("infopark")
        self.base_url = "https://infopark.in/companies-job"

    def fetch_jobs(self, max_pages: int = 5) -> List[Job]:
        logger.info("Fetching jobs from Infopark Kochi portal...")
        jobs: List[Job] = []
        email_regex = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b')

        for page in range(1, max_pages + 1):
            try:
                self.polite_delay()
                page_url = f"{self.base_url}?page={page}"
                res = self.session.get(page_url, timeout=12)
                if res.status_code != 200:
                    break

                soup = BeautifulSoup(res.text, "html.parser")
                job_links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/company-jobs/details/" in href:
                        if href not in job_links:
                            job_links.append(href)

                if not job_links:
                    break

                for detail_url in job_links:
                    if self.is_duplicate(detail_url):
                        continue

                    try:
                        self.polite_delay()
                        det_res = self.session.get(detail_url, timeout=10)
                        if det_res.status_code != 200:
                            continue

                        det_soup = BeautifulSoup(det_res.text, "html.parser")

                        # Title & Company
                        page_title = det_soup.title.text if det_soup.title else ""
                        # Format is often "Job Title Jobs at Company Name | Infoparks Kerala"
                        title = "Software Engineer"
                        company_name = "Infopark Company"
                        if "Jobs at" in page_title:
                            parts = page_title.split("Jobs at")
                            title = parts[0].strip()
                            comp_part = parts[1].split("|")[0].strip()
                            if comp_part:
                                company_name = comp_part

                        # Extract HR email from text
                        all_emails = email_regex.findall(det_res.text)
                        hr_email = None
                        for em in all_emails:
                            em_low = em.lower().strip()
                            if "infopark.in" not in em_low and not em_low.startswith(("support@", "info@", "admin@")):
                                hr_email = em_low
                                break

                        desc_text = self.strip_html(det_res.text)

                        job = Job(
                            id=self.generate_id(company_name, detail_url),
                            company=company_name,
                            title=title,
                            location="Kochi, Kerala, India",
                            url=detail_url,
                            description=desc_text,
                            source="infopark_kochi",
                            recruiter_email=hr_email
                        )
                        jobs.append(job)

                    except Exception as e:
                        logger.debug("Failed fetching Infopark job %s: %s", detail_url, e)

            except Exception as e:
                logger.error("Error scraping Infopark page %d: %s", page, e)
                break

        logger.info("Infopark Kochi scraper collected %d jobs.", len(jobs))
        return jobs

