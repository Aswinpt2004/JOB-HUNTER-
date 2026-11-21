import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from jobpilot.core.config import settings
from jobpilot.core.db import (
    get_connection, get_all_jobs, get_job, get_pipeline_counts,
    get_all_answers, get_missing_answers_count, get_recent_runs,
    get_today_llm_usage
)
from jobpilot.core.scheduler import start_scheduler, stop_scheduler
from jobpilot.app.api import api_router
from jobpilot.apply.email_sender import get_sent_count_today, get_due_followups, mask_email
from jobpilot.sources.base import get_registered_sources

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "ui" / "static"
TEMPLATES_DIR = BASE_DIR / "ui" / "templates"
OUTPUT_DIR = settings.root_dir / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start APScheduler
    start_scheduler()
    yield
    # Shutdown: Stop scheduler
    stop_scheduler()


app = FastAPI(
    title="JobPilot v2",
    description="Multi-Source Job Search & Application Assistant for Aswin P T",
    version="2.0.0",
    lifespan=lifespan
)

# Static and output mounts
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.include_router(api_router)


# --- UI Pages ---

@app.get("/", response_class=HTMLResponse)
def page_today(request: Request):
    counts = get_pipeline_counts()
    sent_today = get_sent_count_today()
    due_followups = get_due_followups()
    missing_answers = get_missing_answers_count()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1")
        total_jobs = cursor.fetchone()[0]

        cursor.execute("""
            SELECT j.id, j.title, j.company, j.location, j.source, j.apply_kind,
                   a.status as app_status, a.match_score, a.route, a.id as application_id
            FROM jobs j
            LEFT JOIN applications a ON j.id = a.job_id
            WHERE a.status = 'drafted'
            ORDER BY a.match_score DESC
            LIMIT 10
        """)
        pending_jobs = [dict(r) for r in cursor.fetchall()]

    stats = {
        "total_jobs": total_jobs,
        "active_jobs": total_jobs,
        "drafted_count": counts.get("drafted", 0),
        "approved_count": counts.get("approved", 0),
        "applied_count": counts.get("applied", 0) + counts.get("emailed", 0) + counts.get("sent", 0),
        "replied_count": counts.get("replied", 0) + counts.get("interview", 0),
        "sent_today": sent_today
    }

    return templates.TemplateResponse(
        request=request,
        name="today.html",
        context={
            "active_page": "today",
            "stats": stats,
            "pending_jobs": pending_jobs,
            "due_followups": due_followups,
            "missing_answers": missing_answers
        }
    )


@app.get("/discover", response_class=HTMLResponse)
def page_discover(
    request: Request,
    page: int = Query(1, ge=1),
    search: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    apply_kind: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    page_size = 25
    offset = (page - 1) * page_size

    jobs, total_count = get_all_jobs(
        limit=page_size,
        offset=offset,
        status=status,
        apply_kind=apply_kind,
        search=search
    )
    total_pages = max(1, math.ceil(total_count / page_size))

    return templates.TemplateResponse(
        request=request,
        name="discover.html",
        context={
            "active_page": "discover",
            "jobs": jobs,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "filters": {
                "search": search,
                "location": location,
                "apply_kind": apply_kind,
                "status": status
            }
        }
    )


@app.get("/workbench", response_class=HTMLResponse)
def page_workbench_index():
    jobs, _ = get_all_jobs(limit=1, status="drafted")
    if not jobs:
        jobs, _ = get_all_jobs(limit=1)
    if jobs:
        return RedirectResponse(url=f"/workbench/{jobs[0]['id']}", status_code=303)
    return RedirectResponse(url="/discover", status_code=303)


@app.get("/workbench/{job_id}", response_class=HTMLResponse)
def page_workbench(request: Request, job_id: str):
    job = get_job(job_id)
    if not job:
        return HTMLResponse("Job not found", status_code=404)

    resume_pdf_url = None
    if job.get("resume_path") and Path(job["resume_path"]).exists():
        resume_pdf_url = f"/output/resumes/{Path(job['resume_path']).name}"

    return templates.TemplateResponse(
        request=request,
        name="workbench.html",
        context={
            "active_page": "discover",
            "job": job,
            "resume_pdf_url": resume_pdf_url
        }
    )


@app.get("/pipeline", response_class=HTMLResponse)
def page_pipeline(request: Request):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT j.id, j.title, j.company, j.location, j.apply_kind,
                   a.id as application_id, a.status as app_status, a.match_score,
                   a.route, a.applied_at, a.sent_at
            FROM jobs j
            JOIN applications a ON j.id = a.job_id
            ORDER BY a.updated_at DESC
        """)
        all_apps = [dict(r) for r in cursor.fetchall()]

    columns = {
        "new": [a for a in all_apps if a["app_status"] in ["new", None]],
        "drafted": [a for a in all_apps if a["app_status"] in ["drafted", "drafted_gmail"]],
        "approved": [a for a in all_apps if a["app_status"] == "approved"],
        "applied": [a for a in all_apps if a["app_status"] in ["applied", "emailed", "sent"]],
        "interview": [a for a in all_apps if a["app_status"] in ["replied", "interview"]],
        "closed": [a for a in all_apps if a["app_status"] in ["offer", "rejected", "skipped"]]
    }

    return templates.TemplateResponse(
        request=request,
        name="pipeline.html",
        context={
            "active_page": "pipeline",
            "columns": columns
        }
    )


@app.get("/companies", response_class=HTMLResponse)
def page_companies(request: Request):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies ORDER BY tier ASC, name ASC")
        companies = [dict(r) for r in cursor.fetchall()]
        for c in companies:
            import json
            try:
                c["field_tags"] = json.loads(c.get("field_tags") or "[]")
            except Exception:
                c["field_tags"] = []

            cursor.execute("SELECT email, name, role, domain_mx_valid FROM contacts WHERE company_id = ?", (c["id"],))
            c["contacts"] = [dict(ct) for ct in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={
            "active_page": "companies",
            "companies": companies
        }
    )


@app.get("/outbox", response_class=HTMLResponse)
def page_outbox(request: Request):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.sent_at, a.applied_at, a.recipient_email, a.email_subject,
                   a.route, a.status, a.resume_path, j.title, j.company
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.status IN ('sent', 'emailed', 'applied')
            ORDER BY COALESCE(a.sent_at, a.applied_at) DESC
        """)
        sent_items = [dict(r) for r in cursor.fetchall()]
        for s in sent_items:
            s["recipient_email"] = mask_email(s.get("recipient_email") or "")
            if s.get("resume_path"):
                s["resume_filename"] = Path(s["resume_path"]).name

    return templates.TemplateResponse(
        request=request,
        name="outbox.html",
        context={
            "active_page": "outbox",
            "sent_items": sent_items
        }
    )


