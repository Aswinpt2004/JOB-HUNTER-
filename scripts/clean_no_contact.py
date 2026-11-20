from src.db import get_connection, get_contacts_for_job

def clean_no_contacts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT job_id, status FROM applications WHERE status IN ('drafted', 'approved', 'matched')")
    rows = cursor.fetchall()

    cleaned = 0
    for r in rows:
        job_id = r["job_id"]
        contacts = get_contacts_for_job(job_id)
        if not contacts:
            cursor.execute(
                "UPDATE applications SET status='skipped', rationale='Skipped: No verified HR contact email available for outreach', updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                (job_id,)
            )
            cleaned += 1

    conn.commit()
    conn.close()
    print(f"Cleaned {cleaned} applications without HR contacts. Only jobs with verified HR emails remain in active queue.")

if __name__ == "__main__":
    clean_no_contacts()

