#!/usr/bin/env python3
"""
nasr_diff.py - tell pilots what changed at their airports between two FAA NASR cycles.

usage:
    python nasr_diff.py OLD.zip NEW.zip VRB DAB ISM [--json] [--raw] [--all] [--llm]
    python nasr_diff.py OLD.zip NEW.zip --all-airports [--llm]

OLD/NEW  "Data in CSV format" zips from
         https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/
ids      FAA 3-letter ids (VRB, not KVRB). K-prefixed 4-letter ids get stripped.

--json   write out/<AIRPORT>.json + out/index.json (what the app reads)
--raw    print field-level before/after under each summary line
--all    also print hidden noise changes
--routes list every preferred route / procedure change instead of one summary line
--all-airports  diff EVERY airport (no ids needed). writes out/ json + prints a summary.
               add --print to also dump every airport to the terminal.
--out DIR      where json goes (default: out)
--dtpp FILE    also report approach/departure/STAR/diagram chart changes from the FAA
               d-TPP metafile (d-TPP_Metafile.xml for the NEW cycle)
--llm    translate FAA remarks to plain english with Claude
         (key comes from .env or ANTHROPIC_API_KEY; results cached in remark_cache.json)

one-time setup:
    python nasr_diff.py --set-key      (paste your key, saved to .env, never printed)
"""
import csv
import io
import re
import json
import os
import sys
import urllib.request
import zipfile
from collections import defaultdict

# ---------------------------------------------------------------- config

IGNORE_COLS = {"EFF_DATE", "LAST_INFO_RESPONSE", "LAST_INFO_RESPONSE_DATE"}

# identity columns: hidden in summaries
ID_COLS = {"SITE_NO", "SITE_TYPE_CODE", "STATE_CODE", "CITY", "COUNTRY_CODE", "ARPT_ID"}

# columns that decide which airport a row belongs to, in order of preference.
# FRQ rows use SERVICED_FACILITY so "DAB approach serving NSB" goes to NSB, not DAB.
ATTRIB_COLS = ("ARPT_ID", "SERVICED_FACILITY", "FACILITY_ID", "NAV_ID", "LOC_ID",
               "ASOS_AWOS_ID", "Orig", "Dest", "ORIGIN_ID", "DSTN_ID")

# when pairing an old row with a new row, these must match (if the file has them)
PAIR_KEYS = {
    "PFR_RMT_FMT": ("Orig", "Dest", "Type"),
    "APT_RMK": ("LEGACY_ELEMENT_NUMBER",),
    "ATC_RMK": ("LEGACY_ELEMENT_NUMBER", "REMARK_NO"),
    "APT_RWY_END": ("RWY_ID", "RWY_END_ID"),
    "APT_RWY": ("RWY_ID",),
    "FRQ": ("SERVICED_FACILITY", "FREQ"),
    "NAV_BASE": ("NAV_ID",),
    "ATC_BASE": ("FACILITY_ID",),
    "CLS_ARSP": ("ARPT_ID",),
    "AWOS": ("ASOS_AWOS_ID",),
    "APT_ATT": ("ARPT_ID",),
    "APT_BASE": ("ARPT_ID",),
}

# columns that are rounding / bookkeeping noise and get stripped from changes
def is_noise_col(c):
    if c in HIDDEN_ONLY_COLS:
        return True
    c = c.upper()
    return (c.startswith(("LAT_", "LONG_", "MAG_VARN")) or
            c.endswith(("SRC_DATE", "SOURCE_DATE")) or
            c in {"LEGACY_ELEMENT_NUMBER", "REF_COL_SEQ_NO", "SEQ", "ALT_CODE", "ELEV", "DME_SSV"})

HIDDEN_FILES = ("PFR_SEG", "PFR_BASE", "LID")
HIDDEN_ONLY_COLS = {"AIR_TAXI_OPS", "ANNUAL_OPS_DATE", "BASED_GLIDERS", "BASED_HEL",
                    "BASED_JET_ENG", "BASED_MIL_ACFT", "BASED_MULTI_ENG", "BASED_SINGLE_ENG",
                    "BASED_ULTRALGT_ACFT", "COMMERCIAL_OPS", "COMMUTER_OPS", "ITNRNT_OPS",
                    "LOCAL_OPS", "MIL_ACFT_OPS", "LAST_INSPECTION", "LENGTH_SOURCE_DATE",
                    "PAVEMENT_CLASSIFICATION", "PCN_PCR_NUMBER", "PCN", "PAVEMENT_TYPE_CODE",
                    "SUBGRADE_STRENGTH_CODE", "TIRE_PRES_CODE", "DTRM_METHOD_CODE",
                    "GROSS_WT_SW", "GROSS_WT_DW", "GROSS_WT_DTW", "GROSS_WT_DDTW"}
NAME_COLS = {"FACILITY_NAME", "FAC_NAME", "SERVICED_FAC_NAME", "NAME", "ARPT_NAME"}
FYI_ONLY_COLS = {"OBSTN_HGT", "OBSTN_CLNC_SLOPE", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE",
                 "DIST_FROM_THR", "FREQ_USE", "RWY_MARKING_COND", "COND"}

