"""
master_pipeline.py — SSU Campus Energy Pipeline 

Pipeline stages:
  0. Test DB connection (required unique indexes verified on first run)
  1. FTP download (preserves existing FTP logic)
  2. For each raw CSV: energy_core.process_csv() → INSERT IGNORE into MySQL
  3. Regenerate weekly_energy.csv from the three MySQL tables
  4. Move processed files, log summary, email + PowerBI refresh

Changes vs. master_pipeline_final.py:
  • Cleaning logic extracted into energy_core.py — shared with app.py
  • daily_energy.csv and generate_daily_csv() REMOVED (redundant with weekly)
  • normalize_csv → thin wrapper over energy_core.process_csv
  • Guard: ensures UNIQUE(timestamp, location, unit) index before first insert

Required MySQL schema (run once):
  ALTER TABLE energy_usage ADD UNIQUE KEY uq_energy (timestamp, location, unit);
  ALTER TABLE gas_usage    ADD UNIQUE KEY uq_gas    (timestamp, location, unit);
  ALTER TABLE water_usage  ADD UNIQUE KEY uq_water  (timestamp, location, unit);

Cron (daily 06:00):
  0 6 * * * /usr/bin/python3 /var/www/html/Energy/master_pipeline.py \
      >> /var/www/html/Energy/logs/cron.log 2>&1
"""
from __future__ import annotations
import os, sys, shutil, smtplib, traceback
from collections import defaultdict
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from ftplib import FTP

import pandas as pd
import pymysql
import requests

from energy_core import (
    POINT_ID_MAP, UNIT_TO_KWH, ENERGY_UNITS, THERMAL_UNITS,
    process_csv, to_kwh,
)

# ── Config ────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "user": "u209446640_SSUTeam", "password": "SsuIot!432",
    "host": "193.203.166.234", "database": "u209446640_SSUEnergy",
    "port": 3306, "connect_timeout": 30,
}
FTP_CONFIG = {
    "host": "145.223.107.54", "username": "u209446640.csu",
    "password": "Energy!2", "base_directory": "/siqReports",
}
EMAIL_CONFIG = {
    "enabled": False, "smtp_server": "smtp.gmail.com", "smtp_port": 587,
    "sender_email": "your-email@gmail.com", "sender_password": "your-app-password",
    "recipient_email": "admin@ssu.edu",
}
POWERBI_CONFIG = {
    "enabled": False, "dataset_id": "YOUR-DATASET-ID",
    "access_token": "YOUR-ACCESS-TOKEN",
}
BASE_DIR        = "/var/www/html/Energy"
UPLOAD_DIR      = os.path.join(BASE_DIR, "uploads")
PROCESSED_DIR   = os.path.join(BASE_DIR, "processed")
FAILED_DIR      = os.path.join(BASE_DIR, "failed")
LOG_DIR         = os.path.join(BASE_DIR, "logs")
TEMP_DIR        = os.path.join(BASE_DIR, "temp")
WEEKLY_CSV_PATH = os.path.join(BASE_DIR, "weekly_energy.csv")
FTP_FOLDERS     = ["degreeDayReports", "intervalMeterReports", "pgeReports"]

for _d in [UPLOAD_DIR, PROCESSED_DIR, FAILED_DIR, LOG_DIR, TEMP_DIR]:
    os.makedirs(_d, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"pipeline_{datetime.now():%Y%m%d}.log")


# ── Logging ───────────────────────────────────────────────────────────────
def log(msg, level="INFO", error=False):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
            if error:
                f.write(traceback.format_exc() + "\n")
    except Exception:
        pass


# ── Email / PowerBI  ───────────────────────────────────────────
def send_email(subject, body, is_error=False):
    if not EMAIL_CONFIG["enabled"]:
        return
    try:
        m = MIMEMultipart()
        m["From"], m["To"] = EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["recipient_email"]
        m["Subject"] = f"SSU Energy Pipeline: {subject}"
        m.attach(MIMEText(body, "plain"))
        s = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"])
        s.starttls()
        s.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
        s.send_message(m); s.quit()
    except Exception as e:
        log(f"Email failed: {e}", "WARNING", error=True)


