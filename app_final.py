"""SSU Campus Energy Dashboard."""

import base64
import datetime
import glob
import os
import re
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Shared cleaning logic from energy_core
from energy_core import (
    POINT_ID_MAP,
    UNIT_TO_KWH,
    VALID_UNITS,
    ENERGY_UNITS,
    THERMAL_UNITS,
    RAW_CSV_RE,
    parse_cell,
    process_csv as _ec_process_csv,
    to_kwh,
)

# Logo loader
def _load_logo_b64() -> str:
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_header.png")
    try:
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except FileNotFoundError:
        return ""

_LOGO_B64_LB = _load_logo_b64()
_LOGO_B64_DI = _LOGO_B64_LB

def load_weekly() -> pd.DataFrame:
    """Fetch weekly_energy.csv from the Hostinger pipeline output."""
    import urllib.request, email.utils, io
    cols = ["week", "building", "kWh", "thermal_kWh", "gas_therm",
            "water_gallon", "heating_dd", "normalized_kWh"]
    try:
        url = st.secrets.get("WEEKLY_CSV_URL",
                             "https://faridfarahmand.net/data/weekly_energy.csv")
    except Exception:
        url = "https://faridfarahmand.net/data/weekly_energy.csv"
    df = None
    last_modified_dt = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ssu-dashboard"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_bytes = resp.read()
            lm_header = resp.headers.get("Last-Modified")
            if lm_header:
                try:
                    lm_utc = email.utils.parsedate_to_datetime(lm_header)
                    last_modified_dt = pd.Timestamp(lm_utc)
                except Exception:
                    last_modified_dt = None
        df = pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)
    except Exception as e:
        st.warning(f"Remote CSV unreachable ({e}); falling back to local copy.")
        base = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base, "weekly_energy.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, low_memory=False)

    if df is None or df.empty:
        return pd.DataFrame(columns=cols)

    # Normalise week column
    df["week"] = df["week"].astype(str).str.strip().str.split("/").str[0]
    df["week"] = pd.to_datetime(df["week"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["week"]).copy()
    for col in ["kWh", "thermal_kWh", "gas_therm", "water_gallon", "heating_dd", "normalized_kWh"]:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if last_modified_dt is not None:
        df.attrs["last_modified"] = last_modified_dt
    return df

st.set_page_config(
    page_title="SSU Campus Energy Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# STYLES
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"], p, label, button {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-size: 16px;
}
span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded):not(.material-icons),
div:not([data-testid="stIconMaterial"]) {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
[data-testid="stIconMaterial"],
span[data-testid="stIconMaterial"],
.material-symbols-rounded,
.material-icons {
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined',
                 'Material Icons', sans-serif !important;
    font-feature-settings: 'liga' 1 !important;
    -webkit-font-feature-settings: 'liga' 1 !important;
    font-variant-ligatures: normal !important;
    text-rendering: optimizeLegibility !important;
    visibility: visible !important;
    display: inline-block !important;
    width: auto !important;
    height: auto !important;
    opacity: 1 !important;
}

.stApp { background-color: #f4f6f8 !important; color: #111827 !important; }

.block-container {
    padding-top: 2.5rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    padding-bottom: 3rem !important;
    max-width: 100% !important;
}

section[data-testid="stSidebar"] { background-color: #1b3a5c !important; border-right: none !important; }
section[data-testid="stSidebar"] *:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded):not(.material-icons) {
    color: #c8d9ea !important;
    font-family: 'Inter', sans-serif !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color: #ffffff !important; font-weight: 700 !important; font-size: 1.1rem !important; }
section[data-testid="stSidebar"] .stRadio > label { color: #a3bcd0 !important; font-size: 1.0rem !important; font-weight: 700 !important; text-transform: uppercase !important; letter-spacing: 0.08em !important; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label { font-size: 1.05rem !important; font-weight: 500 !important; color: #c8d9ea !important; text-transform: none !important; letter-spacing: 0 !important; }
section[data-testid="stSidebar"] .stMultiSelect > label,
section[data-testid="stSidebar"] .stSelectbox > label { color: #a3bcd0 !important; font-size: 1.0rem !important; font-weight: 700 !important; text-transform: uppercase !important; letter-spacing: 0.08em !important; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.12) !important; }

/* Last 12 months / All time toggle — force visible dark text everywhere */
div[role="radiogroup"] label { color: #000000 !important; font-weight: 900 !important; font-size: 1.1rem !important; }
div[role="radiogroup"] label p { color: #000000 !important; font-weight: 900 !important; font-size: 1.1rem !important; }
div[role="radiogroup"] label span { color: #000000 !important; font-weight: 900 !important; }
div[role="radiogroup"] label div { color: #000000 !important; }
div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label,
div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label p,
div[data-testid="stHorizontalBlock"] div[role="radiogroup"] label span { color: #000000 !important; font-weight: 900 !important; font-size: 1.1rem !important; }

[data-testid="collapsedControl"] { background-color: #1b3a5c !important; border-right: 2px solid #2a5180 !important; }
[data-testid="collapsedControl"] button [data-testid="stIconMaterial"],
button[data-testid="baseButton-headerNoPadding"] [data-testid="stIconMaterial"] {
    color: #c8d9ea !important;
    font-size: 1.6rem !important;
}

h1 { font-family: 'Inter', sans-serif !important; font-size: 2.5rem !important; font-weight: 800 !important; color: #111827 !important; letter-spacing: -0.04em !important; line-height: 1.1 !important; margin-bottom: 2px !important; margin-top: 0 !important; }
h2, h3 { font-family: 'Inter', sans-serif !important; font-weight: 700 !important; color: #111827 !important; }

[data-testid="stMetric"] { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 12px !important; padding: 20px 22px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important; }
[data-testid="stMetricLabel"] p { font-size: 0.82rem !important; font-weight: 700 !important; color: #6b7280 !important; text-transform: uppercase !important; letter-spacing: 0.1em !important; margin-bottom: 4px !important; }
[data-testid="stMetricValue"] { font-size: 2.2rem !important; font-weight: 800 !important; color: #111827 !important; letter-spacing: -0.03em !important; line-height: 1.15 !important; }
[data-testid="stMetricDelta"] { font-size: 0.92rem !important; font-weight: 600 !important; }
[data-testid="stMetricDelta"] svg { display: none !important; }

.sec-label { font-family: 'Inter', sans-serif; font-size: 1.5rem; font-weight: 800; color: #111827; text-transform: none; letter-spacing: -0.01em; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; margin: 28px 0 16px 0; }

.rw-box { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 18px; text-align: right; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.rw-label { font-size: 0.72rem; font-weight: 700; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.1em; display: block; margin-bottom: 4px; }
.rw-value { font-size: 1.1rem; font-weight: 700; color: #111827; }

.card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.card-title { font-size: 1.1rem; font-weight: 700; color: #111827; margin-bottom: 4px; }
.card-sub { font-size: 0.88rem; color: #6b7280; margin-bottom: 14px; }

.topbld { margin-bottom: 14px; }
.topbld-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 5px; }
.topbld-name { font-size: 1.0rem; font-weight: 600; color: #111827; }
.topbld-val { font-size: 0.95rem; font-weight: 600; color: #6b7280; }
.topbld-track { background: #f1f5f9; border-radius: 3px; height: 8px; overflow: hidden; }
.topbld-fill { height: 100%; background: #1b3a5c; border-radius: 3px; }

.alert-red   { background: #fef2f2; border-left: 4px solid #dc2626; border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 0.95rem; color: #7f1d1d; font-weight: 500; margin-bottom: 12px; }
.alert-amber { background: #fffbeb; border-left: 4px solid #f59e0b; border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 0.95rem; color: #78350f; font-weight: 500; margin-bottom: 12px; }
.alert-blue  { background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 0.95rem; color: #1e40af; font-weight: 500; margin-bottom: 12px; }
.alert-green { background: #f0fdf4; border-left: 4px solid #16a34a; border-radius: 0 8px 8px 0; padding: 12px 16px; font-size: 0.95rem; color: #166534; font-weight: 500; margin-bottom: 12px; }

.lb-row { display: flex; align-items: center; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 18px; margin-bottom: 8px; gap: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.lb-rank { font-size: 1.5rem; font-weight: 800; color: #1b3a5c; min-width: 46px; text-align: center; line-height: 1; flex-shrink: 0; }
.lb-rank.gold   { color: #b45309; }
.lb-rank.silver { color: #64748b; }
.lb-rank.bronze { color: #92400e; }
.lb-name { font-size: 1.1rem; font-weight: 700; color: #111827; }
.lb-sub { font-size: 0.9rem; color: #6b7280; margin-top: 4px; line-height: 1.5; }
.lb-pct { font-size: 1.8rem; font-weight: 800; text-align: right; line-height: 1.1; min-width: 90px; flex-shrink: 0; letter-spacing: -0.03em; }
.lb-pct-lbl { font-size: 0.72rem; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.08em; text-align: right; }
.streak { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px; padding: 3px 10px; font-size: 0.85rem; color: #c2410c; font-weight: 700; white-space: nowrap; flex-shrink: 0; }

.goal-box { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 22px 24px; margin-top: 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.goal-lbl { font-size: 0.78rem; font-weight: 700; color: #9ca3af; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
.goal-status { font-size: 1.4rem; font-weight: 800; margin-bottom: 14px; line-height: 1.25; letter-spacing: -0.02em; }
.prog-bg { background: #e5e7eb; border-radius: 6px; height: 12px; overflow: hidden; margin-bottom: 8px; }
.prog-fill { height: 100%; border-radius: 6px; }

.di-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
.di-table th { background: #f1f5f9; color: #374151; font-weight: 700; padding: 11px 14px; text-align: left; border-bottom: 2px solid #e2e8f0; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; }
.di-table td { padding: 10px 14px; border-bottom: 1px solid #f1f5f9; color: #111827; vertical-align: middle; }
.di-table tr:hover td { background: #f8fafc; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 700; }
.badge-ok     { background: #dcfce7; color: #166534; }
.badge-open   { background: #fee2e2; color: #991b1b; }
.badge-review { background: #fef3c7; color: #92400e; }
.badge-skip   { background: #f1f5f9; color: #6b7280; }
.badge-raw    { background: #dbeafe; color: #1e40af; }

div[data-testid="column"] { padding: 0 6px !important; }

@media (max-width: 768px) {
    h1 { font-size: 1.6rem !important; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
    .lb-row { flex-wrap: wrap; gap: 8px; }
    .lb-pct { font-size: 1.3rem !important; }
}
</style>
""", unsafe_allow_html=True)


# PIPELINE CLEANING LOGIC

def _process_one_csv(filepath: str) -> dict:
    """Wrapper over energy_core.process_csv."""
    cleaned, _stats = _ec_process_csv(filepath)
    if cleaned.empty:
        return {}

    cleaned = cleaned.copy()
    cleaned["_date"] = pd.to_datetime(cleaned["timestamp"], errors="coerce").dt.date.astype(str)
    cleaned = cleaned[cleaned["_date"] != "NaT"]
    if cleaned.empty:
        return {}

    acc: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for _, row in cleaned.iterrows():
        d        = row["_date"]
        bld      = row["building"]
        unit     = row["unit"]
        val      = float(row["value"])
        tbl      = row["table"]
        if tbl == "energy":
            kwh = to_kwh(val, unit)
            acc[d][bld]["kWh"] += kwh
            if unit in THERMAL_UNITS:
                acc[d][bld]["thermal_kWh"] += kwh
        elif tbl == "gas":
            acc[d][bld]["therm"] += val
        elif tbl == "water":
            acc[d][bld]["gallon"] += val

    return {d: dict(bmap) for d, bmap in acc.items()}


def _find_raw_csv_files() -> list[str]:
    """Scan for raw CSV files matching the YYYYMMDD pattern."""
    base = os.path.dirname(os.path.abspath(__file__))
    search_roots = [
        base,
        os.path.join(base, "raw_data"),
        os.path.join(base, "uploads"),
        os.path.join(base, "processed"),
    ]
    found_by_name: dict = {}
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fname in files:
                if RAW_CSV_RE.match(fname) and fname not in found_by_name:
                    found_by_name[fname] = os.path.join(dirpath, fname)
    return sorted(found_by_name.values())


@st.cache_data(ttl=300, show_spinner=False)
def _process_raw_csvs() -> tuple[pd.DataFrame, set]:
    """Process all discovered raw CSV files."""
    files = _find_raw_csv_files()
    if not files:
        return pd.DataFrame(columns=["date", "building", "kWh", "thermal_kWh",
                                     "gas_therm", "water_gallon"]), set()

    merged: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for fp in files:
        result = _process_one_csv(fp)
        for date_str, bmap in result.items():
            for building, ubuckets in bmap.items():
                for bucket, val in ubuckets.items():
                    merged[date_str][building][bucket] += val

    rows = []
    for date_str in sorted(merged):
        for building in sorted(merged[date_str]):
            ub = merged[date_str][building]
            rows.append({
                "date":         date_str,
                "building":     building,
                "kWh":          round(ub.get("kWh", 0.0), 6),
                "thermal_kWh":  round(ub.get("thermal_kWh", 0.0), 6),
                "gas_therm":    round(ub.get("therm", 0.0), 6),
                "water_gallon": round(ub.get("gallon", 0.0), 6),
            })

    df = pd.DataFrame(rows)
    raw_dates = set(df["date"].unique()) if not df.empty else set()
    return df, raw_dates


@st.cache_data(ttl=300, show_spinner=False)
def load_daily_data() -> pd.DataFrame:
    """Build the authoritative daily DataFrame."""
    DAILY_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_energy.csv")

    raw_df, raw_dates = _process_raw_csvs()

    hist_rows = []
    if os.path.exists(DAILY_CSV):
        hist = pd.read_csv(DAILY_CSV)
        for col in ("gas_therm", "water_gallon", "thermal_kWh"):
            if col not in hist.columns:
                hist[col] = 0.0
        hist["date"] = hist["date"].astype(str).str.strip()
        hist_filtered = hist[~hist["date"].isin(raw_dates)].copy()
        hist_rows = hist_filtered[["date", "building", "kWh", "thermal_kWh",
                                    "gas_therm", "water_gallon"]].to_dict("records")

    combined_rows = hist_rows
    if not raw_df.empty:
        combined_rows += raw_df[["date", "building", "kWh", "thermal_kWh",
                                  "gas_therm", "water_gallon"]].to_dict("records")

    if not combined_rows:
        return pd.DataFrame(columns=["date", "building", "kWh", "thermal_kWh",
                                      "gas_therm", "water_gallon"]), raw_dates

    daily = pd.DataFrame(combined_rows)
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    daily = daily.dropna(subset=["date"]).copy()
    daily["date"] = daily["date"].dt.normalize()
    daily = (
        daily.groupby(["date", "building"])
        .agg(kWh=("kWh", "sum"),
             thermal_kWh=("thermal_kWh", "sum"),
             gas_therm=("gas_therm", "sum"),
             water_gallon=("water_gallon", "sum"))
        .reset_index()
    )
    daily = daily[daily["kWh"] >= 0].copy()
    return daily, raw_dates


@st.cache_data(ttl=300, show_spinner=False)
def load_data() -> pd.DataFrame:
    """Read weekly_energy.csv directly."""
    weekly = load_weekly()
    if weekly.empty:
        return pd.DataFrame(columns=["week", "building", "kWh", "thermal_kWh",
                                     "gas_therm", "water_gallon",
                                     "heating_dd", "normalized_kWh"]), set()
    _saved_attrs = dict(weekly.attrs)
    if pd.api.types.is_datetime64_any_dtype(weekly["week"]):
        weekly = weekly.copy()
        weekly["week"] = weekly["week"].dt.date.astype(str)
    weekly = weekly[weekly["kWh"] > 0].copy()
    weekly.attrs.update(_saved_attrs)
    return weekly, set()


# CONSTANTS
PLOT_BG   = "#ffffff"
PLOT_GRID = "#f1f5f9"
PLOT_TEXT = "#111827"
C_NAVY    = "#1b3a5c"
C_GREEN   = "#16a34a"
C_RED     = "#dc2626"
C_AMBER   = "#d97706"
C_MUTED   = "#6b7280"
C_SLATE   = "#64748b"

BUILDINGS_STATUS = {
    "Green Music Center":          "ok",
    "Nichols Hall":                "ok",
    "Rachel Carson Hall":          "ok",
    "Wine Spectator Learning Ctr": "review",
    "Student Center":              "ok",
    "Physical Education":          "ok",
    "Ives Hall":                   "ok",
    "Campus Misc":                 "ok",
}

SENSOR_REGISTRY = [
    ("Green Music Center",          "234ab131-e413ba29", "Electric", "kWh",   "OK",      "Active — primary electric meter, ~85 kWh per reading"),
    ("Green Music Center",          "1f98265e-39835c84", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop"),
    ("Green Music Center",          "234aa956-82d369b2", "Thermal",  "kBTU",  "OK",      "Active — heating hot water loop (BMS labels as _MBTU, pipeline remaps to kBTU)"),
    ("Green Music Center",          "234aab84-c656a0e0", "Gas",      "therm", "Missing", "No data received"),
    ("Green Music Center",          "234aa782-f7b1eef2", "Water",    "gallon","Missing", "No data received"),
    ("Nichols Hall",                "234e3ee2-f6fcea18", "Thermal",  "BTU",   "OK",      "Active — heating hot water loop, ~20,000 kWh/day"),
    ("Nichols Hall",                "234e3ee2-b06b6c8c", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop, reporting zero"),
    ("Nichols Hall",                "234e40da-635bc7c1", "Electric", "kWh",   "OK",      "Active — reporting zero, meter may be offline"),
    ("Physical Education",          "206db469-c986212b", "Electric", "kWh",   "OK",      "Active — consistent readings, ~11 kWh per reading"),
    ("Rachel Carson Hall",          "1f98265e-cbf77175", "Electric", "kWh",   "Missing", "No data received"),
    ("Rachel Carson Hall",          "234aa121-a983880d", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop, minor daily gaps"),
    ("Rachel Carson Hall",          "234aa43b-a73abf5e", "Thermal",  "BTU",   "OK",      "Active — heating hot water loop, reporting zero"),
    ("Ives Hall",                   "234e3195-7d72fbdc", "Thermal",  "BTU",   "OK",      "Active — heating hot water loop, 950–1,243 kWh/day"),
    ("Ives Hall",                   "234e3195-c20a1a8e", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop, reporting zero"),
    ("Ives Hall",                   "206d9425-f3361ab6", "Electric", "kWh",   "OK",      "Active — reporting zero, meter may be offline"),
    ("Student Center",              "234e5dff-8d8eb031", "Thermal",  "BTU",   "OK",      "Active — heating hot water loop, variable output"),
    ("Student Center",              "234e5dff-6fe20abd", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop"),
    ("Student Center",              "20c9aa07-acd1558a", "Electric", "kWh",   "OK",      "Active — reporting zero, meter may be offline"),
    ("Wine Spectator Learning Ctr", "250ea73e-3b55a6cf", "Electric", "kWh",   "Review",  "Only ~25% of expected readings received — kWh may be understated"),
    ("Art Building",                "1f97c82e-36e60525", "Thermal",  "BTU",   "Missing", "No data received"),
    ("Art Building",                "1f97c82e-d1a92673", "Thermal",  "BTU",   "Missing", "No data received"),
    ("Boiler Plant",                "234a6e2b-318cf13d", "Gas",      "therm", "Missing", "No data received"),
    ("Darwin Hall",                 "267e6fd0-93d67a62", "Electric", "kWh",   "Missing", "No data received"),
    ("ETC",                         "1f97c82e-dd011464", "Electric", "kWh",   "Missing", "No data received"),
    ("Salazar Hall",                "20c9b2e1-d7263cf1", "Electric", "kWh",   "Missing", "No data received"),
    ("Salazar Hall",                "234e4c64-930d1fd6", "Electric", "kWh",   "Missing", "No data received"),
    ("Salazar Hall",                "20c9b4d5-5ea6aa0b", "Thermal",  "BTU",   "Missing", "No data received"),
    ("Schulz Info Center",          "1f97c82e-c34c4f2e", "Electric", "kWh",   "Missing", "No data received"),
    ("Schulz Info Center",          "1f97c82e-525ca261", "Thermal",  "BTU",   "Missing", "No data received"),
    ("Schulz Info Center",          "206e94b8-3b05cb50", "Gas",      "therm", "Missing", "No data received"),
    ("Stevenson Hall",              "251810ce-f429b841", "Electric", "kWh",   "Missing", "No data received"),
    ("Stevenson Hall",              "267fcb62-ed42e3b3", "Thermal",  "BTU",   "Missing", "No data received"),
    ("Student Health Center",       "234e61c5-021da430", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop, reporting zero"),
    ("Student Health Center",       "234e61c5-83f6cf71", "Thermal",  "BTU",   "OK",      "Active — chilled water cooling loop, reporting zero"),
    ("Campus Misc",                 "214981c7-dd0b1593", "Electric", "kWh",   "PGE",     "PG&E utility account meter"),
    ("Campus Misc",                 "214981c7-5530731e", "Electric", "kWh",   "PGE",     "PG&E utility account meter"),
    ("Campus Misc",                 "214981c7-63077e46", "Electric", "kWh",   "PGE",     "PG&E utility account meter"),
]


# Map utility-type to the row's contribution
def _row_contribution(row, utility: str) -> float:
    """Return how much of `utility` a single df_all row carries."""
    if utility == "Electric":
        # Total kWh minus thermal portion = electric kWh
        kwh   = float(row.get("kWh") or 0)
        thrm  = float(row.get("thermal_kWh") or 0)
        return max(0.0, kwh - thrm)
    if utility == "Thermal":
        return float(row.get("thermal_kWh") or 0)
    if utility == "Gas":
        return float(row.get("gas_therm") or 0)
    if utility == "Water":
        return float(row.get("water_gallon") or 0)
    return 0.0


def compute_sensor_statuses(df_all: pd.DataFrame, recent_weeks: int = 4):
    """Derive Status and Notes for each sensor from df_all."""
    out: dict[str, tuple[str, str]] = {}
    if df_all is None or df_all.empty:
        for bld, sid, util, unit, status, notes in SENSOR_REGISTRY:
            out[sid] = (status, notes)
        return out

    df_dates = df_all.dropna(subset=["_wstart"]).copy()
    if df_dates.empty:
        for bld, sid, util, unit, status, notes in SENSOR_REGISTRY:
            out[sid] = (status, notes)
        return out
    latest_week = df_dates["_wstart"].max()
    recent_cut  = latest_week - pd.Timedelta(weeks=recent_weeks)

    by_bld_all     = df_dates.groupby("building")
    df_recent      = df_dates[df_dates["_wstart"] > recent_cut]
    by_bld_recent  = df_recent.groupby("building")

    def _bld_utility_total(grouper, bld: str, util: str) -> tuple[float, pd.Timestamp | None]:
        """Total contribution and last-seen week for this (building, utility)."""
        if bld not in grouper.groups:
            return 0.0, None
        rows = grouper.get_group(bld)
        contribs = rows.apply(lambda r: _row_contribution(r, util), axis=1)
        nonzero  = rows[contribs > 0]
        total    = float(contribs.sum())
        last_seen = nonzero["_wstart"].max() if not nonzero.empty else None
        return total, last_seen

    for bld, sid, util, unit, orig_status, orig_notes in SENSOR_REGISTRY:
        # PG&E utility-account meters: preserve identity
        if orig_status == "PGE":
            recent_total, _ = _bld_utility_total(by_bld_recent, bld, util)
            if recent_total > 0:
                note = (f"PG&E utility-account meter — actively contributing "
                        f"to the campus electric total")
            else:
                note = ("PG&E utility-account meter — no recent activity "
                        "(check account status)")
            out[sid] = ("PGE", note)
            continue

        all_total, last_seen   = _bld_utility_total(by_bld_all,    bld, util)
        recent_total, _        = _bld_utility_total(by_bld_recent, bld, util)

        if recent_total > 0:
            note = f"Active — last reading {last_seen.strftime('%b %d, %Y')}"
            out[sid] = ("OK", note)
        elif all_total > 0:
            weeks_since = max(0, int((latest_week - last_seen).days // 7)) if last_seen else None
            since_str = (f" ({weeks_since} weeks ago)"
                         if weeks_since and weeks_since > 0 else "")
            note = (f"No recent data — last seen "
                    f"{last_seen.strftime('%b %d, %Y') if last_seen else 'unknown'}"
                    f"{since_str}. Meter may be offline.")
            out[sid] = ("Review", note)
        else:
            note = "No data received — sensor not contributing to weekly CSV"
            out[sid] = ("Missing", note)

    return out


# HELPERS
def plot_base(height=300):
    return dict(
        paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, sans-serif", color=PLOT_TEXT, size=18, weight=700),
        margin=dict(l=8, r=60, t=36, b=8),
        height=height,
        xaxis=dict(
            gridcolor=PLOT_GRID, zerolinecolor="#e2e8f0", linecolor="#e2e8f0",
            tickfont=dict(size=16, family="Inter", color=PLOT_TEXT, weight=700),
            title_font=dict(size=16, family="Inter", color=PLOT_TEXT, weight=700),
        ),
        yaxis=dict(
            gridcolor=PLOT_GRID, zerolinecolor="#e2e8f0", linecolor="#e2e8f0",
            tickfont=dict(size=16, family="Inter", color="#111827", weight=700),
            title_font=dict(size=16, family="Inter", color="#111827", weight=700),
        ),
    )


def week_label(w, cap_at=None):
    """Convert '2026-02-02' to 'Feb 2 – Feb 8, 2026'."""
    try:
        start = pd.to_datetime(str(w).split("/")[0].strip())
        end   = start + pd.Timedelta(days=6)
        if cap_at is not None:
            cap_ts = pd.to_datetime(cap_at) if not isinstance(cap_at, pd.Timestamp) else cap_at
            if cap_ts < end and cap_ts >= start:
                end = cap_ts
        ss = start.strftime("%b ") + start.strftime("%d").lstrip("0")
        es = end.strftime("%b ")   + end.strftime("%d").lstrip("0")
        return f"{ss} – {es}, {end.year}"
    except Exception:
        return str(w)


def fmt_kwh(v):
    if v >= 1_000_000: return f"{v/1_000_000:.2f} GWh"
    if v >= 1_000:     return f"{v/1000:.1f} MWh"
    return f"{v:,.0f} kWh"


def fmt_cost(v):
    return f"${abs(v):,.0f}"


def fmt_power(kwh: float, days: float) -> str:
    """Average power in kW or MW."""
    if days is None or days <= 0:
        return "—"
    kw = kwh / (days * 24.0)
    if kw >= 1000:
        return f"{kw/1000:.2f} MW"
    return f"{kw:,.1f} kW"


def fmt_co2(kwh: float, factor: float) -> str:
    """CO2 in kg and metric tons."""
    kg = kwh * factor
    tons = kg / 1000.0
    return f"{kg:,.0f} kg ({tons:,.0f} t)"


def render_kpis(items, columns=None):
    """Render a row of stat cards."""
    n = len(items)
    if n == 0:
        return
    cols = columns if columns is not None else n
    cards_html = []
    for it in items:
        note_html = ""
        if it.get("note"):
            note_html = (f'<div style="margin-top:4px;font-size:14px;'
                         f'color:#6b7280;font-weight:500;font-family:Inter,sans-serif;">'
                         f'{it["note"]}</div>')
        cards_html.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;'
            f'border-radius:16px;padding:20px 22px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
            f'<div style="font-size:13px;color:#6b7280;font-weight:800;'
            f'text-transform:uppercase;letter-spacing:0.08em;'
            f'font-family:Inter,sans-serif;">{it["label"]}</div>'
            f'<div style="margin-top:8px;font-size:36px;font-weight:800;'
            f'color:#0f172a;letter-spacing:-0.03em;line-height:1.15;'
            f'font-family:Inter,sans-serif;">{it["value"]}</div>'
            f'{note_html}'
            f'</div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({cols},1fr);'
        f'gap:14px;margin-top:16px;margin-bottom:16px;">'
        + "".join(cards_html) +
        '</div>',
        unsafe_allow_html=True)


def days_in_period(weeks: list, time_filter: str, df_scope: pd.DataFrame = None) -> float:
    """Total exposure-days for a list of period keys."""
    n = len(weeks) if weeks else 0
    if n == 0:
        return 0.0
    if time_filter == "Weekly":
        return n * 7.0

    # Monthly / Yearly: prefer actual data span when df_scope is supplied
    if df_scope is not None and not df_scope.empty and "_wstart" in df_scope.columns:
        d = df_scope.dropna(subset=["_wstart"]).copy()
        if time_filter == "Monthly":
            d["_p"] = d["_wstart"].dt.to_period("M").astype(str)
        elif time_filter == "Yearly":
            d["_p"] = d["_wstart"].dt.year.astype(str)
        else:
            d["_p"] = None
        d = d[d["_p"].isin([str(w) for w in weeks])]
        if not d.empty:
            return float((d["_wstart"].max() - d["_wstart"].min()).days + 7)

    # Calendar-based fallback
    if time_filter == "Monthly":
        total = 0.0
        for w in weeks:
            try:
                total += pd.Period(str(w), freq="M").days_in_month
            except Exception:
                total += 30.0
        return total
    if time_filter == "Yearly":
        total = 0.0
        for w in weeks:
            try:
                yr = int(str(w))
                total += 366.0 if (yr % 4 == 0 and (yr % 100 != 0 or yr % 400 == 0)) else 365.0
            except Exception:
                total += 365.0
        return total
    return n * 7.0


def badge_html(status):
    cls = {"OK": "badge-ok", "Missing": "badge-open", "Review": "badge-review",
           "PGE": "badge-skip", "Raw CSV": "badge-raw"}.get(status, "badge-skip")
    label = "Missing Data" if status == "Missing" else status
    return f'<span class="badge {cls}">{label}</span>'


# LOAD DATA
_load_result = load_data()
if isinstance(_load_result, tuple):
    df_all, _raw_dates_loaded = _load_result
else:
    df_all, _raw_dates_loaded = _load_result, set()

if df_all.empty:
    st.error("No energy data found. Place weekly_energy.csv and/or raw CSV files "
             "(YYYYMMDD.csv / YYYYMMDDint.csv) in the same folder as app.py.")
    st.stop()

all_weeks = sorted(df_all["week"].unique())

_daily_result = load_daily_data()
_daily_df = _daily_result[0] if isinstance(_daily_result, tuple) else _daily_result
_raw_dates_loaded = _daily_result[1] if isinstance(_daily_result, tuple) else set()

# Thermal kWh resolution: prefer weekly_energy.csv, fall back to raw CSV
if not _daily_df.empty and "thermal_kWh" in _daily_df.columns:
    _wk = _daily_df.copy()
    _wk["week"] = (_wk["date"] - pd.to_timedelta(_wk["date"].dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    _th_by_wk_bld = (
        _wk.groupby(["week", "building"])["thermal_kWh"].sum()
        .reset_index()
        .rename(columns={"thermal_kWh": "_thermal_kWh_raw"})
    )
    df_all = df_all.merge(_th_by_wk_bld, on=["week", "building"], how="left")
    df_all["_thermal_kWh_raw"] = df_all["_thermal_kWh_raw"].fillna(0.0)
    df_all["thermal_kWh"] = df_all[["thermal_kWh", "_thermal_kWh_raw"]].max(axis=1)
    df_all = df_all.drop(columns=["_thermal_kWh_raw"])
    # Clamp: thermal_kWh must never exceed total kWh
    df_all["thermal_kWh"] = df_all[["thermal_kWh", "kWh"]].min(axis=1)

def _week_has_raw(w):
    try:
        start = pd.to_datetime(str(w))
        dates = [(start + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        return any(d in _raw_dates_loaded for d in dates)
    except Exception:
        return False

_raw_weeks = {w for w in all_weeks if _week_has_raw(w)}
_n_raw_files = len(_find_raw_csv_files())


# SIDEBAR
with st.sidebar:
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    st.markdown("""
<style>
/* SELECTBOX — fill the whole inner control red, white text, no nested pill.
   Simple & reliable: avoids fighting BaseWeb's flex layout so text never
   disappears and the colored "box" the user requested is always visible. */
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
    background-color: #dc2626 !important;
    border: 1px solid #dc2626 !important;
    border-radius: 6px !important;
}
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] *,
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] input {
    color: #ffffff !important;
    background-color: transparent !important;
}
/* Chevron arrow — white on the red */
section[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
}
/* MULTISELECT outer — subtle dark border */
section[data-testid="stSidebar"] .stMultiSelect > div > div[data-baseweb="select"] {
    border: 1px solid #2a5180 !important;
    border-radius: 6px !important;
}
section[data-testid="stSidebar"] .stMultiSelect > div > div[data-baseweb="select"] > div {
    color: #ffffff !important;
}
/* MULTISELECT pills — filled red with white text */
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
    background-color: #dc2626 !important;
    border-color: #dc2626 !important;
}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] span {
    color: #ffffff !important;
}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] svg {
    color: #ffffff !important;
    fill: #ffffff !important;
}
/* Sidebar headings */
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] .sidebar-title {
    color: #4dabf7 !important;
    font-size: 1.25rem !important;
    font-weight: 800 !important;
}
</style>
""", unsafe_allow_html=True)

    st.markdown('<p style="color:#4dabf7;font-size:1.25rem;font-weight:800;margin-bottom:4px;">Section</p>', unsafe_allow_html=True)
    _role_preview = st.session_state.get("_role_radio", "Student (Gamified)")
    if _role_preview == "Student (Gamified)":
        nav_opts_preview = ["📊 Electricity", "🔥 Thermal", "🏆 Leaderboard", "🔍 Data Integrity"]
    else:
        nav_opts_preview = ["📊 Electricity", "🔥 Thermal", "🔍 Data Integrity"]
    _tab = st.radio("nav", nav_opts_preview, label_visibility="collapsed")
    active_tab = ("Overview" if "Electricity" in _tab else
                  "Leaderboard" if "Leaderboard" in _tab else
                  "Thermal" if "Thermal" in _tab else "DataIntegrity")
    st.markdown("---")

    # TIME RANGE
    st.markdown('<p style="color:#4dabf7;font-size:1.25rem;font-weight:800;margin-bottom:4px;">Time Range</p>', unsafe_allow_html=True)
    time_filter = st.radio("time", ["Weekly", "Monthly", "Yearly"],
                           horizontal=True, label_visibility="collapsed")

    df_all["_wstart"] = pd.to_datetime(df_all["week"], errors="coerce")

    _latest_week_default = all_weeks[-1] if all_weeks else None

    if time_filter == "Weekly":
        avail_w = list(reversed(all_weeks))
        st.markdown('<p style="color:#c8d9ea;font-size:1.0rem;font-weight:700;margin-bottom:2px;">Select up to 4 weeks</p>', unsafe_allow_html=True)
        _default_weeks = [_latest_week_default] if _latest_week_default else []
        selected_weeks = st.multiselect(
            "weeks", avail_w, default=_default_weeks,
            format_func=week_label, label_visibility="collapsed")
        df_view      = df_all.copy()
        _cap_lm = df_all.attrs.get("last_modified")
        if _cap_lm is not None:
            _wk_label_cap = pd.Timestamp(_cap_lm.date())
        else:
            _wk_label_cap = pd.Timestamp(datetime.datetime.now().date())
        period_label = lambda w: week_label(w, cap_at=_wk_label_cap)

    elif time_filter == "Monthly":
        df_all["_period"] = df_all["_wstart"].dt.to_period("M").astype(str)
        monthly = (df_all.groupby(["_period", "building"])
                   .agg(kWh=("kWh", "sum"),
                        thermal_kWh=("thermal_kWh", "sum"),
                        gas_therm=("gas_therm", "sum"),
                        water_gallon=("water_gallon", "sum"))
                   .reset_index().rename(columns={"_period": "week"}))
        all_periods = sorted(monthly["week"].unique(), reverse=True)
        def month_label(p):
            try:    return pd.to_datetime(p + "-01").strftime("%B %Y")
            except: return str(p)
        st.markdown('<p style="color:#c8d9ea;font-size:1.0rem;font-weight:700;margin-bottom:2px;">Select up to 4 months</p>', unsafe_allow_html=True)
        selected_weeks = st.multiselect(
            "months", all_periods, default=[],
            format_func=month_label, label_visibility="collapsed")
        df_view      = monthly
        period_label = month_label

    else:  # Yearly
        df_all["_period"] = df_all["_wstart"].dt.year.astype(str)
        yearly = (df_all.groupby(["_period", "building"])
                  .agg(kWh=("kWh", "sum"),
                       thermal_kWh=("thermal_kWh", "sum"),
                       gas_therm=("gas_therm", "sum"),
                       water_gallon=("water_gallon", "sum"))
                  .reset_index().rename(columns={"_period": "week"}))
        all_periods = sorted(yearly["week"].unique(), reverse=True)
        def year_label(p): return str(p)
        st.markdown('<p style="color:#c8d9ea;font-size:1.0rem;font-weight:700;margin-bottom:2px;">Select years</p>', unsafe_allow_html=True)
        selected_weeks = st.multiselect(
            "years", all_periods, default=[],
            format_func=year_label, label_visibility="collapsed")
        df_view      = yearly
        period_label = year_label

    st.markdown("---")

    # COST
    st.markdown('<p style="color:#4dabf7;font-size:1.25rem;font-weight:800;margin-bottom:4px;">Cost</p>', unsafe_allow_html=True)
    st.markdown('<p style="color:#a3bcd0;font-size:1.0rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:2px;">Estimated Cost Rate ($/kWh)</p>', unsafe_allow_html=True)
    COST_RATE_OPTIONS = {
        "$0.10 / kWh": 0.10,
        "$0.12 / kWh": 0.12,
        "$0.15 / kWh (default)": 0.15,
        "$0.18 / kWh": 0.18,
        "$0.20 / kWh": 0.20,
        "$0.25 / kWh": 0.25,
        "$0.30 / kWh": 0.30,
        "$0.35 / kWh": 0.35,
        "$0.40 / kWh": 0.40,
        "$0.45 / kWh": 0.45,
        "$0.50 / kWh": 0.50,
    }
    selected_rate_label = st.selectbox(
        "cost_rate", list(COST_RATE_OPTIONS.keys()),
        index=2, label_visibility="collapsed")
    ENERGY_RATE = COST_RATE_OPTIONS[selected_rate_label]
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#c8d9ea;margin-top:6px;margin-bottom:4px;">'
        f'All cost estimates use <b style="color:#ffffff">${ENERGY_RATE:.2f}/kWh</b></div>',
        unsafe_allow_html=True)

    # CO2 emission factor
    st.markdown(
        '<p style="color:#a3bcd0;font-size:1.0rem;font-weight:700;text-transform:uppercase;'
        'letter-spacing:0.06em;margin-top:14px;margin-bottom:2px;">CO₂ Emission Factor</p>',
        unsafe_allow_html=True)
    EMISSION_FACTOR = st.number_input(
        "CO₂ Emission Factor (kg CO₂ / kWh)",
        min_value=0.0, max_value=1.0, value=0.20, step=0.01,
        format="%.2f", label_visibility="collapsed", key="co2_emission_factor")
    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:600;color:#c8d9ea;margin-top:4px;line-height:1.6;">'
        f'kg CO₂ produced per kWh of energy. '
        f'<b style="color:#ffffff">{EMISSION_FACTOR:.2f}</b> means '
        f'{EMISSION_FACTOR:.2f} kg CO₂ per 1 kWh used.<br>'
        f'<span style="color:#7ab4d4">Formula: CO₂ = Energy (kWh) × Emission Factor</span>'
        f'</div>',
        unsafe_allow_html=True)
    st.markdown("---")

    # BUILDING DETAIL
    st.markdown('<p style="color:#4dabf7;font-size:1.25rem;font-weight:800;margin-bottom:4px;">Building Detail</p>', unsafe_allow_html=True)

    _sidebar_bld_options = []
    _sidebar_thermal_blds = set()
    if all_weeks:
        _th_by_bld_total      = df_all.groupby("building")["thermal_kWh"].sum()
        _sidebar_thermal_blds = set(_th_by_bld_total[_th_by_bld_total > 0].index.tolist())

        _scope_periods = list(selected_weeks) if selected_weeks else None
        _scope_df      = df_view.copy()
        if _scope_periods is not None:
            _scope_df = _scope_df[_scope_df["week"].isin(_scope_periods)]

        if active_tab == "Thermal":
            _bld_th_kwh = (_scope_df.groupby("building")["thermal_kWh"].sum()
                           .sort_values(ascending=False))
            _bld_th_kwh = _bld_th_kwh[_bld_th_kwh > 0]
            _sidebar_bld_options = _bld_th_kwh.index.tolist()
        else:
            _bld_kwh_scope = (_scope_df.groupby("building")["kWh"].sum()
                              .sort_values(ascending=False))
            _bld_kwh_scope = _bld_kwh_scope[_bld_kwh_scope > 0]
            _sidebar_bld_options = _bld_kwh_scope.index.tolist()

        if not _sidebar_bld_options:
            _all_bld_kwh = (df_all.groupby("building")["kWh"].sum()
                            .sort_values(ascending=False))
            _sidebar_bld_options = _all_bld_kwh[_all_bld_kwh > 0].index.tolist()

    def _bld_dropdown_label(b: str) -> str:
        if b in _sidebar_thermal_blds:
            return b
        return f"{b}  ·  (no thermal data)"

    if _sidebar_bld_options:
        _sidebar_sel_bld = st.selectbox(
            "sidebar_bld_detail",
            _sidebar_bld_options,
            index=0,
            format_func=_bld_dropdown_label,
            label_visibility="collapsed"
        )
        if active_tab != "Thermal":
            st.markdown(
                '<div style="font-size:1.05rem;font-weight:600;color:#c8d9ea;margin-top:6px;line-height:1.6;">'
                'Buildings marked <b style="color:#ffffff">"(no thermal data)"</b> '
                'have electric meters only — selecting them in the Thermal tab will '
                'show no thermal breakdown.'
                '</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-size:1.05rem;font-weight:600;color:#c8d9ea;margin-top:6px;line-height:1.6;">'
                'Showing only buildings with thermal sensor data in the selected period(s).'
                '</div>',
                unsafe_allow_html=True)
    else:
        _sidebar_sel_bld = None

    st.markdown("---")

    st.markdown('<p style="color:#4dabf7;font-size:1.25rem;font-weight:800;margin-bottom:4px;">View Mode</p>', unsafe_allow_html=True)
    role = st.radio("mode", ["Student (Gamified)", "Admin (Basic)"],
                    label_visibility="collapsed", key="_role_radio")
    if role == "Student (Gamified)":
        nav_opts = ["📊 Electricity", "🔥 Thermal", "🏆 Leaderboard", "🔍 Data Integrity"]
    else:
        nav_opts = ["📊 Electricity", "🔥 Thermal", "🔍 Data Integrity"]
    if _tab not in nav_opts:
        active_tab = "Overview"

    # Latest data display
    _last_mod = df_all.attrs.get("last_modified")
    if _last_mod is not None:
        _hour_padded = _last_mod.strftime("%I")
        _hour_clean  = _hour_padded.lstrip("0") or "0"
        _latest_day_display = (
            _last_mod.strftime("%B %d, %Y at ")
            + _hour_clean
            + _last_mod.strftime(":%M %p")
            + " UTC"
        )
        _latest_label = "Data refreshed:"
    elif all_weeks:
        _week_end       = pd.to_datetime(all_weeks[-1]) + pd.Timedelta(days=6)
        _today          = pd.Timestamp(datetime.datetime.now().date())
        _latest_actual  = min(_week_end, _today)
        _latest_day_display = _latest_actual.strftime("%B %d, %Y")
        _latest_label = "Latest data:"
    else:
        _latest_day_display = "—"
        _latest_label = "Latest data:"
    st.markdown(
        f'<div style="font-size:1.0rem;font-weight:600;color:#7ab4d4;line-height:1.9;">'
        f'{len(all_weeks)} week(s) in database<br>'
        f'{_latest_label} {_latest_day_display}</div>',
        unsafe_allow_html=True)


# SELECTION STATE
if selected_weeks:
    if len(selected_weeks) > 4:
        st.warning("Maximum 4 periods can be selected at once. Showing the most recent 4.")
        selected_weeks = sorted(selected_weeks)[-4:]

    sorted_sel       = sorted(selected_weeks)
    latest_week      = sorted_sel[-1]
    by_bld           = df_view.groupby(["week", "building"])["kWh"].sum().reset_index()
    campus_cur       = by_bld[by_bld["week"] == latest_week]["kWh"].sum()
    campus_cost      = campus_cur * ENERGY_RATE
    campus_total_sel = by_bld[by_bld["week"].isin(sorted_sel)]["kWh"].sum()
    campus_total_cost = campus_total_sel * ENERGY_RATE
    prev_week        = sorted_sel[-2] if len(sorted_sel) >= 2 else None
    campus_prev      = by_bld[by_bld["week"] == prev_week]["kWh"].sum() if prev_week else None
    pct_change       = ((campus_cur - campus_prev) / campus_prev * 100) if campus_prev else None
else:
    sorted_sel        = []
    latest_week       = None
    by_bld            = pd.DataFrame(columns=["week", "building", "kWh"])
    campus_total_sel  = 0.0
    campus_total_cost = 0.0
    prev_week         = None
    campus_prev       = None
    pct_change        = None


# OVERVIEW TAB
if active_tab == "Overview":

    st.image(
        "dashboard_header.png",
        use_container_width=True
    )

    
    # All-time campus energy chart
    _at = df_all.dropna(subset=["_wstart"]).copy()
    _at["_month"] = _at["_wstart"].dt.to_period("M")
    _at_monthly = (
        _at.groupby("_month")["kWh"].sum()
        .reset_index()
        .sort_values("_month")
    )
    # Per-month data completeness flag
    _bld_per_month = (
        _at[_at["kWh"] > 0]
        .groupby("_month")["building"].nunique()
        .reset_index(name="_n_bld")
    )
    _at_monthly = _at_monthly.merge(_bld_per_month, on="_month", how="left")
    _at_monthly["_n_bld"] = _at_monthly["_n_bld"].fillna(0).astype(int)
    _max_bld_seen          = int(_at_monthly["_n_bld"].max()) if not _at_monthly.empty else 0
    _bld_threshold         = max(1, int(_max_bld_seen * 0.7))
    _at_monthly["_partial"] = _at_monthly["_n_bld"] < _bld_threshold
    _at_monthly["_label"]   = _at_monthly["_month"].dt.strftime("%b %Y") + \
                              _at_monthly["_partial"].map({True: " *", False: ""})
    _at_monthly["_mwh"]   = _at_monthly["kWh"] / 1000
    _at_total_kwh  = float(_at_monthly["kWh"].sum())
    _at_total_cost = _at_total_kwh * ENERGY_RATE

    if not _at_monthly.empty:
        _first_month = _at_monthly["_month"].iloc[0].to_timestamp().strftime("%b %Y")
        _last_month_str = _at_monthly["_month"].iloc[-1].to_timestamp().strftime("%b %Y")
        _at_section_label = f"Campus Energy — {_first_month} to {_last_month_str}"
    else:
        _at_section_label = "Campus Energy — All Time"
    st.markdown(f'<div class="sec-label">{_at_section_label}</div>', unsafe_allow_html=True)

    if not _at.empty:
        _at_days_span = float((_at["_wstart"].max() - _at["_wstart"].min()).days + 7)
    else:
        _at_days_span = 0.0

    _co2_kg = _at_total_kwh * EMISSION_FACTOR
    _co2_t  = _co2_kg / 1000.0
    _at_mwh = _at_total_kwh / 1000.0
    render_kpis([
        {"label": "Total Energy Consumed",
         "value": fmt_kwh(_at_total_kwh),
         "note":  f"{_at_mwh:,.0f} MWh"},
        {"label": "Total Energy Cost",
         "value": (f"${_at_total_cost/1_000_000:.2f}M"
                   if _at_total_cost >= 1_000_000
                   else fmt_cost(_at_total_cost)),
         "note":  fmt_cost(_at_total_cost)},
        {"label": "Average Power",
         "value": fmt_power(_at_total_kwh, _at_days_span),
         "note":  "Energy per hour"},
        {"label": "CO₂ Emitted",
         "value": f"{_co2_t:,.0f} t",
         "note":  f"{_co2_kg:,.0f} kg"},
    ])
    st.markdown(
        '<p style="font-size:1.05rem;font-weight:700;color:#374151;margin-top:-4px;line-height:1.4;">'
        '<b>Avg Power:</b> energy per hour over the period (kWh ÷ total hours). '
        f'<b>CO₂:</b> kWh × {EMISSION_FACTOR:.2f} kg/kWh — adjustable in the sidebar.'
        '</p>',
        unsafe_allow_html=True)

    # Range toggle: last 12 months vs all time
    if len(_at_monthly) > 12:
        _range_choice = st.radio(
            "campus_energy_range",
            ["Last 12 months", "All time"],
            horizontal=True, index=0,
            key="campus_energy_range",
            label_visibility="collapsed")
        _at_monthly_view = _at_monthly.tail(12).copy() if _range_choice == "Last 12 months" else _at_monthly
    else:
        _at_monthly_view = _at_monthly

    y_at_max = _at_monthly_view["_mwh"].max() * 1.35 if not _at_monthly_view.empty else 1
    _n_months = len(_at_monthly_view)
    _bar_chart_height = max(380, min(560, 340 + _n_months * 6))
    _show_bar_text    = _n_months <= 12
    _tick_angle       = -45 if _n_months > 10 else 0
    _tick_size        = 14 if _n_months <= 10 else (12 if _n_months <= 18 else 10)
    fig_at = go.Figure(go.Bar(
        x=_at_monthly_view["_label"],
        y=_at_monthly_view["_mwh"],
        marker_color=C_NAVY,
        text=[f"{v:.1f}" for v in _at_monthly_view["_mwh"]] if _show_bar_text else None,
        textposition="outside" if _show_bar_text else "none",
        textfont=dict(size=14, color="#374151", family="Inter", weight=700),
        hovertemplate="<b>%{x}</b><br>%{y:.1f} MWh  ·  $%{customdata[0]:,.0f}"
                      "<br><span style='color:#9ca3af'>%{customdata[1]} buildings reporting</span>"
                      "<extra></extra>",
        customdata=list(zip(_at_monthly_view["kWh"] * ENERGY_RATE,
                            _at_monthly_view["_n_bld"])),
    ))
    fig_at.update_layout(
        **plot_base(height=_bar_chart_height),
        bargap=0.25, yaxis_title="MWh", xaxis_title="",
    )
    fig_at.update_xaxes(tickangle=_tick_angle, tickfont=dict(size=_tick_size, family="Inter", color=PLOT_TEXT, weight=700))
    fig_at.update_yaxes(range=[0, y_at_max], tickfont=dict(size=14, family="Inter", color=PLOT_TEXT, weight=700))
    st.plotly_chart(fig_at, use_container_width=True)

    # Footnote for partial months
    if _at_monthly_view["_partial"].any():
        _partial_labels_view = [
            lbl.replace(" *", "")
            for lbl, p in zip(_at_monthly_view["_label"], _at_monthly_view["_partial"]) if p
        ]
        st.markdown(
            f'<div style="font-size:0.85rem;color:#6b7280;margin-top:-6px;margin-bottom:14px;'
            f'font-family:Inter,sans-serif;line-height:1.5;">'
            f'<b style="color:#92400e;">*</b> &nbsp;Months marked with an asterisk have '
            f'fewer reporting buildings than typical and should be read as partial data, '
            f'not lower consumption. Affected: {", ".join(_partial_labels_view)}. '
            f'See the <b>Data Integrity</b> tab for the full coverage breakdown.'
            f'</div>',
            unsafe_allow_html=True)

    if not selected_weeks:
        st.markdown(
            '<div class="alert-blue" style="margin-top:4px;">'
            '👈  Select a time period from the sidebar to see detailed building breakdowns.</div>',
            unsafe_allow_html=True)

    else:
        missing_blds = [b for b, s in BUILDINGS_STATUS.items() if s not in ("ok", "review")]
        if missing_blds:
            st.markdown(
                f'<div class="alert-amber">⚠️ <b>Missing Data:</b> '
                f'{", ".join(sorted(missing_blds))} have no FTP sensor data. '
                f'See the Data Integrity tab for details.</div>',
                unsafe_allow_html=True)

        # Campus KPIs
        st.markdown('<div class="sec-label">Consumption During Selected Periods — All Buildings</div>', unsafe_allow_html=True)
        _sel_days = days_in_period(sorted_sel, time_filter, df_all)
        k1_label = (f"Energy During — {period_label(sorted_sel[0])}"
                    if len(sorted_sel) == 1
                    else f"Energy During — {len(sorted_sel)} Periods Combined")
        _sel_co2_kg = campus_total_sel * EMISSION_FACTOR
        _sel_co2_t  = _sel_co2_kg / 1000.0
        _sel_mwh    = campus_total_sel / 1000.0
        render_kpis([
            {"label": k1_label,
             "value": fmt_kwh(campus_total_sel),
             "note":  (f"{_sel_mwh:,.0f} MWh"
                       if campus_total_sel >= 1_000_000
                       else None)},
            {"label": f"Estimated Energy Cost (@ ${ENERGY_RATE}/kWh)",
             "value": (f"${campus_total_cost/1_000_000:.2f}M"
                       if campus_total_cost >= 1_000_000
                       else fmt_cost(campus_total_cost)),
             "note":  (fmt_cost(campus_total_cost)
                       if campus_total_cost >= 1_000_000
                       else None)},
            {"label": "Average Power",
             "value": fmt_power(campus_total_sel, _sel_days),
             "note":  "Energy per hour"},
            {"label": "CO₂ Emitted",
             "value": f"{_sel_co2_t:,.1f} t" if _sel_co2_t >= 1 else f"{_sel_co2_kg:,.0f} kg",
             "note":  (f"{_sel_co2_kg:,.0f} kg" if _sel_co2_t >= 1 else None)},
        ])

        # All Buildings chart
        max_periods = 4
        chart_weeks = sorted_sel[-max_periods:]
        n_periods   = len(chart_weeks)
        if n_periods == 1:
            chart_title = f"All Buildings — {period_label(chart_weeks[0])}"
        else:
            chart_title = "All Buildings"
        st.markdown(f'<div class="sec-label">{chart_title}</div>', unsafe_allow_html=True)

        if n_periods == 1:
            ldf = (by_bld[by_bld["week"] == chart_weeks[0]]
                   .sort_values("kWh", ascending=True).copy())
            ldf["disp"] = ldf["kWh"] / 1000
            fig_all = go.Figure(go.Bar(
                name=period_label(chart_weeks[0]),
                y=ldf["building"], x=ldf["disp"],
                orientation="h", marker_color=C_NAVY,
                text=[f"{v:.1f}" for v in ldf["disp"]],
                textposition="outside",
                textfont=dict(size=19, color="#111827", family="Inter", weight=700),
                hovertemplate="<b>%{y}</b><br>%{x:.1f} MWh<extra></extra>",
            ))
            fig_all.update_layout(
                **plot_base(height=max(340, len(ldf) * 68)),
                xaxis_title="MWh", yaxis_title="", showlegend=False)
            fig_all.update_yaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            fig_all.update_xaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            st.plotly_chart(fig_all, use_container_width=True)
        else:
            palette = [C_NAVY, "#3b82f6", "#6366f1", C_SLATE]
            all_blds = sorted(by_bld[by_bld["week"].isin(chart_weeks)]["building"].unique())
            latest_bld_kwh = (by_bld[by_bld["week"] == chart_weeks[-1]]
                              .set_index("building")["kWh"].reindex(all_blds).fillna(0))
            all_blds_sorted = latest_bld_kwh.sort_values(ascending=True).index.tolist()
            fig_all = go.Figure()
            for idx, wk in enumerate(chart_weeks):
                wk_data = (by_bld[by_bld["week"] == wk]
                           .set_index("building")["kWh"]
                           .reindex(all_blds_sorted).fillna(0) / 1000)
                fig_all.add_trace(go.Bar(
                    name=period_label(wk),
                    y=all_blds_sorted, x=wk_data.values,
                    orientation="h",
                    marker_color=palette[idx % len(palette)],
                    text=[f"{v:.1f}" if v > 0 else "" for v in wk_data.values],
                    textposition="outside",
                    textfont=dict(size=19, color="#111827", family="Inter", weight=700),
                    hovertemplate=f"<b>%{{y}}</b><br>{period_label(wk)}: %{{x:.1f}} MWh<extra></extra>",
                ))
            fig_all.update_layout(
                **plot_base(height=max(380, len(all_blds_sorted) * 82)),
                barmode="group", bargap=0.15, bargroupgap=0.05,
                xaxis_title="MWh", yaxis_title="", showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=16, family="Inter", color=PLOT_TEXT),
                    bgcolor="#ffffff", bordercolor="#e2e8f0", borderwidth=1),
            )
            fig_all.update_yaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            fig_all.update_xaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            st.plotly_chart(fig_all, use_container_width=True)

        # Building detail
        st.markdown('<div class="sec-label">Building Detail — Select a Building to View Details</div>', unsafe_allow_html=True)

        bld_kwh_all_sel = (by_bld[by_bld["week"].isin(sorted_sel)]
                           .groupby("building")["kWh"].sum()
                           .sort_values(ascending=False)
                           .reset_index())
        bld_order = bld_kwh_all_sel["building"].tolist()
        bld_kwh_lkp = (by_bld[by_bld["week"] == latest_week]
                       .set_index("building")["kWh"].to_dict())

        if not bld_order:
            st.info("No buildings available — no data in the selected period.")
            st.stop()

        _default_idx = 0
        if _sidebar_sel_bld and _sidebar_sel_bld in bld_order:
            _default_idx = bld_order.index(_sidebar_sel_bld)

        sel_bld = st.selectbox(
            "Select a building (sorted highest to lowest kWh)",
            bld_order, index=_default_idx,
            format_func=lambda b: b,
            label_visibility="collapsed")

        if BUILDINGS_STATUS.get(sel_bld, "ok") == "review":
            st.markdown(
                f'<div class="alert-amber">⚠️ <b>{sel_bld}</b> — '
                f'Only ~25% of expected daily 15-minute intervals received. '
                f'The kWh shown may be understated.</div>',
                unsafe_allow_html=True)

        b_cur  = (by_bld[(by_bld["building"] == sel_bld) &
                         (by_bld["week"].isin(sorted_sel))]["kWh"].sum())
        b_cost = b_cur * ENERGY_RATE
        _bld_short = "Wine Spectator LC" if sel_bld == "Wine Spectator Learning Ctr" else sel_bld

        bm1_label = (f"{_bld_short} — {period_label(sorted_sel[0])}"
                     if len(sorted_sel) == 1
                     else f"{_bld_short} — {len(sorted_sel)} Selected Periods")
        bm2_label = (f"Estimated Cost (@ ${ENERGY_RATE}/kWh)"
                     if len(sorted_sel) == 1
                     else f"Combined Cost of {len(sorted_sel)} Periods (@ ${ENERGY_RATE}/kWh)")
        _b_scope = df_all[df_all["building"] == sel_bld]
        _b_co2_kg = b_cur * EMISSION_FACTOR
        _b_co2_t  = _b_co2_kg / 1000.0
        _b_mwh    = b_cur / 1000.0
        render_kpis([
            {"label": bm1_label,
             "value": fmt_kwh(b_cur),
             "note":  (f"{_b_mwh:,.0f} MWh"
                       if b_cur >= 1_000_000 else None)},
            {"label": bm2_label,
             "value": (f"${b_cost/1_000_000:.2f}M"
                       if b_cost >= 1_000_000
                       else fmt_cost(b_cost)),
             "note":  (fmt_cost(b_cost)
                       if b_cost >= 1_000_000 else None)},
            {"label": "Average Power",
             "value": fmt_power(b_cur, days_in_period(sorted_sel, time_filter, _b_scope)),
             "note":  "Energy per hour"},
            {"label": "CO₂ Emitted",
             "value": (f"{_b_co2_t:,.1f} t" if _b_co2_t >= 1
                       else f"{_b_co2_kg:,.0f} kg"),
             "note":  (f"{_b_co2_kg:,.0f} kg" if _b_co2_t >= 1 else None)},
        ])

        st.markdown(
            f'<div style="font-size:1.25rem;font-weight:800;color:#111827;font-family:Inter,sans-serif;'
            f'margin-top:6px;margin-bottom:2px;">{sel_bld} — {time_filter} Trend</div>',
            unsafe_allow_html=True)

        bld_trend = (by_bld[
            (by_bld["building"] == sel_bld) &
            (by_bld["week"].isin(sorted_sel))
        ].sort_values("week").copy())
        if len(bld_trend) >= 1:
            bld_trend["label"] = bld_trend["week"].apply(period_label)
            bld_trend["disp"]  = bld_trend["kWh"] / 1000
            bld_trend["disp"] = bld_trend["disp"].clip(lower=0.0)
            fig_trend = go.Figure(go.Bar(
                x=bld_trend["label"], y=bld_trend["disp"],
                marker_color=C_NAVY,
                text=[f"{v:.1f} MWh" if v > 0 else "0" for v in bld_trend["disp"]],
                textposition="outside",
                textfont=dict(size=16, color=PLOT_TEXT, family="Inter", weight=700),
                hovertemplate="<b>%{x}</b><br>%{y:.1f} MWh<extra></extra>",
                showlegend=False,
                base=0,
            ))
            yt = bld_trend["disp"].max() * 1.3 if (not bld_trend.empty and bld_trend["disp"].max() > 0) else 1
            fig_trend.update_layout(**plot_base(height=280), bargap=0.45, yaxis_title="MWh")
            fig_trend.update_yaxes(range=[0, yt], tickfont=dict(size=16, family="Inter", weight=700))
            fig_trend.update_xaxes(tickfont=dict(size=16, family="Inter", color=PLOT_TEXT, weight=700))
            st.plotly_chart(fig_trend, use_container_width=True)

        # Total campus energy
        if len(sorted_sel) == 1:
            _campus_title = f"Total Campus Energy — {period_label(sorted_sel[0])}"
        else:
            _campus_title = "Total Campus Energy — All Selected Periods"
        st.markdown(f'<div class="sec-label">{_campus_title}</div>',
                    unsafe_allow_html=True)
        campus_by_week = (by_bld[by_bld["week"].isin(sorted_sel)]
                          .groupby("week")["kWh"].sum()
                          .reset_index().sort_values("week"))
        campus_by_week["label"] = campus_by_week["week"].apply(period_label)
        campus_by_week["disp"]  = campus_by_week["kWh"] / 1000
        fig_campus = go.Figure(go.Bar(
            x=campus_by_week["label"],
            y=campus_by_week["disp"],
            marker_color=C_NAVY,
            text=[f"{v:.1f} MWh" for v in campus_by_week["disp"]],
            textposition="outside",
            textfont=dict(size=16, color=PLOT_TEXT, family="Inter", weight=700),
            hovertemplate="<b>%{x}</b><br>%{y:.1f} MWh<br>$%{customdata:,.0f}<extra></extra>",
            customdata=campus_by_week["kWh"] * ENERGY_RATE,
        ))
        y_max = campus_by_week["disp"].max() * 1.3 if not campus_by_week.empty else 1
        fig_campus.update_layout(**plot_base(height=300), bargap=0.45, yaxis_title="MWh")
        fig_campus.update_yaxes(range=[0, y_max], tickfont=dict(size=16, family="Inter", weight=700))
        fig_campus.update_xaxes(tickfont=dict(size=16, family="Inter", color=PLOT_TEXT, weight=700))
        st.plotly_chart(fig_campus, use_container_width=True)


# LEADERBOARD TAB
elif active_tab == "Leaderboard":

    if not selected_weeks:
        st.title("Building Energy Leaderboard")
        st.markdown(
            '<div class="alert-blue" style="margin-top:8px;">'
            '👈  Select at least two periods from the sidebar to unlock leaderboard rankings.</div>',
            unsafe_allow_html=True)
        st.stop()

    st.markdown(
        f'<div style="width:100%;margin-bottom:24px;border-radius:12px;overflow:hidden;'
        f'box-shadow:0 4px 20px rgba(0,0,0,0.18);border:1px solid rgba(255,255,255,0.10);">'
        f'<img src="data:image/png;base64,{_LOGO_B64_LB}" '
        f'style="width:100%;height:auto;display:block;" '
        f'alt="SSU Campus Energy Dashboard"/>'
        f'</div>',
        unsafe_allow_html=True)
    hcol_l2, hcol_r2 = st.columns([3, 1])
    with hcol_l2:
        st.title("Building Energy Leaderboard")
        st.markdown(
            '<p style="font-size:1.05rem;color:#6b7280;margin-top:2px;line-height:1.5;">'
            'Ranked by <b style="color:#111827">% reduction</b> compared to the prior selected week.</p>',
            unsafe_allow_html=True)

    lb_latest = sorted_sel[-1]
    lb_prev   = sorted_sel[-2] if len(sorted_sel) >= 2 else None

    with hcol_r2:
        cmp_str = (f"{period_label(lb_prev)}  vs  {period_label(lb_latest)}"
                   if lb_prev else period_label(lb_latest))
        st.markdown(
            f'<div style="margin-top:32px"><div class="rw-box">'
            f'<span class="rw-label">Comparing</span>'
            f'<span class="rw-value">{cmp_str}</span>'
            f'</div></div>', unsafe_allow_html=True)

    if lb_prev is None:
        st.info("Select two or more weeks in the sidebar to unlock the leaderboard rankings.")
        st.stop()

    c_df = (by_bld[by_bld["week"] == lb_latest][["building", "kWh"]]
            .rename(columns={"kWh": "kWh_c"}))
    p_df = (by_bld[by_bld["week"] == lb_prev][["building", "kWh"]]
            .rename(columns={"kWh": "kWh_p"}))
    cmp  = pd.merge(c_df, p_df, on="building", how="outer").fillna(0)
    cmp  = cmp[(cmp["kWh_c"] > 0) | (cmp["kWh_p"] > 0)].copy()
    cmp["delta_kwh"]  = cmp["kWh_p"] - cmp["kWh_c"]
    cmp["delta_pct"]  = cmp.apply(
        lambda r: r["delta_kwh"] / r["kWh_p"] * 100 if r["kWh_p"] > 0 else 0.0, axis=1)
    cmp["cost_saved"] = cmp["delta_kwh"] * ENERGY_RATE

    all_pvt = (by_bld.pivot_table(index="week", columns="building",
                                   values="kWh", aggfunc="sum").fillna(0).sort_index())
    streak_map = {}
    for b in all_pvt.columns:
        s, k = all_pvt[b].values, 0
        for i in range(len(s) - 1, 0, -1):
            # Treat any 0 in the comparison pair as missing data
            if s[i] == 0 or s[i - 1] == 0:
                break
            if s[i] < s[i - 1]: k += 1
            else: break
        streak_map[b] = k
    cmp["streak"] = cmp["building"].map(streak_map).fillna(0).astype(int)

    lb = cmp.sort_values(["delta_pct", "delta_kwh"], ascending=[False, False]).reset_index(drop=True)

    tot_c    = float(cmp["kWh_c"].sum())
    tot_p    = float(cmp["kWh_p"].sum())
    tot_pct  = (tot_p - tot_c) / tot_p * 100 if tot_p > 0 else 0.0
    n_better = int((cmp["delta_pct"] > 0.5).sum())
    n_worse  = int((cmp["delta_pct"] < -0.5).sum())
    d_col    = C_GREEN if tot_pct >= 0 else C_RED

    st.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px;margin-top:8px;">'
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:7px 14px;font-size:0.92rem;color:#4b5563;font-weight:500;">'
        f'🏫 <b style="color:#111827">{len(lb)}</b> buildings ranked</div>'
        f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:7px 14px;font-size:0.92rem;color:#166534;font-weight:600;">'
        f'✅ {n_better} used less</div>'
        f'<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:7px 14px;font-size:0.92rem;color:#991b1b;font-weight:600;">'
        f'⚠️ {n_worse} used more</div>'
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:7px 14px;font-size:0.92rem;color:#4b5563;font-weight:500;">'
        f'Campus: <b style="color:{d_col}">{tot_pct:+.1f}%</b></div>'
        f'</div>', unsafe_allow_html=True)

    rank_cls  = ["gold", "silver", "bronze"]
    rows_html = ""
    for i, row in lb.iterrows():
        pct      = float(row["delta_pct"])
        kwh_abs  = abs(int(float(row["delta_kwh"])))
        saved    = pct > 0.5
        neutral  = abs(pct) <= 0.5
        bld      = str(row["building"])
        p_kwh    = fmt_kwh(float(row["kWh_p"]))
        c_kwh    = fmt_kwh(float(row["kWh_c"]))
        cost_abs = abs(float(row["cost_saved"]))

        if saved:
            pts_col  = C_GREEN;  pct_disp = f"+{pct:.1f}%"
            act_str  = f"{fmt_kwh(kwh_abs)} saved"
            cost_str = f"💰 {fmt_cost(cost_abs)} saved"
        elif neutral:
            pts_col  = C_MUTED;  pct_disp = "≈ 0%"
            act_str  = "No significant change";  cost_str = ""
        else:
            pts_col  = C_RED;    pct_disp = f"{pct:.1f}%"
            act_str  = f"{fmt_kwh(kwh_abs)} more used"
            cost_str = f"💸 {fmt_cost(cost_abs)} extra"

        rc  = rank_cls[i] if i < 3 else ""
        rd  = f"#{i + 1}"
        streak_tag = (f'<span class="streak">🔥 {int(row["streak"])}w streak</span>'
                      if row["streak"] > 0 else "")
        gap_tag = ""
        if BUILDINGS_STATUS.get(bld) == "review":
            gap_tag = ('<span style="font-size:0.72rem;font-weight:700;color:#92400e;'
                       'background:#fef3c7;border-radius:4px;padding:2px 7px;margin-left:7px;">'
                       'PARTIAL DATA</span>')

        rows_html += (
            '<div class="lb-row">'
            f'<div class="lb-rank {rc}">{rd}</div>'
            '<div style="flex:1;min-width:0">'
            f'<div class="lb-name">{bld}{gap_tag}</div>'
            '<div class="lb-sub">'
            f'<span style="color:{pts_col};font-weight:700">{act_str}</span>'
            + (f'  ·  {cost_str}' if cost_str else '') +
            f'<br><span style="color:#9ca3af;font-size:0.82rem">'
            f'{period_label(lb_prev)}: {p_kwh} → {period_label(lb_latest)}: {c_kwh}</span>'
            '</div></div>'
            + streak_tag +
            f'<div style="text-align:right;min-width:88px">'
            f'<div class="lb-pct" style="color:{pts_col}">{pct_disp}</div>'
            f'<div class="lb-pct-lbl">% change</div>'
            f'</div></div>'
        )
    st.markdown(rows_html, unsafe_allow_html=True)

    st.markdown('<div class="sec-label">Highlights</div>', unsafe_allow_html=True)
    saved_df  = lb[lb["delta_pct"] > 0.5]
    wasted_df = lb[lb["delta_pct"] < -0.5]
    streak_df = lb[lb["streak"] > 0].sort_values("streak", ascending=False)

    hc1, hc2, hc3 = st.columns(3)
    if not saved_df.empty:
        t = saved_df.iloc[0]
        hc1.metric("🥇 Best Reduction", t["building"],
                   f"{float(t['delta_pct']):.1f}%  ·  {fmt_kwh(int(float(t['delta_kwh'])))} saved")
    else:
        hc1.metric("🥇 Best Reduction", "—", "No reductions this period")

    if not wasted_df.empty:
        w = wasted_df.iloc[-1]
        hc2.metric("⚠️ Highest Increase", w["building"],
                   f"{abs(float(w['delta_pct'])):.1f}%  ·  {fmt_cost(abs(float(w['cost_saved'])))} extra")
    else:
        hc2.metric("⚠️ Highest Increase", "—", "All buildings improved 🎉")

    if not streak_df.empty:
        s = streak_df.iloc[0]
        hc3.metric("🔥 Longest Streak", s["building"],
                   f"{int(s['streak'])} week{'s' if s['streak'] != 1 else ''} of reductions")
    else:
        hc3.metric("🔥 Longest Streak", "—", "Reduce 2+ weeks in a row to earn one")

    st.markdown('<div class="sec-label">Campus Goal — 5% Weekly Reduction</div>',
                unsafe_allow_html=True)
    GOAL     = 5.0
    progress = min(max(-tot_pct / GOAL * 100, 0.0), 100.0) if tot_pct < 0 else min(tot_pct / GOAL * 100, 100.0)
    achieved = tot_pct >= GOAL
    bar_col  = C_GREEN if achieved else C_AMBER
    txt_col  = "#166534" if achieved else "#92400e"

    if achieved:
        status = f"🎉 Goal achieved! Campus used {tot_pct:.1f}% less this period."
    elif tot_pct > 0:
        status = f"Reduced by {tot_pct:.1f}% — {GOAL - tot_pct:.1f}% more to hit the {GOAL:.0f}% target."
    else:
        status = f"Campus energy up {abs(tot_pct):.1f}% — need to cut {GOAL + abs(tot_pct):.1f}% to reach {GOAL:.0f}%."

    st.markdown(f"""
<div class="goal-box">
  <div class="goal-lbl">Weekly Campus Target — {GOAL:.0f}% Reduction</div>
  <div class="goal-status" style="color:{txt_col}">{status}</div>
  <div class="prog-bg"><div class="prog-fill" style="width:{progress:.1f}%;background:{bar_col}"></div></div>
  <div style="display:flex;justify-content:space-between;font-size:0.88rem;color:{C_MUTED};margin-top:6px;font-weight:500;">
    <span>{progress:.0f}% of goal reached</span>
    <span>Campus change: {tot_pct:+.1f}%  ·  Target: -{GOAL:.0f}%</span>
  </div>
</div>""", unsafe_allow_html=True)



# THERMAL TAB
elif active_tab == "Thermal":

    st.title("🔥 Thermal Energy Usage")
    st.markdown(
        '<p style="font-size:1.05rem;color:#6b7280;margin-top:2px;line-height:1.5;">'
        'Thermal energy (BTU/kBTU meters converted to kWh) as a proportion of total campus electricity. '
        'Thermal includes heating hot water and chilled water cooling loops.</p>',
        unsafe_allow_html=True)

    # Buildings with at least one active thermal sensor
    _thermal_buildings = set()
    _dyn_st_for_th = compute_sensor_statuses(df_all)
    for _b, _sid, _util, _unit, _orig_st, _orig_notes in SENSOR_REGISTRY:
        if _util == "Thermal":
            _live_st, _ = _dyn_st_for_th.get(_sid, (_orig_st, _orig_notes))
            if _live_st == "OK":
                _thermal_buildings.add(_b)

    # All-time monthly thermal data
    _th_at = df_all.dropna(subset=["_wstart"]).copy()
    _th_at["_month"] = _th_at["_wstart"].dt.to_period("M")

    _th_all_monthly = _th_at.groupby("_month").agg(
        total_kWh=("kWh", "sum"),
        thermal_kWh=("thermal_kWh", "sum"),
    ).reset_index().sort_values("_month")

    _th_all_monthly["_label"] = _th_all_monthly["_month"].dt.strftime("%b %Y")
    _th_merged = _th_all_monthly.copy()
    _th_merged["electric_kWh"] = (_th_merged["total_kWh"] - _th_merged["thermal_kWh"]).clip(lower=0)
    _th_merged["thermal_pct"] = (_th_merged["thermal_kWh"] / _th_merged["total_kWh"].replace(0, float("nan")) * 100).fillna(0)

    _th_total_kwh   = float(_th_merged["total_kWh"].sum())
    _th_thermal_kwh = float(_th_merged["thermal_kWh"].sum())
    _th_electric_kwh = float(_th_merged["electric_kWh"].sum())
    _th_avg_pct = (_th_thermal_kwh / _th_total_kwh * 100) if _th_total_kwh > 0 else 0.0
    _th_total_cost   = _th_total_kwh * ENERGY_RATE
    _th_thermal_cost = _th_thermal_kwh * ENERGY_RATE

    st.markdown('<div class="sec-label">All-Time Thermal Overview</div>', unsafe_allow_html=True)
    _th_total_mwh   = _th_total_kwh   / 1000.0
    _th_thermal_mwh = _th_thermal_kwh / 1000.0
    render_kpis([
        {"label": "Total Campus kWh (All Time)",
         "value": fmt_kwh(_th_total_kwh),
         "note":  (f"{_th_total_mwh:,.0f} MWh"
                   if _th_total_kwh >= 1_000_000 else None)},
        {"label": "Thermal Portion (kWh equiv)",
         "value": fmt_kwh(_th_thermal_kwh),
         "note":  (f"{_th_thermal_mwh:,.0f} MWh"
                   if _th_thermal_kwh >= 1_000_000 else None)},
        {"label": "Avg Thermal Share",
         "value": f"{_th_avg_pct:.1f}%",
         "note":  "Heating + cooling vs total"},
    ], columns=3)

    # Stacked bar chart: thermal vs non-thermal by month
    st.markdown('<div class="sec-label">Monthly Energy Split — Thermal vs Electric</div>', unsafe_allow_html=True)
    if len(_th_merged) > 12:
        _th_range_choice = st.radio(
            "thermal_split_range",
            ["Last 12 months", "All time"],
            horizontal=True, index=0,
            key="thermal_split_range",
            label_visibility="collapsed")
        _th_merged_view = _th_merged.tail(12).copy() if _th_range_choice == "Last 12 months" else _th_merged
    else:
        _th_merged_view = _th_merged

    _n_th_months = len(_th_merged_view)
    _th_chart_height = max(380, min(560, 340 + _n_th_months * 6))
    _th_tick_angle   = -45 if _n_th_months > 10 else 0
    _th_tick_size    = 14 if _n_th_months <= 10 else (12 if _n_th_months <= 18 else 10)
    fig_th_stack = go.Figure()
    fig_th_stack.add_trace(go.Bar(
        name="Electric (kWh meters)",
        x=_th_merged_view["_label"],
        y=_th_merged_view["electric_kWh"] / 1000,
        marker_color=C_NAVY,
        hovertemplate="<b>%{x}</b><br>Electric: %{y:.1f} MWh<extra></extra>",
    ))
    fig_th_stack.add_trace(go.Bar(
        name="Thermal (BTU/kBTU → kWh)",
        x=_th_merged_view["_label"],
        y=_th_merged_view["thermal_kWh"] / 1000,
        marker_color="#ec4899",
        hovertemplate="<b>%{x}</b><br>Thermal: %{y:.1f} MWh<extra></extra>",
    ))
    fig_th_stack.update_layout(
        **plot_base(height=_th_chart_height),
        barmode="stack", bargap=0.25, yaxis_title="MWh",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=14, family="Inter", color="#111827"),
                    bgcolor="#ffffff", bordercolor="#e2e8f0", borderwidth=1),
    )
    fig_th_stack.update_xaxes(tickangle=_th_tick_angle, tickfont=dict(size=_th_tick_size, family="Inter", color=PLOT_TEXT, weight=700))
    fig_th_stack.update_yaxes(tickfont=dict(size=14, family="Inter", color=PLOT_TEXT, weight=700))
    st.plotly_chart(fig_th_stack, use_container_width=True)

    # All Buildings: Thermal Energy
    if selected_weeks:
        _th_max_periods = 4
        _th_chart_weeks = sorted_sel[-_th_max_periods:]
        _th_n_periods   = len(_th_chart_weeks)
        if _th_n_periods == 1:
            _th_chart_title = f"All Buildings — Thermal Energy — {period_label(_th_chart_weeks[0])}"
        else:
            _th_chart_title = "All Buildings — Thermal Energy"
        st.markdown(f'<div class="sec-label">{_th_chart_title}</div>', unsafe_allow_html=True)

        _th_by_bld = (df_view[df_view["week"].isin(_th_chart_weeks)]
                      .groupby(["week", "building"])["thermal_kWh"].sum()
                      .reset_index())

        if _th_by_bld["thermal_kWh"].sum() == 0:
            st.info("No thermal sensor data available for the selected period(s).")
        elif _th_n_periods == 1:
            _ldf = (_th_by_bld[_th_by_bld["week"] == _th_chart_weeks[0]]
                    .sort_values("thermal_kWh", ascending=True).copy())
            _ldf = _ldf[_ldf["thermal_kWh"] > 0]
            _ldf["disp"] = _ldf["thermal_kWh"] / 1000
            fig_th_all = go.Figure(go.Bar(
                name=period_label(_th_chart_weeks[0]),
                y=_ldf["building"], x=_ldf["disp"],
                orientation="h", marker_color="#ec4899",
                text=[f"{v:.1f}" for v in _ldf["disp"]],
                textposition="outside",
                textfont=dict(size=19, color="#111827", family="Inter", weight=700),
                hovertemplate="<b>%{y}</b><br>%{x:.1f} MWh Thermal<extra></extra>",
            ))
            fig_th_all.update_layout(
                **plot_base(height=max(340, len(_ldf) * 68)),
                xaxis_title="MWh", yaxis_title="", showlegend=False)
            fig_th_all.update_yaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            fig_th_all.update_xaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            st.plotly_chart(fig_th_all, use_container_width=True)
        else:
            _th_palette = ["#ec4899", "#3b82f6", "#6366f1", C_SLATE]
            _th_all_blds = (_th_by_bld.groupby("building")["thermal_kWh"].sum()
                            .loc[lambda s: s > 0].index.tolist())
            _th_latest_kwh = (_th_by_bld[_th_by_bld["week"] == _th_chart_weeks[-1]]
                              .set_index("building")["thermal_kWh"]
                              .reindex(_th_all_blds).fillna(0))
            _th_blds_sorted = _th_latest_kwh.sort_values(ascending=True).index.tolist()
            fig_th_all = go.Figure()
            for _idx, _wk in enumerate(_th_chart_weeks):
                _wk_data = (_th_by_bld[_th_by_bld["week"] == _wk]
                            .set_index("building")["thermal_kWh"]
                            .reindex(_th_blds_sorted).fillna(0) / 1000)
                fig_th_all.add_trace(go.Bar(
                    name=period_label(_wk),
                    y=_th_blds_sorted, x=_wk_data.values,
                    orientation="h",
                    marker_color=_th_palette[_idx % len(_th_palette)],
                    text=[f"{v:.1f}" if v > 0 else "" for v in _wk_data.values],
                    textposition="outside",
                    textfont=dict(size=19, color="#111827", family="Inter", weight=700),
                    hovertemplate=f"<b>%{{y}}</b><br>{period_label(_wk)}: %{{x:.1f}} MWh Thermal<extra></extra>",
                ))
            fig_th_all.update_layout(
                **plot_base(height=max(380, len(_th_blds_sorted) * 82)),
                barmode="group", bargap=0.15, bargroupgap=0.05,
                xaxis_title="MWh", yaxis_title="", showlegend=True,
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1,
                    font=dict(size=16, family="Inter", color=PLOT_TEXT),
                    bgcolor="#ffffff", bordercolor="#e2e8f0", borderwidth=1),
            )
            fig_th_all.update_yaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            fig_th_all.update_xaxes(tickfont=dict(size=17, color="#111827", family="Inter", weight=700))
            st.plotly_chart(fig_th_all, use_container_width=True)
    else:
        st.markdown('<div class="sec-label">All Buildings — Thermal Energy</div>', unsafe_allow_html=True)
        st.info("👈 Select a time period from the sidebar to see thermal energy by building.")

    # Building-level thermal breakdown
    if selected_weeks:
        st.markdown('<div class="sec-label">Thermal Breakdown — Select a Building to View Details</div>', unsafe_allow_html=True)

        _th_sel = df_view[df_view["week"].isin(sorted_sel)].copy()
        _th_bld_kwh = (_th_sel.groupby("building")["thermal_kWh"].sum()
                       .sort_values(ascending=False)
                       .reset_index())
        _th_bld_kwh = _th_bld_kwh[_th_bld_kwh["thermal_kWh"] > 0]
        _th_bld_order = _th_bld_kwh["building"].tolist()

        if not _th_bld_order:
            st.info("No thermal sensor data available for the selected period(s).")
        else:
            _PICKER_KEY  = "thermal_bld_picker"
            _LAST_SB_KEY = "_th_last_sidebar_bld"

            # Sync sidebar to in-page picker
            _prev_sidebar = st.session_state.get(_LAST_SB_KEY)
            if _prev_sidebar != _sidebar_sel_bld:
                if _sidebar_sel_bld in _th_bld_order:
                    st.session_state[_PICKER_KEY] = _sidebar_sel_bld
                st.session_state[_LAST_SB_KEY] = _sidebar_sel_bld

            # Drop stale picker value
            if _PICKER_KEY in st.session_state and st.session_state[_PICKER_KEY] not in _th_bld_order:
                del st.session_state[_PICKER_KEY]

            # Default value
            if _PICKER_KEY not in st.session_state:
                st.session_state[_PICKER_KEY] = (
                    _sidebar_sel_bld if _sidebar_sel_bld in _th_bld_order
                    else _th_bld_order[0]
                )

            _th_sel_bld = st.selectbox(
                "Select a building (sorted highest to lowest thermal kWh)",
                _th_bld_order,
                key=_PICKER_KEY,
                format_func=lambda b: b,
                label_visibility="collapsed")

            _b_th_cur = float(_th_sel[(_th_sel["building"] == _th_sel_bld)]["thermal_kWh"].sum())
            _b_th_cost = _b_th_cur * ENERGY_RATE
            _bld_short_th = "Wine Spectator LC" if _th_sel_bld == "Wine Spectator Learning Ctr" else _th_sel_bld

            _tbm1_label = (f"{_bld_short_th} — {period_label(sorted_sel[0])} (Thermal)"
                           if len(sorted_sel) == 1
                           else f"{_bld_short_th} — {len(sorted_sel)} Selected Periods (Thermal)")
            _tbm2_label = (f"Estimated Thermal Cost (@ ${ENERGY_RATE}/kWh)"
                           if len(sorted_sel) == 1
                           else f"Combined Thermal Cost of {len(sorted_sel)} Periods (@ ${ENERGY_RATE}/kWh)")
            _th_b_scope = df_all[df_all["building"] == _th_sel_bld]
            _bth_co2_kg = _b_th_cur * EMISSION_FACTOR
            _bth_co2_t  = _bth_co2_kg / 1000.0
            _bth_mwh    = _b_th_cur / 1000.0
            render_kpis([
                {"label": _tbm1_label,
                 "value": fmt_kwh(_b_th_cur),
                 "note":  (f"{_bth_mwh:,.0f} MWh"
                           if _b_th_cur >= 1_000_000 else None)},
                {"label": _tbm2_label,
                 "value": (f"${_b_th_cost/1_000_000:.2f}M"
                           if _b_th_cost >= 1_000_000
                           else fmt_cost(_b_th_cost)),
                 "note":  (fmt_cost(_b_th_cost)
                           if _b_th_cost >= 1_000_000 else None)},
                {"label": "Average Thermal Power",
                 "value": fmt_power(_b_th_cur, days_in_period(sorted_sel, time_filter, _th_b_scope)),
                 "note":  "Energy per hour"},
                {"label": "CO₂ Emitted",
                 "value": (f"{_bth_co2_t:,.1f} t" if _bth_co2_t >= 1
                           else f"{_bth_co2_kg:,.0f} kg"),
                 "note":  (f"{_bth_co2_kg:,.0f} kg" if _bth_co2_t >= 1 else None)},
            ])

            st.markdown(
                f'<div style="font-size:1.25rem;font-weight:800;color:#111827;font-family:Inter,sans-serif;'
                f'margin-top:6px;margin-bottom:2px;">{_th_sel_bld} — {time_filter} Thermal Trend</div>',
                unsafe_allow_html=True)

            _bld_th_trend = (_th_sel[_th_sel["building"] == _th_sel_bld]
                             .groupby("week")["thermal_kWh"].sum()
                             .reset_index().sort_values("week"))
            if len(_bld_th_trend) >= 1:
                _bld_th_trend["label"] = _bld_th_trend["week"].apply(period_label)
                _bld_th_trend["disp"]  = (_bld_th_trend["thermal_kWh"] / 1000).clip(lower=0.0)
                _fig_bld_th = go.Figure(go.Bar(
                    x=_bld_th_trend["label"], y=_bld_th_trend["disp"],
                    marker_color="#ec4899",
                    text=[f"{v:.1f} MWh" if v > 0 else "0" for v in _bld_th_trend["disp"]],
                    textposition="outside",
                    textfont=dict(size=16, color=PLOT_TEXT, family="Inter", weight=700),
                    hovertemplate="<b>%{x}</b><br>%{y:.1f} MWh Thermal<extra></extra>",
                    showlegend=False,
                    base=0,
                ))
                _yt_th = _bld_th_trend["disp"].max() * 1.3 if (not _bld_th_trend.empty and _bld_th_trend["disp"].max() > 0) else 1
                _fig_bld_th.update_layout(**plot_base(height=280), bargap=0.45, yaxis_title="MWh (Thermal)")
                _fig_bld_th.update_yaxes(range=[0, _yt_th], tickfont=dict(size=16, family="Inter", weight=700))
                _fig_bld_th.update_xaxes(tickfont=dict(size=16, family="Inter", color=PLOT_TEXT, weight=700))
                st.plotly_chart(_fig_bld_th, use_container_width=True)

        # Total Campus Thermals
        _th_campus_week = (
            _th_sel.groupby("week")["thermal_kWh"].sum()
            .reset_index().rename(columns={"thermal_kWh": "kWh"})
            .sort_values("week")
        )
        if not _th_campus_week.empty:
            if len(sorted_sel) == 1:
                _th_campus_title = f"Total Campus Thermals — {period_label(sorted_sel[0])}"
            else:
                _th_campus_title = "Total Campus Thermals — All Selected Periods"
            st.markdown(f'<div class="sec-label">{_th_campus_title}</div>', unsafe_allow_html=True)
            _th_campus_week["label"] = _th_campus_week["week"].apply(period_label)
            _th_campus_week["disp"]  = (_th_campus_week["kWh"] / 1000).clip(lower=0.0)
            fig_th_trend = go.Figure(go.Bar(
                x=_th_campus_week["label"],
                y=_th_campus_week["disp"],
                marker_color="#ec4899",
                text=[f"{v:.1f} MWh" if v > 0 else "0" for v in _th_campus_week["disp"]],
                textposition="outside",
                textfont=dict(size=14, color=PLOT_TEXT, family="Inter", weight=700),
                hovertemplate="<b>%{x}</b><br>%{y:.1f} MWh Thermal<extra></extra>",
                base=0,
            ))
            _th_yt = _th_campus_week["disp"].max() * 1.3 if _th_campus_week["disp"].max() > 0 else 1
            fig_th_trend.update_layout(**plot_base(height=280), bargap=0.45, yaxis_title="MWh (Thermal)")
            fig_th_trend.update_yaxes(range=[0, _th_yt])
            st.plotly_chart(fig_th_trend, use_container_width=True)

    st.markdown(
        '<div style="font-size:1.05rem;font-weight:700;color:#374151;margin-top:12px;">'
        'Thermal readings include BTU and kBTU sensors (heating hot water &amp; chilled water loops) '
        'converted to kWh using pipeline constants: BTU × 0.000293071, kBTU × 0.293071. '
        'All underlying numbers are identical to the Overview page.'
        '</div>', unsafe_allow_html=True)


# DATA INTEGRITY TAB
elif active_tab == "DataIntegrity":

    st.markdown(
        f'<div style="width:100%;margin-bottom:24px;border-radius:12px;overflow:hidden;'
        f'box-shadow:0 4px 20px rgba(0,0,0,0.18);border:1px solid rgba(255,255,255,0.10);">'
        f'<img src="data:image/png;base64,{_LOGO_B64_DI}" '
        f'style="width:100%;height:auto;display:block;" '
        f'alt="SSU Campus Energy Dashboard"/>'
        f'</div>',
        unsafe_allow_html=True)
    st.title("Data Integrity Report")
    st.markdown(
        '<p style="font-size:1.05rem;color:#6b7280;margin-top:2px;line-height:1.5;">'
        'Full sensor registry, verified data, gap analysis, and deployment notes.</p>',
        unsafe_allow_html=True)

    # Known data-quality issue: Physical Education meter (May–Aug 2025)
    st.markdown(
        '<div style="background:#fffbeb;border:1px solid #fcd34d;'
        'border-left:5px solid #f59e0b;border-radius:12px;padding:18px 22px;'
        'margin-bottom:18px;font-family:Inter,sans-serif;">'
        '<div style="font-size:0.78rem;font-weight:800;color:#92400e;'
        'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">'
        '⚠️ Known Data-Quality Issue — Documented &amp; Resolved'
        '</div>'
        '<div style="font-size:1.15rem;font-weight:800;color:#0f172a;'
        'margin-bottom:8px;letter-spacing:-0.01em;">'
        'Physical Education electric meter — May 1 to August 31, 2025'
        '</div>'
        '<div style="font-size:0.95rem;color:#374151;line-height:1.6;">'
        'During this 4-month window the PE meter reported values in '
        '<b>watt-hours</b> while labeled as <b>kilowatt-hours</b> — a unit '
        'mismatch that inflated readings ~1,000×. The meter recalibrated on '
        'its own in early September 2025 and has reported correctly since.'
        '<br><br>'
        '<b>Evidence:</b> May–Jul averaged 15,232 kWh per 15-min reading '
        'against 12.76 kWh post-September — a 1,194× ratio. Pre-cleanup '
        'totals reached 110 million kWh over three months for a single gym '
        'building, which is physically impossible (typical campus gym is '
        '50,000–200,000 kWh per <em>year</em>).'
        '<br><br>'
        '<b>Action taken:</b> 7,745 affected rows were removed from MySQL '
        'after backup. PE shows no data for May–Aug 2025; this is more '
        'honest than displaying inflated values. All other buildings and '
        'time periods are unaffected.'
        '</div>'
        '</div>',
        unsafe_allow_html=True)

    # Latest week verified data table
    _di_latest   = all_weeks[-1]
    _di_earliest = all_weeks[0]
    wdf = df_all[df_all["week"] == _di_latest].sort_values("kWh", ascending=False)

    _di_lm = df_all.attrs.get("last_modified")
    if _di_lm is not None:
        _di_cap = pd.Timestamp(_di_lm.date())
    else:
        _di_cap = pd.Timestamp(datetime.datetime.now().date())

    st.markdown(
        f'<div class="sec-label">Verified Data — {week_label(_di_latest, cap_at=_di_cap)}'
        + (' <span style="color:#3b82f6;font-size:0.75rem;font-weight:700;'
           'background:#dbeafe;border-radius:4px;padding:2px 8px;margin-left:6px;">'
           '⚡ FROM RAW CSV</span>' if _di_latest in _raw_weeks else '') +
        '</div>',
        unsafe_allow_html=True)

    v_tbl = ('<table class="di-table"><thead><tr>'
             f'<th>Building</th><th>kWh</th><th>MWh</th>'
             f'<th>Est. Energy Cost @ ${ENERGY_RATE:.2f}/kWh equiv</th><th>Status</th>'
             '</tr></thead><tbody>')
    total_kwh = 0.0
    for _, r in wdf.iterrows():
        kwh   = r["kWh"]
        total_kwh += kwh
        bst   = BUILDINGS_STATUS.get(r["building"], "ok")
        smap  = {"ok": "OK", "review": "Review", "open": "Missing Data"}
        sbadge = badge_html(smap.get(bst, bst))
        src_badge = (' <span style="font-size:0.72rem;background:#dbeafe;color:#1e40af;'
                     'border-radius:3px;padding:1px 5px;font-weight:700;">RAW</span>'
                     if _di_latest in _raw_weeks else "")
        v_tbl += (f'<tr><td><b>{r["building"]}</b>{src_badge}</td>'
                  f'<td>{kwh:,.1f}</td><td>{kwh/1000:.2f}</td>'
                  f'<td>${kwh * ENERGY_RATE:,.0f}</td><td>{sbadge}</td></tr>')
    v_tbl += (f'<tr style="background:#f8fafc;font-weight:700;">'
              f'<td>CAMPUS TOTAL</td><td>{total_kwh:,.1f}</td><td>{total_kwh/1000:.2f}</td>'
              f'<td>${total_kwh * ENERGY_RATE:,.0f}</td><td></td></tr>')
    v_tbl += '</tbody></table>'
    st.markdown(f'<div class="card">{v_tbl}</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="font-size:1.05rem;font-weight:700;color:#374151;margin-top:8px;margin-bottom:4px;">'
        f'Showing most recent week: {week_label(_di_latest, cap_at=_di_cap)}. '
        f'kWh includes both electric meters and thermal energy sensors (heating &amp; cooling loops) '
        f'converted to kWh. Gas and water meters currently have no data available.'
        f'</div>', unsafe_allow_html=True)

    # Monthly Data Coverage
    st.markdown('<div class="sec-label">Monthly Data Coverage</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<p style="font-size:0.95rem;color:#6b7280;margin-top:-2px;line-height:1.5;">'
        'Per-month breakdown of how many buildings reported and how many weeks '
        'were covered. Months marked <b style="color:#92400e;">Partial</b> have '
        'fewer reporting buildings than typical and contribute artificially low '
        'totals to the campus chart.'
        '</p>', unsafe_allow_html=True)

    _cov = df_all.dropna(subset=["_wstart"]).copy()
    _cov["_month"] = _cov["_wstart"].dt.to_period("M")
    _cov_agg = (
        _cov[_cov["kWh"] > 0]
        .groupby("_month")
        .agg(_n_bld=("building", "nunique"),
             _n_weeks=("week", "nunique"),
             _kwh=("kWh", "sum"))
        .reset_index()
        .sort_values("_month")
    )
    _cov_max_bld    = int(_cov_agg["_n_bld"].max()) if not _cov_agg.empty else 0
    _cov_threshold  = max(1, int(_cov_max_bld * 0.7))

    def _verdict_for_row(n_bld, n_weeks):
        if n_bld == 0:
            return ("None", "#dc2626", "#fee2e2")
        if n_bld < _cov_threshold or n_weeks < 3:
            return ("Partial", "#92400e", "#fef3c7")
        return ("Complete", "#15803d", "#dcfce7")

    cov_tbl = ('<table class="di-table"><thead><tr>'
               '<th>Month</th>'
               '<th style="text-align:right;">Buildings Reporting</th>'
               '<th style="text-align:right;">Weeks Covered</th>'
               '<th style="text-align:right;">Total Energy (MWh)</th>'
               '<th>Status</th>'
               '</tr></thead><tbody>')
    for _, r in _cov_agg.iterrows():
        _label_m = r["_month"].to_timestamp().strftime("%b %Y")
        _verdict, _verdict_color, _verdict_bg = _verdict_for_row(int(r["_n_bld"]), int(r["_n_weeks"]))
        _badge = (f'<span style="background:{_verdict_bg};color:{_verdict_color};'
                  f'font-weight:700;padding:2px 10px;border-radius:6px;font-size:0.85rem;'
                  f'font-family:Inter,sans-serif;">{_verdict}</span>')
        cov_tbl += (f'<tr><td><b>{_label_m}</b></td>'
                    f'<td style="text-align:right;">{int(r["_n_bld"])} of {_cov_max_bld}</td>'
                    f'<td style="text-align:right;">{int(r["_n_weeks"])}</td>'
                    f'<td style="text-align:right;">{r["_kwh"]/1000:,.1f}</td>'
                    f'<td>{_badge}</td></tr>')
    cov_tbl += '</tbody></table>'
    st.markdown(f'<div class="card" style="overflow-x:auto">{cov_tbl}</div>',
                unsafe_allow_html=True)

    _n_complete = sum(1 for _, r in _cov_agg.iterrows()
                      if _verdict_for_row(int(r["_n_bld"]), int(r["_n_weeks"]))[0] == "Complete")
    _n_partial_cov = sum(1 for _, r in _cov_agg.iterrows()
                         if _verdict_for_row(int(r["_n_bld"]), int(r["_n_weeks"]))[0] == "Partial")
    _total_months = len(_cov_agg)
    _complete_pct = (_n_complete / _total_months * 100) if _total_months else 0

    cv1, cv2, cv3 = st.columns(3)
    cv1.markdown(
        f'<div class="card"><div class="card-title">📅 Months in Database</div>'
        f'<div style="font-size:1.6rem;font-weight:800;color:#111827;letter-spacing:-0.02em;">'
        f'{_total_months}</div>'
        f'<div style="font-size:0.85rem;color:#6b7280;margin-top:2px;">'
        f'Earliest data point: {_cov_agg.iloc[0]["_month"].to_timestamp().strftime("%b %Y") if not _cov_agg.empty else "—"}'
        f'</div></div>', unsafe_allow_html=True)
    cv2.markdown(
        f'<div class="card"><div class="card-title">✅ Complete Months</div>'
        f'<div style="font-size:1.6rem;font-weight:800;color:#15803d;letter-spacing:-0.02em;">'
        f'{_n_complete} <span style="font-size:1rem;color:#6b7280;font-weight:600;">'
        f'({_complete_pct:.0f}%)</span></div>'
        f'<div style="font-size:0.85rem;color:#6b7280;margin-top:2px;">'
        f'Full-fleet reporting; year-over-year comparable.'
        f'</div></div>', unsafe_allow_html=True)
    cv3.markdown(
        f'<div class="card"><div class="card-title">⚠️ Partial Months</div>'
        f'<div style="font-size:1.6rem;font-weight:800;color:#92400e;letter-spacing:-0.02em;">'
        f'{_n_partial_cov}</div>'
        f'<div style="font-size:0.85rem;color:#6b7280;margin-top:2px;">'
        f'Fewer reporting buildings than typical; treat totals as lower bound.'
        f'</div></div>', unsafe_allow_html=True)

    # Building data status chart
    _dyn_statuses_for_chart = compute_sensor_statuses(df_all)
    _bld_sensor_statuses = defaultdict(list)
    for _b, _sid, _util, _unit, _orig_st, _orig_notes in SENSOR_REGISTRY:
        _live_st, _ = _dyn_statuses_for_chart.get(_sid, (_orig_st, _orig_notes))
        _bld_sensor_statuses[_b].append(_live_st)

    _bld_chart_data = []
    for _b, _sts in _bld_sensor_statuses.items():
        _ok   = sum(1 for s in _sts if s in ("OK", "PGE"))
        _miss = sum(1 for s in _sts if s == "Missing")
        _rev  = sum(1 for s in _sts if s == "Review")
        _tot  = len(_sts)
        if _rev > 0 or (_ok > 0 and _miss > 0):
            _lbl = "Partial Data"; _col = "#d97706"; _fill = round(_ok / _tot, 4) if _tot else 0
        elif _miss == _tot:
            _lbl = "No Data"; _col = "#dc2626"; _fill = 0.0
        else:
            _lbl = "Active"; _col = "#16a34a"; _fill = 1.0
        _bld_chart_data.append({"building": _b, "label": _lbl, "color": _col,
                                 "fill": _fill, "ok": _ok, "total": _tot})
    _order_map = {"Active": 0, "Partial Data": 1, "No Data": 2}
    _bld_chart_data.sort(key=lambda x: (_order_map[x["label"]], x["building"]))

    _n_active  = sum(1 for d in _bld_chart_data if d["label"] == "Active")
    _n_partial = sum(1 for d in _bld_chart_data if d["label"] == "Partial Data")
    _n_nodata  = sum(1 for d in _bld_chart_data if d["label"] == "No Data")
    _partial_names = [d["building"] for d in _bld_chart_data if d["label"] == "Partial Data"]

    # Building Data Gaps
    st.markdown('<div class="sec-label">Building Data Gaps</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<p style="font-size:0.95rem;color:#6b7280;margin-top:-2px;line-height:1.5;">'
        'Months where a building has no data despite reporting in earlier and '
        'later months. This is the dashboard\'s honest accounting of what is '
        'and isn\'t in the database.'
        '</p>', unsafe_allow_html=True)

    KNOWN_GAP_CAUSES = {
        ("Physical Education", "2025-05"):
            "Unit mismatch — meter reported watt-hours labeled as kWh; readings removed during data quality review (May–Aug 2025).",
        ("Physical Education", "2025-06"):
            "Unit mismatch — meter reported watt-hours labeled as kWh; readings removed during data quality review (May–Aug 2025).",
        ("Physical Education", "2025-07"):
            "Unit mismatch — meter reported watt-hours labeled as kWh; readings removed during data quality review (May–Aug 2025).",
        ("Physical Education", "2025-08"):
            "Unit mismatch — meter reported watt-hours labeled as kWh; readings removed during data quality review (May–Aug 2025).",
    }

    # Compute gaps per building
    _gap_df = df_all.dropna(subset=["_wstart"]).copy()
    _gap_df["_month"] = _gap_df["_wstart"].dt.to_period("M")

    gap_rows = []
    for _bld in sorted(_gap_df["building"].unique()):
        _bld_df = _gap_df[(_gap_df["building"] == _bld) & (_gap_df["kWh"] > 0)]
        if _bld_df.empty:
            continue
        _months = sorted(_bld_df["_month"].unique())
        if len(_months) < 2:
            continue
        _all_months_range = pd.period_range(_months[0], _months[-1], freq="M")
        _present = set(_months)
        for _m in _all_months_range:
            if _m not in _present:
                _m_str = str(_m)
                _cause = KNOWN_GAP_CAUSES.get(
                    (_bld, _m_str),
                    "No data reported in this period — meter may have been offline or undergoing maintenance."
                )
                gap_rows.append((_bld, _m_str, _cause))

    if not gap_rows:
        st.markdown(
            '<div class="card" style="border-left:4px solid #15803d;">'
            '<div style="font-family:Inter,sans-serif;color:#374151;font-size:0.95rem;">'
            '✅ <b>No gaps detected.</b> Every building in the database has '
            'continuous month-to-month coverage within its operational range.'
            '</div></div>',
            unsafe_allow_html=True)
    else:
        from itertools import groupby
        by_bld = defaultdict(list)
        for _b, _m, _c in gap_rows:
            by_bld[_b].append((_m, _c))

        gap_tbl = ('<table class="di-table"><thead><tr>'
                   '<th>Building</th>'
                   '<th>Affected Months</th>'
                   '<th>Explanation</th>'
                   '</tr></thead><tbody>')
        for _b in sorted(by_bld):
            rows_for_bld = sorted(by_bld[_b], key=lambda x: x[0])
            groups = []
            for _, run in groupby(enumerate(rows_for_bld),
                                  key=lambda iv: (
                                      pd.Period(iv[1][0]).ordinal - iv[0],
                                      iv[1][1])):
                run_list = [x[1] for x in run]
                groups.append((run_list[0][1],
                               run_list[0][0],
                               run_list[-1][0]))
            for cause, m_start, m_end in groups:
                if m_start == m_end:
                    months_label = pd.Period(m_start).to_timestamp().strftime("%b %Y")
                else:
                    months_label = (pd.Period(m_start).to_timestamp().strftime("%b %Y")
                                    + " – "
                                    + pd.Period(m_end).to_timestamp().strftime("%b %Y"))
                _is_known = "data quality review" in cause or "Unit mismatch" in cause
                _row_bg = "#fffbeb" if _is_known else "#ffffff"
                _icon   = "⚠️" if _is_known else "🔇"
                gap_tbl += (f'<tr style="background:{_row_bg};">'
                            f'<td><b>{_b}</b></td>'
                            f'<td><b>{months_label}</b></td>'
                            f'<td>{_icon} &nbsp;{cause}</td></tr>')
        gap_tbl += '</tbody></table>'
        st.markdown(f'<div class="card" style="overflow-x:auto">{gap_tbl}</div>',
                    unsafe_allow_html=True)

        st.markdown(
            '<div style="display:flex;gap:20px;flex-wrap:wrap;margin-top:8px;'
            'font-family:Inter,sans-serif;font-size:0.85rem;color:#6b7280;">'
            '<span><b style="color:#92400e;">⚠️</b> &nbsp;Known data-quality issue — investigated and documented</span>'
            '<span><b>🔇</b> &nbsp;Cause unknown — meter offline or not reporting during the gap</span>'
            '</div>', unsafe_allow_html=True)

    st.markdown("---")

    st.markdown('<div class="sec-label">Building Data Status</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px;">'
        '<span style="font-family:Inter,sans-serif;font-size:0.88rem;font-weight:600;color:#16a34a;">'
        '● Active — all meters reporting</span>'
        '<span style="font-family:Inter,sans-serif;font-size:0.88rem;font-weight:600;color:#d97706;">'
        '● Partial — some meters missing</span>'
        '<span style="font-family:Inter,sans-serif;font-size:0.88rem;font-weight:600;color:#dc2626;">'
        '● No Data — no readings received</span>'
        '</div>', unsafe_allow_html=True)

    _blds_c  = [d["building"] for d in _bld_chart_data]
    _fills_c = [d["fill"]     for d in _bld_chart_data]
    _cols_c  = [d["color"]    for d in _bld_chart_data]
    _texts_inside = [
        f'{d["label"]}  ({d["ok"]}/{d["total"]} meters active)' if d["fill"] > 0 else ''
        for d in _bld_chart_data
    ]
    _texts_outside = [
        f'{d["label"]}  ({d["ok"]}/{d["total"]} meters active)' if d["fill"] == 0 else ''
        for d in _bld_chart_data
    ]

    fig_status = go.Figure()
    fig_status.add_trace(go.Bar(
        y=_blds_c, x=[1.0] * len(_bld_chart_data), orientation="h",
        marker_color="#f1f5f9", marker_line_width=0,
        showlegend=False, hoverinfo="skip",
    ))
    fig_status.add_trace(go.Bar(
        y=_blds_c, x=_fills_c, orientation="h",
        marker_color=_cols_c, marker_line_width=0,
        text=_texts_inside, textposition="inside", insidetextanchor="start",
        textfont=dict(size=12, color="#ffffff", family="Inter"),
        hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
        customdata=[f'{d["label"]}  ({d["ok"]}/{d["total"]} meters active)' for d in _bld_chart_data],
        showlegend=False,
    ))
    fig_status.add_trace(go.Bar(
        y=_blds_c, x=[0.01 if d["fill"] == 0 else 0 for d in _bld_chart_data], orientation="h",
        marker_color='rgba(0,0,0,0)', marker_line_width=0,
        text=_texts_outside, textposition="outside",
        textfont=dict(size=11, family="Inter"),
        hoverinfo='skip', showlegend=False,
    ))
    fig_status.update_layout(
        paper_bgcolor=PLOT_BG, plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, sans-serif", color=PLOT_TEXT, size=13),
        height=max(380, len(_bld_chart_data) * 36),
        barmode="overlay", bargap=0.28,
        margin=dict(l=8, r=20, t=20, b=8),
        xaxis=dict(
            range=[0, 1.0], tickformat=".0%", title="Meter Coverage",
            gridcolor=PLOT_GRID, zerolinecolor="#e2e8f0", linecolor="#e2e8f0",
            tickfont=dict(size=12, family="Inter", color=PLOT_TEXT),
        ),
        yaxis=dict(
            autorange="reversed", gridcolor="rgba(0,0,0,0)",
            zerolinecolor="#e2e8f0", linecolor="#e2e8f0",
            tickfont=dict(size=12, color="#111827", family="Inter"),
        ),
    )
    st.plotly_chart(fig_status, use_container_width=True)

    # Data summary cards
    st.markdown('<div class="sec-label">Data Summary</div>', unsafe_allow_html=True)

    _start_dt  = pd.to_datetime(_di_earliest)
    _last_mod_di = df_all.attrs.get("last_modified")
    if _last_mod_di is not None:
        _end_dt = pd.Timestamp(_last_mod_di.date())
    else:
        _week_end_dt = pd.to_datetime(_di_latest) + pd.Timedelta(days=6)
        _today_dt    = pd.Timestamp(datetime.datetime.now().date())
        _end_dt      = min(_week_end_dt, _today_dt)
    _start_str = _start_dt.strftime("%B %d, %Y") if _start_dt else _di_earliest
    _end_str   = _end_dt.strftime("%B %d, %Y")   if _end_dt   else _di_latest
    _now_str   = datetime.datetime.now().strftime("%B %d, %Y  —  %I:%M %p")
    _partial_note = (
        ", ".join(_partial_names) + " have partial meter coverage."
        if _partial_names else "No partial-coverage buildings."
    )

    _lbl_style = ('font-size:0.75rem;font-weight:700;color:#9ca3af;text-transform:uppercase;'
                  'letter-spacing:0.1em;font-family:Inter,sans-serif;')
    _val_style = 'font-size:1.05rem;font-weight:700;color:#111827;font-family:Inter,sans-serif;'

    ds1, ds2 = st.columns(2)
    ds1.markdown(
        f'<div class="card">'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Starting Date</span></div>'
        f'<div style="margin:4px 0 18px;"><span style="{_val_style}">{_start_str}</span></div>'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Latest Date in Database</span></div>'
        f'<div style="margin:4px 0 18px;"><span style="{_val_style}">{_end_str}</span></div>'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Last Updated</span></div>'
        f'<div style="margin:4px 0 0;"><span style="{_val_style}">{_now_str}</span></div>'
        f'</div>', unsafe_allow_html=True)

    ds2.markdown(
        f'<div class="card">'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Reporting Buildings</span></div>'
        f'<div style="margin:4px 0 18px;">'
        f'<span style="font-size:1.05rem;font-weight:700;color:#16a34a;font-family:Inter,sans-serif;">{_n_active} fully active</span>'
        f'<span style="font-size:1.05rem;font-weight:700;color:#d97706;font-family:Inter,sans-serif;margin-left:10px;">+ {_n_partial} partial</span></div>'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Buildings with No Data</span></div>'
        f'<div style="margin:4px 0 18px;"><span style="font-size:1.05rem;font-weight:700;color:#dc2626;font-family:Inter,sans-serif;">{_n_nodata} buildings</span></div>'
        f'<div style="line-height:1;"><span style="{_lbl_style}">Partial Data Note</span></div>'
        f'<div style="margin:4px 0 0;"><span style="font-size:0.9rem;font-weight:500;color:#78350f;font-family:Inter,sans-serif;">{_partial_note}</span></div>'
        f'</div>', unsafe_allow_html=True)

    # Utility coverage
    st.markdown('<div class="sec-label">Utility Coverage</div>', unsafe_allow_html=True)

    _dyn = df_all.copy()
    _dyn["electric_kWh"] = (_dyn["kWh"] - _dyn["thermal_kWh"]).clip(lower=0)

    _elec_by_bld = _dyn.groupby("building")["electric_kWh"].sum()
    _elec_active = sorted([b for b, v in _elec_by_bld.items() if v > 0])
    _elec_total  = float(_dyn["electric_kWh"].sum())

    _th_by_bld   = _dyn.groupby("building")["thermal_kWh"].sum()
    _th_active   = sorted([b for b, v in _th_by_bld.items() if v > 0])
    _th_total    = float(_dyn["thermal_kWh"].sum())
    _th_share    = (_th_total / (_elec_total + _th_total) * 100) if (_elec_total + _th_total) > 0 else 0.0

    _gas_by_bld  = _dyn.groupby("building")["gas_therm"].sum()
    _gas_active  = sorted([b for b, v in _gas_by_bld.items() if v > 0])
    _gas_total   = float(_dyn["gas_therm"].sum())

    _wat_by_bld  = _dyn.groupby("building")["water_gallon"].sum()
    _wat_active  = sorted([b for b, v in _wat_by_bld.items() if v > 0])
    _wat_total   = float(_dyn["water_gallon"].sum())

    _reg_elec = [r for r in SENSOR_REGISTRY if r[2] == "Electric"]
    _reg_th   = [r for r in SENSOR_REGISTRY if r[2] == "Thermal"]
    _reg_gas  = [r for r in SENSOR_REGISTRY if r[2] == "Gas"]
    _reg_wat  = [r for r in SENSOR_REGISTRY if r[2] == "Water"]

    def _status_badge(n_active, label_active="Active", label_none="No data"):
        if n_active > 0:
            return f'<span style="color:#16a34a;font-weight:700">● {label_active}</span>'
        return f'<span style="color:#dc2626;font-weight:700">● {label_none}</span>'

    def _active_list(names):
        if not names:
            return '<span style="color:#6b7280;font-style:italic">none reporting</span>'
        return ", ".join(names) if len(names) <= 6 else f"{', '.join(names[:6])}, +{len(names)-6} more"

    u1, u2, u3, u4 = st.columns(4)
    u1.markdown(
        f'<div class="card"><div class="card-title">⚡ Electricity</div>'
        f'<div style="font-size:0.92rem;color:#374151;line-height:1.7;margin-top:6px;">'
        f'<b>Status:</b> {_status_badge(len(_elec_active))}<br>'
        f'<b>Reporting:</b> {len(_elec_active)} of {len({r[0] for r in _reg_elec})} buildings<br>'
        f'<b>Total:</b> {_elec_total/1000:,.1f} MWh<br>'
        f'<b>Buildings:</b> <span style="font-size:0.85rem">{_active_list(_elec_active)}</span><br>'
        f'<b>Source:</b> kWh interval meters<br>'
        f'<b>Rate:</b> ${ENERGY_RATE:.2f}/kWh'
        f'</div></div>', unsafe_allow_html=True)
    u2.markdown(
        f'<div class="card"><div class="card-title">🌡️ Thermal</div>'
        f'<div style="font-size:0.92rem;color:#374151;line-height:1.7;margin-top:6px;">'
        f'<b>Status:</b> {_status_badge(len(_th_active))}<br>'
        f'<b>Reporting:</b> {len(_th_active)} of {len({r[0] for r in _reg_th})} buildings<br>'
        f'<b>Total:</b> {_th_total/1000:,.1f} MWh ({_th_share:.1f}% of campus)<br>'
        f'<b>Buildings:</b> <span style="font-size:0.85rem">{_active_list(_th_active)}</span><br>'
        f'<b>Source:</b> BTU/kBTU heating &amp; cooling loops<br>'
        f'<b>Conversion:</b> BTU × 0.000293071'
        f'</div></div>', unsafe_allow_html=True)
    u3.markdown(
        f'<div class="card"><div class="card-title">🔥 Gas</div>'
        f'<div style="font-size:0.92rem;color:#374151;line-height:1.7;margin-top:6px;">'
        f'<b>Status:</b> {_status_badge(len(_gas_active))}<br>'
        f'<b>Reporting:</b> {len(_gas_active)} of {len({r[0] for r in _reg_gas})} buildings<br>'
        f'<b>Total:</b> {_gas_total:,.0f} therms<br>'
        f'<b>Meters:</b> <span style="font-size:0.85rem">{_active_list([r[0] for r in _reg_gas]) if _reg_gas else "none"}</span><br>'
        f'<b>Note:</b> {"Meters registered; no readings received" if len(_gas_active)==0 else "Readings received"}'
        f'</div></div>', unsafe_allow_html=True)
    u4.markdown(
        f'<div class="card"><div class="card-title">💧 Water</div>'
        f'<div style="font-size:0.92rem;color:#374151;line-height:1.7;margin-top:6px;">'
        f'<b>Status:</b> {_status_badge(len(_wat_active))}<br>'
        f'<b>Reporting:</b> {len(_wat_active)} of {len({r[0] for r in _reg_wat})} buildings<br>'
        f'<b>Total:</b> {_wat_total:,.0f} gallons<br>'
        f'<b>Meters:</b> <span style="font-size:0.85rem">{_active_list([r[0] for r in _reg_wat]) if _reg_wat else "none"}</span><br>'
        f'<b>Note:</b> {"Meters registered; no readings received" if len(_wat_active)==0 else "Readings received"}'
        f'</div></div>', unsafe_allow_html=True)

    # Full sensor registry
    st.markdown('<div class="sec-label">Full Sensor Registry — All 37 Sensors</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<p style="font-size:0.95rem;color:#6b7280;margin-top:-2px;line-height:1.5;">'
        'Status and notes are derived dynamically from the weekly data. A sensor '
        'reads <b>OK</b> when its building has activity for that utility in the '
        'last 4 weeks, <b>Review</b> when it has historical data but nothing '
        'recent, and <b>Missing</b> when it has never contributed to the weekly '
        'CSV. Multiple sensors of the same utility at the same building share a '
        'status because the weekly CSV aggregates them.'
        '</p>', unsafe_allow_html=True)
    _dynamic_statuses = compute_sensor_statuses(df_all)
    tbl = ('<table class="di-table"><thead><tr>'
           '<th>Building</th><th>Sensor ID</th><th>Utility</th><th>Raw Unit</th>'
           '<th>Status</th><th>Notes</th>'
           '</tr></thead><tbody>')
    for bld, sid, util, unit, _orig_status, _orig_notes in SENSOR_REGISTRY:
        status, notes = _dynamic_statuses.get(sid, (_orig_status, _orig_notes))
        sbadge = badge_html(status)
        tbl += (f'<tr><td><b>{bld}</b></td>'
                f'<td><code style="background:#f1f5f9;padding:2px 6px;border-radius:3px;font-size:0.82rem">{sid}</code></td>'
                f'<td>{util}</td><td>{unit}</td><td>{sbadge}</td>'
                f'<td style="color:#6b7280;font-size:0.88rem">{notes}</td></tr>')
    tbl += '</tbody></table>'
    st.markdown(f'<div class="card" style="overflow-x:auto">{tbl}</div>', unsafe_allow_html=True)

    # Unit conversions
    st.markdown('<div class="sec-label">Unit Conversions Applied</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="card">'
        '<div style="font-size:0.95rem;color:#374151;line-height:2.2;">'
        '<span style="display:inline-block;background:#e8eef5;color:#1b3a5c;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">BTU × 0.000293071 = kWh</span><br>'
        '<span style="display:inline-block;background:#e8eef5;color:#1b3a5c;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">kBTU × 0.293071 = kWh</span><br>'
        '<span style="display:inline-block;background:#fff7ed;color:#92400e;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">'
        '_MBTU cell value → remapped to kBTU before conversion (BMS label quirk)</span><br>'
        '<span style="display:inline-block;background:#e8eef5;color:#1b3a5c;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">therm × 29.3071 = kWh</span><br>'
        '<span style="display:inline-block;background:#e8eef5;color:#1b3a5c;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">kWh → kWh direct</span><br>'
        '<span style="display:inline-block;background:#e8eef5;color:#1b3a5c;font-weight:600;padding:2px 12px;border-radius:6px;font-family:Inter,sans-serif;">Water (gallon) → stored as-is, no conversion</span>'
        '</div></div>', unsafe_allow_html=True)

    # Pipeline info
    st.markdown('<div class="sec-label">Pipeline</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="card">'
        '<div style="font-size:0.95rem;color:#374151;line-height:1.9;">'
        '<b>Schedule:</b> Daily, 6 AM (cron job)<br>'
        '<b>DB:</b> 193.203.166.234 | u209446640_SSUEnergy<br>'
        '</div></div>', unsafe_allow_html=True)
