import json
import logging
from typing import List
from bs4 import BeautifulSoup
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.kerala_parks")


@register_source
class KeralaParksSource(BaseSource):
    name = "kerala_parks"
    display_name = "Kerala IT Parks (Technopark TVM & Infopark Kochi)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        jobs.extend(self._fetch_technopark(max_pages=3))
        jobs.extend(self._fetch_infopark(max_pages=2))
        return jobs

    def _fetch_technopark(self, max_pages: int = 3) -> List[RawJob]:
        results: List[RawJob] = []
        api_base = "https://technopark.in/api/paginated-jobs"
        detail_base = "https://technopark.in/job-details"

        for page in range(1, max_pages + 1):
            try:
                self.polite_delay()
                url = f"{api_base}?page={page}&search=&type="
                res = self.session.get(url, timeout=12)
                if res.status_code != 200:
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
                    detail_url = f"{detail_base}/{job_id_num}"

                    # Fetch job detail
                    hr_email = None
                    description = ""
                    try:
                        self.polite_delay()
                        det_res = self.session.get(detail_url, timeout=10)
                        if det_res.status_code == 200:
                            soup = BeautifulSoup(det_res.text, "html.parser")
                            app_div = soup.find(id="app")
                            if app_div and app_div.has_attr("data-page"):
                                page_data = json.loads(app_div["data-page"])
                                listing = page_data.get("props", {}).get("jobListing", {})
                                hr_email = listing.get("contact_email")
                                raw_desc = listing.get("job_description", "")
                                raw_skills = listing.get("preferred_skills", "")
                                description = self.strip_html(f"{raw_desc}\n\nKey Skills: {raw_skills}")
                    except Exception:
                        pass

                    if not description:
                        description = title

                    results.append(RawJob(
                        title=title,
                        company=company_name,
                        location="Thiruvananthapuram",
                        url=detail_url,
                        apply_url=f"mailto:{hr_email}" if hr_email else detail_url,
                        description=description,
                        source="kerala_parks",
                        source_job_id=str(job_id_num),
                        recruiter_email=hr_email,
                        apply_kind="email" if hr_email else "company_form",
                        posted_date=item.get("closing_date")
                    ))
            except Exception as e:
                logger.error("Error fetching Technopark page %d: %s", page, e)
        return results

    def _fetch_infopark(self, max_pages: int = 2) -> List[RawJob]:
        results: List[RawJob] = []
        base_url = "https://infopark.in/companies/job-search"
        try:
            self.polite_delay()
            resp = self.session.get(base_url, timeout=15)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select(".job-list-row, tr")
            for row in rows[:40]:
                link_tag = row.find("a")
                if not link_tag:
                    continue
                title = link_tag.get_text(strip=True)
                url = link_tag.get("href", "")
                if not url.startswith("http"):
                    url = f"https://infopark.in{url}"

                company_tag = row.find(class_=lambda c: c and "company" in c.lower())
                company_name = company_tag.get_text(strip=True) if company_tag else "Infopark Company"

                if title and url:
                    results.append(RawJob(
                        title=title,
                        company=company_name,
                        location="Kochi",
                        url=url,
                        description=f"{title} at {company_name}",
                        source="kerala_parks",
                        apply_kind="company_form"
                    ))
        except Exception as e:
            logger.error("Error fetching Infopark jobs: %s", e)
        return results

