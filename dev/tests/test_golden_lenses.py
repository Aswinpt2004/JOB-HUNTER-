import pytest
import pypdf
from pathlib import Path
from src.pipeline import load_master_resume
from src.models import JDParsed
from src.matcher import compute_match_score, classify_role
from src.resume_tailor import tailor_resume
from src.verifier import verify_no_fabrication
from src.pdf_builder import build_tailored_resume_files


@pytest.fixture(scope="module")
def master():
    return load_master_resume()


def test_cv_drone_lens_golden(master):
    jd = JDParsed(
        role="Computer Vision Engineer",
        must_have_skills=["PyTorch", "OpenCV", "YOLO", "ByteTrack", "Object Detection"],
        nice_to_have_skills=["RT-DETR", "Docker"],
        responsibilities=["Develop UAV tracking pipelines and drone video analytics"]
    )
    match_res = compute_match_score(jd, master)
    assert match_res.role_tier == "Tier A"
    assert match_res.role_lens == "Computer Vision / Drone / Surveillance"
    assert match_res.match_score >= 65.0

    tailored = tailor_resume(master, jd)
    is_valid, violations = verify_no_fabrication(tailored, master)
    assert is_valid, f"Verification failed: {violations}"

    # Assert project order starts with SHADER (p5)
    assert tailored.projects[0].name.startswith("Adaptive Confidence Modeling for SHADER")
    # Assert summary emphasis
    assert "drone and surveillance video" in tailored.summary

    # Assert exactly 2 pages
    pdf_path, _ = build_tailored_resume_files(tailored, "AeroTech", "CV_Engineer")
    reader = pypdf.PdfReader(str(pdf_path))
    assert len(reader.pages) == 2, f"Expected 2 pages, got {len(reader.pages)}"


def test_llm_rag_lens_golden(master):
    jd = JDParsed(
        role="GenAI / LLM Engineer",
        must_have_skills=["LLM", "RAG", "Python", "FastAPI", "Prompt Engineering"],
        nice_to_have_skills=["Ollama", "Pydantic"],
        responsibilities=["Build agentic workflows and local retrieval augmented generation"]
    )
    match_res = compute_match_score(jd, master)
    assert match_res.role_tier == "Tier A"
    assert match_res.role_lens == "LLM / GenAI / RAG / Agents"
    assert match_res.match_score >= 65.0

    tailored = tailor_resume(master, jd)
    is_valid, violations = verify_no_fabrication(tailored, master)
    assert is_valid, f"Verification failed: {violations}"

    # Assert project order starts with Storefront (p1)
    assert tailored.projects[0].name.startswith("AI-Powered E-Commerce Storefront")
    assert "retrieval-augmented generation" in tailored.summary

    # Assert exactly 2 pages
    pdf_path, _ = build_tailored_resume_files(tailored, "GenAI_Labs", "LLM_Engineer")
    reader = pypdf.PdfReader(str(pdf_path))
    assert len(reader.pages) == 2, f"Expected 2 pages, got {len(reader.pages)}"


def test_document_ai_lens_golden(master):
    jd = JDParsed(
        role="Document AI Engineer",
        must_have_skills=["Document Extraction", "Python", "Pydantic", "FastAPI", "OCR"],
        nice_to_have_skills=["Docker", "SQL"],
        responsibilities=["Build PDF medical report extraction pipeline and schemas"]
    )
    match_res = compute_match_score(jd, master)
    assert match_res.role_tier == "Tier B"
    assert match_res.role_lens == "Document AI / Healthcare AI"
    assert match_res.match_score >= 65.0

    tailored = tailor_resume(master, jd)
    is_valid, violations = verify_no_fabrication(tailored, master)
    assert is_valid, f"Verification failed: {violations}"

    # Assert summary emphasis
    assert "document extraction" in tailored.summary or "Pydantic" in tailored.summary

    # Assert exactly 2 pages
    pdf_path, _ = build_tailored_resume_files(tailored, "HealthDoc", "DocAI_Engineer")
    reader = pypdf.PdfReader(str(pdf_path))
    assert len(reader.pages) == 2, f"Expected 2 pages, got {len(reader.pages)}"


def test_backend_ai_lens_golden(master):
    jd = JDParsed(
        role="Python Backend Developer (AI Team)",
        must_have_skills=["Python", "FastAPI", "Django", "PostgreSQL", "Docker", "REST APIs"],
        nice_to_have_skills=["MySQL", "Git"],
        responsibilities=["Engineer microservices and backend pipelines for AI services"]
    )
    match_res = compute_match_score(jd, master)
    assert match_res.role_tier in ["Tier B", "Tier C"]
    assert match_res.role_lens == "Backend / Full-stack with AI"
    assert match_res.match_score >= 60.0

    tailored = tailor_resume(master, jd)
    is_valid, violations = verify_no_fabrication(tailored, master)
    assert is_valid, f"Verification failed: {violations}"

    # Assert project order starts with PETZZO (p7)
    assert tailored.projects[0].name.startswith("PETZZO")
    assert "FastAPI, Django" in tailored.summary

    # Assert exactly 2 pages
    pdf_path, _ = build_tailored_resume_files(tailored, "CloudServe", "Backend_Dev")
    reader = pypdf.PdfReader(str(pdf_path))
    assert len(reader.pages) == 2, f"Expected 2 pages, got {len(reader.pages)}"


def test_reject_roles_score_below_65(master):
    # Java Developer
    jd_java = JDParsed(
        role="Senior Java Developer",
        must_have_skills=["Java", "Spring Boot", "Hibernate"],
        responsibilities=["Build enterprise banking backend in Java"]
    )
    res_java = compute_match_score(jd_java, master)
    assert res_java.match_score < 65.0, f"Expected Java role to score below 65, got {res_java.match_score}"
    assert res_java.meets_threshold is False

    # Frontend React Developer
    jd_fe = JDParsed(
        role="Frontend React Developer",
        must_have_skills=["React", "CSS", "HTML", "Redux", "Figma"],
        responsibilities=["Design UI components and user experiences"]
    )
    res_fe = compute_match_score(jd_fe, master)
    assert res_fe.match_score < 65.0, f"Expected Frontend role to score below 65, got {res_fe.match_score}"
    assert res_fe.meets_threshold is False

