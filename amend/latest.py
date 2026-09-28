"""Build site/ for GitHub Pages: upcoming (or current) changes + the history timeline."""
import datetime as dt
import json
import os
import shutil

from . import ENGINE_VERSION, SCHEMA_VERSION
from . import audit, watchlists, web
from .airports import directory
from .cycles import CYCLE, airspace_path, forget, get_airspace_pair, get_cycle, get_dtpp, in_effect, zip_path
from .freshness import fingerprint
from .output import dump, write_diff
from .pipeline import run
from .runlog import Run

SITE = "site"
HISTORY = "history"

def build(llm=True):
    with Run("latest") as log:
        _build(llm, log)


def _build(llm, log):
    current = in_effect()   # 0901Z changeover, not the runner's midnight
    nxt, prev = current + CYCLE, current - CYCLE

    # upcoming if the FAA already posted next cycle (~3 weeks early), else this cycle.
    # False only means a real "not posted"; a failed download raises, so a flaky FAA server
    # stops the run (last good site stays up) instead of quietly dropping the preview
    if get_cycle(nxt):
        old, new, upcoming = current, nxt, True
    else:
        old, new, upcoming = prev, current, False
    log.cycles(old, new, upcoming)
    for d in (old, new):
        if not get_cycle(d):
            raise SystemExit(f"can't get NASR data for {d}, giving up")
    dtpp = get_dtpp(new)
    airspace = get_airspace_pair(old, new)
    log.faa_sources(old, new, dtpp, airspace)

    shutil.rmtree(SITE, ignore_errors=True)
    out = os.path.join(SITE, "latest")
    result = run(zip_path(old), zip_path(new), None, dtpp, llm and bool(os.environ.get("ANTHROPIC_API_KEY")),
                 airspace=airspace)
    log.result(result)
    if result["airspace_error"]:
        # meta.json says includes_airspace false, so the next scheduled check rebuilds. without
        # this the Actions cache would hand it the same unreadable zips and it'd fail the same way
        for d in (old, new):
            forget(airspace_path(d))
        print("  dropped the cached airspace zips, so the next build downloads them again")
    lists = watchlists.load_all()
    report = audit.audit(result, HISTORY)
    report["errors"] = log.problems + report["errors"]   # a cached file that isn't what was downloaded
    report["warnings"] += log.engine_warning()
    log.checks(report)
    audit.write_packet(audit.packet(result, report, lists))
    audit.report_to_actions(report, f"{old} -> {new}")
    if report["errors"]:     # keep the last good site up; the failed run is the alarm
        msg = f"audit failed for {old} -> {new}, not publishing (see audit/{new}.json)"
        log.block(msg)
        raise SystemExit(msg)
    n = write_diff(result, out)
    dump({"schema_version": SCHEMA_VERSION, "engine": ENGINE_VERSION,
          "from_cycle": old.isoformat(), "to_cycle": new.isoformat(),
          "upcoming": upcoming, "effective": f"{new.isoformat()}T09:01:00Z", "includes_charts": bool(dtpp),
          "includes_airspace": result["includes_airspace"], "changed_airports": n,
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
    # what this build was made from, so the scheduled check can tell when a merge isn't live yet
    # run: which run log record (audit/runs/) this deploy is, so "published" can be confirmed live
    dump({"inputs": fingerprint(), "commit": os.environ.get("GITHUB_SHA", ""), "engine": ENGINE_VERSION,
          "run": os.environ.get("GITHUB_RUN_ID"),
          "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
         os.path.join(SITE, "build.json"))
    log.done()
    print(f"site built: {old} -> {new} ({'upcoming' if upcoming else 'current'}), "
          f"{n} changed airports, {pages} airport pages, {len(lists)} named watchlists")
