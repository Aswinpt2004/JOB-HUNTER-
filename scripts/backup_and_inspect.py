import zipfile
import os
import sqlite3

def run():
    # 1. Create zip backup
    zip_path = os.path.abspath("../jobpilot_backup_20261120.zip")
    print(f"Creating zip backup at: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in ("venv", ".git", "__pycache__", ".pytest_cache")]
            for file in files:
                if file.endswith(".zip"):
                    continue
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, ".")
                zipf.write(filepath, arcname)
    size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
    print(f"Zip backup created successfully ({size_mb} MB).")

    # 2. Database Inspection
    db_path = "data/jobpilot.db"
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]
        print("\nDatabase Tables and row counts in data/jobpilot.db:")
        for t in sorted(tables):
            if t.startswith("sqlite_"):
                continue
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            cnt = cur.fetchone()[0]
            print(f"  - {t}: {cnt} rows")

        if "blocklist" in tables:
            cur.execute("SELECT * FROM blocklist")
            rows = cur.fetchall()
            print(f"\nBlocklist table contents ({len(rows)} entries):")
            for r in rows:
                print("   ", r)
        conn.close()

if __name__ == "__main__":
    run()
