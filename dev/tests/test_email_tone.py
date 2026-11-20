import pytest
from src.email_writer import score_email_tone, build_polite_fallback
from src.models import Job, JDParsed, MasterResume

SAMPLE_JOB = Job(
    id="test_job_1",
    company="Techversant Infotech",
    title="Junior Python Engineer",
    location="Thiruvananthapuram, Kerala",
    url="https://technopark.in/job-details/34297",
    description="Looking for Python developer with FastAPI and PostgreSQL.",
    source="technopark_tvm",
    recruiter_email="careers@techversantinfotech.com"
)

SAMPLE_JD = JDParsed(
    role="Junior Python Engineer",
    seniority="junior",
    must_have_skills=["Python", "FastAPI", "SQL"],
    nice_to_have_skills=["Docker", "Git"],
    responsibilities=["Build backend microservices", "Optimize database queries"],
    domain="AI / Web"
)


def test_polite_fallback_tone():
    from src.pipeline import load_master_resume
    master_resume = load_master_resume()
    subject, body = build_polite_fallback(SAMPLE_JOB, SAMPLE_JD, master_resume)
    metrics = score_email_tone(body)

    assert metrics["score"] >= 8.5, f"Tone score {metrics['score']} too low!"
    assert metrics["has_optout"] is True
    assert metrics["has_humble_cta"] is True
    assert len(metrics["banned_phrases"]) == 0
    assert 80 <= metrics["word_count"] <= 160


def test_pushy_sales_email_gets_low_score():
    pushy_body = """
    Hi Techversant Team,

    Over the past few years, I have established a proven track record delivering enterprise AI architectures.
    I am the ideal candidate for your opening and want to discuss synergies.

    Would you be open to a brief 10-minute conversation this week to discuss how my technical skill set supports your roadmap?

    Best regards,
    Aswin
    """
    metrics = score_email_tone(pushy_body)
    assert metrics["score"] < 5.0, f"Expected low score for pushy email but got {metrics['score']}"
    assert len(metrics["banned_phrases"]) >= 3
    assert metrics["has_optout"] is False
