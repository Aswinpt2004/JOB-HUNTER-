import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse

from jobpilot.core.config import settings
from jobpilot.core.db import (
    get_connection, get_job, update_application_status,
    save_tailored_application, update_answer, add_to_blocklist
)
from jobpilot.core.events import event_broadcaster
from jobpilot.tailor.resume_tailor import tailor_resume_for_job
from jobpilot.tailor.pdf_builder import generate_tailored_pdf
from jobpilot.tailor.cover_note import generate_cover_note, check_cover_note_tone
from jobpilot.tailor.email_writer import generate_tailored_email
from jobpilot.apply.email_sender import send_application_email
from jobpilot.apply.ats_assist import run_ats_assistant
from jobpilot.apply.packet import build_apply_packet
from jobpilot.sources.base import get_source, run_all_enabled_sources
from jobpilot.sources.manual import ManualImportSource

logger = logging.getLogger("jobpilot.api")

api_router = APIRouter(prefix="/api")


@api_router.get("/events")
async def sse_events():
    """SSE streaming endpoint for real-time progress and notifications."""
    q = event_broadcaster.subscribe()
    return StreamingResponse(
        event_broadcaster.event_generator(q),
        media_type="text/event-stream"
    )


@api_router.get("/health")
def health_check():
    """Fail-fast health report."""
    smtp_ok = bool(settings.smtp_user and settings.smtp_password and not settings.smtp_password.startswith("your_"))
    gemini_ok = bool(settings.gemini_api_key and not settings.gemini_api_key.startswith("your_"))
    db_ok = settings.db_path.exists()
    return {
        "status": "healthy" if (smtp_ok and gemini_ok and db_ok) else "degraded",
        "database": {"connected": db_ok, "path": str(settings.db_path)},
        "gemini": {"configured": gemini_ok, "model": settings.gemini_model},
        "smtp": {"configured": smtp_ok, "host": settings.smtp_host, "port": settings.smtp_port}
    }


@api_router.post("/jobs/{job_id}/tailor")
def tailor_job_endpoint(job_id: str, request: Request):
    job_dict = get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")

    from jobpilot.core.models import Job
    job = Job(**job_dict)

    # 1. Tailor Resume
    tailored = tailor_resume_for_job(job)

    # 2. Build 2-Page PDF
    pdf_path, fill_ratio = generate_tailored_pdf(tailored, job.id, job.company)

    # 3. Generate Cover Note
    cover_note = generate_cover_note(
        job_title=job.title,
        company=job.company,
        role_lens=tailored.lens or "Generic ML / Data Science",
        matched_skills=list(tailored.skills.get("Core AI/ML & Vision", []))[:3],
        location=job.location
    )
    tone_score = check_cover_note_tone(cover_note)

    # 4. Generate Email if route is email
    email_sub, email_bod = None, None
    if job.apply_kind == "email":
        email_sub, email_bod, email_tone = generate_tailored_email(job, tailored)
        tone_score = email_tone

    # 5. Generate Packet if route is packet
    packet_path = None
    route = "email" if job.apply_kind == "email" else ("ats_assist" if job.apply_kind.startswith("ats_") else "packet")
    if route == "packet":
        pkt = build_apply_packet(
            app_id=job_dict.get("application_id") or 0,
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            apply_url=job.apply_url or job.url,
            resume_pdf_path=pdf_path,
            cover_note=cover_note,
            matched_skills=list(tailored.skills.get("Core AI/ML & Vision", []))[:3]
        )
        packet_path = pkt["packet_path"]

    # 6. Save tailored application to SQLite
    tailored_json_path = str(settings.resume_output_dir / f"tailored_{job.id}.json")
    with open(tailored_json_path, "w", encoding="utf-8") as f:
        json.dump(tailored.model_dump(), f, indent=2, default=str)

    app_id = save_tailored_application(
        job_id=job.id,
        match_score=tailored.match_score or 85.0,
        resume_path=pdf_path,
        tailored_json_path=tailored_json_path,
        role_lens=tailored.lens or "Generic ML / Data Science",
        role_tier=tailored.target_tier or "Tier A",
        rationale=f"Tailored with lens {tailored.lens}. 2-page fit ratio: {fill_ratio*100:.1f}%.",
        route=route,
        email_subject=email_sub,
        email_body=email_bod,
        cover_note=cover_note,
        packet_path=packet_path,
        tone_score=tone_score
    )

    return RedirectResponse(url=f"/workbench/{job_id}", status_code=303)


@api_router.post("/applications/{app_id}/approve")
def approve_application(app_id: int, request: Request):
    update_application_status(app_id, "approved", note="Approved by candidate")
    if request.headers.get("hx-request") or "application/json" in request.headers.get("accept", ""):
        return {"status": "approved", "application_id": app_id}
    referer = request.headers.get("referer")
    if referer:
        return RedirectResponse(url=referer, status_code=303)
    return RedirectResponse(url="/pipeline", status_code=303)


