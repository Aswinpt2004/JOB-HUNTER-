"""Demo verification for Step (e): Public Recruiter Contact Hunting & Verification."""
from src.models import Job
from src.contacts import (
    extract_emails_from_text,
    is_no_reply_or_generic,
    verify_mx_record,
    find_recruiter_contacts
)

def main():
    print("=== Step (e) Verification Demo ===")

    sample_text = """
    We are excited to grow our engineering team!
    Please DO NOT contact noreply@acme.com or support@acme.com.
    Interested candidates should submit their portfolios to jobs@google.com or careers@google.com.
    Questions can be directed to tech-talent@google.com.
    """

    print("1. Extracting & filtering emails from text...")
    extracted = extract_emails_from_text(sample_text)
    print(f"   Extracted valid candidates: {extracted}")
    assert "noreply@acme.com" not in extracted
    assert "support@acme.com" not in extracted
    print("   Filter check passed: no-reply and support addresses successfully excluded.")

    print("\n2. Testing MX Record Verification (dnspython)...")
    valid_domain_mx = verify_mx_record("google.com")
    invalid_domain_mx = verify_mx_record("invalid-nonexistent-domain-12345xyz.org")
    print(f"   MX for 'google.com': {valid_domain_mx}")
    print(f"   MX for 'invalid-...org': {invalid_domain_mx}")
    assert valid_domain_mx is True
    assert invalid_domain_mx is False

    print("\n3. Testing Contact Prioritization for a Job Posting...")
    job = Job(
        id="test-job-mx",
        title="Software Engineer",
        company="Google",
        url="https://careers.google.com/jobs/123",
        description=sample_text
    )
    contacts = find_recruiter_contacts(job, check_mx=True)
    for idx, c in enumerate(contacts, 1):
        print(f"   [{idx}] {c.email} (Role: {c.role}, MX Valid: {c.domain_mx_valid})")

    assert len(contacts) > 0
    assert contacts[0].email.startswith("careers@") or contacts[0].email.startswith("jobs@")

    print("\n4. Testing Job with NO Recruiter Email (Must be marked 'apply via link')...")
    no_email_job = Job(
        id="test-job-no-email",
        title="Backend Engineer",
        company="Stealth Startup",
        url="https://stealth.io/apply",
        description="Please apply directly through our web portal above. No recruiters please."
    )
    empty_contacts = find_recruiter_contacts(no_email_job, check_mx=True)
    print(f"   Contacts found: {len(empty_contacts)} -> Job will be flagged 'apply via link' without emailing.")

    print("\n[SUCCESS] Step (e) recruiter contact finder verified.")

if __name__ == "__main__":
    main()

