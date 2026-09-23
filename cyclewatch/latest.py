"""Build site/ for GitHub Pages: upcoming (or current) changes + the history timeline."""
import datetime as dt
import json
import os
import shutil

from . import SCHEMA_VERSION
from .airports import directory
from .cycles import CYCLE, cycle_on_or_before, get_cycle, get_dtpp, zip_path
from .output import dump, write_diff
from .pipeline import run

SITE = "site"
HISTORY = "history"

INDEX_HTML = """<!doctype html><meta charset="utf-8"><title>Cyclewatch</title>
<body style="font-family:system-ui;max-width:40em;margin:3em auto;padding:0 1em;line-height:1.5">
<h1>Cyclewatch</h1>
<p>{label} changes: FAA cycle {old} &rarr; {new}.</p>
<ul>
<li>Changed airports: <a href="latest/index.json">latest/index.json</a></li>
<li>One airport: <code>latest/&lt;ID&gt;.json</code> (FAA id, e.g. <code>VRB</code>)</li>
<li>History since Aug 2024: <code>history/&lt;ID&gt;.json</code>, <a href="history/index.json">history/index.json</a></li>
<li>Run info: <a href="latest/meta.json">latest/meta.json</a></li>
<li>Airport directory (names, search): <a href="airports.json">airports.json</a></li>
</ul>
<p>Format: see SCHEMA.md in the repo. <b>Not for navigation.</b> Always check official FAA publications and NOTAMs.</p>
</body>"""


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

    shutil.rmtree(SITE, ignore_errors=True)
    out = os.path.join(SITE, "latest")
    result = run(zip_path(old), zip_path(new), None, dtpp, llm and bool(os.environ.get("ANTHROPIC_API_KEY")))
    n = write_diff(result, out)
    dump({"schema_version": SCHEMA_VERSION, "from_cycle": old.isoformat(), "to_cycle": new.isoformat(),
          "upcoming": upcoming, "includes_charts": bool(dtpp), "changed_airports": n,
          "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
         os.path.join(out, "meta.json"))
    apts = directory(zip_path(new))
    dump({"schema_version": SCHEMA_VERSION, "cycle": new.isoformat(), "airports": apts},
         os.path.join(SITE, "airports.json"))
    if os.path.isdir(HISTORY):
        shutil.copytree(HISTORY, os.path.join(SITE, "history"),
                        ignore=shutil.ignore_patterns("cycles.json"))
    with open(os.path.join(SITE, "index.html"), "w") as f:
        f.write(INDEX_HTML.format(label="Upcoming" if upcoming else "Current", old=old, new=new))
    print(f"site built: {old} -> {new} ({'upcoming' if upcoming else 'current'}), {n} airports")