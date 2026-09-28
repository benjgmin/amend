"""The whole diff in one call: load two cycles, diff, collapse, summarize, add charts and airspace."""
import datetime as dt
import hashlib
import json
import os
import re
import time
from collections import defaultdict

from . import airspace as arsp
from .collapse import collapse, is_frq_remark, merge_freq_uses
from .diff import diff
from .dtpp import load_dtpp
from .english import plain_values, record_values, summarize, unsupported
from .nasr import NearIndex, airport_ids, load
from .procedures import airports_by_procedure, load_routes
from .remarks import translate_remarks
from .rules import REMARK_FILES, base

PRIORITY_ORDER = {"action": 0, "ifr": 1, "fyi": 2}

CATEGORY = [  # (source prefix, category) - first match wins
    ("CLS_ARSP", "airspace"), ("ATC", "tower"), ("FRQ", "frequency"), ("NAV", "navaid"),
    ("ILS", "navaid"), ("APT_RWY", "runway"), ("APT_RMK", "remark"), ("STAR/DP", "procedure"),
    ("PFR", "route"), ("D-TPP", "chart"), ("AWOS", "weather"), ("APT", "airport"),
    ("PJA", "airspace"), ("RDR", "tower"),
]


def category(source):
    s = source.upper()
    if base(s) in REMARK_FILES:   # an ILS or tower remark is still a remark, not a navaid/tower
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


def change_key(rec):
    """what a change is, whatever words describe it: its file, kind and FAA values. rewording a
    summary or a better remark translation keeps the id, so 'new since you last looked' holds."""
    k = {"source": base(rec["source"]), "kind": rec["kind"]}
    for f in ("row", "fields", "context", "procedures", "folded", "chart", "key"):
        if rec.get(f):
            k[f] = rec[f]
    if len(k) == 2:      # airspace shape changes carry nothing else: their text is the change
        k["summary"] = rec["summary"]
    return json.dumps(k, sort_keys=True, ensure_ascii=False)


def change_id(airport, to_cycle, key):
    """stable id so the app can remember which changes you've already seen."""
    return hashlib.sha1(f"{airport}|{to_cycle}|{key}".encode()).hexdigest()[:12]


def row_fields(rec):
    """a whole row added or removed, as the fields it brought or took away: the FAA values
    behind the summary, published with it. contact names stay in their summary only."""
    row = rec.get("row")
    if not row or rec.get("fields") or rec.get("original") or base(rec["source"]) == "APT_CON":
        return None
    old = rec["kind"] == "removed"
    return [{"field": k, "old": v if old else "", "new": "" if old else v}
            for k, v in row.items() if not k.startswith("_")]


def to_change(rec, airport, to_cycle):
    """internal record -> the public JSON shape (see SCHEMA.md)."""
    out = {
        "id": change_id(airport, to_cycle, change_key(rec)),
        "priority": rec["priority"],
        "category": ("remark" if is_frq_remark(rec)
                     else rec.get("category") or category(rec["source"])),
        "kind": rec["kind"],
        "summary": rec["summary"],
        "source": base(rec["source"]),
    }
    for k in ("original", "fields", "details", "procedures", "chart"):
        if rec.get(k):
            out[k] = rec[k]
    if "fields" not in out and row_fields(rec):
        out["fields"] = row_fields(rec)
    return out


def check_summaries(recs, log):
    """every number and identifier in a summary must be in the FAA record it came from. one
    that isn't is a template bug: the record shows the FAA values instead, and it's counted.
    remark text (rec['original']) is checked by remarks.problems() before it's ever used."""
    bad = 0
    for r in recs:
        if r.get("original"):
            continue
        miss = unsupported(r["summary"], record_values(r))
        if miss:
            bad += 1
            log(f"  {r['airport']}: summary has {', '.join(miss)} which the FAA record doesn't: {r['summary']!r}")
            r["summary"] = plain_values(r)
    return bad


def run(old_zip, new_zip, ids=None, dtpp_path=None, llm=False, log=print, airspace=None):
    """diff two NASR CSV zips. ids=None means every airport.
    airspace: optional (old, new) class airspace shapefile zips for floor/ceiling/boundary changes.
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
        elif is_frq_remark(r):
            texts.append(r["fields"][0]["new"])
    remarks = translate_remarks(texts, llm)
    routes = (load_routes(old_zip), load_routes(new_zip))
    records = merge_freq_uses(collapse(records, routes))

    # summarize; drop phrases already said at that airport (tower hours live in 3 files)
    by_apt, hidden = defaultdict(list), defaultdict(int)
    no_template = defaultdict(int)
    for r in records:
        s = summarize(r, remarks)
        r["_phrases"] = s if isinstance(s, list) else [s]
        if r.pop("no_template", False):
            # no English written for this file yet: FAA column names aren't an alert
            no_template[f"{base(r['source'])} {r['kind']}"] += 1
            if r["priority"] in ("action", "ifr"):
                r["priority"] = "fyi"
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
    for k, n in sorted(no_template.items()):
        log(f"  no English for {k} rows ({n}), shown with FAA column names")
    mismatched = check_summaries([r for recs in by_apt.values() for r in recs], log)

    if dtpp_path:
        log(f"loading d-TPP {dtpp_path} ...")
        charts = load_dtpp(dtpp_path, ids)
        for apt, recs in charts.items():
            for r in recs:
                r["summary"] = r["summary_override"]
            by_apt[apt].extend(recs)
        log(f"  {sum(len(v) for v in charts.values())} chart changes at {len(charts)} airports")

    if airspace:
        try:
            old_a, new_a = (arsp.load(p) for p in airspace)
        except Exception as e:     # a surprise in the shapefile must never stop the daily run
            log(f"  couldn't read the class airspace shapefile ({e}), skipping airspace shapes")
            old_a = new_a = None
        if old_a is None or new_a is None:
            log("  no class airspace shapefile in one of the airspace zips, skipping airspace shapes")
        else:
            recs = arsp.diff(old_a, new_a, near or NearIndex.from_zip(new_zip), ids)
            for r in recs:
                by_apt[r["airport"]].append(r)
            log(f"  {len(recs)} airspace shape changes")

    airports = {}
    for apt, recs in by_apt.items():
        # charts and airspace skip the phrase dedup above; an E3 and E4 extension changed
        # together read the same, and one line twice is noise (and one id twice)
        seen = set()
        recs = [r for r in recs if not (r["summary"] in seen or seen.add(r["summary"]))]
        if not recs:
            continue
        recs = sorted(recs, key=lambda r: PRIORITY_ORDER[r["priority"]])  # stable
        out, ids_seen = [], set()
        for r in recs:
            c = to_change(r, apt, to_cycle)
            n = 1
            while c["id"] in ids_seen:    # two rows that differ only in dropped survey columns
                n += 1
                c["id"] = change_id(apt, to_cycle, f"{change_key(r)}#{n}")
            ids_seen.add(c["id"])
            out.append(c)
        airports[apt] = out
    return {"from_cycle": from_cycle, "to_cycle": to_cycle, "airports": airports,
            "hidden": dict(hidden), "seconds": time.time() - t0,
            "checks": {"no_english": dict(no_template), "summary_value_mismatches": mismatched}}


def counts(changes):
    return {p: sum(c["priority"] == p for c in changes) for p in ("action", "ifr", "fyi")}