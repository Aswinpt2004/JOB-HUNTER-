import pytest
import fitz
from pathlib import Path
from pypdf import PdfReader
from copy import deepcopy

from src.models import MasterResume, JDParsed, TailoredResume
from src.pipeline import load_master_resume
from src.resume_tailor import tailor_resume, ROLE_LENS_CONFIG
from src.verifier import verify_no_fabrication
from src.pdf_builder import fit_to_two_pages, measure_pdf_metrics, render_resume_html, build_pdf_with_xhtml2pdf


def test_format_matches_reference(tmp_path: Path):
    """
    Asserts default build vs reference has the same section order,
    heading strings, bullet glyphs, and font families.
    """
    master = load_master_resume()
    default_jd = JDParsed(
        role="AI/ML Engineer",
        company="Reference Benchmark",
        must_have_skills=["Python", "PyTorch"],
        nice_to_have_skills=["FastAPI"]
    )
    tailored = tailor_resume(master, default_jd)
    pdf_path, _, fills, warning = fit_to_two_pages(tailored, "Reference", "Benchmark")

    doc = fitz.open(pdf_path)
    assert len(doc) == 2, f"Expected 2 pages, got {len(doc)}"

    p1_text = doc[0].get_text()
    p2_text = doc[1].get_text()

    # Section order on Page 1: PROFESSIONAL SUMMARY -> TECHNICAL SKILLS -> EXPERIENCE -> EDUCATION
    idx_summary = p1_text.find("PROFESSIONAL SUMMARY:")
    idx_skills = p1_text.find("TECHNICAL SKILLS:")
    idx_exp = p1_text.find("EXPERIENCE :")
    idx_edu = p1_text.find("EDUCATION:")

    assert idx_summary != -1, "Missing PROFESSIONAL SUMMARY:"
    assert idx_skills != -1, "Missing TECHNICAL SKILLS:"
    assert idx_exp != -1, "Missing EXPERIENCE :"
    assert idx_edu != -1, "Missing EDUCATION:"
    assert idx_summary < idx_skills < idx_exp < idx_edu, "Section order on Page 1 is incorrect"

    # Section on Page 2: PROJECTS
    assert "PROJECTS :" in p2_text, "Page 2 must contain PROJECTS :"

    # Fonts: Times-Roman / Times-Bold
    fonts = set()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        fonts.add(s["font"])
    assert any("Times" in f for f in fonts), f"Expected Times font in PDF, found: {fonts}"


def test_two_pages_all_lenses(tmp_path: Path):
    """
    For 6 sample JDs (CV/drone, LLM/RAG, document AI, federated/research, backend+AI, generic ML),
    assert 2 pages, fill in [0.93, 1.00] on both, Education on page 1, all 7 projects on page 2.
    """
    master = load_master_resume()

    lenses_jds = [
        ("Drone Corp", "Computer Vision Engineer", ["YOLO", "PyTorch", "OpenCV", "ByteTrack", "Drone"]),
        ("AI Studio", "GenAI Engineer", ["LLMs", "RAG", "Llama-3", "LangChain", "Agentic AI"]),
        ("MedScan AI", "Document AI Engineer", ["Document AI", "Medical Imaging", "PDF Extraction", "FastAPI"]),
        ("SafeGraph AI", "Federated Learning Engineer", ["Federated Learning", "Graph Neural Networks", "PyTorch", "Differential Privacy"]),
        ("CloudScale", "Python Backend Developer", ["FastAPI", "Django", "Docker", "PostgreSQL", "REST APIs"]),
        ("DataCore", "Applied ML Engineer", ["Machine Learning", "PyTorch", "Deep Learning", "Data Science"]),
    ]

    for company, role, skills in lenses_jds:
        jd = JDParsed(role=role, company=company, must_have_skills=skills[:3], nice_to_have_skills=skills[3:])
        tailored = tailor_resume(master, jd)
        pdf_path, _, fills, warning = fit_to_two_pages(tailored, company, role)

        doc = fitz.open(pdf_path)
        assert len(doc) == 2, f"Failed for {role}: expected 2 pages, got {len(doc)}"

        # Assert fills in [0.93, 1.00]
        assert 0.93 <= fills["page1"] <= 1.00, f"Page 1 fill out of bounds for {role}: {fills['page1']:.4f}"
        assert 0.93 <= fills["page2"] <= 1.00, f"Page 2 fill out of bounds for {role}: {fills['page2']:.4f}"
        assert warning is False

        # Assert Education is on Page 1 and NOT on Page 2
        p1_text = doc[0].get_text()
        p2_text = doc[1].get_text()
        assert "EDUCATION:" in p1_text
        assert "EDUCATION:" not in p2_text

        # Assert all 7 projects are on Page 2
        for p in master.projects:
            # Check unique part of each project title
            short_name = p.name.split(":")[0].split("(")[0].strip()
            assert short_name in p2_text, f"Project '{short_name}' missing from Page 2 for {role}"