@api_router.post("/applications/{app_id}/send")
def send_email_endpoint(
    app_id: int,
    recipient_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...)
):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.resume_path, j.company, j.id as job_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = ?
        """, (app_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")

    res = send_application_email(
        app_id=app_id,
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        pdf_attachment_path=Path(row["resume_path"]) if row["resume_path"] else None,
        company_name=row["company"]
    )

    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["error"])

    return RedirectResponse(url=f"/workbench/{row['job_id']}", status_code=303)


@api_router.post("/applications/{app_id}/ats-assist")
def ats_assist_endpoint(app_id: int, background_tasks: BackgroundTasks):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.resume_path, a.cover_note, j.apply_url, j.url, j.id as job_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = ?
        """, (app_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")

    target_url = row["apply_url"] or row["url"]

    # Run visible Playwright assist in thread/background so FastAPI doesn't block completely
    background_tasks.add_task(
        run_ats_assistant,
        app_id=app_id,
        apply_url=target_url,
        resume_pdf_path=row["resume_path"],
        cover_note=row["cover_note"]
    )

    return RedirectResponse(url=f"/workbench/{row['job_id']}?assist_launched=1", status_code=303)


@api_router.post("/applications/{app_id}/status")
def update_status_endpoint(request: Request, app_id: int, status: str = Form(...), note: Optional[str] = Form(None)):
    update_application_status(app_id, status, note=note or f"Updated to {status}")
    referer = request.headers.get("referer")
    if referer and "/pipeline" in referer:
        return RedirectResponse(url="/pipeline", status_code=303)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT job_id FROM applications WHERE id = ?", (app_id,))
        row = cursor.fetchone()
        job_id = row["job_id"] if row else None
    if job_id:
        return RedirectResponse(url=f"/workbench/{job_id}", status_code=303)
    return RedirectResponse(url="/pipeline", status_code=303)


@api_router.post("/sources/{source_name}/run")
def run_source_endpoint(source_name: str, background_tasks: BackgroundTasks):
    src = get_source(source_name)
    if not src:
        raise HTTPException(status_code=404, detail=f"Source {source_name} not found")
    if not src.is_configured():
        raise HTTPException(status_code=400, detail=f"Source {source_name} credentials not configured")

    background_tasks.add_task(src.run)
    return RedirectResponse(url="/sources?started=1", status_code=303)


@api_router.post("/sources/run-all")
def run_all_sources_endpoint(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_all_enabled_sources)
    return RedirectResponse(url="/sources?started=all", status_code=303)


@api_router.post("/answers/update")
def update_answer_endpoint(key: str = Form(...), value: str = Form(...)):
    update_answer(key, value)
    # Also update answers.json on disk
    if settings.answers_path.exists():
        try:
            with open(settings.answers_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data[key] = value
            with open(settings.answers_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
    return RedirectResponse(url="/answers?saved=1", status_code=303)


@api_router.post("/import/url")
def import_url_endpoint(
    url: str = Form(...),
    title: Optional[str] = Form(None),
    company: Optional[str] = Form(None)
):
    src = ManualImportSource()
    raw = src.import_from_url(url, custom_title=title, custom_company=company)
    from jobpilot.core.db import save_job
    job_id = save_job(raw)
    return RedirectResponse(url=f"/workbench/{job_id}", status_code=303)


@api_router.post("/import/text")
def import_text_endpoint(
    title: str = Form(...),
    company: str = Form(...),
    description: str = Form(...),
    location: str = Form("Bangalore")
):
    src = ManualImportSource()
    raw = src.import_from_text(title=title, company=company, description=description, location=location)
    from jobpilot.core.db import save_job
    job_id = save_job(raw)
    return RedirectResponse(url=f"/workbench/{job_id}", status_code=303)


@api_router.post("/blocklist/add")
def add_blocklist_endpoint(email: str = Form(...), reason: str = Form("User opt-out")):
    add_to_blocklist(email, reason)
    return RedirectResponse(url="/settings?blocked=1", status_code=303)


@api_router.post("/draft-all-gmail")
def draft_all_gmail_endpoint(
    background_tasks: BackgroundTasks,
    min_score: float = Form(75.0),
    limit: int = Form(30)
):
    from jobpilot.apply.gmail_drafts import draft_all_qualified_jobs_to_gmail
    background_tasks.add_task(draft_all_qualified_jobs_to_gmail, min_score=min_score, max_jobs=limit)
    return RedirectResponse(url="/?gmail_drafting=1", status_code=303)


@api_router.post("/applications/{app_id}/draft-gmail")
def draft_single_gmail_endpoint(
    app_id: int,
    recipient_email: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...)
):
    from jobpilot.apply.gmail_drafts import save_draft_to_gmail
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.resume_path, j.company, j.id as job_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.id = ?
        """, (app_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")

    res = save_draft_to_gmail(
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        pdf_attachment_path=Path(row["resume_path"]) if row["resume_path"] else None
    )

    if not res["success"]:
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to save draft to Gmail"))

    update_application_status(
        app_id,
        to_status="drafted_gmail",
        note=f"Saved directly to Gmail Drafts for {recipient_email}"
    )

    return RedirectResponse(url=f"/workbench/{row['job_id']}?drafted_gmail=1", status_code=303)


