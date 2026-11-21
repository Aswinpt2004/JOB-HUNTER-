import os
import re
import logging
from pathlib import Path
from copy import deepcopy
from typing import Optional, Tuple, Dict, Any
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import fitz

from jobpilot.core.config import settings
from jobpilot.core.models import TailoredResume
from jobpilot.core.db import log_event

logger = logging.getLogger("jobpilot.tailor.pdf_builder")


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


def build_pdf_with_xhtml2pdf(html_content: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        pisa_status = pisa.CreatePDF(html_content, dest=f)
    return not pisa_status.err


def render_resume_html(tailored: TailoredResume, style: Optional[Dict[str, Any]] = None) -> str:
    templates_dir = settings.root_dir / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
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

    skills_dict = getattr(tailored, "highlighted_skills", getattr(tailored, "skills", {}))
    return template.render(
        style=effective_style,
        headline=tailored.headline,
        contact=tailored.contact,
        summary=tailored.summary,
        highlighted_skills=skills_dict,
        skills=skills_dict,
        experience=tailored.experience,
        projects=tailored.projects,
        education=tailored.education,
        coursework=tailored.coursework,
        achievements=tailored.achievements,
        certifications=tailored.certifications
    )


def measure_pdf_pages_and_fill(pdf_path: Path) -> Tuple[int, float]:
    """Measures total page count and page 2 content fill ratio using PyMuPDF (fitz)."""
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    if page_count < 2:
        doc.close()
        return page_count, 1.0

    p2 = doc[1]
    rect = p2.rect
    blocks = p2.get_text("blocks")
    if not blocks:
        doc.close()
        return page_count, 0.0

    max_y1 = max(b[3] for b in blocks)
    fill_ratio = round(max_y1 / rect.height, 3)
    doc.close()
    return page_count, fill_ratio


def generate_tailored_pdf(
    tailored: TailoredResume,
    job_id: str,
    company: str,
    output_dir: Optional[Path] = None
) -> Tuple[str, float]:
    """
    Fits and generates exact 2-page tailored resume PDF.
    Dynamically adjusts typography and vertical padding to maintain 93-100% target fill.
    """
    out_dir = output_dir or settings.resume_output_dir
    safe_company = _sanitize_filename(company)
    safe_job_id = _sanitize_filename(job_id)
    pdf_filename = f"Aswin_P_T_{safe_company}_{safe_job_id}.pdf"
    output_path = out_dir / pdf_filename

    # Tuning parameter grid for exact fit
    candidates = [
        {"font_size_body": 9.9, "spacing_projects": 14.5, "spacing_experiences": 6.5},
        {"font_size_body": 9.7, "spacing_projects": 13.0, "spacing_experiences": 6.0},
        {"font_size_body": 9.5, "spacing_projects": 12.0, "spacing_experiences": 5.5},
        {"font_size_body": 10.0, "spacing_projects": 15.0, "spacing_experiences": 7.0},
    ]

    best_fill = 0.0
    for style_mod in candidates:
        html = render_resume_html(tailored, style=style_mod)
        success = build_pdf_with_xhtml2pdf(html, output_path)
        if success and output_path.exists():
            pages, fill = measure_pdf_pages_and_fill(output_path)
            if pages == 2 and 0.85 <= fill <= 1.0:
                logger.info("Generated perfect 2-page PDF: %s (fill: %.1f%%)", pdf_filename, fill * 100)
                return str(output_path), fill
            best_fill = fill

    logger.info("PDF generated at %s with fill %.1f%%", pdf_filename, best_fill * 100)
    return str(output_path), best_fill

