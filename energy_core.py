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
NATIVE_VOLUME_UNITS = {"gal", "ft³"}
VALID_UNITS  = NATIVE_VOLUME_UNITS | {"kWh", "Wh", "therm", "BTU", "tonref", "MBTU", "kBTU", "gallon"}
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
    # Tuscany Village incoming submeter reports; retain native volume units.
    "227239a6-05331d1c": ("Tuscany Village", "kWh"),
    "227239a6-0ed5faa7": ("Tuscany Village", "ft³"),
    "227239a6-114f7e41": ("Tuscany Village", "gal"),
    "227239a6-1488449f": ("Tuscany Village", "kWh"),
    "227239a6-1a6b53fd": ("Tuscany Village", "ft³"),
    "227239a6-1d3d3ac8": ("Tuscany Village", "gal"),
    "227239a6-299a16f6": ("Tuscany Village", "kWh"),
    "227239a6-2b1494cf": ("Tuscany Village", "ft³"),
    "227239a6-2e46276f": ("Tuscany Village", "ft³"),
    "227239a6-35e1acda": ("Tuscany Village", "gal"),
    "227239a6-3eef0316": ("Tuscany Village", "gal"),
    "227239a6-409d1263": ("Tuscany Village", "gal"),
    "227239a6-43141a5d": ("Tuscany Village", "ft³"),
    "227239a6-4635bdfe": ("Tuscany Village", "ft³"),
    "227239a6-4b5194e4": ("Tuscany Village", "ft³"),
    "227239a6-553895e3": ("Tuscany Village", "gal"),
    "227239a6-58cd5e23": ("Tuscany Village", "kWh"),
    "227239a6-59c95805": ("Tuscany Village", "ft³"),
    "227239a6-5a711e2f": ("Tuscany Village", "gal"),
    "227239a6-6436d1e2": ("Tuscany Village", "kWh"),
    "227239a6-67c200f7": ("Tuscany Village", "kWh"),
    "227239a6-6a36efa0": ("Tuscany Village", "kWh"),
    "227239a6-6b34e009": ("Tuscany Village", "kWh"),
    "227239a6-79c265d7": ("Tuscany Village", "gal"),
    "227239a6-7ae00b27": ("Tuscany Village", "ft³"),
    "227239a6-81f1baee": ("Tuscany Village", "ft³"),
    "227239a6-8aab3f6f": ("Tuscany Village", "ft³"),
    "227239a6-8d89283c": ("Tuscany Village", "kWh"),
    "227239a6-9ec2eb0f": ("Tuscany Village", "gal"),
    "227239a6-a24ba253": ("Tuscany Village", "kWh"),
    "227239a6-aafb5033": ("Tuscany Village", "gal"),
    "227239a6-b4361f24": ("Tuscany Village", "kWh"),
    "227239a6-dc2bf8d9": ("Tuscany Village", "gal"),
    "227239a6-de1a23f4": ("Tuscany Village", "kWh"),
    "227239a6-e2cdff5d": ("Tuscany Village", "kWh"),
    "227239a6-e501bf3e": ("Tuscany Village", "gal"),
    "227239a6-eaadfd82": ("Tuscany Village", "ft³"),
    "227239a6-f111d879": ("Tuscany Village", "kWh"),
    "227239a6-fbf2707d": ("Tuscany Village", "ft³"),
    "227239a7-08b0fbe2": ("Tuscany Village", "kWh"),
    "227239a7-35351d6d": ("Tuscany Village", "gal"),
    "227239a7-4d43f006": ("Tuscany Village", "kWh"),
    "227239a7-5315c733": ("Tuscany Village", "ft³"),
    "227239a7-58783ae5": ("Tuscany Village", "kWh"),
    "227239a7-98254fc2": ("Tuscany Village", "kWh"),
    "227239a7-9a0372a4": ("Tuscany Village", "ft³"),
    "227239a7-9b9e47a8": ("Tuscany Village", "gal"),
    "227239a7-b530f4f7": ("Tuscany Village", "kWh"),
    "227239a7-c527f8bb": ("Tuscany Village", "gal"),
    "227239a7-e579cd5e": ("Tuscany Village", "ft³"),
    "25335b19-ac5587eb": ("Tuscany Village", "ft³"),
    "25335c14-0e156d62": ("Tuscany Village", "gal"),
    "2537688b-e8590060": ("Tuscany Village", "gal"),
}

