"""The whole diff in one call: load two cycles, diff, collapse, summarize, add charts."""
import datetime as dt
import hashlib
import os
import re
import time
from collections import defaultdict

from .collapse import collapse, merge_freq_uses
from .diff import diff
from .dtpp import load_dtpp
from .english import summarize
from .nasr import NearIndex, airport_ids, load
from .procedures import airports_by_procedure, load_routes
from .remarks import translate_remarks
from .rules import REMARK_FILES, base

PRIORITY_ORDER = {"action": 0, "ifr": 1, "fyi": 2}

CATEGORY = [  # (source prefix, category) - first match wins
    ("CLS_ARSP", "airspace"), ("ATC", "tower"), ("FRQ", "frequency"), ("NAV", "navaid"),
    ("ILS", "navaid"), ("APT_RWY", "runway"), ("APT_RMK", "remark"), ("STAR/DP", "procedure"),
    ("PFR", "route"), ("D-TPP", "chart"), ("AWOS", "weather"), ("APT", "airport"),
]


def category(source):
    s = source.upper()
    if s.startswith("ATC_RMK"):
        return "remark"
    return next((c for prefix, c in CATEGORY if s.startswith(prefix)), "other")


def cycle_label(path):
    """'03_Sep_2026_CSV.zip' or '2026-09-03_CSV.zip' -> '2026-09-03'; anything else -> filename."""
    name = os.path.basename(path)
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    m = re.search(r"(\d{2})_([A-Za-z]{3})_(\d{4})", name)
    if m:
        return dt.datetime.strptime("-".join(m.groups()), "%d-%b-%Y").date().isoformat()
    return name


def change_id(airport, to_cycle, summary):
    """stable id so the app can remember which changes you've already seen."""
    return hashlib.sha1(f"{airport}|{to_cycle}|{summary}".encode()).hexdigest()[:12]


def to_change(rec, airport, to_cycle):
    """internal record -> the public JSON shape (see SCHEMA.md)."""
    out = {
        "id": change_id(airport, to_cycle, rec["summary"]),
        "priority": rec["priority"],
        "category": category(rec["source"]),
        "kind": rec["kind"],
        "summary": rec["summary"],
        "source": base(rec["source"]),
    }
    for k in ("original", "fields", "details", "procedures", "chart"):
        if rec.get(k):
            out[k] = rec[k]
    return out


def run(old_zip, new_zip, ids=None, dtpp_path=None, llm=False, log=print):
    """diff two NASR CSV zips. ids=None means every airport.
    returns {"from_cycle", "to_cycle", "airports": {apt: [change, ...]}, "hidden": {apt: n}}"""
    t0 = time.time()
    all_mode = ids is None
    if all_mode:
        ids = airport_ids(old_zip) | airport_ids(new_zip)
        log(f"all-airports mode: {len(ids)} airports")
    from_cycle, to_cycle = cycle_label(old_zip), cycle_label(new_zip)

    log(f"loading {old_zip} ...")
    near = NearIndex.from_zip(new_zip) if all_mode else None
    proc_airports = airports_by_procedure(old_zip, new_zip)
    old = load(old_zip, ids, strict=all_mode, near=near, proc_airports=proc_airports)
    log(f"loading {new_zip} ...")
    new = load(new_zip, ids, strict=all_mode, near=near, proc_airports=proc_airports)
    log(f"  loaded in {time.time() - t0:.0f}s, diffing ...")

    records = diff(old, new)
    texts = []
    for r in records:
        if base(r["source"]) in REMARK_FILES:
            texts.append(r.get("row", {}).get("REMARK", ""))
            texts += [f["new"] for f in r.get("fields", []) if f["field"] == "REMARK"]
    remarks = translate_remarks(texts, llm)
    routes = (load_routes(old_zip), load_routes(new_zip))
    records = merge_freq_uses(collapse(records, routes))

    # summarize; drop phrases already said at that airport (tower hours live in 3 files)
    by_apt, hidden = defaultdict(list), defaultdict(int)
    for r in records:
        s = summarize(r, remarks)
        r["_phrases"] = s if isinstance(s, list) else [s]
        if r["priority"] == "hidden":
            hidden[r["airport"]] += 1
        else:
            by_apt[r["airport"]].append(r)
    for apt in list(by_apt):
        seen, uniq = set(), []
        for r in sorted(by_apt[apt], key=lambda r: (r["priority"] != "action", r["_phrases"])):
            phrases = [p for p in r.pop("_phrases") if p not in seen]
            if phrases:
                seen.update(phrases)
                r["summary"] = "; ".join(phrases)
                uniq.append(r)
        by_apt[apt] = uniq

    if dtpp_path:
        log(f"loading d-TPP {dtpp_path} ...")
        charts = load_dtpp(dtpp_path, ids)
        for apt, recs in charts.items():
            for r in recs:
                r["summary"] = r["summary_override"]
            by_apt[apt].extend(recs)
        log(f"  {sum(len(v) for v in charts.values())} chart changes at {len(charts)} airports")

    airports = {}
    for apt, recs in by_apt.items():
        if not recs:
            continue
        recs = sorted(recs, key=lambda r: PRIORITY_ORDER[r["priority"]])  # stable
        airports[apt] = [to_change(r, apt, to_cycle) for r in recs]
    return {"from_cycle": from_cycle, "to_cycle": to_cycle, "airports": airports,
            "hidden": dict(hidden), "seconds": time.time() - t0}


def counts(changes):
    return {p: sum(c["priority"] == p for c in changes) for p in ("action", "ifr", "fyi")}