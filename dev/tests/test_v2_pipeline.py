import pytest
from pathlib import Path
from jobpilot.pipeline.location import normalize_location
from jobpilot.pipeline.prescreen import prescreen_job
from jobpilot.pipeline.route import resolve_apply_target, classify_url_domain
from jobpilot.tailor.cover_note import generate_cover_note, check_cover_note_tone
from jobpilot.apply.packet import build_apply_packet
from jobpilot.sources.base import get_registered_sources


def test_location_normalization_v2():
    # Target cities
    assert normalize_location("Bangalore, Karnataka")["matched"] is True
    assert normalize_location("Bengaluru, India")["matched"] is True
    assert normalize_location("Trivandrum, Kerala")["matched"] is True
    assert normalize_location("Thiruvananthapuram")["matched"] is True
    assert normalize_location("Kochi, Kerala")["matched"] is True
    assert normalize_location("Cochin / Infopark")["matched"] is True
    assert normalize_location("Kozhikode, India")["matched"] is True
    assert normalize_location("Remote - India")["matched"] is True

    # Excluded foreign & non-target
    assert normalize_location("San Francisco, CA")["matched"] is False
    assert normalize_location("London, UK")["matched"] is False
    assert normalize_location("Remote - US")["matched"] is False


def test_prescreen_v2():
    # Senior rejection
    assert prescreen_job("Senior AI Engineer", "")["eligible"] is False
    assert prescreen_job("Lead Machine Learning Architect", "")["eligible"] is False
    assert prescreen_job("Director of Engineering", "")["eligible"] is False
    assert prescreen_job("Staff ML Engineer", "")["eligible"] is False
    assert prescreen_job("AI Engineer", "Requires 5+ years of experience in PyTorch")["eligible"] is False

    # Fresher acceptance
    assert prescreen_job("Junior ML Engineer", "0-1 years experience required")["eligible"] is True
    assert prescreen_job("Computer Vision Intern", "Graduate or final year student")["eligible"] is True
    assert prescreen_job("Associate Python Developer", "Freshers can apply")["eligible"] is True


def test_route_classification_v2():
    # ATS URLs
    assert classify_url_domain("https://boards.greenhouse.io/inmobi/jobs/123") == "ats_greenhouse"
    assert classify_url_domain("https://jobs.lever.co/meesho/abc-def") == "ats_lever"
    assert classify_url_domain("https://jobs.ashbyhq.com/postman/xyz") == "ats_ashby"
    assert classify_url_domain("https://apply.workable.com/browserstack/j/123") == "ats_workable"
    assert classify_url_domain("https://jobs.smartrecruiters.com/bosch/789") == "ats_smartrecruiters"

    # Aggregator / External
    assert classify_url_domain("https://www.linkedin.com/jobs/view/12345") == "linkedin"
    assert classify_url_domain("https://www.naukri.com/job-listings-123") == "naukri"
    assert classify_url_domain("https://in.indeed.com/viewjob?jk=123") == "indeed"

    # Route resolution
    r_ats = resolve_apply_target("https://jobs.lever.co/meesho/123", description="Apply via Lever")
    assert r_ats["route"] == "ats_assist"
    assert r_ats["apply_kind"] == "ats_lever"

    r_email = resolve_apply_target("https://company.com/job", description="Send your CV to careers@company.com")
    assert r_email["route"] == "email"
    assert r_email["recruiter_email"] == "careers@company.com"

    r_packet = resolve_apply_target("https://www.linkedin.com/jobs/view/123", description="Easy Apply on LinkedIn")
    assert r_packet["route"] == "packet"
    assert r_packet["easy_apply"] is True


def test_cover_note_and_tone():
    note = generate_cover_note(
        job_title="Computer Vision Engineer",
        company="Tonbo Imaging",
        role_lens="Computer Vision / Drone / Aerial Perception",
        matched_skills=["YOLOv8", "RT-DETR", "ByteTrack"],
        location="Bangalore"
    )
    assert "Aswin P T" in note
    assert "Tonbo Imaging" in note
    assert "Computer Vision Engineer" in note
    assert "YOLOv8" in note or "detection" in note

    score = check_cover_note_tone(note)
    assert score >= 9.0


def test_sources_registered():
    sources = get_registered_sources()
    expected = ["adzuna", "jooble", "careerjet", "jsearch", "remotive", "arbeitnow", "ats", "kerala_parks", "company_careers", "manual"]
    for exp in expected:
        assert exp in sources, f"Source {exp} must be registered"


def test_apply_packet_creation(tmp_path):
    packet = build_apply_packet(
        app_id=999,
        job_id="test_job_123",
        job_title="Python Developer",
        company="CareStack",
        apply_url="https://carestack.com/careers",
        resume_pdf_path="output/resumes/dummy.pdf",
        cover_note="Test note",
        matched_skills=["FastAPI", "Python"]
    )
    p_path = Path(packet["packet_path"])
    assert p_path.exists()
    content = p_path.read_text(encoding="utf-8")
    assert "CareStack" in content
    assert "Python Developer" in content
    assert "Notice Period" in content