def refresh_powerbi():
    if not POWERBI_CONFIG["enabled"]:
        return True
    try:
        url = f"https://api.powerbi.com/v1.0/myorg/datasets/{POWERBI_CONFIG['dataset_id']}/refreshes"
        r = requests.post(url, headers={
            "Authorization": f"Bearer {POWERBI_CONFIG['access_token']}",
            "Content-Type": "application/json"})
        return r.status_code == 202
    except Exception as e:
        log(f"PowerBI error: {e}", "ERROR", error=True); return False


# ── FTP download  ────────────────────────────────
def download_from_ftp():
    stats = {"downloaded": 0, "errors": 0}
    try:
        ftp = FTP(FTP_CONFIG["host"])
        ftp.login(FTP_CONFIG["username"], FTP_CONFIG["password"])
        log("FTP connected", "SUCCESS")
        for folder in FTP_FOLDERS:
            ftp_dir   = f"{FTP_CONFIG['base_directory']}/{folder}"
            local_dir = os.path.join(UPLOAD_DIR, folder)
            os.makedirs(local_dir, exist_ok=True)
            try:
                ftp.cwd(ftp_dir)
                try: ftp.mkd("Backup")
                except Exception: pass
                for fname in ftp.nlst():
                    if not fname.endswith(".csv"):
                        continue
                    local_path = os.path.join(local_dir, fname)
                    with open(local_path, "wb") as fh:
                        ftp.retrbinary(f"RETR {fname}", fh.write)
                    stats["downloaded"] += 1
                    try: ftp.rename(fname, f"Backup/{fname}")
                    except Exception: pass
                ftp.cwd(FTP_CONFIG["base_directory"])
            except Exception as e:
                log(f"FTP folder {folder}: {e}", "ERROR", error=True)
                stats["errors"] += 1
        ftp.quit()
    except Exception as e:
        log(f"FTP connect: {e}", "ERROR", error=True)
        stats["errors"] += 1
    return stats


# ── DB helpers ────────────────────────────────────────────────────────────
def ensure_unique_indexes(conn):
    """
    Guarantee UNIQUE(timestamp, location, unit) on all three tables.
    INSERT IGNORE is only idempotent with these indexes in place.
    Safe to run every invocation — ALTER TABLE ADD UNIQUE IF NOT EXISTS
    via pre-check (MySQL 8 supports IF NOT EXISTS on CREATE, not ALTER).
    """
    cur = conn.cursor()
    for table in ("energy_usage", "gas_usage", "water_usage"):
        cur.execute(f"SHOW INDEX FROM {table} WHERE Key_name = 'uq_{table}'")
        if not cur.fetchone():
            cur.execute(
                f"ALTER TABLE {table} ADD UNIQUE KEY uq_{table} "
                "(timestamp, location, unit)"
            )
            log(f"Added UNIQUE index on {table}", "SUCCESS")
    conn.commit()
    cur.close()