ACTION_PREFIXES = ("ATC", "CLS_ARSP", "FRQ", "ILS", "APT_ATT", "AWOS")
ACTION_COL_WORDS = {"NAV", "PROVIDER", "HRS", "HOURS", "FREQ", "CLASS", "AIRSPACE", "CLOSED",
                    "STATUS", "LGT", "LIGHT", "LIGHTS", "LEN", "WIDTH", "TPA", "ATTEND"}
ACTION_TEXT_WORDS = ("CLSD", "CLOSED", "TWR", "PPR", "NOT AVBL", "UNAVBL", "CTAF", "TPA",
                     "PROHIBITED", "RSTD", "NOISE", "TRANSPONDER")

CONTEXT_COLS = ("Orig", "Dest", "Route String", "FREQ", "FREQ_USE", "NAV_ID", "NAV_TYPE",
                "RWY_ID", "RWY_END_ID", "ELEMENT", "SERVICED_FACILITY", "REMARK",
                "STAR_COMPUTER_CODE", "DP_COMPUTER_CODE", "NAME", "OBSTN_HGT", "DIST_FROM_THR",
                "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE", "OBSTN_TYPE")

NAV_NAMES = {"VOT": "VOR test signal (VOT)", "VORTAC": "VORTAC", "VOR/DME": "VOR/DME",
             "DME": "DME", "NDB": "NDB", "VOR": "VOR", "TACAN": "TACAN"}

LLM_MODEL = "claude-haiku-4-5-20251001"
# FAA contractions the model is allowed to expand. anything not here and not certain stays as-is.
GLOSSARY = ("ACFT=aircraft, ACR=air carrier, AP=airport, ARPT=airport, ARR=arrival, "
            "AVBL=available, CK=check, CLSD=closed, CTC=contact, CTN=caution, DEP=departure, "
            "DTLS=details, HOL=holidays, INVOF=in vicinity of, LGTD=lighted, "
            "MNT/MNTD=monitored, MRKGS=markings, NA=not authorized, OPS=operations, "
            "PAX=passengers, PPR=prior permission required, RSCD=runway surface condition, "
            "RWY=runway, SKED=scheduled, TWY=taxiway, UNSKED=unscheduled, WKEND=weekend, "
            "WX=weather, M-F=Monday through Friday")
CACHE_FILE = "remark_cache.json"

# ---------------------------------------------------------------- loading

def iter_csvs(zf):
    for name in zf.namelist():
        low = name.lower()
        if low.endswith(".csv"):
            yield name.split("/")[-1], zf.read(name)
        elif low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                yield from iter_csvs(inner)


# files where a row can mention our airport while being ABOUT another one
# (DAB approach serving NSB, a route from DAB to ATL). only these use strict attribution.
STRICT_FILES = ("FRQ", "PFR")


def attribute(row, ids, fname="", strict=False):
    """which of our airports this row belongs to (list; routes can belong to both ends)."""
    if base(fname).startswith("PFR"):
        return sorted({row[c].upper() for c in ("Orig", "Dest", "ORIGIN_ID", "DSTN_ID")
                       if row.get(c, "").upper() in ids})
    for col in ATTRIB_COLS:
        if col in row and row[col].upper() in ids:
            return [row[col].upper()]
    if strict or base(fname).startswith(STRICT_FILES):
        return []  # row is about something else
    for v in row.values():
        if v.upper() in ids:
            return [v.upper()]
    return []


def airport_ids(zip_path):
    """every airport id in a cycle, from APT_BASE."""
    out = set()
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            if fname.upper() == "APT_BASE.CSV":
                text = raw.decode("latin-1").lstrip("\ufeff").lstrip("ï»¿")
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                for row in csv.DictReader(io.StringIO(text, newline="")):
                    a = (row.get("ARPT_ID") or "").strip().upper()
                    if a:
                        out.add(a)
                break
    return out


def load(zip_path, ids, strict=False):
    """return {filename: [(airport, row), ...]}"""
    out = defaultdict(list)
    seen = set()
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            up = fname.upper()
            if ("_CHG_RPT" in up or "DATA_STRUCTURE" in up or fname in seen
                    or base(fname).startswith(HIDDEN_FILES)):
                continue
            seen.add(fname)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
            reader = csv.DictReader(io.StringIO(text, newline=""))
            try:
                for row in reader:
                    vals = {(v or "").strip().upper() for v in row.values() if isinstance(v, str)}
                    if not vals & ids:
                        continue
                    clean = {k.strip(): (v or "").strip() for k, v in row.items()
                             if k and k.strip() not in IGNORE_COLS}
                    for apt in attribute(clean, ids, fname, strict):
                        out[fname].append((apt, clean))
            except csv.Error as e:
                print(f"  warning: skipped rest of {fname}: {e}")
    return out

# ---------------------------------------------------------------- diffing

def base(fname):
    return fname.upper().replace(".CSV", "")


def similarity(a, b):
    keys = set(a) | set(b)
    return sum(a.get(k) == b.get(k) for k in keys) / max(len(keys), 1)


def can_pair(fname, a, b):
    for k in PAIR_KEYS.get(base(fname), ()):
        if k in a and a.get(k) != b.get(k):
            return False
    return True


def keyed(fname, a):
    """true if this file has pair keys and the row has them - a key match is enough to pair."""
    keys = PAIR_KEYS.get(base(fname), ())
    return bool(keys) and all(k in a for k in keys)


