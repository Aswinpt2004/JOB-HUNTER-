import pytest
from src.contacts import (
    extract_emails_from_text,
    is_valid_email_syntax,
    is_no_reply_or_generic,
    score_email_priority
)

def test_email_syntax_validation():
    assert is_valid_email_syntax("careers@company.com") is True
    assert is_valid_email_syntax("sarah.smith@domain.co.uk") is True
    assert is_valid_email_syntax("invalid-email-no-at.com") is False
    assert is_valid_email_syntax("@missingusername.com") is False
    assert is_valid_email_syntax("") is False


def test_no_reply_filtering():
    assert is_no_reply_or_generic("no-reply@company.com") is True
    assert is_no_reply_or_generic("noreply@company.com") is True
    assert is_no_reply_or_generic("donotreply@mail.com") is True
    assert is_no_reply_or_generic("support@company.com") is True
    assert is_no_reply_or_generic("careers@company.com") is False
    assert is_no_reply_or_generic("jobs@company.com") is False


def test_regex_extraction_and_filtering():
    sample_text = """
    Contact us at support@example.com for bugs, or no-reply@example.com for automated alerts.
    Recruiting inquiries can be sent to jobs@example.com or lead-recruiter@example.com.
    """
    extracted = extract_emails_from_text(sample_text)
    assert "jobs@example.com" in extracted
    assert "lead-recruiter@example.com" in extracted
    assert "support@example.com" not in extracted
    assert "no-reply@example.com" not in extracted


def test_email_priority_ranking():
    assert score_email_priority("careers@company.com") > score_email_priority("sarah@company.com")
    assert score_email_priority("jobs@company.com") > score_email_priority("john.doe@company.com")

