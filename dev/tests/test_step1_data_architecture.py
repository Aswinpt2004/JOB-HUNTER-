import pytest
import sqlite3
from pathlib import Path
from jobpilot.core.db import (
    init_db,
    get_connection,
    is_recipient_in_cooldown,
    is_company_in_cooldown_ledger,
    create_or_get_outreach,
    update_outreach_status,
    save_raw_job
)


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_architecture.db"
    init_db(db_file)
    return db_file


def test_unique_canonical_key_on_jobs(test_db):
    with get_connection(test_db) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (id, title, company, url, description, canonical_key)
            VALUES ('job_1', 'AI Engineer', 'Acme', 'https://acme.com/1', 'Desc', 'key_abc_123')
        """)
        conn.commit()

        # Duplicate canonical_key should fail hard
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute("""
                INSERT INTO jobs (id, title, company, url, description, canonical_key)
                VALUES ('job_2', 'AI Engineer Reposted', 'Acme', 'https://acme.com/2', 'Desc 2', 'key_abc_123')
            """)
            conn.commit()


def test_outreach_idempotency_and_ledger(test_db):
    with get_connection(test_db) as conn:
        conn.execute("INSERT INTO companies (id, name, domain) VALUES (101, 'Acme AI', 'acme.ai')")
        conn.commit()

    # 1. First outreach insertion
    outreach_id_1, is_new_1 = create_or_get_outreach(
        job_id="job_1",
        company_id=101,
        contact_email="hr@acme.ai",
        idempotency_key="idemp_hash_999",
        score=85.0,
        score_basis="rules",
        status="queued",
        db_path=test_db
    )
    assert is_new_1 is True
    assert outreach_id_1 > 0

    # 2. Second attempt with exact same idempotency_key must return existing row and is_new=False
    outreach_id_2, is_new_2 = create_or_get_outreach(
        job_id="job_1",
        company_id=101,
        contact_email="hr@acme.ai",
        idempotency_key="idemp_hash_999",
        score=85.0,
        db_path=test_db
    )
    assert is_new_2 is False
    assert outreach_id_2 == outreach_id_1

    # 3. Initially not in cooldown (still queued)
    in_cool, _ = is_recipient_in_cooldown("hr@acme.ai", db_path=test_db)
    assert in_cool is False

    # 4. Update status to sent_detected -> triggers ledgers
    update_outreach_status(outreach_id_1, to_status="sent_detected", db_path=test_db)

    # 5. Now recipient and company must be in 30-day cooldown
    in_cool_rec, reason_rec = is_recipient_in_cooldown("hr@acme.ai", cooldown_days=30, db_path=test_db)
    assert in_cool_rec is True
    assert "cooldown is 30 days" in reason_rec

    in_cool_comp, reason_comp = is_company_in_cooldown_ledger(101, cooldown_days=30, db_path=test_db)
    assert in_cool_comp is True


def test_raw_jobs_immutable_append(test_db):
    raw_id = save_raw_job(
        run_id=1,
        source="adzuna",
        external_id="adz_12345",
        url="https://adzuna.in/job/12345",
        payload_json='{"title": "Junior ML Engineer"}',
        db_path=test_db
    )
    assert raw_id > 0
    with get_connection(test_db) as conn:
        c = conn.cursor()
        c.execute("SELECT source, external_id FROM raw_jobs WHERE id = ?", (raw_id,))
        row = c.fetchone()
        assert row["source"] == "adzuna"
        assert row["external_id"] == "adz_12345"
