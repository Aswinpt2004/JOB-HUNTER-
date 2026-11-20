import socket
import smtplib
import ssl
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from src.config import settings, Config
from src.db import (
    init_db,
    save_job,
    update_application,
    get_connection,
    list_applications_by_status,
    add_to_blocklist
)
from src.models import Job
from src.sender import (
    send_application_email,
    send_company_outreach_email,
    is_within_sending_hours,
    check_smtp_health,
    mask_email,
    IST
)
from src.send_worker import SendWorker
from src.send_diagnose import run_send_diagnosis


@pytest.fixture
def temp_db(tmp_path: Path, monkeypatch):
    db_file = tmp_path / "test_sender_worker.db"
    init_db(db_file)
    monkeypatch.setattr(Config, "db_path", property(lambda self: db_file))
    return db_file


def test_mask_email():
    assert mask_email("aswinpt2004@gmail.com") == "a***4@gmail.com"
    assert mask_email("hr@company.com") == "h*@company.com"
    assert mask_email("invalid-email") == "invalid-email"
    assert mask_email("") == ""


def test_is_within_sending_hours_ist():
    # 02:30 IST -> should be False (Outside sending window 09:00 - 18:00 IST)
    dt_night = datetime(2026, 11, 19, 2, 30, tzinfo=IST)
    allowed, msg = is_within_sending_hours(dt_night)
    assert allowed is False
    assert "Waiting: sending hours are 9:00 - 18:00 IST" in msg
    assert "02:30 IST" in msg

    # 11:15 IST -> should be True (Within window)
    dt_morning = datetime(2026, 11, 19, 11, 15, tzinfo=IST)
    allowed, msg = is_within_sending_hours(dt_morning)
    assert allowed is True
    assert "Within sending window" in msg

    # 18:00 IST -> should be False (Closed at 18:00)
    dt_closed = datetime(2026, 11, 19, 18, 0, tzinfo=IST)
    allowed, msg = is_within_sending_hours(dt_closed)
    assert allowed is False

    # 09:00 IST -> should be True (Window opens)
    dt_open = datetime(2026, 11, 19, 9, 0, tzinfo=IST)
    allowed, msg = is_within_sending_hours(dt_open)
    assert allowed is True


def test_smtp_mocked_success(temp_db, monkeypatch):
    # Setup job and application
    j = Job(id="job-mock-1", title="AI Engineer", company="NovaTech", url="https://nova.ai/job1", description="ML role")
    save_job(j, db_path=temp_db)
    update_application(job_id=j.id, status="approved", email_subject="Subject", email_body="Body", db_path=temp_db)

    # Mock smtplib.SMTP_SSL
    mock_server = MagicMock()
    mock_server.login.return_value = (235, b"2.7.0 Accepted")
    mock_server.send_message.return_value = {}

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        ok, msg = send_application_email(
            job_id=j.id,
            recipient_email="recruiter@novatech.ai",
            subject="Application for AI Engineer",
            body="Dear Hiring Manager...",
            company_name="NovaTech",
            ignore_hours=True
        )

        assert ok is True
        assert "sent successfully" in msg.lower()
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()

    # Check honest database record updates
    with get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, sent_at, attempted_at, message_id, smtp_response, error FROM applications WHERE job_id = ?", (j.id,))
        row = dict(cursor.fetchone())

    assert row["status"] == "sent"
    assert row["sent_at"] is not None
    assert row["attempted_at"] is not None
    assert row["message_id"] is not None
    assert "@gmail.com" in row["message_id"]
    assert "250 OK" in row["smtp_response"]
    assert row["error"] is None


def test_smtp_auth_failure_535_halts_immediately(temp_db, monkeypatch):
    j = Job(id="job-mock-auth", title="CV Engineer", company="VisionCorp", url="https://vc.ai/1", description="CV role")
    save_job(j, db_path=temp_db)
    update_application(job_id=j.id, status="approved", db_path=temp_db)

    mock_server = MagicMock()
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        ok, msg = send_application_email(
            job_id=j.id,
            recipient_email="recruiter@visioncorp.ai",
            subject="Application",
            body="Body",
            company_name="VisionCorp",
            ignore_hours=True
        )

        assert ok is False
        assert "535" in msg or "app password invalid" in msg.lower()
        # Halts immediately: exactly 1 login attempt
        assert mock_server.login.call_count == 1

    with get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, error, smtp_response, attempted_at, sent_at FROM applications WHERE job_id = ?", (j.id,))
        row = dict(cursor.fetchone())

    assert row["status"] == "failed"
    assert "535" in row["error"]
    assert row["smtp_response"] == "FAILED"
    assert row["attempted_at"] is not None
    assert row["sent_at"] is None


