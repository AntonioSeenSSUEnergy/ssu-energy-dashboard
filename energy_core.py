"""
energy_core.py — Single source of truth for SSU campus energy cleaning.

Both master_pipeline.py and app.py import from here. Any unit-mapping change
happens in ONE file. Eliminates drift between ingestion and display.

Public surface:
    POINT_ID_MAP        — point-id → (building_name, canonical_unit)
    UNIT_TO_KWH         — conversion factors
    VALID_UNITS         — set of recognised units
    ENERGY_UNITS        — units routed to energy_usage table
    parse_cell(value)   — extract (number, unit) from raw cell
    process_csv(path)   — clean a raw FTP CSV → flat normalised DataFrame
    route_unit(unit)    — 'energy' | 'gas' | 'water' | None
"""
from __future__ import annotations
import os, re
from collections import defaultdict
import pandas as pd

# ── Units ─────────────────────────────────────────────────────────────────
VALID_UNITS  = {"kWh", "Wh", "therm", "BTU", "tonref", "MBTU", "kBTU", "gallon"}
ENERGY_UNITS = {"kWh", "Wh", "BTU", "MBTU", "kBTU", "tonref"}
# Energy units that come from THERMAL sensors (heating hot water, chilled
# water, chiller output). Everything else in ENERGY_UNITS — kWh, Wh — is
# electric. Used by the pipeline + dashboard to split kWh into electric vs
# thermal in weekly_energy.csv. Defined here so the rule lives in ONE place.
THERMAL_UNITS = {"BTU", "MBTU", "kBTU", "tonref"}

UNIT_TO_KWH = {
    "kWh":    1.0,
    "Wh":     0.001,        # watt-hours → kilowatt-hours
    "BTU":    0.000293071,
    "MBTU":   293.071,      # true megaBTU = 1,000,000 BTU
    "kBTU":   0.293071,     # BMS sends "_MBTU" label but values are kBTU
    "tonref": 3.51685,
    "therm":  29.3071,
}

# ── Point-id → (building, canonical unit) ─────────────────────────────────
POINT_ID_MAP = {
    "1f97c82e-36e60525": ("Art Building", "BTU"),
    "1f97c82e-d1a92673": ("Art Building", "BTU"),
    "1f97c82e-525ca261": ("Schulz Info Center", "BTU"),
    "1f97c82e-c34c4f2e": ("Schulz Info Center", "kWh"),
    "206e94b8-3b05cb50": ("Schulz Info Center", "therm"),
    "1f97c82e-dd011464": ("ETC", "kWh"),
    "1f98265e-39835c84": ("Green Music Center", "BTU"),
    "234aa956-82d369b2": ("Green Music Center", "kBTU"),    # _MBTU label
    "234ab131-e413ba29": ("Green Music Center", "kWh"),
    "234aab84-c656a0e0": ("Green Music Center", "therm"),
    "234aa782-f7b1eef2": ("Green Music Center", "gallon"),
    "1f98265e-cbf77175": ("Rachel Carson Hall", "kWh"),
    "234aa121-a983880d": ("Rachel Carson Hall", "BTU"),
    "234aa43b-a73abf5e": ("Rachel Carson Hall", "BTU"),
    "206d9425-f3361ab6": ("Ives Hall", "kWh"),
    "234e3195-7d72fbdc": ("Ives Hall", "BTU"),
    "234e3195-c20a1a8e": ("Ives Hall", "BTU"),
    "206db469-c986212b": ("Physical Education", "kWh"),
    "20c9b2e1-d7263cf1": ("Salazar Hall", "kWh"),
    "234e4c64-930d1fd6": ("Salazar Hall", "kWh"),
    "20c9b4d5-5ea6aa0b": ("Salazar Hall", "BTU"),
    "234a6e2b-318cf13d": ("Boiler Plant", "therm"),
    "234e3ee2-b06b6c8c": ("Nichols Hall", "BTU"),
    "234e3ee2-f6fcea18": ("Nichols Hall", "BTU"),
    "234e40da-635bc7c1": ("Nichols Hall", "kWh"),
    "20c9aa07-acd1558a": ("Student Center", "kWh"),
    "234e5dff-6fe20abd": ("Student Center", "BTU"),
    "234e5dff-8d8eb031": ("Student Center", "BTU"),
    "234e61c5-021da430": ("Student Health Center", "BTU"),
    "234e61c5-83f6cf71": ("Student Health Center", "BTU"),
    "250ea73e-3b55a6cf": ("Wine Spectator Learning Ctr", "kWh"),
    "251810ce-f429b841": ("Stevenson Hall", "kWh"),
    "267fcb62-ed42e3b3": ("Stevenson Hall", "BTU"),
    "267e6fd0-93d67a62": ("Darwin Hall", "kWh"),
    "214981c7-5530731e": ("Campus Misc", "kWh"),
    "214981c7-63077e46": ("Campus Misc", "kWh"),
    "214981c7-dd0b1593": ("Campus Misc", "kWh"),
}

# ── Regex patterns ────────────────────────────────────────────────────────
_CELL_RE    = re.compile(r"^([\d.]+)(_?)([a-zA-Z]+)$")
_PID_PREFIX = "p:sonomastate:r:"
_TZ_SUFFIX  = re.compile(r"\s*Los_Angeles$")