def priority(fname, kind, cols, values):
    b = base(fname)
    cols = [c for c in cols if c not in ID_COLS]
    if b.startswith(HIDDEN_FILES):
        return "hidden"
    if kind == "changed" and not cols:
        return "hidden"
    if cols and all(c in HIDDEN_ONLY_COLS for c in cols):
        return "hidden"
    if any("PCR VALUE" in v.upper() for v in values):
        return "hidden"
    if cols and all(c in NAME_COLS or c in FYI_ONLY_COLS or c in HIDDEN_ONLY_COLS for c in cols):
        return "fyi"
    if b.startswith(ACTION_PREFIXES):
        return "action"
    for c in cols:
        if set(c.upper().split("_")) & ACTION_COL_WORDS:
            return "action"
    # routes and procedures are never action (they're long strings full of fix names)
    if b.startswith(("PFR", "STAR", "DP")):
        return "fyi"
    for v in values:
        if any(re.search(rf"\b{re.escape(w)}\b", v.upper()) for w in ACTION_TEXT_WORDS):
            return "action"
    return "fyi"


def just_reworded(old, new):
    """same numbers/ids and mostly the same words -> the FAA just reworded it."""
    import difflib
    nums = lambda s: set(re.findall(r"[A-Z]*\d+[A-Z0-9/]*", s.upper()))
    if nums(old) != nums(new):
        return False
    return difflib.SequenceMatcher(None, old.upper(), new.upper()).ratio() >= 0.6


def diff(old, new):
    records = []
    for fname in sorted(set(old) | set(new)):
        o, n = defaultdict(dict), defaultdict(dict)
        for apt, r in old.get(fname, []):
            o[apt][tuple(sorted(r.items()))] = r
        for apt, r in new.get(fname, []):
            n[apt][tuple(sorted(r.items()))] = r

        for apt in sorted(set(o) | set(n)):
            removed = [o[apt][k] for k in o[apt].keys() - n[apt].keys()]
            added = [n[apt][k] for k in n[apt].keys() - o[apt].keys()]

            for r in list(removed):
                best, score = None, 0.0
                for a in added:
                    if not can_pair(fname, r, a):
                        continue
                    s = similarity(r, a)
                    if best is None or s > score:
                        best, score = a, s
                if best is None or (score < 0.5 and not keyed(fname, r)):
                    continue
                removed.remove(r)
                added.remove(best)
                cols = sorted(c for c in set(r) | set(best)
                              if r.get(c, "") != best.get(c, "") and not is_noise_col(c))
                vals = [r.get(c, "") for c in cols] + [best.get(c, "") for c in cols]
                pri = priority(fname, "changed", cols, vals)
                if cols == ["REMARK"] and just_reworded(r["REMARK"], best["REMARK"]):
                    pri = "fyi"
                records.append({
                    "airport": apt, "source": fname, "kind": "changed",
                    "priority": pri,
                    "fields": [{"field": c, "old": r.get(c, ""), "new": best.get(c, "")} for c in cols],
                    "context": {c: best[c] for c in CONTEXT_COLS if best.get(c)},
                })

            still_there = {r.get("FREQ") for r in n[apt].values()}
            existed = {r.get("FREQ") for r in o[apt].values()}
            for kind, rows in (("removed", removed), ("added", added)):
                for r in rows:
                    if base(fname) == "FRQ" and kind == "removed" and r.get("FREQ") in still_there:
                        records.append({
                            "airport": apt, "source": fname, "kind": "changed", "priority": "fyi",
                            "fields": [{"field": "FREQ_USE", "old": r.get("FREQ_USE", ""), "new": ""}],
                            "context": {"FREQ": r.get("FREQ", "")},
                            "note": "frequency still in use, one listed use was dropped"})
                        continue
                    pri = priority(fname, kind, list(r.keys()), list(r.values()))
                    if base(fname) == "FRQ" and (
                            (kind == "added" and r.get("FREQ") in existed)
                            or re.search(r"\b(STAR|SID|DP)\b", r.get("FREQ_USE", "").upper())):
                        pri = "fyi"  # same freq, new label / procedure listing: not a new frequency
                    records.append({
                        "airport": apt, "source": fname, "kind": kind,
                        "priority": pri,
                        "row": {k: v for k, v in r.items()
                                if v and k not in ID_COLS and not is_noise_col(k)},
                    })
    return records

# ---------------------------------------------------------------- plain english

