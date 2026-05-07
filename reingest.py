"""
reingest.py — one-off re-ingestion of local raw CSVs into MySQL.

Use cases:
    - After TRUNCATE-ing the tables, restore data from archived raw CSVs.
    - Surgical fix for a specific week (combined with a targeted DELETE first).

Workflow:
    1. Ensure energy_core.py, app_data_loader.py, master_pipeline.py are in
       the same folder (or on the Python path).
    2. Edit RAW_FOLDERS and WEEKLY_CSV_PATH below for your environment.
    3. python3 reingest.py

The script walks every folder in RAW_FOLDERS, processes every .csv found,
INSERT IGNOREs into MySQL (so already-correct rows are never overwritten or
duplicated), then rewrites weekly_energy.csv.

This script does NOT touch FTP, does NOT move files, does NOT delete anything.
Any cleanup of corrupt rows must happen via SQL DELETE before running this.
"""
import os
import pymysql

from energy_core import process_csv
from master_pipeline import DB_CONFIG, ensure_unique_indexes, push_to_db, generate_weekly_csv

# ── EDIT THESE FOR YOUR ENVIRONMENT ──────────────────────────────────────
# Each entry in RAW_FOLDERS is a directory that contains raw CSVs.
# Add as many folders as you need — the script processes all of them.
RAW_FOLDERS = [
    "/var/www/html/Energy/processed/intervalMeterReports",
    "/var/www/html/Energy/processed/pgeReports",
    # "/var/www/html/Energy/uploads/intervalMeterReports",   # uncomment if needed
    # "/var/www/html/Energy/uploads/pgeReports",
]
WEEKLY_CSV_PATH = "/var/www/html/Energy/weekly_energy.csv"
# ─────────────────────────────────────────────────────────────────────────


def collect_csvs(folders):
    """Return a sorted list of (folder, filename) pairs for every .csv found."""
    found = []
    for folder in folders:
        if not os.path.isdir(folder):
            print(f"  [skip] not a directory: {folder}")
            continue
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith(".csv"):
                found.append((folder, fname))
    return found


def main():
    files = collect_csvs(RAW_FOLDERS)
    if not files:
        print("No CSV files found in any of RAW_FOLDERS. Check the paths.")
        return

    print(f"Found {len(files)} CSV files across {len(RAW_FOLDERS)} folder(s)\n")

    # Guarantee unique indexes before any insert — makes INSERT IGNORE idempotent
    conn = pymysql.connect(**DB_CONFIG)
    ensure_unique_indexes(conn)
    conn.close()

    total_rows_out = 0
    total_inserted = 0
    total_errors   = 0
    failed_files   = []

    for folder, fname in files:
        fp = os.path.join(folder, fname)
        cleaned, stats = process_csv(fp)

        err = stats["error"] or ""
        print(f"  {fname:<25} rows_in={stats['rows_in']:>4}  "
              f"rows_out={stats['rows_out']:>5}  "
              f"cols_mapped={stats['cols_mapped']:>3}  "
              f"cols_skipped={stats['cols_skipped']:>3}  "
              f"error={err or '-'}")

        if cleaned.empty:
            if err:
                failed_files.append((fname, err))
            continue

        try:
            res = push_to_db(cleaned)
            total_rows_out += stats["rows_out"]
            total_inserted += res["energy"] + res["gas"] + res["water"]
            total_errors   += res["errors"]
        except Exception as e:
            print(f"    DB push failed: {e}")
            failed_files.append((fname, f"db push: {e}"))
            total_errors += 1

    print()
    print("=" * 70)
    print(f"SUMMARY")
    print(f"  files processed:   {len(files)}")
    print(f"  cleaned rows out:  {total_rows_out:,}")
    print(f"  DB rows inserted:  {total_inserted:,}  (INSERT IGNORE dedupes duplicates)")
    print(f"  DB errors:         {total_errors}")
    print(f"  failed files:      {len(failed_files)}")
    for fname, reason in failed_files:
        print(f"    - {fname}: {reason}")
    print("=" * 70)

    # Regenerate weekly_energy.csv from the (now-corrected) DB
    print()
    print("Regenerating weekly_energy.csv…")
    generate_weekly_csv(WEEKLY_CSV_PATH)
    print(f"Wrote {WEEKLY_CSV_PATH}")


if __name__ == "__main__":
    main()
