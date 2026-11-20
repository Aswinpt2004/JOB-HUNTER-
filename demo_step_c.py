"""Demo verification for Step (c): Application Email Writer."""
import json
from src.config import settings
from src.models import MasterResume, Job, JDParsed, TailoredResume
from src.email_writer import generate_application_email, MANDATORY_OPTOUT

def main():
    print("=== Step (c) Verification Demo ===")

    with open(settings.master_resume_path, "r", encoding="utf-8") as f:
        master = MasterResume.model_validate(json.load(f))

    from src.resume_tailor import tailor_resume
    jd_parsed = JDParsed(
        role=settings.target_roles[0] if settings.target_roles else "Software Engineer",
        seniority=settings.user_profile.get("experience_level", "Entry-Level"),
        must_have_skills=["Python", "FastAPI"],
        keywords=["REST API", "Microservices"],
        responsibilities=["Build high-performance REST APIs"],
        application_instructions="Send resume to jobs@example.com"
    )
    tailored = tailor_resume(master, jd_parsed)

    sample_job = Job(
        id="demo-verify-001",
        title=jd_parsed.role,
        company="TechCorp",
        location="Remote",
        url="https://example.com/careers/demo-job",
        description="Software developer needed. Send resume to jobs@example.com",
        source="career_page"
    )

    print("1. Generating Cold Email with Recruiter Contact...")
    subject, body = generate_application_email(
        job=sample_job,
        jd_parsed=jd_parsed,
        tailored_resume=tailored,
        master_resume=master,
        recruiter_name="Sarah"
    )

    print(f"\n--- Subject Line ---\n{subject}")
    print(f"\n--- Email Body ---\n{body}")

    words = [w for w in body.split() if w.strip()]
    word_count = len(words)
    print(f"\nWord count: {word_count} words")
    print(f"Has Opt-Out Line: {MANDATORY_OPTOUT in body}")
    assert MANDATORY_OPTOUT in body, "Opt-out line missing!"
    print("\n[SUCCESS] Step (c) application email writer verified.")

if __name__ == "__main__":
    main()

