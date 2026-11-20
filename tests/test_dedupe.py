import pytest
from pathlib import Path
from src.db import (
    init_db,
    save_job,
    get_job_by_url,
    normalize_job_url,
    is_job_duplicate,
    save_company,
    get_company,
    list_companies,
    save_company_contact,
    get_company_contacts,
    clear_database,
    clean_company_name_for_matching,
    are_company_names_similar
)
from src.models import Job, Company, RecruiterContact


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_dedupe.db"
    init_db(db_file)
    return db_file


def test_job_deduplication_by_url(temp_db):
    job1 = Job(
        id="job-101",
        title="Python Dev",
        company="AlphaCorp",
        url="https://alphacorp.com/jobs/101",
        description="Python FastAPI dev"
    )
    first_save = save_job(job1, db_path=temp_db)
    assert first_save is True

    # Attempt to insert same URL under different ID
    job2 = Job(
        id="job-102",
        title="Python Dev (Duplicate)",
        company="AlphaCorp",
        url="https://alphacorp.com/jobs/101",  # Same URL
        description="Duplicate posting"
    )
    second_save = save_job(job2, db_path=temp_db)
    assert second_save is False

    # Check lookup
    found = get_job_by_url("https://alphacorp.com/jobs/101", db_path=temp_db)
    assert found is not None
    assert found["id"] == "job-101"


def test_job_url_normalization_with_tracking_params(temp_db):
    """Ensure UTM parameters, trailing slashes, and casing variations are normalized and deduplicated."""
    url1 = "https://example.com/careers/ai-engineer/?utm_source=linkedin&utm_medium=job_post&ref=social"
    url2 = "https://EXAMPLE.COM/careers/ai-engineer?ref=share#overview"

    norm1 = normalize_job_url(url1)
    norm2 = normalize_job_url(url2)
    assert norm1 == "https://example.com/careers/ai-engineer"
    assert norm2 == "https://example.com/careers/ai-engineer"
    assert norm1 == norm2

    job1 = Job(
        id="job-201",
        title="Computer Vision Engineer",
        company="VisionLabs",
        url=url1,
        description="Edge CV and Drone analytics"
    )
    assert save_job(job1, db_path=temp_db) is True

    # Same job with tracking parameters from another post
    job2 = Job(
        id="job-202",
        title="Computer Vision Engineer",
        company="VisionLabs",
        url=url2,
        description="Edge CV and Drone analytics"
    )
    assert save_job(job2, db_path=temp_db) is False


def test_job_cross_source_title_and_company_deduplication(temp_db):
    """Ensure that the same company cannot insert the exact same job title under two different URLs."""
    job1 = Job(
        id="job-301",
        title="AI/ML Engineer (Fresher)",
        company="Quantumweave Intelligence Pvt Ltd",
        url="https://technopark.in/job/301",
        description="Intrusion detection on surveillance video"
    )
    assert save_job(job1, db_path=temp_db) is True

    # Same company, same core title, but from their direct careers portal
    job2 = Job(
        id="job-302",
        title="AI / ML Engineer",
        company="Quantumweave Intelligence",
        url="https://quantumweave.ai/careers/ai-ml-engineer",
        description="Intrusion detection on surveillance video"
    )
    # Must be detected as duplicate
    assert is_job_duplicate(job2.title, job2.company, job2.url, db_path=temp_db) is True
    assert save_job(job2, db_path=temp_db) is False


def test_company_deduplication_by_domain_and_variations(temp_db):
    """Ensure companies with different URL schemes or www are deduplicated to 1 company record."""
    c1 = Company(
        name="InMobi",
        domain="https://www.inmobi.com/",
        website="https://www.inmobi.com",
        city="Bangalore"
    )
    cid1 = save_company(c1, db_path=temp_db)

    # Re-insert with bare domain and different case
    c2 = Company(
        name="INMOBI",
        domain="inmobi.com",
        website="https://inmobi.com/about",
        city="Bangalore"
    )
    cid2 = save_company(c2, db_path=temp_db)
    assert cid1 == cid2

    companies = list_companies(db_path=temp_db)
    assert len(companies) == 1
    assert companies[0]["domain"] == "inmobi.com"


def test_company_deduplication_by_legal_name_variations(temp_db):
    """Ensure legal suffixes like 'Technologies Pvt Ltd' or 'Inc' match the base company."""
    c1 = Company(
        name="Mitsogo",
        city="Kochi",
        field_tags=["backend"]
    )
    cid1 = save_company(c1, db_path=temp_db)

    c2 = Company(
        name="Mitsogo Technologies Pvt. Ltd.",
        city="Kochi",
        field_tags=["fastapi", "machine_learning"]
    )
    cid2 = save_company(c2, db_path=temp_db)
    assert cid1 == cid2

    companies = list_companies(db_path=temp_db)
    assert len(companies) == 1
    assert "fastapi" in companies[0]["field_tags"]


def test_company_does_not_collide_on_generic_ats_domain(temp_db):
    """Ensure generic ATS platforms (lever.co, greenhouse.io) do not cause distinct companies to collide."""
    c1 = Company(
        name="Stripe",
        domain="jobs.lever.co/stripe",
        website="https://stripe.com"
    )
    cid1 = save_company(c1, db_path=temp_db)

    c2 = Company(
        name="Canonical",
        domain="jobs.lever.co/canonical",
        website="https://canonical.com"
    )
    cid2 = save_company(c2, db_path=temp_db)
    assert cid1 != cid2

    companies = list_companies(db_path=temp_db)
    assert len(companies) == 2


def test_contact_deduplication_per_company(temp_db):
    """Ensure the same recruiter email is not duplicated for a company."""
    c = Company(name="TestCorp", domain="testcorp.com")
    cid = save_company(c, db_path=temp_db)

    contact1 = RecruiterContact(
        job_id="",
        email="talent@testcorp.com",
        name="Talent Team",
        role="HR",
        verified=True
    )
    cnt_id1 = save_company_contact(cid, contact1, db_path=temp_db)

    contact2 = RecruiterContact(
        job_id="",
        email=" TALENT@TESTCORP.COM ",
        name="Talent Team",
        role="HR",
        verified=True
    )
    cnt_id2 = save_company_contact(cid, contact2, db_path=temp_db)
    assert cnt_id1 == cnt_id2

    contacts = get_company_contacts(cid, db_path=temp_db)
    assert len(contacts) == 1


def test_clear_database_resets_tables_and_preserves_schema(temp_db):
    """Ensure clear_database completely removes records while keeping table structure intact."""
    # Seed data
    c = Company(name="WipeCorp", domain="wipecorp.com")
    cid = save_company(c, db_path=temp_db)

    j = Job(
        id="job-999",
        title="Junior Developer",
        company="WipeCorp",
        url="https://wipecorp.com/careers/999",
        description="Testing clear DB"
    )
    save_job(j, db_path=temp_db)

    # Verify rows exist
    assert len(list_companies(db_path=temp_db)) == 1

    # Clear DB
    deleted = clear_database(db_path=temp_db, keep_cache=True)
    assert deleted["jobs"] == 1
    assert deleted["companies"] == 1

    # Verify tables are now empty
    assert len(list_companies(db_path=temp_db)) == 0

    # Verify schema allows fresh inserts without errors
    c_new = Company(name="FreshCorp", domain="freshcorp.com")
    new_cid = save_company(c_new, db_path=temp_db)
    assert new_cid == 1
