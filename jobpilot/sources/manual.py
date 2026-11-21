import logging
from typing import List, Optional
from bs4 import BeautifulSoup
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.manual")


@register_source
class ManualImportSource(BaseSource):
    name = "manual"
    display_name = "Manual Import (URL / JD Paste)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        # Manual jobs are imported on-demand via import_url or import_text
        return []

    def import_from_url(self, url: str, custom_title: Optional[str] = None, custom_company: Optional[str] = None) -> RawJob:
        """Fetches page content from URL, extracts title, description, and metadata."""
        self.polite_delay()
        resp = self.session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        title = custom_title
        if not title:
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else (soup.title.string.strip() if soup.title else "Imported Job")

        company = custom_company or "Imported Company"
        # Try finding company from og:site_name or domain
        if not custom_company:
            og_site = soup.find("meta", property="og:site_name")
            if og_site and og_site.get("content"):
                company = og_site["content"].strip()
            else:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc.replace("www.", "")
                company = domain.split(".")[0].capitalize()

        body_text = self.strip_html(resp.text)

        return RawJob(
            title=title,
            company=company,
            location="Remote",
            url=url,
            apply_url=url,
            description=body_text[:5000],
            source="manual"
        )

    def import_from_text(self, title: str, company: str, description: str, location: str = "Bangalore", url: Optional[str] = None) -> RawJob:
        target_url = url or f"manual://{abs(hash(company + title))}"
        return RawJob(
            title=title.strip(),
            company=company.strip(),
            location=location.strip(),
            url=target_url,
            apply_url=target_url,
            description=description.strip(),
            source="manual"
        )

