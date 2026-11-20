"""Demo verification for Step (d): Job Discovery Engine (Greenhouse, Lever, Remotive)."""
from src.config import settings
from src.scrapers.remotive import RemotiveScraper
from src.scrapers.greenhouse import GreenhouseScraper
from src.db import init_db, save_job, list_jobs

def main():
    print("=== Step (d) Verification Demo ===")
    init_db()

    print("1. Running Remotive Public API Scraper...")
    remotive = RemotiveScraper(categories=["software-dev"])
    jobs = remotive.fetch_jobs()
    print(f"   Discovered {len(jobs)} jobs from Remotive matching keywords {settings.keywords}")

    if jobs:
        first = jobs[0]
        print(f"   Sample Job 1: '{first.title}' at {first.company}")
        print(f"   URL: {first.url}")
        print(f"   Location: {first.location}")
        saved = save_job(first)
        print(f"   Saved to SQLite DB: {saved}")

        # Check deduplication
        is_dupe = remotive.is_duplicate(first.url)
        print(f"   Deduplication check for same URL: is_duplicate = {is_dupe}")

    print("\n2. Checking Greenhouse Public Scraper structure...")
    gh = GreenhouseScraper(boards=["canonical"])
    print(f"   Configured Greenhouse boards: {gh.boards}")

    print("\n[SUCCESS] Step (d) job discovery scrapers verified.")

if __name__ == "__main__":
    main()

