"""Demo verification for Step (f): Dispatch Engine, Follow-up Engine, and Guardrails."""
from datetime import datetime, timedelta
from src.config import settings
from src.db import init_db, save_job, update_application, is_blocked, add_to_blocklist
from src.models import Job
from src.sender import send_application_email, is_within_sending_hours
from src.followup import generate_followup_draft, mark_as_replied, opt_out_and_block

def main():
    print("=== Step (f) Verification Demo ===")
    init_db()

    # 1. Create a dummy test job & application
    job = Job(
        id="demo-dispatch-001",
        title="Python Engineer",
        company="NexTech Solutions",
        url="https://nextech.io/careers/python-001",
        description="FastAPI developer position."
    )
    save_job(job)

    # 2. Test Dry-Run Dispatch (Simulates full pipeline safely)
    candidate_name = settings.candidate_name
    print("\n1. Testing Dry-Run Send with Safety Guardrails...")
    ok, msg = send_application_email(
        job_id=job.id,
        recipient_email="recruiting@nextech.io",
        subject=f"Application: Python Engineer - {candidate_name}",
        body=f"Dear Team,\n\nI am applying for the role...\n\nBest regards,\n{candidate_name}",
        company_name=job.company,
        dry_run=True,
        ignore_hours=True
    )
    print(f"   Dry Run result: {ok} -> {msg}")
    assert ok is True

    # 3. Test Blocklist Guardrail
    print("\n2. Testing Opt-Out and Blocklist Enforcement...")
    test_blocked_email = "unsubscribe-me@targetcorp.com"
    add_to_blocklist(test_blocked_email, reason="Recruiter opted out")
    assert is_blocked(test_blocked_email) is True
    print(f"   Email '{test_blocked_email}' verified on blocklist.")

    blocked_ok, blocked_msg = send_application_email(
        job_id="test-blocked-job",
        recipient_email=test_blocked_email,
        subject="Job Application",
        body="Hello...",
        company_name="TargetCorp",
        dry_run=True,
        ignore_hours=True
    )
    print(f"   Blocked recipient send attempt: {blocked_ok} -> {blocked_msg}")
    assert blocked_ok is False
    assert "blocklist" in blocked_msg.lower()

    # 4. Test Follow-up Draft Generation
    print("\n3. Testing Follow-up Draft Generator...")
    draft = generate_followup_draft(
        company="NexTech Solutions",
        role="Python Engineer",
        original_subject=f"Application: Python Engineer - {candidate_name}",
        candidate_name=candidate_name
    )
    print(f"   Follow-up Subject: {draft['subject']}")
    print(f"   Follow-up Body:\n{draft['body']}")

    # 5. Mark as Replied
    mark_as_replied(job.id)
    print("   Application successfully marked as replied.")

    print("\n[SUCCESS] Step (f) dispatch engine, follow-up engine, and guardrails verified.")

if __name__ == "__main__":
    main()

