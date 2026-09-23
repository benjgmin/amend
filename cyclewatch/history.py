"""
Per-airport change timeline across every FAA cycle since Aug 2024.

Each cycle is diffed against the one before it and appended to history/<ID>.json (newest
first). history/cycles.json tracks what's done, so re-running only adds new cycles.
"""
import datetime as dt
import glob
import json
import os

from . import SCHEMA_VERSION
from .cycles import (CYCLE, FIRST_ARCHIVED, cycle_on_or_before, dtpp_path, get_cycle,
                     get_dtpp, zip_path)
from .output import dump
from .pipeline import run

HIST = "history"
STATE = os.path.join(HIST, "cycles.json")


def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def append(result):
    """add one cycle's changes to each airport's history file."""
    new, old = result["to_cycle"], result["from_cycle"]
    n = 0
    for apt, changes in result["airports"].items():
        path = os.path.join(HIST, f"{apt}.json")
        h = _load(path, {"schema_version": SCHEMA_VERSION, "airport": apt, "entries": []})
        h["entries"] = [e for e in h["entries"] if e["cycle"] != new]  # re-runs stay idempotent
        h["entries"] += [{"cycle": new, "from_cycle": old, **c} for c in changes]
        h["entries"].sort(key=lambda e: e["cycle"], reverse=True)
        h["first_cycle"] = h["entries"][-1]["cycle"]
        h["last_cycle"] = h["entries"][0]["cycle"]
        dump(h, path)
        n += len(changes)
    return n


def write_index(state):
    airports = {}
    for path in glob.glob(os.path.join(HIST, "*.json")):
        if os.path.basename(path) in ("index.json", "cycles.json"):
            continue
        h = _load(path, None)
        airports[h["airport"]] = {
            "entries": len(h["entries"]), "last_cycle": h["last_cycle"],
            "action": sum(e["priority"] == "action" for e in h["entries"])}
    dump({"schema_version": SCHEMA_VERSION, "cycles": state["cycles"],
          "airports": dict(sorted(airports.items()))}, os.path.join(HIST, "index.json"))


def update(llm=False, keep=False):
    os.makedirs(HIST, exist_ok=True)
    state = _load(STATE, {"cycles": [], "skipped": []})
    current = cycle_on_or_before(dt.date.today())
    cycles, d = [], FIRST_ARCHIVED
    while d <= current:
        cycles.append(d)
        d += CYCLE
    todo = [c for c in cycles[1:] if c.isoformat() not in state["cycles"]]
    if not todo:
        print("history is up to date")
        write_index(state)
        return
    print(f"{len(todo)} cycle(s) to add: {todo[0]} .. {todo[-1]}")

    # resume from the newest cycle before the first missing one
    prev = None
    for c in reversed([c for c in cycles if c < todo[0]]):
        if c.isoformat() not in state["skipped"] and get_cycle(c):
            prev = c
            break

    for new in todo:
        if not get_cycle(new):
            print(f"  {new}: not in FAA archive, skipping (next cycle diffs across the gap)")
            state["skipped"] = sorted(set(state["skipped"]) | {new.isoformat()})
            continue
        if prev is None:
            prev = new
            continue
        print(f"\n=== {prev} -> {new} ===")
        result = run(zip_path(prev), zip_path(new), None, get_dtpp(new), llm, log=lambda *_: None)
        print(f"  {append(result)} changes at {len(result['airports'])} airports")
        state["cycles"] = sorted(set(state["cycles"]) | {new.isoformat()})
        with open(STATE, "w") as f:
            json.dump(state, f, indent=1)
        if not keep:  # only the newest zip is needed for the next step
            for p in (zip_path(prev), dtpp_path(new)):
                if os.path.exists(p):
                    os.remove(p)
        prev = new
    write_index(state)
    print(f"\nhistory up to date through {prev}")