# Filename pattern: YYYYMMDD[int|pge].csv — used by the dashboard to discover files
RAW_CSV_RE  = re.compile(r"^(\d{8})(int|pge)?\.csv$", re.IGNORECASE)


def parse_cell(value):
    """
    Parse a raw cell value into (numeric, unit).

    Handles:
        '150.5kWh'     → (150.5,  'kWh')
        '9000000Wh'    → (9000000.0, 'Wh')   # legacy meters that report watt-hours
        '184.82_MBTU'  → (184.82, 'kBTU')    # BMS mislabel — critical remap
        '27332.59BTU'  → (27332.59, 'BTU')
        '12.5gallon'   → (12.5,   'gallon')
        '0'            → (0.0,    None)      # bare number, unit unknown
        ''  or  '""'   → (None,   None)
        NaN            → (None,   None)
    """
    if pd.isna(value):
        return None, None
    s = str(value).strip().strip('"')
    if not s:
        return None, None
    m = _CELL_RE.match(s)
    if not m:
        try:
            return float(s), None
        except ValueError:
            return None, None
    num = float(m.group(1))
    underscore, unit = m.group(2), m.group(3)
    if underscore == "_" and unit == "MBTU":     # THE critical remap
        unit = "kBTU"
    if unit in VALID_UNITS:
        return num, unit
    return num, None


def extract_point_id(column_name: str) -> str | None:
    """Pull the bare point ID from either a 2025 named column or a 2026 bare-ID column."""
    if _PID_PREFIX in column_name:
        return column_name.split(_PID_PREFIX)[-1].strip()
    return None


def _resolve_unit(map_unit: str, cell_unit: str | None) -> str:
    """
    Reconcile the point-id map's declared unit against the cell's inline unit.

    Rules:
      - If cell carries an explicit valid unit, trust it.
      - EXCEPT: if the meter is mapped as 'therm' (natural gas), only override
        to MBTU. Any other cell unit on a gas meter is treated as a label error
        and the meter stays on therm. Prevents silent gas → BTU conversion.
      - If cell has no unit, use the map unit.
    """
    if cell_unit and cell_unit in VALID_UNITS:
        if map_unit == "therm" and cell_unit != "MBTU":
            return "therm"
        return cell_unit
    return map_unit


def route_unit(unit: str) -> str | None:
    """Return 'energy', 'gas', 'water', or None — which MySQL table to use."""
    if unit in ENERGY_UNITS:
        return "energy"
    if unit == "therm":
        return "gas"
    if unit == "gallon":
        return "water"
    return None


def process_csv(path: str) -> tuple[pd.DataFrame, dict]:
    """
    Ingest one raw FTP CSV and return a flat normalised DataFrame.

    Output columns:
        timestamp   — ISO 'YYYY-MM-DD HH:MM:SS'
        location    — the original column header (preserved for traceability)
        point_id    — bare point ID (primary join key)
        building    — resolved building name from POINT_ID_MAP
        value       — numeric reading
        unit        — final unit after cell-vs-map reconciliation
        table       — 'energy' | 'gas' | 'water'

    Stats dict:
        file, rows_in, rows_out, cols_mapped, cols_skipped, dates, error
    """
    stats = {"file": os.path.basename(path), "rows_in": 0, "rows_out": 0,
             "cols_mapped": 0, "cols_skipped": 0, "dates": set(), "error": None}
    out = []

    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception as e:
        stats["error"] = f"read_csv: {e}"
        return pd.DataFrame(), stats

    if df.empty or len(df.columns) < 2:
        stats["error"] = "empty or single-column file"
        return pd.DataFrame(), stats

    ts_col = df.columns[0]
    stats["rows_in"] = len(df)

    # Normalise timestamp — handles ISO-8601+Los_Angeles AND MM/DD/YYYY HH:MM:SS
    raw_ts = df[ts_col].astype(str).str.replace(_TZ_SUFFIX, "", regex=True)
    df["_ts"] = pd.to_datetime(raw_ts, errors="coerce")
    df = df.dropna(subset=["_ts"]).copy()
    df["_ts_str"] = df["_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    df["_date"]   = df["_ts"].dt.date.astype(str)

    for col in df.columns:
        if col in (ts_col, "_ts", "_ts_str", "_date"):
            continue
        pid = extract_point_id(col)
        if not pid or pid not in POINT_ID_MAP:
            stats["cols_skipped"] += 1
            continue
        building, map_unit = POINT_ID_MAP[pid]
        stats["cols_mapped"] += 1

        for _, row in df.iterrows():
            cell = row[col]
            num, cell_unit = parse_cell(cell)
            if num is None:
                continue
            unit  = _resolve_unit(map_unit, cell_unit)
            table = route_unit(unit)
            if table is None:
                continue
            out.append({
                "timestamp": row["_ts_str"],
                "location":  col,
                "point_id":  pid,
                "building":  building,
                "value":     num,
                "unit":      unit,
                "table":     table,
            })
            stats["dates"].add(row["_date"])

    result = pd.DataFrame(out)
    stats["rows_out"] = len(result)
    return result, stats


def to_kwh(value: float, unit: str) -> float:
    """Convert any ENERGY_UNITS value to kWh. Returns 0.0 for non-energy units."""
    return value * UNIT_TO_KWH.get(unit, 0.0) if unit in ENERGY_UNITS else 0.0
