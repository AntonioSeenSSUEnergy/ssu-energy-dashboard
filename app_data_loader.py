"""
app_data_loader.py — Streamlit Cloud reads weekly_energy.csv from Hostinger.

Single source of truth lives on Hostinger Premium. The dashboard does NOT
re-clean raw CSVs at page load anymore — the cron-driven pipeline owns the
CSV, and the dashboard fetches it over HTTPS with a 5-minute cache.

If the remote CSV is unreachable (network blip, deploy in flight), the
dashboard shows a warning and falls back to whatever raw CSVs may still be
present locally — same behaviour as before, just much rarer.

Required Streamlit secret (Settings → Secrets):
    WEEKLY_CSV_URL = "https://faridfarahmand.net/data/weekly_energy.csv"
"""
from __future__ import annotations
import os
from collections import defaultdict

import pandas as pd
import streamlit as st

from energy_core import (
    POINT_ID_MAP, UNIT_TO_KWH, ENERGY_UNITS, VALID_UNITS,
    RAW_CSV_RE, process_csv, to_kwh,
)

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
WEEKLY_CSV_URL = st.secrets.get(
    "WEEKLY_CSV_URL",
    "https://faridfarahmand.net/data/weekly_energy.csv",
)
WEEKLY_COLS    = ["week", "building", "kWh", "thermal_kWh", "gas_therm",
                  "water_gallon", "heating_dd", "normalized_kWh"]


def _find_raw_csvs():
    """Local fallback only — used if the remote CSV is unreachable."""
    found = set()
    for d in (BASE_DIR, os.path.join(BASE_DIR, "raw_data"),
              os.path.join(BASE_DIR, "uploads")):
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if RAW_CSV_RE.match(fname):
                found.add(os.path.join(d, fname))
    return sorted(found)


def _backfill_from_raw(existing_weeks: set[str]) -> pd.DataFrame:
    """
    Last-resort cleaning if the remote CSV is unreachable AND raw files are
    available locally. In normal operation this returns an empty DataFrame.
    """
    files = _find_raw_csvs()
    if not files:
        return pd.DataFrame(columns=WEEKLY_COLS)
    agg = defaultdict(lambda: defaultdict(lambda: {"kWh": 0.0, "gas": 0.0, "water": 0.0}))
    for fp in files:
        cleaned, _ = process_csv(fp)
        if cleaned.empty:
            continue
        cleaned["_dt"]   = pd.to_datetime(cleaned["timestamp"])
        cleaned["_week"] = (cleaned["_dt"] - pd.to_timedelta(
            cleaned["_dt"].dt.weekday, unit="D")).dt.date.astype(str)
        for _, r in cleaned.iterrows():
            wk, bld = r["_week"], r["building"]
            if wk in existing_weeks:
                continue
            if r["table"] == "energy":
                agg[wk][bld]["kWh"] += to_kwh(r["value"], r["unit"])
            elif r["table"] == "gas":
                agg[wk][bld]["gas"] += r["value"]
            elif r["table"] == "water":
                agg[wk][bld]["water"] += r["value"]
    rows = []
    for wk in sorted(agg):
        for bld in sorted(agg[wk]):
            b = agg[wk][bld]
            rows.append({
                "week": wk, "building": bld,
                "kWh":            round(b["kWh"], 6),
                "thermal_kWh":    0.0,
                "gas_therm":      round(b["gas"], 6),
                "water_gallon":   round(b["water"], 6),
                "heating_dd":     0.0,
                "normalized_kWh": round(b["kWh"], 6),
            })
    return pd.DataFrame(rows, columns=WEEKLY_COLS)


@st.cache_data(ttl=300, show_spinner=False)
def load_weekly() -> pd.DataFrame:
    """
    Authoritative weekly DataFrame.

    Priority:
      1. weekly_energy.csv from Hostinger over HTTPS  — pipeline output
      2. Local raw-CSV backfill                       — only if URL unreachable
    """
    try:
        weekly = pd.read_csv(WEEKLY_CSV_URL)
        for c in WEEKLY_COLS:
            if c not in weekly.columns:
                weekly[c] = 0.0
        weekly = weekly[WEEKLY_COLS].copy()
    except Exception as e:
        st.warning(f"Remote CSV unreachable ({e}); falling back to local data.")
        weekly = pd.DataFrame(columns=WEEKLY_COLS)

    # Backfill only kicks in when the remote fetch failed entirely.
    if weekly.empty:
        backfill = _backfill_from_raw(set())
        weekly = backfill if not backfill.empty else weekly

    weekly = weekly[weekly["kWh"] >= 0].copy()
    return weekly
