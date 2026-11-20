"""Demo verification for Step (a): Database, LLM unified interface, and Configuration."""
import json
from src.config import settings
from src.db import init_db, save_job, get_job, list_jobs
from src.models import Job
from src.llm import generate

def main():
    print("=== Step (a) Verification Demo ===")
    print(f"1. Config loaded:")
    print(f"   Candidate: {settings.candidate_name} ({settings.candidate_email})")
    print(f"   Target roles: {settings.target_roles}")
    print(f"   Daily sending cap: {settings.daily_cap}")
    print(f"   Database path: {settings.db_path}")

    print("\n2. Initializing SQLite Database...")
    init_db()
    print("   Database schema created successfully.")

    print("\n3. Inserting Sample Job into DB...")
    sample_job = Job(
        id="demo-job-001",
        title="Python Backend Developer",
        company="Acme Cloud Technologies",
        location="Bangalore / Hybrid",
        url="https://jobs.lever.co/acme/demo-job-001",
        description="We are seeking a Python Developer with FastAPI and PostgreSQL expertise. Please send your resume to careers@acmecloud.com.",
        source="lever",
        recruiter_email="careers@acmecloud.com"
    )
    inserted = save_job(sample_job)
    print(f"   Job inserted: {inserted}")
    retrieved = get_job(sample_job.id)
    print(f"   Retrieved from DB: {retrieved['title']} at {retrieved['company']}")

    print("\n4. Testing Unified LLM Interface (JSON mode)...")
    prompt = f"Parse the following JD into JSON with keys role, must_have_skills, recruiter_email: {sample_job.description}"
    result = generate(prompt, json_mode=True)
    print("   LLM Response:")
    print(result)

    print("\n5. Testing LLM Cache...")
    # Second call with identical prompt should hit SQLite cache instantly
    cached_result = generate(prompt, json_mode=True)
    print(f"   Cache verification: identical result = {result == cached_result}")

    print("\n[SUCCESS] Step (a) database, LLM interface, and configuration verified.")

if __name__ == "__main__":
    main()

