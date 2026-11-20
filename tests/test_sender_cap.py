import pytest
from datetime import datetime
from pathlib import Path
from src.db import (
    init_db,
    save_job,
    update_application,
    add_to_blocklist,
    is_blocked,
    get_sent_count_today,
    has_company_or_email_been_contacted_recently
)
from src.models import Job
from src.sender import send_application_email, is_within_sending_hours

@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_sender.db"
    init_db(db_file)
    from src.config import settings, Config
    monkeypatch.setattr(Config, "db_path", property(lambda self: db_file))
    return db_file


def test_blocklist_stops_sending(temp_db):
    blocked_email = "do-not-email@company.com"
    add_to_blocklist(blocked_email, reason="Opted out", db_path=temp_db)
    assert is_blocked(blocked_email, db_path=temp_db) is True

    ok, msg = send_application_email(
        job_id="any-job",
        recipient_email=blocked_email,
        subject="Hello",
        body="Body",
        company_name="TestCorp",
        dry_run=True,
        ignore_hours=True
    )
    assert ok is False
    assert "blocklist" in msg.lower()


def test_daily_cap_enforcement(temp_db, monkeypatch):
    from src.config import settings, Config
    monkeypatch.setattr(Config, "daily_cap", property(lambda self: 2))

    # Simulate 2 sent today
    now = datetime.now()
    for i in range(2):
        j = Job(id=f"cap-job-{i}", title="Dev", company=f"Company{i}", url=f"http://test.com/{i}", description="desc")
        save_job(j, db_path=temp_db)
        update_application(job_id=j.id, status="sent", sent_at=now, db_path=temp_db)

    count = get_sent_count_today(db_path=temp_db)
    assert count == 2

    # 3rd send should be halted by daily cap
    ok, msg = send_application_email(
        job_id="cap-job-3",
        recipient_email="recruiter@newcompany.com",
        subject="Hello",
        body="Body",
        company_name="NewCompany",
        dry_run=True,
        ignore_hours=True
    )
    assert ok is False
    assert "daily sending cap" in msg.lower()


def test_cooldown_per_company(temp_db):
    now = datetime.now()
    j = Job(id="cool-1", title="Dev", company="BetaTech", url="http://beta.com/1", description="desc")
    save_job(j, db_path=temp_db)
    update_application(job_id=j.id, status="sent", sent_at=now, db_path=temp_db)

    # Within 30 days, BetaTech should be on cooldown
    is_cooled = has_company_or_email_been_contacted_recently("BetaTech", cooldown_days=30, db_path=temp_db)
    assert is_cooled is True

    # Unknown company is not on cooldown
    not_cooled = has_company_or_email_been_contacted_recently("FreshStartup", cooldown_days=30, db_path=temp_db)
    assert not_cooled is False


def test_send_company_outreach_email_dry_run_and_cooldown(temp_db):
    from src.models import Company, CompanyOutreach, RecruiterContact
    from src.db import save_company, save_company_outreach, save_company_contact, get_company_outreach_by_id
    from src.sender import send_company_outreach_email

    c = Company(name="TestOutreachCorp", domain="outreachcorp.com")
    cid = save_company(c, db_path=temp_db)

    contact = RecruiterContact(
        job_id="",
        company_id=cid,
        email="hiring@outreachcorp.com",
        name="Hiring Lead",
        role="Recruiter",
        verified=True
    )
    cnt_id = save_company_contact(cid, contact, db_path=temp_db)

    outreach = CompanyOutreach(
        company_id=cid,
        contact_id=cnt_id,
        mode="speculative",
        email_subject="Speculative Inquiry",
        email_body="Hello team, interested in roles.",
        status="approved"
    )
    oid = save_company_outreach(outreach, db_path=temp_db)

    # Test dry-run dispatch
    ok, msg = send_company_outreach_email(outreach_id=oid, dry_run=True, ignore_hours=True)
    assert ok is True
    assert "[DRY-RUN]" in msg
