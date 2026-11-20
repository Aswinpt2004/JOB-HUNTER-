import pytest
from src.models import (
    MasterResume,
    TailoredResume,
    ResumeContactInfo,
    ResumeExperience,
    ResumeProject,
    ResumeEducation
)
from src.resume_tailor import verify_no_fabrication, sanitize_tailored_resume

@pytest.fixture
def sample_master():
    return MasterResume(
        contact=ResumeContactInfo(
            name="Candidate Test",
            email="candidate@example.com",
            phone="+91 9999999999",
            location="Remote"
        ),
        summary="Python Engineer with experience in FastAPI and PostgreSQL.",
        skills={
            "Languages": ["Python", "SQL"],
            "Frameworks": ["FastAPI", "Django"],
            "Databases": ["PostgreSQL", "SQLite"]
        },
        experience=[
            ResumeExperience(
                company="RealCorp",
                role="Backend Developer",
                start_date="2022",
                end_date="Present",
                bullets=["Built Python REST APIs with FastAPI."]
            )
        ],
        projects=[
            ResumeProject(
                name="ProjectAlpha",
                technologies=["Python", "FastAPI"],
                description="Backend API",
                bullets=["Built service."]
            )
        ],
        education=[
            ResumeEducation(
                institution="National Tech University",
                degree="B.Tech",
                field_of_study="Computer Science",
                graduation_year="2022"
            )
        ],
        certifications=["AWS Cloud Practitioner"]
    )


def test_verifier_passes_valid_tailored(sample_master):
    valid_tailored = TailoredResume(
        contact=sample_master.contact,
        targeted_title="Python Developer",
        summary="Python Engineer with experience in FastAPI.",
        highlighted_skills={
            "Core": ["Python", "SQL"],
            "Frameworks": ["FastAPI"]
        },
        experience=sample_master.experience,
        projects=sample_master.projects,
        education=sample_master.education,
        certifications=sample_master.certifications
    )
    is_valid, violations = verify_no_fabrication(valid_tailored, sample_master)
    assert is_valid is True
    assert len(violations) == 0


def test_verifier_catches_fabricated_skill(sample_master):
    fake_tailored = TailoredResume(
        contact=sample_master.contact,
        targeted_title="Python Developer",
        summary="Summary",
        highlighted_skills={
            "Core": ["Python", "QuantumComputingAdvanced99"]  # Fabricated
        },
        experience=sample_master.experience,
        projects=sample_master.projects,
        education=sample_master.education,
        certifications=sample_master.certifications
    )
    is_valid, violations = verify_no_fabrication(fake_tailored, sample_master)
    assert is_valid is False
    assert any("QuantumComputingAdvanced99" in v for v in violations)


def test_verifier_catches_fabricated_employer(sample_master):
    fake_tailored = TailoredResume(
        contact=sample_master.contact,
        targeted_title="Python Developer",
        summary="Summary",
        highlighted_skills=sample_master.skills,
        experience=[
            ResumeExperience(
                company="Google Inc Silicon Valley",  # Fabricated
                role="Principal Architect",
                start_date="2020",
                end_date="Present",
                bullets=["Led architecture."]
            )
        ],
        projects=sample_master.projects,
        education=sample_master.education,
        certifications=sample_master.certifications
    )
    is_valid, violations = verify_no_fabrication(fake_tailored, sample_master)
    assert is_valid is False
    assert any("Google Inc Silicon Valley" in v for v in violations)


def test_sanitizer_removes_fabrications(sample_master):
    dirty_tailored = TailoredResume(
        contact=sample_master.contact,
        targeted_title="Python Developer",
        summary="Summary",
        highlighted_skills={
            "Core": ["Python", "FabricatedSkillXYZ"]
        },
        experience=[
            ResumeExperience(
                company="FakeCompany",
                role="Role",
                start_date="2020",
                end_date="2021",
                bullets=["..."]
            )
        ],
        projects=sample_master.projects,
        education=sample_master.education,
        certifications=sample_master.certifications
    )
    cleaned = sanitize_tailored_resume(dirty_tailored, sample_master)
    is_valid, violations = verify_no_fabrication(cleaned, sample_master)
    assert is_valid is True
    assert "FabricatedSkillXYZ" not in cleaned.highlighted_skills.get("Core", [])