def translate_remarks(texts, use_llm):
    """map raw FAA remark -> plain english. cached; falls back to raw text."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    todo = sorted({t for t in texts if t and t not in cache})
    key = os.environ.get("ANTHROPIC_API_KEY")
    if use_llm and todo and not key:
        print("  warning: --llm set but ANTHROPIC_API_KEY missing, using raw remarks")
    if use_llm and todo and key:
        if len(todo) > 30:
            print(f"  translating {len(todo)} remarks with Claude ...")
        for i in range(0, len(todo), 30):
            batch = todo[i:i + 30]
            if len(todo) > 300 and i % 300 == 0:
                print(f"    {i}/{len(todo)}")
            prompt = (
                "Translate each FAA airport/ATC remark below into ONE short plain-English "
                "sentence a student pilot would understand.\n"
                "Rules:\n"
                "- Expand ONLY abbreviations listed in the glossary or ones you are certain of.\n"
                "- If you are not certain what an abbreviation or acronym means, leave it "
                "exactly as written. Never guess an expansion. A wrong expansion is dangerous.\n"
                "- Keep all numbers, times, runway ids, frequencies and phone numbers exactly.\n"
                "- Do not add or remove information. Keep every regulatory reference "
                "(Part 121, Part 135, Part 380, FAR, etc.) exactly as written.\n"
                "Glossary: " + GLOSSARY + "\n"
                "Return ONLY a JSON array of strings, same order and same length as the input.\n\n"
                + json.dumps(batch, indent=1))
            body = json.dumps({"model": LLM_MODEL, "max_tokens": 4000,
                               "messages": [{"role": "user", "content": prompt}]}).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=body,
                headers={"content-type": "application/json", "x-api-key": key,
                         "anthropic-version": "2023-06-01"})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.load(resp)
                text = "".join(b.get("text", "") for b in data.get("content", []))
                text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
                out = json.loads(text)
                if len(out) == len(batch):
                    cache.update(dict(zip(batch, out)))
                else:
                    print("  warning: llm returned wrong number of remarks, skipping batch")
            except Exception as e:
                print(f"  warning: llm call failed ({e}), using raw remarks")
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=1)
    return cache


def label(field):
    return field.replace("_", " ").lower()


def field_phrases(fields, source, ctx=None):
    ctx = ctx or {}
    by = {f["field"]: f for f in fields}
    phrases = []
    done = set()

    def hrs(f):
        return f or "none listed"

    for k in ("TWR_HRS", "TOWER_HRS"):
        if k in by and "tower" not in done:
            f = by[k]
            phrases.append(f"tower hours changed: {hrs(f['old'])} -> {hrs(f['new'])} local")
            done |= {"tower", k}
    if "AIRSPACE_HRS" in by:
        f = by["AIRSPACE_HRS"]
        phrases.append(f"airspace is now: {f['new'].lower()} (was: {f['old'].lower()})")
    prov = [by[k] for k in ("APCH_P_PROVIDER", "DEP_P_PROVIDER") if k in by]
    if prov:
        phrases.append(f"approach/departure control now provided by {prov[0]['new']} "
                       f"(was {prov[0]['old']})")
    if "HOUR" in by and base(source) == "APT_ATT":
        f = by["HOUR"]
        phrases.append(f"airport attendance hours changed: {f['old']} -> {f['new']}")
    if "PHONE_NO" in by:
        what = ("AWOS/ASOS " if base(source).startswith("AWOS")
                else "airport " if base(source).startswith("APT") else "")
        phrases.append(f"{what}phone number changed to {by['PHONE_NO']['new']}")
    if "LNDG_FEE_FLAG" in by:
        phrases.append("landing fee now charged" if by["LNDG_FEE_FLAG"]["new"] == "Y"
                       else "landing fee removed")
    if "FREQ_USE" in by:
        f = by["FREQ_USE"]
        if f["new"]:
            phrases.append(f"frequency {ctx.get('FREQ', '')} now listed for {f['new']} (was {f['old']})")
        else:
            phrases.append(f"frequency {ctx.get('FREQ', '')} no longer listed for {f['old']}")
    obst = {"OBSTN_HGT", "DIST_FROM_THR", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE"}
    if obst & set(by):
        side = {"L": "left of", "R": "right of", "B": "either side of"}.get(ctx.get("CNTRLN_DIR_CODE", ""), "off")
        bits = []
        if ctx.get("OBSTN_HGT"):
            bits.append(f"{ctx['OBSTN_HGT']} ft tall")
        if ctx.get("DIST_FROM_THR"):
            bits.append(f"{ctx['DIST_FROM_THR']} ft from threshold")
        if ctx.get("CNTRLN_OFFSET"):
            bits.append(f"{ctx['CNTRLN_OFFSET']} ft {side} centerline")
        slope = f", clearance slope {ctx['OBSTN_CLNC_SLOPE']}:1" if ctx.get("OBSTN_CLNC_SLOPE") else ""
        phrases.append(f"controlling obstacle changed (now {', '.join(bits)}{slope})")
    if "RWY_MARKING_COND" in by:
        phrases.append(f"markings now in {by['RWY_MARKING_COND']['new'].lower()} condition")
    if "COND" in by:
        phrases.append(f"pavement now in {by['COND']['new'].lower()} condition")
    if "NAV_TYPE" in by:
        f = by["NAV_TYPE"]
        phrases.append(f"now a {NAV_NAMES.get(f['new'], f['new'])} "
                       f"(was a {NAV_NAMES.get(f['old'], f['old'])})")
    if "TACAN_DME_STATUS" in by:
        phrases.append(f"status: {by['TACAN_DME_STATUS']['new'].lower() or 'none listed'}")
    if "FREQ" in by:
        f = by["FREQ"]
        phrases.append(f"frequency changed: {f['old']} -> {f['new']}")
    if "FACILITY" in by:
        f = by["FACILITY"]
        phrases.append(f"frequency now provided by {f['new']} (was {f['old']})")
    handled = {"TWR_HRS", "TOWER_HRS", "AIRSPACE_HRS", "APCH_P_PROVIDER", "DEP_P_PROVIDER",
               "PHONE_NO", "NAV_TYPE", "FREQ", "FACILITY", "FAC_NAME", "LNDG_FEE_FLAG", "FREQ_USE",
               "RWY_MARKING_COND", "COND", "TACAN_DME_STATUS"} | obst
    if base(source) == "APT_ATT":
        handled.add("HOUR")
    for k, f in by.items():
        if k in handled:
            continue
        if k in NAME_COLS:
            phrases.append(f"name changed: {f['old'].title()} -> {f['new'].title()}")
        else:
            phrases.append(f"{label(k)}: {f['old'] or '(none)'} -> {f['new'] or '(none)'}")
    return phrases


def summarize(rec, remarks):
    if rec.get("summary_override"):
        return rec["summary_override"]
    b = base(rec["source"])
    kind = rec["kind"]
    row = rec.get("row", {})
    ctx = rec.get("context", {})

    if b in ("APT_RMK", "ATC_RMK"):
        if kind == "changed":
            new = next((f["new"] for f in rec["fields"] if f["field"] == "REMARK"), ctx.get("REMARK", ""))
            rec["original"] = new
            return f"remark updated: {remarks.get(new, new)}"
        text = row.get("REMARK", "")
        rec["original"] = text
        return f"{'new remark' if kind == 'added' else 'remark removed'}: {remarks.get(text, text)}"

    if b == "PFR_RMT_FMT":
        o, d = (row or ctx).get("Orig", "?"), (row or ctx).get("Dest", "?")
        route = (row or ctx).get("Route String", "")
        if kind == "added":
            return f"new preferred IFR route {o} -> {d}: {route}"
        if kind == "removed":
            return f"preferred IFR route {o} -> {d} removed"
        return f"preferred IFR route {o} -> {d} is now: {route}"

    if b.startswith(("STAR", "DP")):
        what = "arrival (STAR)" if b.startswith("STAR") else "departure (DP)"
        codes = []
        for src_row in (row, ctx):
            for k, v in src_row.items():
                if k.endswith("COMPUTER_CODE") and v:
                    codes.append(v)
        for f in rec.get("fields", []):
            if f["field"].endswith("COMPUTER_CODE") and f["new"]:
                codes.append(f["new"])
        name = codes[0].split(".")[-1] if codes else "procedure"
        verb = {"added": "added", "removed": "removed"}.get(kind, "updated")
        return f"{what} {name} {verb}"

    if b == "NAV_BASE" and kind != "changed":
        t = NAV_NAMES.get(row.get("NAV_TYPE", ""), row.get("NAV_TYPE", "navaid"))
        freq = f" ({row['FREQ']})" if row.get("FREQ") else ""
        verb = "decommissioned/removed" if kind == "removed" else "added"
        return f"{row.get('NAV_ID', '')} {t}{freq} {verb}"

    if b == "FRQ" and kind != "changed":
        use = row.get("FREQ_USE", "")
        if kind == "added" and rec["priority"] == "fyi":
            return f"frequency {row.get('FREQ', '?')} now also listed for {use}"
        return f"frequency {row.get('FREQ', '?')} ({use}) {kind}"

    if kind == "changed":
        where = ""
        if ctx.get("RWY_END_ID"):
            where = f"runway {ctx['RWY_END_ID']}: "
        elif ctx.get("RWY_ID"):
            where = f"runway {ctx['RWY_ID']}: "
        elif ctx.get("NAV_ID"):
            nm = f" ({ctx['NAME'].title()})" if ctx.get("NAME") else ""
            where = f"{ctx['NAV_ID']}{nm} navaid: "
        phrases = field_phrases(rec["fields"], rec["source"], ctx)
        return [where + "; ".join(phrases)] if where else phrases

    shown = ", ".join(f"{label(k)}={v}" for k, v in list(row.items())[:6])
    return f"{kind} ({b.lower()}): {shown}"

# ---------------------------------------------------------------- output

def collapse(records):
    """turn piles of raw added/removed rows into the events a pilot would describe."""
    by_apt = defaultdict(list)
    for r in records:
        by_apt[r["airport"]].append(r)
    out = []
    for apt, rs in by_apt.items():
        src = lambda r: base(r["source"])

        # 1. brand new / removed airport: one line instead of every field
        for kind, word in (("added", "new airport added to FAA database"),
                           ("removed", "airport removed from FAA database")):
            base_row = next((r for r in rs if src(r) == "APT_BASE" and r["kind"] == kind), None)
            if not base_row:
                continue
            name = base_row["row"].get("ARPT_NAME", "").title()
            rwys = [r["row"] for r in rs if src(r) == "APT_RWY" and r["kind"] == kind]
            rwy_txt = "; ".join(
                f"runway {w.get('RWY_ID', '?')} {w.get('RWY_LEN', '?')}x{w.get('RWY_WIDTH', '?')} ft "
                f"{w.get('SURFACE_TYPE_CODE', '').lower()}".strip() for w in rwys)
            ctaf = next((r["row"].get("FREQ") for r in rs if src(r) == "FRQ" and r["kind"] == kind
                         and "CTAF" in r["row"].get("FREQ_USE", "").upper()), None)
            bits = [b for b in (name, rwy_txt, f"CTAF {ctaf}" if ctaf else "") if b]
            out.append({"airport": apt, "source": "APT_BASE.csv", "kind": kind,
                        "priority": "action" if kind == "removed" else "fyi",
                        "summary_override": f"{word}: " + ", ".join(bits), "row": {}})
            rs = [r for r in rs if r["kind"] != kind]

        # 2. runway renumbered: removed + added runway with same length and width
        removed_rwys = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "removed"]
        added_rwys = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "added"]
        renumbered = []
        def rwy_num(rid):
            m = re.match(r"(\d{1,2})", rid or "")
            return int(m.group(1)) if m else None

        def close_numbers(a, b):
            # runway numbers one apart (mag variation drift), 36 wraps to 01
            if a is None or b is None or a == b:
                return False
            d = abs(a - b)
            return min(d, 36 - d) == 1

        for old in removed_rwys:
            for new in added_rwys:
                o, n = old["row"], new["row"]
                same_size = (o.get("RWY_LEN") and o.get("RWY_LEN") == n.get("RWY_LEN")
                             and o.get("RWY_WIDTH") == n.get("RWY_WIDTH"))
                if same_size or close_numbers(rwy_num(o.get("RWY_ID")), rwy_num(n.get("RWY_ID"))):
                    renumbered.append((old, new))
                    added_rwys.remove(new)
                    break
        # exactly one runway gone and one new one left over -> it was replaced/realigned
        left_removed = [r for r in removed_rwys if all(r is not o for o, _ in renumbered)]
        if len(left_removed) == 1 and len(added_rwys) == 1:
            renumbered.append((left_removed[0], added_rwys.pop()))
        drop = set()
        for old, new in renumbered:
            o_id, n_id = old["row"].get("RWY_ID", "?"), new["row"].get("RWY_ID", "?")
            o, n = old["row"], new["row"]
            extra = []
            if (o.get("RWY_LEN"), o.get("RWY_WIDTH")) != (n.get("RWY_LEN"), n.get("RWY_WIDTH")):
                extra.append(f"now {n.get('RWY_LEN', '?')}x{n.get('RWY_WIDTH', '?')} ft, "
                             f"was {o.get('RWY_LEN', '?')}x{o.get('RWY_WIDTH', '?')}")
            if o.get("SURFACE_TYPE_CODE") != n.get("SURFACE_TYPE_CODE"):
                extra.append(f"surface now {n.get('SURFACE_TYPE_CODE', '?').lower()}")
            tail = f" ({'; '.join(extra)})" if extra else ""
            out.append({"airport": apt, "source": "APT_RWY.csv", "kind": "changed", "priority": "action",
                        "summary_override": (
                            f"runway {o_id} renumbered to {n_id}{tail}"
                            if close_numbers(rwy_num(o_id), rwy_num(n_id)) or
                            (o.get("RWY_LEN") == n.get("RWY_LEN") and o.get("RWY_WIDTH") == n.get("RWY_WIDTH"))
                            else f"runway {o_id} replaced by runway {n_id}{tail}"),
                        "fields": [{"field": "RWY_ID", "old": o_id, "new": n_id}]})
            drop |= {id(old), id(new)}
            old_ids = set(o_id.split("/")) | {o_id}
            new_ids = set(n_id.split("/")) | {n_id}
            for r in rs:  # the runway-end rows for those ids are covered by the one line
                if src(r) == "APT_RWY_END" and r["kind"] in ("added", "removed"):
                    rid = r["row"].get("RWY_ID", "")
                    if rid in old_ids | new_ids:
                        drop.add(id(r))

        # 3. same remark text "removed" and "added" (FAA just renumbered the remark)
        texts = defaultdict(list)
        for r in rs:
            if src(r) in ("APT_RMK", "ATC_RMK") and r["kind"] in ("added", "removed"):
                texts[r["row"].get("REMARK", "")].append(r)
        for t, group in texts.items():
            kinds = {r["kind"] for r in group}
            if t and kinds == {"added", "removed"}:
                drop |= {id(r) for r in group}

        out.extend(r for r in rs if id(r) not in drop)
    return out


# ---------------------------------------------------------------- d-TPP (approach plates etc.)

DTPP_KINDS = {
    "IAP": "approach", "DP": "departure", "ODP": "obstacle departure", "STAR": "arrival (STAR)",
    "APD": "airport diagram", "HOT": "hot spot page", "MIN": "minimums page",
    "LAH": "LAHSO page", "DAU": "diverse vector area page", "CVFP": "charted visual procedure",
}
DTPP_ACTIONS = {"A": "added", "C": "changed", "D": "removed"}


def load_dtpp(path, ids):
    """read the FAA d-TPP metafile; return {airport: [record, ...]} for added/changed/deleted charts.
    each record's useraction already compares against the previous edition, so one file is enough."""
    import xml.etree.ElementTree as ET
    out = defaultdict(list)
    cycle = ""
    seen = set()
    apt = None
    for event, el in ET.iterparse(path, events=("start", "end")):
        tag = el.tag.lower()
        if event == "start" and tag == "digital_tpp":
            cycle = el.get("cycle", "")
        elif event == "start" and tag == "airport_name":
            apt = (el.get("apt_ident") or "").upper()
        elif event == "end" and tag == "record":
            get = lambda k: (el.findtext(k) or "").strip()
            act = get("useraction").upper()
            if apt in ids and act in DTPP_ACTIONS:
                code, name = get("chart_code").upper(), get("chart_name")
                key = (apt, code, name.replace(", CONT.", "").replace(" CONT.", ""), act)
                if key not in seen:  # continuation pages list the same chart twice
                    seen.add(key)
                    what = DTPP_KINDS.get(code, code.lower() or "chart")
                    verb = DTPP_ACTIONS[act]
                    amdt = get("amdtnum")
                    if code in ("IAP", "DP", "ODP", "STAR", "CVFP"):
                        s = f"{what} {name} {verb}"
                        if act == "C" and amdt:
                            label = "original" if amdt.upper() in ("0", "ORIG") else f"amdt {amdt}"
                            s = f"{what} {name} amended ({label})"
                        pri = "ifr"
                    else:
                        s = f"{what} {verb}" if code in ("APD",) else f"{what} ({name}) {verb}"
                        pri = "fyi" if code in ("APD", "HOT") else "ifr"
                    pdf = get("pdf_name")
                    rec = {"source": "d-TPP", "kind": verb, "priority": pri, "summary": s,
                           "chart_code": code, "chart_name": name, "amdt": amdt}
                    if cycle and pdf and act != "D" and "DELETED" not in pdf.upper():
                        rec["pdf"] = f"https://aeronav.faa.gov/d-tpp/{cycle}/{pdf}"
                    out[apt].append(rec)
            el.clear()
        elif event == "end" and tag == "airport_name":
            el.clear()
    return out


