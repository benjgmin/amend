"""
Bring history/ up to today's engine where older code wrote something no pilot should read:
  - raw dumps of FAA column names ("removed (ils_mkr): rwy end id=34, ils loc id=FKZ, ...")
    get the English today's engine writes, from the FAA values the dump kept
  - the parts of a whole ILS that came or went (glideslope, DME, markers) fold into its line,
    and so do the runway-end rows of a runway that came or went
  - holding patterns and military route points (hidden since PR #14) go
Everything else stays as it was, and every entry keeps its id, so nobody's "seen" list moves.
Safe to run again (it only touches entries it can still parse as a dump):
  python -m amend.backfill
"""
import glob
import json
import os
import re
from collections import defaultdict

from .diff import empty_non_atct, priority, row_priority, schedule_text
from .english import ils, ils_part, summarize, unsupported
from .history import HIST, STATE, write_index
from .output import dump
from .rules import HIDDEN_FILES, ID_COLS, IFR_REMARK_FILES, REMARK_FILES, is_noise_col

RAW = re.compile(r"^(added|removed) \(([a-z0-9_]+)\): (.*)$", re.S)
ITEM = re.compile(r", (?=[a-z][a-z0-9 ]*=)")     # 'rwy id=18/36, rwy len=2546'
ILS_PARTS = ("ILS_GS", "ILS_DME", "ILS_MKR")


def parse(summary):
    """(kind, FILE, row) from an old dump, or None. labels go back to FAA column names."""
    m = RAW.match(summary)
    if not m:
        return None
    row = {}
    for item in ITEM.split(m.group(3)):
        k, eq, v = item.partition("=")
        if not eq:
            return None
        row[k.strip().upper().replace(" ", "_")] = v
    return m.group(1), m.group(2).upper(), row


def clean(row):
    """the columns today's engine keeps on a row (the old code kept survey columns too)."""
    return {k: v for k, v in row.items() if v and k not in ID_COLS and not is_noise_col(k)}


def _entry(e, fname, kind, row):
    """the entry as today's engine would write it for this row: None if the engine hides it
    now, the old entry unchanged if there's no English for it that checks out."""
    row = clean(row)
    pri = priority(fname, kind, list(row), list(row.values()))
    if pri == "action" and empty_non_atct(fname, row):
        pri = "fyi"
    pri = row_priority(fname, kind, row, pri)
    if fname[:-4] in IFR_REMARK_FILES and pri == "action":
        pri = "ifr"
    if pri == "hidden":
        return None
    rec = {"airport": "", "source": fname, "kind": kind, "priority": pri, "row": row}
    s = summarize(rec, {})       # remarks: the FAA text itself, never a cached translation
    if fname[:-4] in REMARK_FILES and not row.get("REMARK"):
        # the old dump showed six columns and the remark text was the seventh (FRH 2024)
        s = s.rstrip(": ") + " (its text isn't in this old record)"
        rec.pop("original", None)
    if rec.get("no_template") or unsupported(s, list(row.values())):
        return e
    out = {**e, "priority": pri, "summary": s}
    if rec.get("original"):
        out["original"] = rec["original"]
    else:
        old = kind == "removed"
        out["fields"] = [{"field": k, "old": v if old else "", "new": "" if old else v} for k, v in row.items()]
    return out


def _cycle(entries):
    """rewrite one airport's entries for one cycle. returns the new list."""
    parsed = {id(e): parse(e["summary"]) for e in entries}
    out, drop = {}, set()
    rows = lambda f, k: [(e, parsed[id(e)][2]) for e in entries
                         if parsed[id(e)] and parsed[id(e)][1] == f and parsed[id(e)][0] == k]

    # runway-end rows of a runway that came or went: the runway line says it
    for kind in ("added", "removed"):
        gone = {r.get("RWY_ID") for _, r in rows("APT_RWY", kind)}
        drop |= {id(e) for e, r in rows("APT_RWY_END", kind) if r.get("RWY_ID") in gone}

    # a whole ILS and its parts: one line, with the id of the ILS entry
    for kind in ("added", "removed"):
        for e, r in rows("ILS_BASE", kind):
            key = (r.get("RWY_END_ID"), r.get("ILS_LOC_ID"))
            parts = [(x, xr) for f in ILS_PARTS for x, xr in rows(f, kind)
                     if (xr.get("RWY_END_ID"), xr.get("ILS_LOC_ID")) == key]
            new = _entry(e, "ILS_BASE.csv", kind, r)
            if new is None or new is e:
                continue
            if parts:
                new["summary"] = ils(kind, clean(r), [ils_part(parsed[id(x)][1], xr) for x, xr in parts])
                new["priority"] = "action"
                drop |= {id(x) for x, _ in parts}
            out[id(e)] = new

    # attendance: the dump only kept the rows that came or went, so say exactly that
    att = [(e, parsed[id(e)][0], parsed[id(e)][2]) for e in entries
           if parsed[id(e)] and parsed[id(e)][1] == "APT_ATT"]
    if att:
        gone = schedule_text([r for _, k, r in att if k == "removed"])
        came = schedule_text([r for _, k, r in att if k == "added"])
        drop |= {id(e) for e, _, _ in att}
        if gone != came:
            if gone and came:
                s = f"airport attendance schedule: dropped {gone}; added {came}"
            elif came:
                s = f"airport attendance schedule: added {came}"
            else:
                s = f"airport attendance schedule: dropped {gone}"
            first = att[0][0]
            out[id(first)] = {**first, "summary": s,
                              "priority": "fyi" if came == "UNATNDD" and not gone else "action",
                              "kind": "added" if not gone else "removed" if not came else "changed"}
            drop.discard(id(first))

    result, seen = [], set()
    for e in entries:
        if id(e) in drop or e["source"].startswith(HIDDEN_FILES):
            continue
        new = out.get(id(e), e)
        if id(e) not in out and parsed[id(e)]:
            kind, f, r = parsed[id(e)]
            new = _entry(e, f + ".csv", kind, r)
        if new is not None and new["summary"] not in seen:
            seen.add(new["summary"])
            result.append(new)
    return result


def rewrite(h):
    by_cycle = defaultdict(list)
    for e in h["entries"]:
        by_cycle[e["cycle"]].append(e)
    entries = []
    for cyc in sorted(by_cycle, reverse=True):
        entries += _cycle(by_cycle[cyc])
    return entries


def count(paths):
    n = 0
    for p in paths:
        with open(p, encoding="utf-8") as f:
            n += sum(bool(RAW.match(e["summary"])) for e in json.load(f)["entries"])
    return n


def main():
    paths = [p for p in sorted(glob.glob(os.path.join(HIST, "*.json")))
             if os.path.basename(p) not in ("index.json", "cycles.json")]
    before = count(paths)
    changed = removed = 0
    for p in paths:
        with open(p, encoding="utf-8") as f:
            h = json.load(f)
        entries = rewrite(h)
        if entries == h["entries"]:
            continue
        changed += 1
        if not entries:
            os.remove(p)
            removed += 1
            continue
        h["entries"] = entries
        h["first_cycle"], h["last_cycle"] = entries[-1]["cycle"], entries[0]["cycle"]
        dump(h, p)
    with open(STATE, encoding="utf-8") as f:
        write_index(json.load(f))
    left = [p for p in paths if os.path.exists(p)]
    print(f"raw dumps in history: {before} -> {count(left)}; "
          f"{changed} airport files rewritten, {removed} left empty and removed")


if __name__ == "__main__":
    main()
