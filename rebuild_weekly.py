"""
rebuild_weekly.py — regenerate weekly_energy.csv using ONE MySQL connection.

Use after a reingest that failed mid-run, or any time the DB is correct but
weekly_energy.csv is stale. Uses a single pymysql.connect() — safe on hosts
with strict max_connections_per_hour limits.

Run:
    python3 rebuild_weekly.py
"""
from master_pipeline import generate_weekly_csv, WEEKLY_CSV_PATH

if __name__ == "__main__":
    print(f"Regenerating {WEEKLY_CSV_PATH}…")
    ok = generate_weekly_csv(WEEKLY_CSV_PATH)
    print("Done." if ok else "Failed — check pipeline log.")
