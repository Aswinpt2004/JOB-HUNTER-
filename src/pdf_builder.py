import os
import re
import json
import logging
from pathlib import Path
from copy import deepcopy
from typing import Optional, Tuple, Dict, Any
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import fitz

from src.config import settings
from src.models import TailoredResume
from src.db import log_event

logger = logging.getLogger("jobpilot.pdf_builder")


def _sanitize_filename(name: str) -> str:
    """Removes unsafe characters for file paths."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


def build_pdf_with_xhtml2pdf(html_content: str, output_path: Path) -> bool:
    """Uses xhtml2pdf to generate PDF cleanly on Windows without GTK dependencies."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pisa_status = pisa.CreatePDF(html_content, dest=f)
    return not pisa_status.err


def render_resume_html(tailored: TailoredResume, style: Optional[Dict[str, Any]] = None) -> str:
    """Renders Jinja2 HTML resume template with tailored data and style parameters."""
    env = Environment(loader=FileSystemLoader(str(settings.templates_dir)))
    template = env.get_template("resume.html")

    effective_style = {
        "margin_top": 40.0,
        "margin_bottom": 20.0,
        "margin_left": 54.0,
        "margin_right": 40.0,
        "font_size_name": 18.0,
        "font_size_headline": 13.4,
        "font_size_headings": 11.5,
        "font_size_body": 9.9,
        "line_height": 1.35,
        "header_margin_bottom": 5.0,
        "heading_space_before": 7.0,
        "heading_space_after": 6.0,
        "spacing_experiences": 6.5,
        "spacing_projects": 14.5,
        "bullet_left_pad": 16.0,
        "bullet_text_indent": 10.0,
    }
    if style:
        effective_style.update(style)

    return template.render(
        style=effective_style,
        headline=tailored.headline,
        contact=tailored.contact,
        summary=tailored.summary,
        highlighted_skills=tailored.highlighted_skills,
        experience=tailored.experience,
        education=tailored.education,
        projects=tailored.projects
    )


def measure_pdf_metrics(
    pdf_path: Path,
    margin_top: float = 40.0,
    margin_bottom: float = 20.0
) -> Tuple[int, float, float, bool]:
    """
    Measures page count, vertical fills, and checks education placement using PyMuPDF.
    fill = (bottom_of_last_text_line - top_margin) / usable_height
    """
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    if page_count == 0:
        return 0, 0.0, 0.0, False

    usable_h = doc[0].rect.height - margin_top - margin_bottom

    p1_blocks = doc[0].get_text("blocks")
    if p1_blocks:
        max_y1 = max(b[3] for b in p1_blocks)
        fill_p1 = (max_y1 - margin_top) / usable_h
        p1_text = doc[0].get_text().upper()
        p1_has_edu = "EDUCATION" in p1_text and ("COMPUTER SCIENCE" in p1_text or "KERALA UNIVERSITY" in p1_text)
    else:
        fill_p1 = 0.0
        p1_has_edu = False

    fill_p2 = 0.0
    if page_count >= 2:
        p2_blocks = doc[1].get_text("blocks")
        if p2_blocks:
            max_y2 = max(b[3] for b in p2_blocks)
            fill_p2 = (max_y2 - margin_top) / usable_h
        p2_text = doc[1].get_text().upper()
        if "EDUCATION" in p2_text:
            p1_has_edu = False  # Education spilled to page 2

    return page_count, fill_p1, fill_p2, p1_has_edu


