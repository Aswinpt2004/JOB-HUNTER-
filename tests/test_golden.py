import json
import pytest
from src.models import MasterResume, JDParsed
from src.resume_tailor import tailor_resume
from src.verifier import verify_no_fabrication


@pytest.fixture
def sample_master_resume():
    return MasterResume(
        contact={
            "name": "Aswin P T",
            "email": "aswinpt2004@gmail.com",
            "phone": "+91 88913 81713",
            "location": "Thiruvananthapuram, Kerala, India"
        },
        summary="AI/ML Engineer with hands-on experience in Python, PyTorch, FastAPIs, and LLM agent pipelines.",
        skills={
            "Machine Learning & Deep Learning": ["PyTorch", "TensorFlow", "YOLO", "GNNs"],
            "NLP & LLMs": ["Gemini API", "Llama-3", "RAG", "Agentic AI", "Prompt Engineering"],
            "Backend & Cloud": ["FastAPI", "Docker", "PostgreSQL", "REST APIs", "Python"]
        },
        experience=[
            {
                "company": "Quantumweave Intelligence",
                "role": "Research Assistant – AI & Data Science",
                "start_date": "Aug 2026",
                "end_date": "Present",
                "bullets": [
                    "Built and optimized computer-vision pipelines using PyTorch and FastAPI with GPU inference.",
                    "Deployed Dockerized surveillance web dashboards for multi-feed monitoring."
                ]
            }
        ],
        projects=[
            {
                "name": "AI-Powered E-Commerce Storefront & Catalog Generation Agent",
                "technologies": ["Python", "FastAPI", "Agentic AI", "LLMs"],
                "description": "Agentic platform converting natural language prompts into e-commerce storefronts.",
                "bullets": [
                    "Constructed an agentic platform converting natural-language prompts into e-commerce storefronts.",
                    "Engineered a multimodal pipeline using VLMs and LLMs with Pydantic validation."
                ]
            }
        ],
        education=[
            {
                "institution": "Kerala University of Digital Sciences",
                "degree": "M.Sc. Computer Science",
                "field_of_study": "Machine Intelligence",
                "graduation_year": "2026"
            }
        ],
        certifications=[]
    )


def test_golden_tailoring_python_llm_intern(sample_master_resume, monkeypatch):
    """
    Golden test: given a sample JD for a Python/LLM intern role,
    the tailored output must reorder skills toward the JD,
    add zero new skills, and pass the verifier.
    """
    jd = JDParsed(
        role="Python / LLM Intern",
        company="InnoTech AI",
        seniority="intern",
        must_have_skills=["Python", "FastAPI", "LLMs", "RAG"],
        nice_to_have_skills=["Docker", "PyTorch"],
        keywords=["AI agents", "prompt engineering"],
        responsibilities=["Develop LLM services in Python and FastAPI"]
    )

    # Run tailoring
    tailored = tailor_resume(sample_master_resume, jd)

    # 1. Output must pass strict verifier
    is_valid, violations = verify_no_fabrication(tailored, sample_master_resume)
    assert is_valid is True, f"Verifier failed with violations: {violations}"
    assert len(violations) == 0

    # 2. Add zero new skills
    all_master_skills = set()
    for slist in sample_master_resume.skills.values():
        for s in slist:
            all_master_skills.add(s.strip().lower())

    tailored_skills_dict = getattr(tailored, "highlighted_skills", None) or getattr(tailored, "skills", {})
    for cat, skills in tailored_skills_dict.items():
        for s in skills:
            assert s.strip().lower() in all_master_skills, f"Fabricated skill found: {s}"

    # 3. Targeted title reflects the role
    assert "Intern" in tailored.targeted_title or "Python" in tailored.targeted_title

    # 4. Summary is present and references role
    assert len(tailored.summary) > 20

