import logging
from typing import List, Dict, Any
from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.sources.base import BaseSource, register_source

logger = logging.getLogger("jobpilot.sources.ats")


@register_source
class ATSSource(BaseSource):
    name = "ats"
    display_name = "ATS Direct Boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)"
    requires_api_key = False

    def is_configured(self) -> bool:
        return True

    def fetch_jobs(self) -> List[RawJob]:
        jobs: List[RawJob] = []
        cfg = settings.sources_config.get("ats", {})

        # 1. Greenhouse
        gh_boards = cfg.get("greenhouse_boards", ["inmobi", "groww", "thoughtworks", "canonical", "gitlab", "slice"])
        jobs.extend(self._fetch_greenhouse(gh_boards))

        # 2. Lever
        lever_boards = cfg.get("lever_boards", ["meesho", "palantir", "cred"])
        jobs.extend(self._fetch_lever(lever_boards))

        # 3. Ashby
        ashby_boards = cfg.get("ashby_boards", ["postman", "zapier"])
        jobs.extend(self._fetch_ashby(ashby_boards))

        # 4. Workable
        workable_accounts = cfg.get("workable_accounts", ["browserstack"])
        jobs.extend(self._fetch_workable(workable_accounts))

        # 5. SmartRecruiters
        sr_companies = cfg.get("smartrecruiters_companies", ["bosch"])
        jobs.extend(self._fetch_smartrecruiters(sr_companies))

        return jobs

    def _fetch_greenhouse(self, boards: List[str]) -> List[RawJob]:
        results: List[RawJob] = []
        for board in boards:
            api_url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
            try:
                self.polite_delay()
                resp = self.session.get(api_url, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    job_url = item.get("absolute_url", "")
                    loc_obj = item.get("location", {})
                    loc_name = loc_obj.get("name", "Remote") if isinstance(loc_obj, dict) else str(loc_obj)
                    desc = self.strip_html(item.get("content", ""))

                    if job_url and title:
                        results.append(RawJob(
                            title=title,
                            company=board.capitalize(),
                            location=loc_name,
                            url=job_url,
                            apply_url=job_url,
                            description=desc,
                            source="ats_greenhouse",
                            source_job_id=str(item.get("id")),
                            posted_date=item.get("updated_at"),
                            apply_kind="ats_greenhouse"
                        ))
            except Exception as e:
                logger.error("Error fetching Greenhouse board %s: %s", board, e)
        return results

    def _fetch_lever(self, boards: List[str]) -> List[RawJob]:
        results: List[RawJob] = []
        for board in boards:
            api_url = f"https://api.lever.co/v0/postings/{board}?mode=json"
            try:
                self.polite_delay()
                resp = self.session.get(api_url, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data:
                    title = item.get("text", "").strip()
                    job_url = item.get("hostedUrl", "")
                    apply_url = item.get("applyUrl", job_url)
                    categories = item.get("categories", {})
                    loc_name = categories.get("location", "Remote")
                    desc = self.strip_html(item.get("descriptionPlain", "") or item.get("description", ""))

                    if job_url and title:
                        results.append(RawJob(
                            title=title,
                            company=board.capitalize(),
                            location=loc_name,
                            url=job_url,
                            apply_url=apply_url,
                            description=desc,
                            source="ats_lever",
                            source_job_id=str(item.get("id")),
                            posted_date=str(item.get("createdAt")),
                            apply_kind="ats_lever"
                        ))
            except Exception as e:
                logger.error("Error fetching Lever board %s: %s", board, e)
        return results

    def _fetch_ashby(self, boards: List[str]) -> List[RawJob]:
        results: List[RawJob] = []
        for board in boards:
            api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
            try:
                self.polite_delay()
                resp = self.session.get(api_url, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    job_url = item.get("jobUrl", "")
                    loc_name = item.get("location", "Remote")
                    desc = self.strip_html(item.get("descriptionHtml", ""))

                    if job_url and title:
                        results.append(RawJob(
                            title=title,
                            company=board.capitalize(),
                            location=loc_name,
                            url=job_url,
                            apply_url=job_url,
                            description=desc,
                            source="ats_ashby",
                            source_job_id=str(item.get("id")),
                            posted_date=item.get("publishedAt"),
                            apply_kind="ats_ashby"
                        ))
            except Exception as e:
                logger.error("Error fetching Ashby board %s: %s", board, e)
        return results

    def _fetch_workable(self, accounts: List[str]) -> List[RawJob]:
        results: List[RawJob] = []
        for acc in accounts:
            api_url = f"https://apply.workable.com/api/v1/widget/accounts/{acc}"
            try:
                self.polite_delay()
                resp = self.session.get(api_url, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("jobs", []):
                    title = item.get("title", "").strip()
                    job_url = item.get("url", "")
                    city = item.get("city", "")
                    country = item.get("country", "")
                    location = f"{city}, {country}".strip(", ") or "Remote"
                    desc = self.strip_html(item.get("description", ""))

                    if job_url and title:
                        results.append(RawJob(
                            title=title,
                            company=acc.capitalize(),
                            location=location,
                            url=job_url,
                            apply_url=job_url,
                            description=desc,
                            source="ats_workable",
                            source_job_id=item.get("shortcode"),
                            apply_kind="ats_workable"
                        ))
            except Exception as e:
                logger.error("Error fetching Workable account %s: %s", acc, e)
        return results

    def _fetch_smartrecruiters(self, companies: List[str]) -> List[RawJob]:
        results: List[RawJob] = []
        for comp in companies:
            api_url = f"https://api.smartrecruiters.com/v1/companies/{comp}/postings"
            try:
                self.polite_delay()
                resp = self.session.get(api_url, timeout=12)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for item in data.get("content", []):
                    title = item.get("name", "").strip()
                    job_url = f"https://jobs.smartrecruiters.com/{comp}/{item.get('id')}"
                    loc_obj = item.get("location", {})
                    city = loc_obj.get("city", "")
                    country = loc_obj.get("country", "")
                    location = f"{city}, {country}".strip(", ") or "Remote"

                    if title:
                        results.append(RawJob(
                            title=title,
                            company=comp.capitalize(),
                            location=location,
                            url=job_url,
                            apply_url=job_url,
                            description=title,
                            source="ats_smartrecruiters",
                            source_job_id=str(item.get("id")),
                            posted_date=item.get("releasedDate"),
                            apply_kind="ats_smartrecruiters"
                        ))
            except Exception as e:
                logger.error("Error fetching SmartRecruiters company %s: %s", comp, e)
        return results