def test_smtp_transient_timeout_exhausts_retries(temp_db, monkeypatch):
    j = Job(id="job-mock-timeout", title="LLM Engineer", company="PromptCo", url="https://pc.ai/1", description="LLM role")
    save_job(j, db_path=temp_db)
    update_application(job_id=j.id, status="approved", db_path=temp_db)

    # Fast forward sleeps
    monkeypatch.setattr("time.sleep", lambda s: None)

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.side_effect = socket.timeout("Timed out connecting to smtp.gmail.com")

        ok, msg = send_application_email(
            job_id=j.id,
            recipient_email="hr@promptco.ai",
            subject="Application",
            body="Body",
            company_name="PromptCo",
            ignore_hours=True
        )

        assert ok is False
        assert "timed out" in msg.lower()
        # Initial attempt + 1 retry = 2 attempts
        assert mock_smtp_cls.call_count == 2

    with get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, error, attempted_at, sent_at FROM applications WHERE job_id = ?", (j.id,))
        row = dict(cursor.fetchone())

    assert row["status"] == "failed"
    assert "Timed out" in row["error"]
    assert row["sent_at"] is None


def test_smtp_transient_recovers_on_retry(temp_db, monkeypatch):
    j = Job(id="job-mock-recovery", title="Backend AI", company="EdgeScale", url="https://es.ai/1", description="Backend")
    save_job(j, db_path=temp_db)
    update_application(job_id=j.id, status="approved", db_path=temp_db)

    monkeypatch.setattr("time.sleep", lambda s: None)

    mock_server = MagicMock()
    mock_server.login.return_value = (235, b"2.7.0 Accepted")
    mock_server.send_message.return_value = {}

    attempt = 0
    def smtp_factory(*args, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise socket.error("Connection reset by peer")
        cm = MagicMock()
        cm.__enter__.return_value = mock_server
        return cm

    with patch("smtplib.SMTP_SSL", side_effect=smtp_factory):
        ok, msg = send_application_email(
            job_id=j.id,
            recipient_email="recruiter@edgescale.ai",
            subject="Application",
            body="Body",
            company_name="EdgeScale",
            ignore_hours=True
        )

        assert ok is True
        assert attempt == 2
        assert "sent successfully" in msg.lower()

    with get_connection(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, sent_at FROM applications WHERE job_id = ?", (j.id,))
        row = dict(cursor.fetchone())

    assert row["status"] == "sent"
    assert row["sent_at"] is not None


def test_check_smtp_health_mocked():
    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_server.login.return_value = (235, b"Accepted")
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        ok, msg = check_smtp_health()
        assert ok is True
        assert "connected and authenticated" in msg.lower()

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.side_effect = Exception("Network unreachable")
        ok, msg = check_smtp_health()
        assert ok is False
        assert "Network unreachable" in msg


def test_send_diagnose_report_generation(temp_db):
    report = run_send_diagnosis()
    assert "# 🩺 JobPilot Email Sending Diagnostic Report" in report
    assert "Credentials Checklist" in report
    assert "SMTP Connectivity & Login Tests" in report
    assert "Pipeline State: Application Audit" in report


def test_send_worker_processes_approved(temp_db, monkeypatch):
    from src.models import RecruiterContact
    from src.db import save_contact

    j = Job(id="worker-job-1", title="AI Specialist", company="WorkerCo", url="https://w.ai/1", description="Worker job")
    save_job(j, db_path=temp_db)
    save_contact(RecruiterContact(job_id=j.id, email="recruiter@workerco.com", name="HR", role="Recruiter", verified=True, domain_mx_valid=True), db_path=temp_db)
    update_application(job_id=j.id, status="approved", email_subject="Hi", email_body="Body", db_path=temp_db)

    # Avoid real 60s sleeps in test
    monkeypatch.setattr("time.sleep", lambda s: None)

    # Mock smtplib.SMTP_SSL
    mock_server = MagicMock()
    mock_server.login.return_value = (235, b"2.7.0 Accepted")
    mock_server.send_message.return_value = {}

    with patch("smtplib.SMTP_SSL") as mock_smtp_cls:
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        # Instantiate worker directly
        worker = SendWorker()
        worker._ignore_hours = True

        # Process 1 iteration of worker logic directly
        apps = list_applications_by_status("approved", db_path=temp_db)
        assert len(apps) == 1

        # Call worker's application handler
        processed = worker.process_next_item()
        assert processed is True

        # Status in live mode transitions to 'sent'
        with get_connection(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, sent_at FROM applications WHERE job_id = ?", (j.id,))
            row = dict(cursor.fetchone())

        assert row["status"] == "sent"
        assert row["sent_at"] is not None
        assert worker._total_sent == 1

