import pytest
import sqlite3
from pathlib import Path
from src.models import Job, RecruiterContact
from src.db import (
    init_db,
    save_job,
    get_job,
    get_job_by_url,
    list_jobs,
    update_application,
    list_applications_by_status,
    save_contact,
    get_contacts_for_job,
    add_to_blocklist,
    is_blocked,
    log_event,
    get_cached_llm_response,
    set_cached_llm_response,
    record_llm_usage,
    get_today_llm_usage,
)


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_jobpilot.db"
    init_db(db_path=db_file)
    return db_file


def test_db_initialization_tables(temp_db):
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()

    expected_tables = {"jobs", "contacts", "applications", "blocklist", "logs", "llm_cache", "llm_usage"}
    assert expected_tables.issubset(tables)


def test_job_save_and_deduplication(temp_db):
    job1 = Job(
        id="job-001",
        title="Junior AI Engineer",
        company="TechCorp",
        location="Bengaluru, Karnataka",
        url="https://techcorp.com/jobs/001",
        description="Python, PyTorch, FastAPIs",
        source="greenhouse"
    )

    # First save succeeds
    assert save_job(job1, db_path=temp_db) is True
    fetched = get_job("job-001", db_path=temp_db)
    assert fetched is not None
    assert fetched["title"] == "Junior AI Engineer"

    # Duplicate URL save returns False
    job2 = Job(
        id="job-002",
        title="Duplicate Job",
        company="TechCorp",
        location="Bengaluru, Karnataka",
        url="https://techcorp.com/jobs/001",
        description="Duplicate description",
        source="greenhouse"
    )
    assert save_job(job2, db_path=temp_db) is False


def test_application_lifecycle_and_rationale(temp_db):
    job = Job(
        id="app-test-job",
        title="Software Engineer, Intern",
        company="Stripe",
        location="Bengaluru",
        url="https://stripe.com/jobs/app-test",
        description="Entry level role"
    )
    save_job(job, db_path=temp_db)

    # Initially in 'new' status
    apps = list_applications_by_status("new", db_path=temp_db)
    assert len(apps) == 1
    assert apps[0]["job_id"] == "app-test-job"

    # Update to matched with score and rationale
    update_application(
        job_id="app-test-job",
        status="matched",
        match_score=85.5,
        rationale="Strong match on Python and FastAPI.",
        db_path=temp_db
    )
    matched_apps = list_applications_by_status("matched", db_path=temp_db)
    assert len(matched_apps) == 1
    assert matched_apps[0]["match_score"] == 85.5
    assert matched_apps[0]["rationale"] == "Strong match on Python and FastAPI."

    # Update to needs_manual_contact
    update_application(job_id="app-test-job", status="needs_manual_contact", db_path=temp_db)
    manual_apps = list_applications_by_status("needs_manual_contact", db_path=temp_db)
    assert len(manual_apps) == 1


def test_blocklist_operations(temp_db):
    assert is_blocked("recruiter@example.com", db_path=temp_db) is False
    add_to_blocklist("recruiter@example.com", reason="Candidate opt-out", db_path=temp_db)
    assert is_blocked("recruiter@example.com", db_path=temp_db) is True
    assert is_blocked("RECRUITER@EXAMPLE.COM", db_path=temp_db) is True


def test_llm_cache_and_usage(temp_db):
    # Cache operations
    assert get_cached_llm_response("hash_abc", db_path=temp_db) is None
    set_cached_llm_response("hash_abc", '{"result": "success"}', db_path=temp_db)
    assert get_cached_llm_response("hash_abc", db_path=temp_db) == '{"result": "success"}'

    # Usage tracking
    record_llm_usage(prompt_tokens=150, completion_tokens=50, db_path=temp_db)
    usage = get_today_llm_usage(db_path=temp_db)
    assert usage["request_count"] == 1
    assert usage["total_tokens"] == 200