def push_to_db(df_clean: pd.DataFrame) -> dict:
    """
    Insert a cleaned DataFrame (output of energy_core.process_csv) into
    the correct MySQL table. INSERT IGNORE dedupes on the unique key.
    """
    stats = {"energy": 0, "gas": 0, "water": 0, "errors": 0}
    if df_clean.empty:
        return stats
    conn = pymysql.connect(**DB_CONFIG)
    try:
        ensure_unique_indexes(conn)
        cur = conn.cursor()
        INSERT = "INSERT IGNORE INTO {} (timestamp, location, value, unit) VALUES (%s,%s,%s,%s)"
        for table_name in ("energy", "gas", "water"):
            subset = df_clean[df_clean["table"] == table_name]
            if subset.empty:
                continue
            rows = list(zip(
                subset["timestamp"], subset["location"],
                subset["value"],     subset["unit"],
            ))
            # Batch 1000 at a time
            sql = INSERT.format(f"{table_name}_usage")
            for i in range(0, len(rows), 1000):
                try:
                    cur.executemany(sql, rows[i:i+1000])
                    stats[table_name] += cur.rowcount
                except pymysql.MySQLError as e:
                    log(f"{table_name} batch error: {e}", "ERROR", error=True)
                    stats["errors"] += 1
        conn.commit()
        log(f"DB insert: energy={stats['energy']} gas={stats['gas']} water={stats['water']}")
    finally:
        conn.close()
    return stats


# ── Weekly CSV export ─────────────────────────────────────────────────────
def generate_weekly_csv(output_path=WEEKLY_CSV_PATH) -> bool:
    """
    Aggregate all three MySQL tables by ISO week (Monday start) + building
    and write weekly_energy.csv. Single source of truth for the dashboard.

    Columns:
      week            — Monday of ISO week (YYYY-MM-DD)
      building        — resolved building name
      kWh             — electricity + thermal (BTU/kBTU/MBTU/tonref) → kWh
      thermal_kWh     — subset of kWh that came from thermal sensors
                        (BTU/kBTU/MBTU/tonref). Electric portion = kWh - thermal_kWh.
      gas_therm       — natural gas, raw therms (NOT converted)
      water_gallon    — water, raw gallons
      heating_dd      — 0.0 (placeholder; degree_days table optional)
      normalized_kWh  — kWh / heating_dd if >0 else kWh
    """
    conn = pymysql.connect(**DB_CONFIG)
    try:
        def _week_query(table):
            return f"""
                SELECT
                    DATE_FORMAT(DATE_SUB(timestamp, INTERVAL WEEKDAY(timestamp) DAY),
                                '%Y-%m-%d') AS week,
                    location, unit, SUM(value) AS total
                FROM {table}
                GROUP BY week, location, unit
            """
        cur = conn.cursor()
        cur.execute(_week_query("energy_usage")); energy_rows = cur.fetchall()
        cur.execute(_week_query("gas_usage"));    gas_rows    = cur.fetchall()
        cur.execute(_week_query("water_usage"));  water_rows  = cur.fetchall()
        cur.close()

        def building_of(loc):
            pid = loc.split("p:sonomastate:r:")[-1].strip() if "p:sonomastate:r:" in str(loc) else None
            return POINT_ID_MAP[pid][0] if pid in POINT_ID_MAP else str(loc)

        kwh_agg, gas_agg, water_agg = defaultdict(float), defaultdict(float), defaultdict(float)
        # Thermal split: any energy-table row whose unit is NOT kWh is a thermal
        # loop (BTU/kBTU/MBTU/tonref → heating hot water or chilled water).
        # Sum these into a separate bucket so the dashboard can show the true
        # thermal vs electric breakdown without re-reading raw CSVs.
        thermal_kwh_agg = defaultdict(float)

        for week, loc, unit, total in energy_rows:
            kwh_contribution = float(total) * UNIT_TO_KWH.get(unit, 0.0 if unit not in ENERGY_UNITS else 1.0)
            bld = building_of(loc)
            kwh_agg[(week, bld)] += kwh_contribution
            if unit in THERMAL_UNITS:
                thermal_kwh_agg[(week, bld)] += kwh_contribution
        for week, loc, _, total in gas_rows:
            gas_agg[(week, building_of(loc))] += float(total)
        for week, loc, _, total in water_rows:
            water_agg[(week, building_of(loc))] += float(total)

        keys = sorted(set(kwh_agg) | set(gas_agg) | set(water_agg))
        rows = []
        for (week, bld) in keys:
            kwh = kwh_agg.get((week, bld), 0.0)
            rows.append({
                "week": week, "building": bld,
                "kWh":           round(kwh, 6),
                "thermal_kWh":   round(thermal_kwh_agg.get((week, bld), 0.0), 6),
                "gas_therm":     round(gas_agg.get((week, bld), 0.0), 6),
                "water_gallon":  round(water_agg.get((week, bld), 0.0), 6),
                "heating_dd":    0.0,
                "normalized_kWh": round(kwh, 6),
            })
        if not rows:
            log("No DB data — weekly_energy.csv not written", "WARNING")
            return False
        pd.DataFrame(rows).to_csv(output_path, index=False)
        log(f"weekly_energy.csv → {len(rows)} rows, {len(set(r['week'] for r in rows))} weeks")
        return True
    finally:
        conn.close()


