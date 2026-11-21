import abc
import logging
import random
import time
import urllib.robotparser
from typing import Dict, List, Optional, Type
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

from jobpilot.core.config import settings
from jobpilot.core.models import RawJob
from jobpilot.core.db import save_job, start_run, finish_run, log_event
from jobpilot.core.events import event_broadcaster

logger = logging.getLogger("jobpilot.sources.base")

_SOURCES_REGISTRY: Dict[str, Type["BaseSource"]] = {}


def register_source(cls: Type["BaseSource"]):
    _SOURCES_REGISTRY[cls.name] = cls
    return cls


def get_registered_sources() -> Dict[str, Type["BaseSource"]]:
    return _SOURCES_REGISTRY


def get_source(name: str) -> Optional["BaseSource"]:
    cls = _SOURCES_REGISTRY.get(name)
    if cls:
        return cls()
    return None


class BaseSource(abc.ABC):
    name: str = "base"
    display_name: str = "Base Source"
    requires_api_key: bool = False

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "JobPilot/2.0 (+https://github.com/Aswinpt2004/JOB-HUNTER-; Candidate Job Finder)",
            "Accept": "application/json, text/html, */*",
        })
        self._robot_parsers: Dict[str, urllib.robotparser.RobotFileParser] = {}

    def is_configured(self) -> bool:
        return True

    def polite_delay(self):
        delay = random.uniform(1.0, 2.5)
        time.sleep(delay)

    def is_allowed_by_robots(self, target_url: str, is_api: bool = False) -> bool:
        if is_api:
            return True
        try:
            parsed = urlparse(target_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            if base_url not in self._robot_parsers:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{base_url}/robots.txt")
                rp.read()
                self._robot_parsers[base_url] = rp
            else:
                rp = self._robot_parsers[base_url]
            allowed = rp.can_fetch(self.session.headers["User-Agent"], target_url)
            return allowed if allowed is not None else True
        except Exception:
            return True

    @staticmethod
    def strip_html(html_text: str) -> str:
        if not html_text:
            return ""
        soup = BeautifulSoup(html_text, "html.parser")
        return soup.get_text(separator="\n").strip()

    @abc.abstractmethod
    def fetch_jobs(self) -> List[RawJob]:
        """Fetch listings from this source, returning normalized RawJob objects."""
        pass

    def run(self) -> Dict[str, int]:
        """Runs this source, processes jobs through pipeline, and records metrics."""
        run_id = start_run(run_type=f"source_{self.name}")
        event_broadcaster.broadcast_sync("source_started", {"source": self.name, "run_id": run_id})
        logger.info("Starting source run: %s (run #%d)", self.name, run_id)

        from jobpilot.pipeline.prescreen import prescreen_job
        from jobpilot.pipeline.location import normalize_location
        from jobpilot.pipeline.route import resolve_apply_target

        counts = {"discovered": 0, "filtered_location": 0, "filtered_senior": 0, "saved": 0}

        try:
            raw_jobs = self.fetch_jobs()
            counts["discovered"] = len(raw_jobs)
            logger.info("Source %s returned %d raw listings", self.name, len(raw_jobs))

            for raw in raw_jobs:
                # 1. Location filtering
                loc_res = normalize_location(raw.location, jd_text=raw.description, title=raw.title)
                if not loc_res["matched"]:
                    counts["filtered_location"] += 1
                    continue
                raw.location = loc_res["normalized_city"]

                # 2. Prescreen senior / overqualified jobs (preserve fresher 0-1 yr)
                screen = prescreen_job(raw.title, raw.description)
                if not screen["eligible"]:
                    counts["filtered_senior"] += 1
                    continue

                # 3. Resolve apply route
                route_res = resolve_apply_target(raw.url, raw.apply_url, raw.description)
                raw.apply_url = route_res["apply_url"]
                raw.apply_kind = route_res["apply_kind"]
                raw.easy_apply = route_res["easy_apply"]
                if route_res.get("recruiter_email") and not raw.recruiter_email:
                    raw.recruiter_email = route_res["recruiter_email"]

                # 4. Save to database
                job_id = save_job(raw)
                counts["saved"] += 1

                event_broadcaster.broadcast_sync("job_saved", {
                    "job_id": job_id,
                    "title": raw.title,
                    "company": raw.company,
                    "source": self.name,
                    "apply_kind": raw.apply_kind
                })

            finish_run(run_id, status="success", counts=counts)
            event_broadcaster.broadcast_sync("source_finished", {"source": self.name, "run_id": run_id, "counts": counts})
            log_event(f"source.{self.name}", f"Run completed: {counts}")
            return counts

        except Exception as e:
            logger.exception("Error in source run %s: %s", self.name, e)
            finish_run(run_id, status="failed", counts=counts, error=str(e))
            event_broadcaster.broadcast_sync("source_error", {"source": self.name, "error": str(e)})
            raise


def run_all_enabled_sources() -> Dict[str, Dict[str, int]]:
    """Runs all configured and enabled sources."""
    results = {}
    sources_cfg = settings.sources_config
    for name, cls in _SOURCES_REGISTRY.items():
        cfg = sources_cfg.get(name, {})
        # Enabled by default if not explicitly disabled in config
        is_enabled = cfg.get("enabled", True) if isinstance(cfg, dict) else True
        if not is_enabled:
            continue
        source_inst = cls()
        if source_inst.is_configured():
            try:
                results[name] = source_inst.run()
            except Exception as e:
                logger.error("Failed to run source %s: %s", name, e)
                results[name] = {"error": str(e)}
        else:
            logger.info("Source %s skipped (API keys or credentials not configured)", name)
    return results

