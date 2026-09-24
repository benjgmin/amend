"""
Waypoint-level detail for STAR / DP changes.

NASR lists every point of every arrival (STAR_RTE) and departure (DP_RTE). When a procedure
gets a new version (TTHOR2 -> TTHOR3), comparing the two versions' points and transitions
says what actually changed: "waypoints added WOXXO; removed LAANA; transition COL removed".
"""
import csv
import io
import re
import zipfile
from collections import defaultdict

from .nasr import decode, iter_csvs

ROUTE_FILES = {"STAR_RTE.CSV": "STAR_COMPUTER_CODE", "DP_RTE.CSV": "DP_COMPUTER_CODE"}
POINT_COLS = ("POINT", "FIX_ID", "POINT_ID")


def split_code(code):
    """'SNFLD.SNFLD3' (STAR) or 'CONLE5.CONLE' (DP) -> ('SNFLD3', 'SNFLD').
    the versioned part (ends in a digit) is the procedure; the other part is the transition fix."""
    parts = [p for p in (code or "").upper().split(".") if p]
    if not parts:
        return "", ""
    versioned = [p for p in parts if p[-1].isdigit()]
    name = versioned[-1] if versioned else parts[-1]
    other = next((p for p in parts if p != name), "")
    return name, other


def load_routes(zip_path):
    """{procedure name: {"points": set, "transitions": set}} for every STAR and DP in a cycle."""
    out = defaultdict(lambda: {"points": set(), "transitions": set()})
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            code_col = ROUTE_FILES.get(fname.upper())
            if not code_col:
                continue
            for row in csv.DictReader(io.StringIO(decode(raw), newline="")):
                row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                name, fix = split_code(row.get(code_col, ""))
                if not name:
                    continue
                point = next((row[c] for c in POINT_COLS if row.get(c)), "")
                if point:
                    out[name]["points"].add(point.upper())
                if "TRANS" in row.get("ROUTE_PORTION_TYPE", "").upper():
                    # real NASR has TRANSITION_COMPUTER_CODE ("CRG.SNFLD3"): its fix part names it
                    tcc = split_code(row.get("TRANSITION_COMPUTER_CODE", ""))[1]
                    trans = tcc or fix or row.get("ROUTE_NAME", "").split("-")[0]
                    if trans:
                        out[name]["transitions"].add(trans.upper())
    return dict(out)


def _join(items):
    return ", ".join(sorted(items))


def describe(new_name, old_name, old_routes, new_routes):
    """one plain-English line about how a procedure changed between versions."""
    new = new_routes.get(new_name)
    if old_name is None:
        if not new:
            return f"{new_name}: new procedure"
        t = f"; transitions {_join(new['transitions'])}" if new["transitions"] else ""
        return f"{new_name}: new procedure{t}"
    old = old_routes.get(old_name)
    label = new_name if old_name == new_name else f"{new_name} (was {old_name})"
    if not old or not new:
        return f"{label}: route details not available"
    bits = []
    added, removed = new["points"] - old["points"], old["points"] - new["points"]
    if added:
        bits.append(f"waypoints added {_join(added)}")
    if removed:
        bits.append(f"waypoints removed {_join(removed)}")
    t_add = new["transitions"] - old["transitions"]
    t_rem = old["transitions"] - new["transitions"]
    if t_add:
        bits.append(f"transitions added {_join(t_add)}")
    if t_rem:
        bits.append(f"transitions removed {_join(t_rem)}")
    if not bits:
        return (f"{label}: same waypoints and transitions; "
                f"altitudes, speeds or notes may have changed, check the chart")
    return f"{label}: " + "; ".join(bits)


def stem(name):
    return re.sub(r"\d+$", "", name)


APT_FILES = {"STAR_APT.CSV": "STAR_COMPUTER_CODE", "DP_APT.CSV": "DP_COMPUTER_CODE"}


def airports_by_procedure(*zip_paths):
    """{procedure name: {airport ids}} from STAR_APT / DP_APT, so route rows can be attributed."""
    out = defaultdict(set)
    for zp in zip_paths:
        with zipfile.ZipFile(zp) as zf:
            for fname, raw in iter_csvs(zf):
                code_col = APT_FILES.get(fname.upper())
                if not code_col:
                    continue
                for row in csv.DictReader(io.StringIO(decode(raw), newline="")):
                    name = split_code((row.get(code_col) or "").strip())[0]
                    apt = (row.get("ARPT_ID") or "").strip().upper()
                    if name and apt:
                        out[name].add(apt)
    return dict(out)