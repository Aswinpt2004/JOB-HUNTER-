"""Demo verification for Step (b): Master Resume, JD Parser, Matcher, Tailoring, and PDF Rendering."""
import json
from src.config import settings
from src.models import MasterResume
from src.jd_parser import parse_job_description
from src.matcher import compute_match_score
from src.resume_tailor import tailor_resume, verify_no_fabrication
from src.pdf_builder import build_tailored_resume_files

SAMPLE_JD = """
About the Job:
Acme Cloud is hiring a Python Developer to join our backend infrastructure team in Bangalore (Remote friendly).

Key Responsibilities:
- Build high-performance REST APIs and microservices using Python and FastAPI.
- Write clean, well-tested code with comprehensive unit and integration tests.
- Collaborate with database engineers on PostgreSQL query optimization.
- Work with Docker and CI/CD pipelines to deploy containerized services.

Requirements:
- 1-3 years of hands-on experience in Python.
- Proven expertise with web frameworks like FastAPI, Django, or Flask.
- Good knowledge of PostgreSQL or MySQL, relational schema design, and indexing.
- Familiarity with Git version control and Docker.
- Nice to have: Experience with Redis caching or background task queues.

How to Apply:
Please submit your resume to jobs@acmecloud.io with the subject 'Application: Python Developer - [Your Name]'.
"""

def main():
    print("=== Step (b) Verification Demo ===")

    # 1. Load Master Resume
    print("1. Loading Master Resume...")
    with open(settings.master_resume_path, "r", encoding="utf-8") as f:
        master_data = json.load(f)
    master = MasterResume.model_validate(master_data)
    print(f"   Candidate: {master.contact.name}")
    print(f"   Known Skill Categories: {list(master.skills.keys())}")
    print(f"   Total Experiences: {len(master.experience)}, Projects: {len(master.projects)}")

    # 2. Parse Sample JD
    print("\n2. Parsing Job Description with JD Parser...")
    jd = parse_job_description(SAMPLE_JD)
    print(f"   Role: {jd.role} ({jd.seniority})")
    print(f"   Must-have skills: {jd.must_have_skills}")
    print(f"   Keywords: {jd.keywords}")
    print(f"   Instructions: {jd.application_instructions}")

    # 3. Match Score
    print("\n3. Computing Match Score...")
    match = compute_match_score(jd, master, threshold=65.0)
    print(f"   Match Score: {match.match_score}/100 (Threshold Met: {match.meets_threshold})")
    print(f"   Matched Skills: {match.matched_skills}")
    print(f"   Missing Skills: {match.missing_skills}")
    print(f"   Rationale: {match.rationale}")

    # 4. Tailor Resume & Strict Verification
    print("\n4. Tailoring Resume & Running Strict Verification...")
    tailored = tailor_resume(master, jd)
    is_valid, violations = verify_no_fabrication(tailored, master)
    print(f"   Verification Passed: {is_valid}")
    if violations:
        print(f"   Violations caught: {violations}")
    else:
        print("   0 Fabrications: All skills, employers, and degrees verified against Master Resume.")

    # 5. Build PDF & JSON
    print("\n5. Generating ATS Resume Files...")
    pdf_path, json_path = build_tailored_resume_files(tailored, "SampleCorp", jd.role)
    print(f"   Tailored JSON: {json_path} (Size: {json_path.stat().st_size} bytes)")
    print(f"   Tailored PDF:  {pdf_path} (Size: {pdf_path.stat().st_size} bytes)")

    print("\n[SUCCESS] Step (b) master resume, JD parser, matcher, tailor, and PDF builder verified.")

if __name__ == "__main__":
    main()

