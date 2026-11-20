import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.models import (
    Company,
    CompanySignal,
    CompanyOutreach,
    MasterResume,
    TailoredResume
)
from src.db import (
    init_db,
    save_company,
    get_company,
    update_company,
    list_companies,
    save_company_outreach,
    get_company_outreach,
    has_company_or_email_been_contacted_recently,
    get_sent_count_today,
    normalize_domain_key
)
from src.companies.discovery import (
    normalize_domain,
    are_company_names_similar,
    clean_company_name_for_matching
)
from src.companies.enrichment import (
    extract_size_from_text,
    fetch_wikidata_employees,
    extract_schema_org_employees,
    get_hiring_volume_proxy
)
from src.companies.scorer import (
    extract_field_tags_and_score,
    compute_company_overall_score,
    assign_tier
)
from src.companies.speculative import (
    generate_pseudo_jd,
    generate_speculative_email,
    determine_dominant_role_lens,
    draft_single_speculative_application
)
from src.email_writer import score_email_tone
from src.verifier import verify_no_fabrication


@pytest.fixture
def test_db_path(tmp_path):
    db_file = tmp_path / "test_companies.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def sample_master_resume():
    master_path = Path("data/master_resume.json")
    with open(master_path, "r", encoding="utf-8") as f:
        return MasterResume.model_validate(json.load(f))


# 1. Size Extraction Regex Tests
def test_size_extraction_regexes():
    # Test "120+ employees" / "team of 120+"
    res1 = extract_size_from_text("We are a fast-growing team of 120+ passionate engineers building AI.")
    assert res1 is not None
    assert res1[2] == 120

    # Test "team of 45"
    res2 = extract_size_from_text("Founded in 2022 with a team of 45 across India.")
    assert res2 is not None
    assert res2[2] == 45

    # Test "50-200 employees"
    res3 = extract_size_from_text("Company size: 50-200 employees headquartered in Bangalore.")
    assert res3 is not None
    assert res3[0] == 50
    assert res3[1] == 200
    assert res3[2] == 125

    # Test "11-50 employees"
    res4 = extract_size_from_text("Organization headcount: 11-50 employees.")
    assert res4 is not None
    assert res4[0] == 11
    assert res4[1] == 50
    assert res4[2] == 30

    # Test "200+ engineers"
    res5 = extract_size_from_text("Our global presence includes 200+ engineers worldwide.")
    assert res5 is not None
    assert res5[2] == 200

    # Test negative: unrelated numbers
    res_none = extract_size_from_text("We processed 5000 images in 2024 at 60 fps.")
    assert res_none is None


