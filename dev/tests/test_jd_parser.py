import pytest
from src.jd_parser import parse_job_description, _rule_based_fallback
from src.models import JDParsed

SAMPLE_JD = """
Company: Apex Innovations
Role: Senior Python Developer
Location: Bangalore, India

Requirements:
- 3+ years experience with Python, FastAPI, and PostgreSQL.
- Experience with Docker, Redis, and automated CI/CD pipelines.
- Excellent communication skills.

Application Instructions:
Send resume and portfolio to careers@apexinno.com with subject 'Application - Python Lead'.
"""

def test_jd_parser_structure():
    parsed = parse_job_description(SAMPLE_JD)
    assert parsed is not None
    assert isinstance(parsed, JDParsed)
    assert parsed.role != ""
    assert len(parsed.must_have_skills) > 0
    assert any("python" in s.lower() for s in parsed.must_have_skills)


def test_jd_parser_empty_fallback():
    empty_res = parse_job_description("")
    assert empty_res is None


def test_rule_based_fallback():
    parsed = _rule_based_fallback("Python backend developer position with PostgreSQL and Docker.")
    assert "Python" in parsed.must_have_skills
    assert "PostgreSQL" in parsed.must_have_skills
    assert parsed.role != ""