# ── Regex patterns ────────────────────────────────────────────────────────
_CELL_RE    = re.compile(r"^([\d.]+)(_?)([a-zA-Z³]+)$")
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
    if column_name.strip() in POINT_ID_MAP:
        return column_name.strip()
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
    if unit in NATIVE_VOLUME_UNITS:
        return "volume"
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

    strict_units = {pid: unit for pid, (building, unit) in POINT_ID_MAP.items()
                    if building == "Tuscany Village"}
    strict_feed = (any(extract_point_id(str(col)) in strict_units for col in df.columns[1:])
                   or "intervalSubmeterReportsTuscanyVillage" in str(path))
    if strict_feed:
        unknown = [str(col) for col in df.columns[1:]
                   if extract_point_id(str(col)) not in POINT_ID_MAP]
        if unknown:
            stats["error"] = "Unregistered meter headers: " + ", ".join(unknown)
            return pd.DataFrame(), stats

    ts_col = df.columns[0]
    stats["rows_in"] = len(df)

    # Normalise timestamp — handles ISO-8601+Los_Angeles AND MM/DD/YYYY HH:MM:SS
    raw_ts = df[ts_col].astype(str).str.replace(_TZ_SUFFIX, "", regex=True)
    df["_ts"] = pd.to_datetime(raw_ts, errors="coerce")
    if strict_feed and df["_ts"].isna().any():
        stats["error"] = "Invalid timestamp in submeter report"
        return pd.DataFrame(), stats
    df = df.dropna(subset=["_ts"]).copy()
    merge_dst_fold = False
    if strict_feed and df["_ts"].duplicated().any():
        # The existing DB key uses campus wall time. A genuine fall-back hour
        # therefore needs one summed bucket per repeated wall-clock quarter hour.
        # Infer only a valid, ordered LA clock transition within this source file;
        # ordinary/conflicting duplicate reports must still fail visibly.
        try:
            absolute = df["_ts"].dt.tz_localize("America/Los_Angeles", ambiguous="infer", nonexistent="raise").dt.tz_convert("UTC")
            if absolute.duplicated().any() or not absolute.is_monotonic_increasing:
                raise ValueError("Repeated non-DST timestamp")
            counts = df["_ts"].value_counts()
            repeated = counts[counts > 1]
            if not repeated.eq(2).all():
                raise ValueError("More than two repeated clock intervals")
            merge_dst_fold = True
            stats["dst_fold_wall_intervals"] = int(len(repeated))
        except Exception:
            stats["error"] = "Duplicate timestamps do not form a valid campus daylight-saving transition"
            return pd.DataFrame(), stats
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
            if pid in strict_units and pd.notna(cell) and str(cell).strip():
                if (num is None or not pd.notna(num) or not float("-inf") < num < float("inf")
                        or num < 0 or cell_unit != strict_units[pid]):
                    stats["error"] = f"Invalid value/unit for {pid}: {cell}"
                    return pd.DataFrame(), stats
            if num is None:
                continue
            unit  = _resolve_unit(map_unit, cell_unit)
            table = route_unit(unit)
            if table is None:
                continue
            out.append({
                "timestamp": row["_ts_str"],
                "location":  (_PID_PREFIX + pid) if pid in strict_units else col,
                "point_id":  pid,
                "building":  building,
                "value":     num,
                "unit":      unit,
                "table":     table,
            })
            stats["dates"].add(row["_date"])

    result = pd.DataFrame(out)
    if merge_dst_fold and not result.empty:
        result = result.groupby(["timestamp", "location", "point_id", "building", "unit", "table"], as_index=False, sort=False)["value"].sum()
    stats["rows_out"] = len(result)
    return result, stats


def to_kwh(value: float, unit: str) -> float:
    """Convert any ENERGY_UNITS value to kWh. Returns 0.0 for non-energy units."""
    return value * UNIT_TO_KWH.get(unit, 0.0) if unit in ENERGY_UNITS else 0.0