def merge_freq_uses(records):
    """several 'freq X use renamed/dropped' records for one frequency -> one record."""
    groups, rest = defaultdict(list), []
    for r in records:
        f = r.get("fields", [])
        if (base(r["source"]) == "FRQ" and r["kind"] == "changed" and len(f) == 1
                and f[0]["field"] == "FREQ_USE"):
            groups[(r["airport"], r.get("context", {}).get("FREQ", ""))].append(r)
        else:
            rest.append(r)
    for (apt, freq), rs in groups.items():
        if len(rs) == 1:
            rest.append(rs[0])
            continue
        old = sorted({r["fields"][0]["old"] for r in rs if r["fields"][0]["old"]})
        new = sorted({r["fields"][0]["new"] for r in rs if r["fields"][0]["new"]})
        rest.append({"airport": apt, "source": "FRQ.csv", "kind": "changed", "priority": "fyi",
                     "fields": [{"field": "FREQ_USE", "old": ", ".join(old), "new": ", ".join(new)}],
                     "context": {"FREQ": freq}})
    return rest


def write_json(by_apt, out_dir, old_zip, new_zip):
    os.makedirs(out_dir, exist_ok=True)
    for apt, recs in by_apt.items():
        with open(os.path.join(out_dir, f"{apt}.json"), "w") as f:
            json.dump({"airport": apt,
                       "from_cycle": os.path.basename(old_zip),
                       "to_cycle": os.path.basename(new_zip),
                       "action_count": sum(r["priority"] == "action" for r in recs),
                       "ifr_count": sum(r["priority"] == "ifr" for r in recs),
                       "changes": recs}, f, indent=2)
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(sorted(by_apt), f)
    print(f"wrote {len(by_apt)} airport file(s) to {out_dir}/")