# 2. Wikidata Employees Parsing Mock Test
def test_wikidata_employees_parsing():
    sample_wikidata_json = {
        "entities": {
            "Q12345": {
                "claims": {
                    "P1128": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "value": {
                                        "amount": "+250"
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
    }

    with patch("requests.get") as mock_get:
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {"search": [{"id": "Q12345"}]}

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = sample_wikidata_json

        mock_get.side_effect = [mock_resp1, mock_resp2]

        emp_count, source_url = fetch_wikidata_employees("Sample AI Tech")
        assert emp_count == 250
        assert "Q12345" in source_url


# 3. Hiring Volume Proxy Thresholds Test
def test_hiring_volume_proxy_thresholds(test_db_path):
    from src.models import Job
    from src.db import save_job

    # Insert 9 jobs for TechCorp
    for i in range(9):
        j = Job(
            id=f"job_techcorp_{i}",
            title=f"Engineer {i}",
            company="TechCorp",
            url=f"https://techcorp.com/job/{i}",
            description="Deep Learning and Python"
        )
        save_job(j, db_path=test_db_path)

    # Insert 4 jobs for SmallAI
    for i in range(4):
        j = Job(
            id=f"job_smallai_{i}",
            title=f"Developer {i}",
            company="SmallAI",
            url=f"https://smallai.com/job/{i}",
            description="Computer vision"
        )
        save_job(j, db_path=test_db_path)

    with patch("src.companies.enrichment.get_connection", return_value=pytest.importorskip("src.db").get_connection(test_db_path)):
        est_large, conf_large, _ = get_hiring_volume_proxy("TechCorp")
        assert est_large == 50
        assert conf_large == 0.5

        est_med, conf_med, _ = get_hiring_volume_proxy("SmallAI")
        assert est_med == 20
        assert conf_med == 0.5

        res_none = get_hiring_volume_proxy("NonExistent")
        assert res_none is None


# 4. Domain Deduplication & Canonical Normalization Test
def test_domain_deduplication_and_normalization():
    assert normalize_domain("https://www.inmobi.com/careers") == "inmobi.com"
    assert normalize_domain("http://accubits.com/") == "accubits.com"
    assert normalize_domain("https://careers.tonboimaging.com/jobs?loc=in") == "careers.tonboimaging.com"
    assert normalize_domain("WWW.QBURST.COM") == "qburst.com"

    # Fuzzy matching
    assert are_company_names_similar("InMobi Technologies Pvt Ltd", "InMobi") is True
    assert are_company_names_similar("Accubits Technologies", "Accubits Inc") is True
    assert are_company_names_similar("QBurst Systems Private Limited", "QBurst") is True
    assert are_company_names_similar("Google India", "Amazon") is False


# 5. Deterministic Field-Tag Scorer Test
def test_field_tag_scorer_deterministic():
    text_cv = "We build computer vision pipelines with deep learning, PyTorch, YOLO, and OpenCV for drone surveillance."
    tags, score = extract_field_tags_and_score(text_cv)
    assert "computer_vision" in tags
    assert "drone" in tags
    assert "pytorch" in tags
    assert score >= 70.0

    text_doc_ai = "Our platform provides document ai and healthcare ai solutions with fastapi and graph neural network."
    tags_doc, score_doc = extract_field_tags_and_score(text_doc_ai)
    assert "document_ai" in tags_doc
    assert "healthcare_ai" in tags_doc
    assert "fastapi" in tags_doc
    assert score_doc >= 40.0

    # Off-field text
    tags_empty, score_empty = extract_field_tags_and_score("We sell retail ceramic tiles and construction hardware.")
    assert len(tags_empty) == 0
    assert score_empty == 0.0


# 6. Tier Assignment Logic Test
def test_tier_assignment_logic():
    # Tier A: >= 70 score and confirmed/likely >= 20
    assert assign_tier(company_score=75.0, size_status="confirmed_20plus", field_fit=80.0, is_on_cooldown=False) == "A"
    assert assign_tier(company_score=72.0, size_status="likely_20plus", field_fit=65.0, is_on_cooldown=False) == "A"

    # Score >= 70 but size is unknown -> falls to Tier B
    assert assign_tier(company_score=75.0, size_status="unknown", field_fit=80.0, is_on_cooldown=False) == "B"

    # Tier B: 50 - 69 score
    assert assign_tier(company_score=58.0, size_status="likely_20plus", field_fit=50.0, is_on_cooldown=False) == "B"

    # Tier C: 35 - 49 score
    assert assign_tier(company_score=42.0, size_status="unknown", field_fit=40.0, is_on_cooldown=False) == "C"

    # Excluded: under 20 employees
    assert assign_tier(company_score=85.0, size_status="under_20", field_fit=90.0, is_on_cooldown=False) == "excluded"

    # Excluded: on 30-day cooldown
    assert assign_tier(company_score=90.0, size_status="confirmed_20plus", field_fit=90.0, is_on_cooldown=True) == "excluded"

    # Excluded: off-field (< 20 field fit)
    assert assign_tier(company_score=40.0, size_status="confirmed_20plus", field_fit=10.0, is_on_cooldown=False) == "excluded"


# 7. Shared Cooldown & Daily Cap Across Engines Test
def test_shared_cooldown_and_daily_cap(test_db_path):
    from datetime import datetime
    c = Company(
        name="Tonbo Imaging",
        domain="tonboimaging.com",
        city="Bangalore",
        status="active"
    )
    cid = save_company(c, db_path=test_db_path)

    # Cooldown initially False
    assert has_company_or_email_been_contacted_recently("Tonbo Imaging", db_path=test_db_path) is False
    assert get_sent_count_today(db_path=test_db_path) == 0

    # Record speculative outreach send
    outreach = CompanyOutreach(
        company_id=cid,
        mode="speculative",
        email_subject="Interested in Tonbo",
        email_body="Dear Team...",
        status="sent",
        sent_at=datetime.now()
    )
    save_company_outreach(outreach, db_path=test_db_path)

    # Cooldown should now be True!
    assert has_company_or_email_been_contacted_recently("Tonbo Imaging", db_path=test_db_path) is True
    # Daily send count must reflect this send
    assert get_sent_count_today(db_path=test_db_path) == 1


# 8. Speculative Email Tone & Fact Checks Test
def test_speculative_email_tone_and_humility(sample_master_resume):
    comp_dict = {
        "id": 99,
        "name": "AeroTech Vision",
        "city": "Bangalore",
        "field_tags": ["computer_vision", "drone", "surveillance"]
    }
    contact = None

    subject, body, tone = generate_speculative_email(comp_dict, contact, "Computer Vision / Drone / Surveillance")

    # Subject check
    assert "Fresher AI/ML Engineer interested in opportunities at AeroTech Vision | Aswin P T" == subject
    # Body checks
    assert "AeroTech Vision" in body
    assert "M.Sc. Machine Intelligence" in body
    assert "Quantumweave Intelligence" in body
    assert "If this isn't the right contact, let me know and I won't follow up." in body
    # Humility and tone score >= 8.5
    assert tone["score"] >= 8.5
    assert 90 <= tone["word_count"] <= 160
    assert len(tone["banned_phrases"]) == 0


def test_draft_single_speculative_application_and_verifier_order(test_db_path, sample_master_resume, monkeypatch):
    # Setup company
    comp = Company(
        name="Test Robotics AI",
        domain="testrobotics.ai",
        website="https://testrobotics.ai",
        city="Bangalore",
        tier="A",
        size_status="confirmed_20plus",
        field_tags=["computer_vision", "drone"]
    )
    cid = save_company(comp, db_path=test_db_path)

    # Monkeypatch settings.db_path to test_db_path
    from src.config import Config
    monkeypatch.setattr(Config, "db_path", property(lambda self: test_db_path))

    with patch("src.pdf_builder.build_tailored_resume_files", return_value=(Path("output/test.pdf"), Path("output/test.json"))):
        oid = draft_single_speculative_application(cid, sample_master_resume)
        assert oid is not None

        outreach = get_company_outreach(cid, db_path=test_db_path)
        assert outreach is not None
        assert outreach["mode"] == "speculative"
        assert outreach["status"] == "drafted"
        assert "Test Robotics AI" in outreach["email_subject"]

    # Also verify verify_no_fabrication works even if args are swapped
    from src.models import JDParsed
    from src.resume_tailor import tailor_resume
    jd = JDParsed(
        role="AI/ML Engineer",
        seniority="Fresher",
        must_have_skills=["Python", "PyTorch"],
        nice_to_have_skills=["Computer Vision"],
        keywords=["computer_vision"],
        responsibilities=["AI development"],
        location="Bangalore"
    )
    tailored = tailor_resume(sample_master_resume, jd)
    # Correct order
    valid1, violations1 = verify_no_fabrication(tailored, sample_master_resume)
    assert valid1 is True
    # Swapped order (master, tailored) - should gracefully swap and not raise AttributeError
    valid2, violations2 = verify_no_fabrication(sample_master_resume, tailored)
    assert valid2 is True


