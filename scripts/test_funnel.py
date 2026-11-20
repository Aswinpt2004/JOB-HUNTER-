from src.db import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM jobs")
    total_ingested = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM applications WHERE match_score > 0 OR status != 'skipped'")
    city_passed = cur.fetchone()[0]

    cur.execute("SELECT role_tier, COUNT(*) FROM applications GROUP BY role_tier")
    tier_counts = dict(cur.fetchall())

    cur.execute("SELECT COUNT(*) FROM applications WHERE match_score >= 65.0")
    scored_65 = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT job_id) FROM contacts")
    contacts_found = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM applications WHERE status IN ('drafted', 'approved', 'sent')")
    total_drafted = cur.fetchone()[0]

funnel_summary = (
    f"\n======================================================\n"
    f"📊 JOBPILOT PIPELINE FUNNEL REPORT\n"
    f"======================================================\n"
    f"  1. Total Postings Ingested    : {total_ingested}\n"
    f"  2. Target City Passed         : {city_passed}\n"
    f"  3. Tier Classification        : Tier A: {tier_counts.get('Tier A', 0)} | Tier B: {tier_counts.get('Tier B', 0)} | Tier C: {tier_counts.get('Tier C', 0)}\n"
    f"  4. Scored >= 65.0 Threshold   : {scored_65}\n"
    f"  5. Verified Contacts Found    : {contacts_found}\n"
    f"  6. Ready Applications Drafted : {total_drafted}\n"
    f"======================================================\n"
)
print(funnel_summary)

