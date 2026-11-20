import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

from src.config import settings
from src.db import (
    init_db,
    list_applications_by_status,
    list_company_outreach_by_status,
    get_job,
    get_contacts_for_job,
    get_connection,
    log_event
)
from src.sender import (
    send_application_email,
    send_company_outreach_email,
    is_within_sending_hours,
    mask_email,
    IST
)

logger = logging.getLogger("jobpilot.send_worker")


class SendWorker:
    """
    Background worker thread that processes approved applications and outreaches.
    Applies sending hours, daily limits, 30-day cooldowns, and anti-spam delays (60-180s)
    inside the background thread without blocking the Streamlit UI.
    """
    _instance: Optional["SendWorker"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._is_running = False
        self._current_task: Optional[str] = None
        self._last_activity: Optional[str] = None
        self._total_sent = 0
        self._total_failed = 0
        self._ignore_hours = False

    @classmethod
    def get_instance(cls) -> "SendWorker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = SendWorker()
            return cls._instance

    def start(self, ignore_hours: bool = False) -> None:
        """Starts the background worker thread if not already active."""
        with self._lock:
            self._ignore_hours = ignore_hours
            if self._thread is not None and self._thread.is_alive():
                logger.info("SendWorker thread is already running.")
                self.trigger()
                return

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="JobPilotSendWorker")
            self._thread.start()
            self._is_running = True
            logger.info("SendWorker background thread started (ignore_hours=%s).", ignore_hours)
            log_event("send_worker", f"Started background send worker (ignore_hours={ignore_hours})")

    def stop(self) -> None:
        """Signals the background worker thread to stop."""
        self._stop_event.set()
        self._wake_event.set()
        self._is_running = False
        logger.info("SendWorker stop signal set.")

    def trigger(self) -> None:
        """Wakes up the worker immediately to process newly approved jobs."""
        self._wake_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Returns live telemetry of the background worker."""
        init_db()
        queued_apps = len(list_applications_by_status("approved"))
        queued_outreach = len(list_company_outreach_by_status("approved"))
        sending_apps = len(list_applications_by_status("sending"))
        sending_outreach = len(list_company_outreach_by_status("sending"))

        is_alive = self._thread is not None and self._thread.is_alive()
        return {
            "is_running": is_alive,
            "current_task": self._current_task,
            "last_activity": self._last_activity,
            "total_sent": self._total_sent,
            "total_failed": self._total_failed,
            "queued_count": queued_apps + queued_outreach,
            "queued_applications": queued_apps,
            "queued_outreach": queued_outreach,
            "sending_count": sending_apps + sending_outreach,
            "ignore_hours": self._ignore_hours
        }

    def process_next_item(self) -> bool:
        """
        Processes a single item from the approved queue (job application or speculative outreach).
        Returns True if an item was processed, False otherwise.
        """
        init_db()
        approved_apps = list_applications_by_status("approved")
        approved_outreach = list_company_outreach_by_status("approved")

        if not approved_apps and not approved_outreach:
            return False

        # Check sending hours in Asia/Kolkata
        now_ist = datetime.now(IST)
        in_window, window_msg = is_within_sending_hours(now_ist)
        if not self._ignore_hours and not in_window:
            self._current_task = f"Waiting for sending window: {window_msg}"
            self._last_activity = f"Paused outside hours: {window_msg}"
            return False

        # 1. Process an approved job application if available
        if approved_apps:
            app = approved_apps[0]
            job_id = app["job_id"]
            job_data = get_job(job_id)

            if not job_data:
                return False

            company = job_data["company"]
            title = job_data["title"]
            contacts = get_contacts_for_job(job_id)
            recip = contacts[0]["email"] if contacts else (job_data.get("recruiter_email") or "")

            if not recip:
                self._last_activity = f"Skipped job {job_id}: No recruiter contact email."
                return False

            self._current_task = f"Dispatching email to {mask_email(recip)} for {title} at {company}..."
            logger.info(self._current_task)

            subject = app["email_subject"] or f"Application: {title} - {settings.candidate_name}"
            body = app["email_body"] or "Please find my attached resume."
            pdf_path = Path(app["resume_path"]) if app["resume_path"] else None

            ok, msg = send_application_email(
                job_id=job_id,
                recipient_email=recip,
                subject=subject,
                body=body,
                pdf_attachment_path=pdf_path,
                company_name=company,
                ignore_hours=self._ignore_hours
            )

            if ok:
                self._total_sent += 1
                self._last_activity = f"Sent to {mask_email(recip)} at {company}: {msg}"
                pacing = random.uniform(settings.send_delay_min, settings.send_delay_max)
                self._current_task = f"Pacing cooldown: sleeping {pacing:.1f}s before next send..."
                time.sleep(pacing)
            else:
                self._total_failed += 1
                self._last_activity = f"Failed for {company}: {msg}"
                time.sleep(5.0)

            return True

        # 2. Process an approved speculative outreach if available
        if approved_outreach:
            outreach = approved_outreach[0]
            oid = outreach["id"]
            cname = outreach.get("company_name", "Target Company")
            recip = outreach.get("contact_email") or ""

            self._current_task = f"Dispatching speculative outreach #{oid} to {mask_email(recip)} at {cname}..."
            logger.info(self._current_task)

            ok, msg = send_company_outreach_email(
                outreach_id=oid,
                ignore_hours=self._ignore_hours
            )

            if ok:
                self._total_sent += 1
                self._last_activity = f"Sent speculative email to {mask_email(recip)} at {cname}."
                pacing = random.uniform(settings.send_delay_min, settings.send_delay_max)
                self._current_task = f"Pacing cooldown: sleeping {pacing:.1f}s before next send..."
                time.sleep(pacing)
            else:
                self._total_failed += 1
                self._last_activity = f"Failed speculative outreach #{oid} for {cname}: {msg}"
                time.sleep(5.0)

            return True

        return False

    def _worker_loop(self) -> None:
        init_db()
        logger.info("SendWorker loop active.")

        while not self._stop_event.is_set():
            try:
                processed = self.process_next_item()
                if not processed:
                    self._current_task = "Idle (waiting for approved applications)"
                    self._wake_event.wait(timeout=10.0)
                    self._wake_event.clear()
            except Exception as e:
                logger.error("Exception in SendWorker thread: %s", e, exc_info=True)
                self._last_activity = f"Worker error: {e}"
                time.sleep(5.0)

        self._is_running = False
        logger.info("SendWorker loop finished.")


# Global singleton access
def get_send_worker() -> SendWorker:
    return SendWorker.get_instance()


def trigger_send_worker(ignore_hours: bool = False) -> None:
    worker = get_send_worker()
    worker.start(ignore_hours=ignore_hours)
    worker.trigger()


def get_worker_status() -> Dict[str, Any]:
    return get_send_worker().get_status()


def run_standalone_worker():
    """Runs the sender worker in a foreground loop for CLI usage."""
    import argparse
    parser = argparse.ArgumentParser(description="JobPilot Standalone Background Send Worker")
    parser.add_argument("--ignore-hours", action="store_true", help="Bypass the 09:00 - 18:00 IST sending window")
    args = parser.parse_args()

    print("=== JobPilot Background Send Worker Started ===")
    print(f"Ignore Hours: {args.ignore_hours}")
    print("Press Ctrl+C to terminate.")

    worker = get_send_worker()
    worker.start(ignore_hours=args.ignore_hours)

    try:
        while True:
            st = worker.get_status()
            print(f"[{datetime.now(IST).strftime('%H:%M:%S')}] Queued: {st['queued_count']} | Sent: {st['total_sent']} | Failed: {st['total_failed']} | Task: {st['current_task']}")
            time.sleep(10)
    except KeyboardInterrupt:
        print("\nStopping worker...")
        worker.stop()
        print("Worker stopped.")


if __name__ == "__main__":
    run_standalone_worker()