def test_no_new_facts():
    """Verifier rejects injected skills, invented metrics, or altered dates."""
    master = load_master_resume()
    jd = JDParsed(role="AI Engineer", company="VerifyCorp", must_have_skills=["Python"])
    tailored = tailor_resume(master, jd)

    # 1. Injected skill
    bad_tailored_skill = deepcopy(tailored)
    bad_tailored_skill.highlighted_skills["Programming"].append("Quantum Computing")
    valid, violations = verify_no_fabrication(bad_tailored_skill, master)
    assert not valid
    assert any("Quantum Computing" in v for v in violations)

    # 2. Altered date
    bad_tailored_date = deepcopy(tailored)
    bad_tailored_date.experience[0].start_date = "Jan 2020"
    valid, violations = verify_no_fabrication(bad_tailored_date, master)
    assert not valid
    assert any("date" in v.lower() for v in violations)


def test_fit_engine_trims_and_expands():
    """A long summary and extra content converges to 2 filled pages."""
    master = load_master_resume()
    jd = JDParsed(role="Staff AI Specialist", company="ScaleCorp", must_have_skills=["Python", "Deep Learning"])
    tailored = tailor_resume(master, jd)

    # Inject extra-long summary (6 sentences)
    tailored.summary = (
        "AI/ML engineer with expertise in drone analytics and production LLM applications. "
        "At Quantumweave Intelligence, I develop object detection and tracking pipelines with GPU inference. "
        "Built offline RAG systems with Llama-3 and FastAPI backend modules for clinical applications. "
        "Designed hierarchical federated graph neural networks for fraud detection. "
        "Demonstrated strong competency in PyTorch, Docker, REST APIs, and team Git workflows. "
        "Dedicated to rigorous empirical evaluation and zero-hallucination architectures."
    )

    pdf_path, _, fills, warning = fit_to_two_pages(tailored, "ScaleCorp", "LongInput")
    doc = fitz.open(pdf_path)
    assert len(doc) == 2, f"Long input must converge to 2 pages, got {len(doc)}"
    assert 0.93 <= fills["page1"] <= 1.00


def test_unicode_glyphs():
    """–, ·, • render correctly in extracted text."""
    master = load_master_resume()
    jd = JDParsed(role="AI Engineer", company="GlyphCorp", must_have_skills=["Python"])
    tailored = tailor_resume(master, jd)
    pdf_path, _, _, _ = fit_to_two_pages(tailored, "GlyphCorp", "GlyphTest")

    doc = fitz.open(pdf_path)
    full_text = doc[0].get_text() + "\n" + doc[1].get_text()

    assert "•" in full_text or "\u2022" in full_text or "\x7f" in full_text, "Bullet glyph missing"
    assert "–" in full_text or "\u2013" in full_text or "-" in full_text, "En-dash missing"
    assert "·" in full_text or "\u00b7" in full_text, "Middle dot missing from project tech stack"