@app.get("/followups", response_class=HTMLResponse)
def page_followups(request: Request):
    due = get_due_followups()
    for d in due:
        from datetime import datetime
        if d.get("sent_at"):
            sent_dt = datetime.fromisoformat(d["sent_at"])
            d["days_elapsed"] = (datetime.now() - sent_dt).days
        else:
            d["days_elapsed"] = 6
        d["recipient_email"] = mask_email(d.get("recipient_email") or "")

    return templates.TemplateResponse(
        request=request,
        name="followups.html",
        context={
            "active_page": "followups",
            "due_followups": due
        }
    )


@app.get("/sources", response_class=HTMLResponse)
def page_sources(request: Request):
    registry = get_registered_sources()
    sources_data = []

    with get_connection() as conn:
        cursor = conn.cursor()
        for name, cls in registry.items():
            src = cls()
            cursor.execute("SELECT COUNT(*) FROM job_sources WHERE source = ?", (name,))
            count = cursor.fetchone()[0]
            sources_data.append({
                "name": name,
                "display_name": src.display_name,
                "is_configured": src.is_configured(),
                "description": f"Harvests listings and apply routes for {src.display_name}",
                "jobs_count": count
            })

    runs = get_recent_runs(limit=15)

    return templates.TemplateResponse(
        request=request,
        name="sources.html",
        context={
            "active_page": "sources",
            "sources": sources_data,
            "runs": runs
        }
    )


@app.get("/answers", response_class=HTMLResponse)
def page_answers(request: Request):
    answers = get_all_answers()
    return templates.TemplateResponse(
        request=request,
        name="answers.html",
        context={
            "active_page": "answers",
            "answers": answers
        }
    )


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    smtp_ok = bool(settings.smtp_user and settings.smtp_password and not settings.smtp_password.startswith("your_"))
    gemini_ok = bool(settings.gemini_api_key and not settings.gemini_api_key.startswith("your_"))
    llm_usage = get_today_llm_usage()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email, reason, added_at FROM blocklist ORDER BY added_at DESC")
        blocklist = [dict(r) for r in cursor.fetchall()]

    db_size = 0.0
    if settings.db_path.exists():
        db_size = round(settings.db_path.stat().st_size / (1024 * 1024), 2)

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "active_page": "settings",
            "gemini_configured": gemini_ok,
            "gemini_model": settings.gemini_model,
            "smtp_configured": smtp_ok,
            "smtp_host": settings.smtp_host,
            "smtp_user_masked": mask_email(settings.smtp_user),
            "llm_usage": llm_usage,
            "db_size_mb": db_size,
            "blocklist": blocklist
        }
    )

