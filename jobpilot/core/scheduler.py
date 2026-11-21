import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from jobpilot.core.config import settings
from jobpilot.core.events import event_broadcaster

logger = logging.getLogger("jobpilot.scheduler")

_scheduler: BackgroundScheduler = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    return _scheduler


def start_scheduler():
    scheduler = get_scheduler()
    if not scheduler.running:
        # 1. Periodic Discovery Job (every 6 hours) - only fetches and drafts listings
        scheduler.add_job(
            scheduled_discovery_job,
            "interval",
            hours=6,
            id="periodic_discovery",
            replace_existing=True
        )

        # 2. Followup Check (daily at 10:00 IST) - only identifies due followups for candidate notification
        scheduler.add_job(
            scheduled_followup_check_job,
            "cron",
            day_of_week="mon-fri",
            hour=10,
            minute=0,
            id="followup_check",
            replace_existing=True
        )

        scheduler.start()
        logger.info("JobPilot background scheduler started with IST timezone (Auto-send disabled: all jobs kept in draft).")



def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("JobPilot background scheduler stopped.")


def scheduled_discovery_job():
    logger.info("Triggered scheduled background discovery job.")
    event_broadcaster.broadcast_sync("scheduler", {"status": "Discovery job triggered", "time": datetime.now().isoformat()})
    try:
        from jobpilot.sources.base import run_all_enabled_sources
        results = run_all_enabled_sources()
        event_broadcaster.broadcast_sync("discovery_complete", {"results": results})
    except Exception as e:
        logger.error("Error in scheduled discovery job: %s", e)
        event_broadcaster.broadcast_sync("scheduler_error", {"error": str(e)})


def scheduled_followup_check_job():
    logger.info("Checking applications eligible for 6-day follow-up.")
    try:
        from jobpilot.apply.email_sender import get_due_followups
        due = get_due_followups()
        if due:
            event_broadcaster.broadcast_sync("followups_due", {"count": len(due)})
    except Exception as e:
        logger.error("Error in scheduled followup check: %s", e)


def get_scheduler_status():
    scheduler = get_scheduler()
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None
            })
    return {
        "running": scheduler.running,
        "jobs": jobs
    }