def load_env(path=".env"):
    """read KEY=value lines from .env into the environment (doesn't override real env vars)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def set_key():
    """prompt for the api key without echoing it, save to .env, make sure git ignores it."""
    import getpass
    key = getpass.getpass("paste your Anthropic API key (it won't show while typing): ").strip()
    if not key.startswith("sk-"):
        print("that doesn't look like an Anthropic key (should start with sk-). nothing saved.")
        return
    lines = []
    if os.path.exists(".env"):
        with open(".env") as f:
            lines = [l for l in f if not l.startswith("ANTHROPIC_API_KEY=")]
    lines.append(f"ANTHROPIC_API_KEY={key}\n")
    with open(".env", "w") as f:
        f.writelines(lines)
    os.chmod(".env", 0o600)
    ignore = set()
    if os.path.exists(".gitignore"):
        with open(".gitignore") as f:
            ignore = {l.strip() for l in f}
    missing = [x for x in (".env", ".venv/", "__pycache__/") if x not in ignore]
    if missing:
        with open(".gitignore", "a") as f:
            f.write("\n".join(missing) + "\n")
    print("saved to .env (and .env is in .gitignore). you can now just use --llm.")


def main():
    if "--set-key" in sys.argv:
        set_key()
        return
    load_env()
    raw = sys.argv[1:]
    args = [a for i, a in enumerate(raw) if not a.startswith("--")
            and not (i > 0 and raw[i - 1] in ("--dtpp", "--out"))]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    all_mode = "--all-airports" in flags
    if len(args) < 2 or (len(args) < 3 and not all_mode):
        print(__doc__)
        sys.exit(1)
    old_zip, new_zip = args[0], args[1]
    import time
    t0 = time.time()
    if all_mode:
        ids = airport_ids(old_zip) | airport_ids(new_zip)
        print(f"all-airports mode: {len(ids)} airports")
    else:
        ids = {a.upper()[1:] if len(a) == 4 and a.upper().startswith("K") else a.upper()
               for a in args[2:]}

    print(f"loading {old_zip} ...")
    old = load(old_zip, ids, strict=all_mode)
    print(f"loading {new_zip} ...")
    new = load(new_zip, ids, strict=all_mode)
    print(f"  loaded in {time.time() - t0:.0f}s, diffing ...")

    records = diff(old, new)
    remark_texts = []
    for r in records:
        if base(r["source"]) in ("APT_RMK", "ATC_RMK"):
            remark_texts.append(r.get("row", {}).get("REMARK", ""))
            remark_texts += [f["new"] for f in r.get("fields", []) if f["field"] == "REMARK"]
    remarks = translate_remarks(remark_texts, "--llm" in flags)

    records = merge_freq_uses(collapse(records))

    # attach summaries, drop duplicate summaries per airport (same change in several files)
    by_apt = defaultdict(list)
    hidden = defaultdict(list)
    for r in records:
        s = summarize(r, remarks)
        r["_phrases"] = s if isinstance(s, list) else [s]
        (hidden if r["priority"] == "hidden" else by_apt)[r["airport"]].append(r)
    for apt in by_apt:
        # drop phrases already said (tower hours live in ATC_BASE, FRQ and CLS_ARSP)
        seen, uniq = set(), []
        for r in sorted(by_apt[apt], key=lambda r: (r["priority"] != "action", r["_phrases"])):
            phrases = [p for p in r.pop("_phrases") if p not in seen]
            if not phrases:
                continue
            seen.update(phrases)
            r["summary"] = "; ".join(phrases)
            uniq.append({k: v for k, v in r.items() if k != "airport"})
        by_apt[apt] = uniq

    dtpp_path = next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                      if a == "--dtpp" and i + 1 < len(sys.argv)), None)
    if dtpp_path:
        print(f"loading d-TPP {dtpp_path} ...")
        dtpp = load_dtpp(dtpp_path, ids)
        for apt, recs in dtpp.items():
            by_apt[apt].extend(recs)
        print(f"  {sum(len(v) for v in dtpp.values())} chart changes at {len(dtpp)} airports")

    out_dir = next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                    if a == "--out" and i + 1 < len(sys.argv)), "out")
    if "--json" in flags or all_mode:
        write_json(by_apt, out_dir, old_zip, new_zip)

    if all_mode and "--print" not in flags:
        ranked = sorted(by_apt.items(), key=lambda kv: -sum(r["priority"] == "action" for r in kv[1]))
        n_action = sum(1 for _, rs in by_apt.items() if any(r["priority"] == "action" for r in rs))
        print(f"\ndone in {time.time() - t0:.0f}s. {len(by_apt)} airports changed, "
              f"{n_action} with action items.")
        print("most action items:")
        for apt, rs in ranked[:15]:
            print(f"  {apt:5} {sum(r['priority'] == 'action' for r in rs):3} action, "
                  f"{sum(r['priority'] == 'ifr' for r in rs):3} ifr, "
                  f"{sum(r['priority'] == 'fyi' for r in rs):3} fyi")
        print(f"\nsee {out_dir}/<AIRPORT>.json, or rerun with --print to dump everything")
        return

    for apt in sorted(set(by_apt) | set(hidden)):
        recs = by_apt.get(apt, [])
        print(f"\n==================== {apt} ====================")
        for pri, icon in (("action", "!!"), ("ifr", ">>"), ("fyi", "--")):
            group = [r for r in recs if r["priority"] == pri]
            if group:
                print(f"\n{'IFR PROCEDURES' if pri == 'ifr' else pri.upper()}")
            if pri == "fyi" and "--routes" not in flags:
                routes = [r for r in group if base(r["source"]).startswith("PFR")]
                procs = [r for r in group if base(r["source"]).startswith(("STAR", "DP"))]
                group = [r for r in group if r not in routes and r not in procs]
                if routes:
                    k = defaultdict(int)
                    for r in routes:
                        k[r["kind"]] += 1
                    parts = ", ".join(f"{n} {kind}" for kind, n in sorted(k.items()))
                    print(f" {icon} preferred IFR routes: {parts} (--routes to list)")
                if procs:
                    new = sorted({r["summary"].split()[-2] for r in procs if r["kind"] != "removed"})
                    gone = sorted({r["summary"].split()[-2] for r in procs if r["kind"] == "removed"} - set(new))
                    line = f"arrival/departure procedures new or updated: {', '.join(new) or 'none'}"
                    if gone:
                        line += f"; removed: {', '.join(gone)}"
                    print(f" {icon} {line}")
            for r in group:
                print(f" {icon} {r['summary']}")
                if "--raw" in flags and r.get("original"):
                    print(f"      FAA: {r['original']}")
                if "--raw" in flags:
                    for f in r.get("fields", []):
                        print(f"      {f['field']}: '{f['old']}' -> '{f['new']}'")
        h = hidden.get(apt, [])
        if h and "--all" in flags:
            print("\nHIDDEN")
            for r in h:
                print(f" .. {'; '.join(r['_phrases'])}")
        elif h:
            print(f"\n ({len(h)} noise changes hidden, --all to show)")


if __name__ == "__main__":
    main()