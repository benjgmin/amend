"""Build site/ for GitHub Pages: upcoming (or current) changes + the history timeline."""
import datetime as dt
import json
import os
import shutil

from . import SCHEMA_VERSION
from . import audit, watchlists, web
from .airports import directory
from .cycles import CYCLE, cycle_on_or_before, get_airspace_pair, get_cycle, get_dtpp, zip_path
from .output import dump, write_diff
from .pipeline import run

SITE = "site"
HISTORY = "history"

def build(llm=True):
    today = dt.date.today()
    current = cycle_on_or_before(today)
    nxt, prev = current + CYCLE, current - CYCLE

    # upcoming if the FAA already posted next cycle (~3 weeks early), else this cycle
    if get_cycle(nxt):
        old, new, upcoming = current, nxt, True
    else:
        old, new, upcoming = prev, current, False
    for d in (old, new):
        if not get_cycle(d):
            raise SystemExit(f"can't get NASR data for {d}, giving up")
    dtpp = get_dtpp(new)
    airspace = get_airspace_pair(old, new)

    shutil.rmtree(SITE, ignore_errors=True)
    out = os.path.join(SITE, "latest")
    result = run(zip_path(old), zip_path(new), None, dtpp, llm and bool(os.environ.get("ANTHROPIC_API_KEY")),
                 airspace=airspace)
    lists = watchlists.load_all()
    report = audit.audit(result, HISTORY)
    audit.write_packet(audit.packet(result, report, lists))
    audit.report_to_actions(report, f"{old} -> {new}")
    if report["errors"]:     # keep the last good site up; the failed run is the alarm
        raise SystemExit(f"audit failed for {old} -> {new}, not publishing (see audit/{new}.json)")
    n = write_diff(result, out)
    dump({"schema_version": SCHEMA_VERSION, "from_cycle": old.isoformat(), "to_cycle": new.isoformat(),
          "upcoming": upcoming, "includes_charts": bool(dtpp),
          "includes_airspace": bool(airspace), "changed_airports": n,
          "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
         os.path.join(out, "meta.json"))
    apts = directory(zip_path(new))
    dump({"schema_version": SCHEMA_VERSION, "cycle": new.isoformat(), "airports": apts},
         os.path.join(SITE, "airports.json"))
    if os.path.isdir(HISTORY):
        shutil.copytree(HISTORY, os.path.join(SITE, "history"),
                        ignore=shutil.ignore_patterns("cycles.json"))
    meta = {"from_cycle": old.isoformat(), "to_cycle": new.isoformat(), "upcoming": upcoming,
            "changed_airports": n}
    pages = web.build(SITE, meta, apts, result["airports"], HISTORY, watchlists=lists)
    print(f"site built: {old} -> {new} ({'upcoming' if upcoming else 'current'}), "
          f"{n} changed airports, {pages} airport pages, {len(lists)} named watchlists")