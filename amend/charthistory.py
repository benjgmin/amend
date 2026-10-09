"""
Say history's chart changes the way today's engine does, from the metafile each cycle's charts
came from and what plates/ read off the plates:
  - "amended (amdt 32A)" on a plate the FAA only redrew under its old amendment becomes
    "redrawn (still amdt 32A)" (1,347 of 1,665 changed approaches on 3 Sep 2026)
  - a course or heading that moved on the plate is said, with the old and new number
Entries are matched by id, or (cycles written before ids hashed the chart this way) by airport,
chart code, chart name and kind, and keep their id, so nobody's "seen" list moves. An entry whose
chart today's engine doesn't list is left alone.
Safe to run again:
  python -m amend.charthistory METAFILE ...    (the d-TPP metafile of each history cycle to redo)
"""
import glob
import json
import os
import sys

from .dtpp import changed_pdfs, load_dtpp
from .history import HIST
from .output import dump
from .pipeline import change_id, change_key


def _name(apt, r):
    c = r.get("chart") or {}
    return apt, c.get("code"), c.get("name"), r["kind"]


class _Every:
    def __contains__(self, _):
        return True


def redo(metafile, hist=HIST, plates_root="."):
    """(entries rewritten, chart entries in that cycle, how many of those matched, airports touched)"""
    _, day, _ = changed_pdfs(metafile)
    cycle = day.isoformat()
    now, named = {}, {}
    for apt, recs in load_dtpp(metafile, _Every(), plates_root).items():
        for r in recs:
            r["summary"] = r["summary_override"]
            now[change_id(apt, cycle, change_key(r))] = r
            named[_name(apt, r)] = r
    fixed = seen = files = matched = 0
    for path in sorted(glob.glob(os.path.join(hist, "*.json"))):
        if os.path.basename(path) in ("index.json", "cycles.json"):
            continue
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        touched = False
        for e in h["entries"]:
            if e["cycle"] != cycle or e["source"].upper() != "D-TPP":
                continue
            seen += 1
            r = now.get(e["id"]) or named.get(_name(h["airport"], e))
            if not r:
                continue
            matched += 1
            want = {"summary": r["summary"], "details": r.get("details")}
            if e["summary"] != want["summary"] or e.get("details") != want["details"]:
                e["summary"] = want["summary"]
                if want["details"]:
                    e["details"] = want["details"]
                else:
                    e.pop("details", None)
                fixed += 1
                touched = True
        if touched:
            files += 1
            dump(h, path)
    return fixed, seen, matched, files


def main(argv=None):
    for m in argv if argv is not None else sys.argv[1:]:
        fixed, seen, matched, files = redo(m)
        print(f"{m}: {seen} chart entries, {matched} matched today's engine, {fixed} rewritten "
              f"({files} airports)")


if __name__ == "__main__":
    main()