# ── File management ───────────────────────────────────────────────────────
def move_to(dest_root, file_path, folder):
    subdir = os.path.join(dest_root, folder)
    os.makedirs(subdir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(file_path))
    dest = os.path.basename(file_path)
    i = 1
    while os.path.exists(os.path.join(subdir, dest)):
        dest = f"{base}_{i}{ext}"; i += 1
    shutil.move(file_path, os.path.join(subdir, dest))


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    start = datetime.now()
    log("=" * 70); log("SSU ENERGY PIPELINE STARTED")

    stats = {"downloaded": 0, "processed": 0, "skipped": 0, "inserted": 0, "errors": 0}

    # Phase 0 — DB sanity
    try:
        conn = pymysql.connect(**DB_CONFIG)
        ensure_unique_indexes(conn)
        conn.close()
    except Exception as e:
        log(f"DB connect failed: {e}", "ERROR", error=True)
        send_email("Pipeline FAILED — DB unreachable", str(e), is_error=True)
        sys.exit(1)

    # Phase 1 — FTP
    ftp = download_from_ftp()
    stats["downloaded"] = ftp["downloaded"]
    stats["errors"]    += ftp["errors"]
    if stats["downloaded"] == 0:
        log("No new files", "INFO")
        generate_weekly_csv()
        send_email("No new data", "FTP had no new files today")
        return

    # Phase 2 — clean + insert
    for folder in FTP_FOLDERS:
        folder_path = os.path.join(UPLOAD_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        for fname in [f for f in os.listdir(folder_path) if f.endswith(".csv")]:
            src = os.path.join(folder_path, fname)
            log(f"→ {fname}")
            cleaned, pstats = process_csv(src)
            if pstats["error"] or cleaned.empty:
                log(f"  skip: {pstats['error'] or 'no data'}", "WARNING")
                move_to(FAILED_DIR, src, folder)
                stats["skipped"] += 1
                continue
            db = push_to_db(cleaned)
            stats["processed"] += 1
            stats["inserted"]  += db["energy"] + db["gas"] + db["water"]
            stats["errors"]    += db["errors"]
            move_to(PROCESSED_DIR, src, folder)

    # Phase 3 — weekly export + PowerBI
    generate_weekly_csv()
    if stats["inserted"] > 0:
        refresh_powerbi()

    # Summary
    end = datetime.now()
    summary = (f"Status: {'OK' if stats['errors']==0 else 'WITH ERRORS'}\n"
               f"Duration: {(end-start).total_seconds():.1f}s\n"
               f"Downloaded: {stats['downloaded']}  Processed: {stats['processed']}  "
               f"Skipped: {stats['skipped']}\n"
               f"DB inserts: {stats['inserted']}  Errors: {stats['errors']}\n"
               f"Output: {WEEKLY_CSV_PATH}\n")
    log(summary)
    send_email(
        "Success" if stats["errors"] == 0 else "Completed with errors",
        summary, is_error=stats["errors"] > 0,
    )
    sys.exit(0 if stats["errors"] == 0 else 1)


if __name__ == "__main__":
    main()
