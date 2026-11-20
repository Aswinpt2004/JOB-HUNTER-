import pytest
from pathlib import Path
from pypdf import PdfReader
from src.models import TailoredResume
from src.pipeline import load_master_resume
from src.pdf_builder import render_resume_html, build_pdf_with_xhtml2pdf

def test_two_page_resume_generation(tmp_path: Path):
    master = load_master_resume()

    tailored = TailoredResume(
        contact=master.contact,
        targeted_title="AI/ML & Computer Vision Engineer",
        summary=master.summary,
        highlighted_skills=master.skills,
        experience=master.experience,
        projects=master.projects,  # All 4 projects
        education=master.education,
        certifications=master.certifications
    )

    html = render_resume_html(tailored)
    out_pdf = tmp_path / "test_aswin_2page.pdf"
    success = build_pdf_with_xhtml2pdf(html, out_pdf)
    assert success is True
    assert out_pdf.exists()

    reader = PdfReader(str(out_pdf))
    assert len(reader.pages) == 2, f"Expected exactly 2 pages, got {len(reader.pages)}"

    p1_text = reader.pages[0].extract_text()
    p2_text = reader.pages[1].extract_text()

    # Page 1 contains Contact, Summary, Skills, Experience, and Education
    assert "PROFESSIONAL SUMMARY" in p1_text
    assert "TECHNICAL SKILLS" in p1_text
    assert "EXPERIENCE" in p1_text
    assert "Quantumweave Intelligence" in p1_text
    assert "EDUCATION" in p1_text
    assert "M.Sc. Computer Science" in p1_text

    # Page 2 contains Key Projects
    assert "PROJECTS" in p2_text
    assert "AI-Powered E-Commerce" in p2_text
    assert "Manglish WhatsApp Chatbot" in p2_text
    assert "FedGraph-Shield" in p2_text
    assert "KuTo" in p2_text

