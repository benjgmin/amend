"""
Per-airport change timeline across every FAA cycle since Aug 2024.

Each cycle is diffed against the one before it and appended to history/<ID>.json (newest
first). history/cycles.json tracks what's done, so re-running only adds new cycles.
"""
import glob
import json
import os

from . import ENGINE_VERSION, SCHEMA_VERSION
from .audit import audit, report_to_actions
from .cycles import (CYCLE, FIRST_ARCHIVED, airspace_path, dtpp_path, forget, get_airspace_pair,
                     get_cycle, get_dtpp, in_effect, zip_path)
from .output import dump
from .pipeline import run
from .runlog import Run

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
        h["entries"] += [{"cycle": new, "from_cycle": old, "engine": ENGINE_VERSION, **c} for c in changes]
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
    current = in_effect()
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

    # resume from the newest cycle before the first missing one. logged only if it crashes
    prev = None
    with Run("history"):
        for c in reversed([c for c in cycles if c < todo[0]]):
            if c.isoformat() not in state["skipped"] and get_cycle(c):
                prev = c
                break

    for new in todo:
        with Run("history") as log:
            prev = _step(prev, new, state, llm, keep, log)
    write_index(state)
    print(f"\nhistory up to date through {prev}")


def _step(prev, new, state, llm, keep, log):
    """diff prev -> new into history (one run log record). returns the new prev."""
    log.cycles(prev, new)
    if not get_cycle(new):   # a failed download raises instead: only a real 404 is a gap
        print(f"  {new}: not in FAA archive, skipping (next cycle diffs across the gap)")
        state["skipped"] = sorted(set(state["skipped"]) | {new.isoformat()})
        log.skip(f"{new} is not in the FAA archive")
        return prev
    if prev is None:         # nothing to diff against yet, nothing to log
        return new
    print(f"\n=== {prev} -> {new} ===")
    dtpp, airspace = get_dtpp(new), get_airspace_pair(prev, new)
    log.faa_sources(prev, new, dtpp, airspace)
    result = run(zip_path(prev), zip_path(new), None, dtpp, llm, log=lambda *_: None,
                 airspace=airspace)
    log.result(result)
    report = audit(result, HIST, gap_ok=True)
    report["errors"] = log.problems + report["errors"]
    report["warnings"] += log.engine_warning()
    log.checks(report)
    report_to_actions(report, f"{prev} -> {new}")
    if report["errors"]:     # history is kept forever, so nothing unchecked goes in
        msg = f"audit failed for {prev} -> {new}, not adding it to history"
        log.block(msg)
        raise SystemExit(msg)
    print(f"  {append(result)} changes at {len(result['airports'])} airports")
    state["cycles"] = sorted(set(state["cycles"]) | {new.isoformat()})
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)
    log.done()
    if not keep:  # only the newest zip is needed for the next step
        for p in (zip_path(prev), dtpp_path(new), airspace_path(prev)):
            forget(p)
    return new
