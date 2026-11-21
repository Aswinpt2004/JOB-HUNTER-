import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.sync_api import sync_playwright

from jobpilot.core.config import settings
from jobpilot.core.db import get_all_answers, update_application_status, log_event

logger = logging.getLogger("jobpilot.apply.ats_assist")


def load_candidate_answers() -> Dict[str, str]:
    db_answers = get_all_answers()
    answers = {k: v["value"] for k, v in db_answers.items() if "[FILL]" not in v["value"]}
    if settings.answers_path.exists():
        try:
            with open(settings.answers_path, "r", encoding="utf-8") as f:
                file_answers = json.load(f)
                for k, v in file_answers.items():
                    if k not in answers and "[FILL]" not in str(v):
                        answers[k] = str(v)
        except Exception:
            pass
    return answers


def run_ats_assistant(
    app_id: int,
    apply_url: str,
    resume_pdf_path: Optional[str] = None,
    cover_note: Optional[str] = None
) -> Dict[str, Any]:
    """
    Launches a visible Chromium browser window to pre-fill ATS job applications.
    Strict safety rule: Uploads resume and pre-fills profile fields, but NEVER submits!
    Leaves the final submission decision and review exclusively to the human candidate.
    """
    answers = load_candidate_answers()
    full_name = answers.get("full_name", settings.user_name)
    name_parts = full_name.split()
    first_name = name_parts[0] if name_parts else ""
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

    email = answers.get("email", settings.user_email)
    phone = answers.get("phone", settings.user_phone)
    linkedin = answers.get("linkedin_url", "")
    github = answers.get("github_url", "")
    portfolio = answers.get("portfolio_url", "")

    filled_fields = []

    try:
        with sync_playwright() as p:
            logger.info("Launching visible Chromium browser for ATS Assist at %s", apply_url)
            browser = p.chromium.launch(headless=False, slow_mo=50)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            page.goto(apply_url, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            # 1. Upload Resume PDF
            if resume_pdf_path and Path(resume_pdf_path).exists():
                try:
                    file_input = page.locator("input[type='file']")
                    if file_input.count() > 0:
                        file_input.first.set_input_files(str(Path(resume_pdf_path).resolve()))
                        filled_fields.append("resume_upload")
                        logger.info("Uploaded tailored resume PDF")
                except Exception as e:
                    logger.warning("Could not auto-upload file: %s", e)

            # 2. Fill Name fields
            try:
                for sel in ["input[name*='name' i]", "input[id*='name' i]", "input[placeholder*='name' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        name_val = loc.first.input_value()
                        if not name_val:
                            # Check if it's first name vs full name
                            outer = loc.first.evaluate("el => el.outerHTML").lower()
                            if "first" in outer:
                                loc.first.fill(first_name)
                                filled_fields.append("first_name")
                            elif "last" in outer:
                                loc.first.fill(last_name)
                                filled_fields.append("last_name")
                            else:
                                loc.first.fill(full_name)
                                filled_fields.append("full_name")
                            break
            except Exception:
                pass

            # 3. Fill Email
            try:
                for sel in ["input[type='email']", "input[name*='email' i]", "input[id*='email' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if not loc.first.input_value():
                            loc.first.fill(email)
                            filled_fields.append("email")
                            break
            except Exception:
                pass

            # 4. Fill Phone
            try:
                for sel in ["input[type='tel']", "input[name*='phone' i]", "input[id*='phone' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if not loc.first.input_value():
                            loc.first.fill(phone)
                            filled_fields.append("phone")
                            break
            except Exception:
                pass

            # 5. Fill URLs (LinkedIn, GitHub, Portfolio)
            try:
                for sel in ["input[name*='linkedin' i]", "input[id*='linkedin' i]", "input[placeholder*='linkedin' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if not loc.first.input_value():
                            loc.first.fill(linkedin)
                            filled_fields.append("linkedin")
                            break
            except Exception:
                pass

            try:
                for sel in ["input[name*='github' i]", "input[id*='github' i]", "input[placeholder*='github' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if not loc.first.input_value():
                            loc.first.fill(github)
                            filled_fields.append("github")
                            break
            except Exception:
                pass

            try:
                for sel in ["input[name*='website' i]", "input[name*='portfolio' i]", "input[id*='portfolio' i]"]:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if not loc.first.input_value():
                            loc.first.fill(portfolio)
                            filled_fields.append("portfolio")
                            break
            except Exception:
                pass

            # 6. Fill Cover Note
            if cover_note:
                try:
                    for sel in ["textarea[name*='cover' i]", "textarea[id*='cover' i]", "textarea[placeholder*='cover' i]"]:
                        loc = page.locator(sel)
                        if loc.count() > 0 and loc.first.is_visible():
                            if not loc.first.input_value():
                                loc.first.fill(cover_note)
                                filled_fields.append("cover_note")
                                break
                except Exception:
                    pass

            logger.info("ATS Assist pre-filled fields: %s", filled_fields)
            log_event("ats_assist", f"Pre-filled application #{app_id}: {filled_fields}")

            # Keep window open for candidate to review and submit manually
            # Sleep 15s to allow candidate to take over the browser window
            time.sleep(15)
            browser.close()

            return {
                "success": True,
                "filled_fields": filled_fields,
                "message": "Application pre-filled in visible browser. Candidate review required."
            }

    except Exception as e:
        logger.exception("ATS assist encountered an error: %s", e)
        return {"success": False, "error": str(e)}