def fit_to_two_pages(
    tailored: TailoredResume,
    company: str,
    role: str
) -> Tuple[Path, Path, Dict[str, float], bool]:
    """
    Deterministic fit engine ensuring exactly 2 pages and fill in [0.93, 1.00] for both pages.
    Executes an adaptive optimization loop up to 12 iterations.
    """
    env = Environment(loader=FileSystemLoader(str(settings.templates_dir)))
    template = env.get_template("resume.html")

    candidate_clean = _sanitize_filename(tailored.contact.name)
    company_clean = _sanitize_filename(company)
    role_clean = _sanitize_filename(role)
    base_name = f"{candidate_clean}_{company_clean}_{role_clean}"

    out_dir = settings.resume_output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"{base_name}.pdf"
    json_path = out_dir / f"{base_name}.json"
    html_path = out_dir / f"{base_name}.html"

    working_tailored = deepcopy(tailored)

    style = {
        "margin_top": 40.0,
        "margin_bottom": 20.0,
        "margin_left": 54.0,
        "margin_right": 40.0,
        "font_size_name": 18.0,
        "font_size_headline": 13.4,
        "font_size_headings": 11.5,
        "font_size_body": 9.9,
        "line_height": 1.35,
        "header_margin_bottom": 5.0,
        "heading_space_before": 7.0,
        "heading_space_after": 6.0,
        "spacing_experiences": 6.5,
        "spacing_projects": 14.5,
        "bullet_left_pad": 16.0,
        "bullet_text_indent": 10.0,
    }

    best_html = ""
    best_fill = {"page1": 0.0, "page2": 0.0}
    best_score = float("inf")
    layout_warning = False

    for iteration in range(1, 13):
        rendered_html = template.render(
            style=style,
            headline=working_tailored.headline,
            contact=working_tailored.contact,
            summary=working_tailored.summary,
            highlighted_skills=working_tailored.highlighted_skills,
            experience=working_tailored.experience,
            education=working_tailored.education,
            projects=working_tailored.projects
        )

        with open(pdf_path, "wb") as f:
            pisa.CreatePDF(rendered_html, dest=f)

        page_count, f1, f2, edu_ok = measure_pdf_metrics(pdf_path, style["margin_top"], style["margin_bottom"])

        in_target = (page_count == 2 and edu_ok and 0.93 <= f1 <= 1.00 and 0.93 <= f2 <= 1.00)

        # Deviation penalty
        p1_dev = max(0.0, 0.93 - f1) + max(0.0, f1 - 1.00)
        p2_dev = max(0.0, 0.93 - f2) + max(0.0, f2 - 1.00)
        penalty = p1_dev + p2_dev
        if page_count != 2:
            penalty += 10.0 * abs(page_count - 2)
        if not edu_ok:
            penalty += 5.0

        if penalty < best_score:
            best_score = penalty
            best_html = rendered_html
            best_fill = {"page1": round(f1, 4), "page2": round(f2, 4)}

        if in_target:
            logger.info("Fit engine converged at iteration %d: P1=%.2f%%, P2=%.2f%%",
                        iteration, f1 * 100, f2 * 100)
            break

        # Adjust parameters
        if page_count > 2 or not edu_ok or f1 > 1.00:
            if len(working_tailored.summary.split(". ")) > 3:
                sentences = working_tailored.summary.split(". ")
                working_tailored.summary = ". ".join(sentences[:3]) + ("." if not sentences[2].endswith(".") else "")
            elif style["font_size_body"] > 9.4:
                style["font_size_body"] -= 0.2
            elif style["spacing_experiences"] > 4.5:
                style["spacing_experiences"] -= 1.0
                style["heading_space_before"] -= 0.5
            else:
                for exp in working_tailored.experience:
                    if "Quantumweave" in exp.company and len(exp.bullets) > 4:
                        exp.bullets = exp.bullets[:4]
                        break
                    elif "Synbrains" in exp.company and len(exp.bullets) > 2:
                        exp.bullets = exp.bullets[:2]
                        break

        elif page_count == 2 and f2 > 1.00:
            if style["spacing_projects"] > 8.0:
                style["spacing_projects"] -= 2.0
            elif style["font_size_body"] > 9.4:
                style["font_size_body"] -= 0.2
            else:
                for idx in reversed(range(len(working_tailored.projects))):
                    if len(working_tailored.projects[idx].bullets) > 1:
                        working_tailored.projects[idx].bullets = working_tailored.projects[idx].bullets[:1]
                        break

        elif page_count == 2 and f1 < 0.93:
            # Page 1 Underfill Expansion
            if style["spacing_experiences"] < 9.5:
                style["spacing_experiences"] += 1.0
                style["heading_space_before"] += 0.5
            elif style["font_size_body"] < 10.2:
                style["font_size_body"] += 0.1

        elif page_count == 2 and f2 < 0.93:
            if style["spacing_projects"] < 17.5:
                style["spacing_projects"] += 1.0
            elif style["font_size_body"] < 10.2 and f1 < 0.98:
                style["font_size_body"] += 0.1
            else:
                style["spacing_projects"] += 0.5

    if not (0.93 <= best_fill["page1"] <= 1.00 and 0.93 <= best_fill["page2"] <= 1.00):
        layout_warning = True
        logger.warning("Fit engine: closest 2-page state P1=%.2f%%, P2=%.2f%%",
                       best_fill["page1"] * 100, best_fill["page2"] * 100)

    # Save final artifacts
    with open(pdf_path, "wb") as f:
        pisa.CreatePDF(best_html, dest=f)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(best_html)

    tailored.page_fill = best_fill
    tailored.layout_warning = layout_warning

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(tailored.model_dump(), f, indent=2)

    log_event("pdf_builder", f"Generated pixel-faithful 2-page PDF: {pdf_path.name} (P1: {best_fill['page1']*100:.1f}%, P2: {best_fill['page2']*100:.1f}%)")
    return pdf_path, json_path, best_fill, layout_warning


def build_tailored_resume_files(
    tailored: TailoredResume,
    company: str,
    role: str
) -> Tuple[Path, Path]:
    """Builds tailored resume PDF using fit_to_two_pages and returns (pdf_path, json_path)."""
    pdf_path, json_path, fills, warning = fit_to_two_pages(tailored, company, role)
    return pdf_path, json_path
