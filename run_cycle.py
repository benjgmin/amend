#!/usr/bin/env python3
"""
run_cycle.py - figure out the FAA cycles, download what's needed, run nasr_diff for every
airport, and build site/ for GitHub Pages. this is what the GitHub Action runs.

if the NEXT cycle's data is already posted (FAA posts it ~3 weeks early), it reports
upcoming changes (current -> next). otherwise it reports what changed this cycle (prev -> current).

run locally:  python run_cycle.py          (add --no-llm to skip Claude)
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

ANCHOR = dt.date(2026, 9, 3)   # a known NASR/d-TPP effective date
CYCLE = dt.timedelta(days=28)
DATA = "data"
SITE = "site"


def cycle_on_or_before(day):
    n = (day - ANCHOR).days // 28
    return ANCHOR + n * CYCLE


def csv_url(d):
    return f"https://nfdc.faa.gov/webContent/28DaySub/extra/{d.day:02d}_{d.strftime('%b')}_{d.year}_CSV.zip"


def dtpp_id(d):
    """d-TPP cycle id, e.g. 2610 = 10th 28-day cycle of 2026."""
    n, x = 1, d
    while (x - CYCLE).year == d.year:
        x -= CYCLE
        n += 1
    return f"{d.year % 100:02d}{n:02d}"


def dtpp_url(d):
    return f"https://aeronav.faa.gov/d-tpp/{dtpp_id(d)}/xml_data/d-tpp_Metafile.xml"


def download(url, path):
    """download url to path unless it's already there. returns True if we have the file."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    print(f"downloading {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "faa-change-tracker"})
        with urllib.request.urlopen(req, timeout=300) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(path + ".part", path)
        return True
    except urllib.error.HTTPError as e:
        print(f"  not available ({e.code})")
    except Exception as e:
        print(f"  failed: {e}")
    if os.path.exists(path + ".part"):
        os.remove(path + ".part")
    return False


def main():
    os.makedirs(DATA, exist_ok=True)
    today = dt.date.today()
    current = cycle_on_or_before(today)
    nxt, prev = current + CYCLE, current - CYCLE

    zip_of = lambda d: os.path.join(DATA, f"{d.isoformat()}_CSV.zip")
    if download(csv_url(nxt), zip_of(nxt)):
        old, new, upcoming = current, nxt, True
    else:
        old, new, upcoming = prev, current, False
    for d in (old, new):
        if not download(csv_url(d), zip_of(d)):
            sys.exit(f"can't get NASR data for {d}, giving up")

    dtpp_path = os.path.join(DATA, f"dtpp_{dtpp_id(new)}.xml")
    have_dtpp = download(dtpp_url(new), dtpp_path)

    out = os.path.join(SITE, "latest")
    shutil.rmtree(SITE, ignore_errors=True)
    cmd = [sys.executable, "nasr_diff.py", zip_of(old), zip_of(new), "--all-airports", "--out", out]
    if have_dtpp:
        cmd += ["--dtpp", dtpp_path]
    if "--no-llm" not in sys.argv and os.environ.get("ANTHROPIC_API_KEY"):
        cmd.append("--llm")
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    meta = {"from_cycle": old.isoformat(), "to_cycle": new.isoformat(), "upcoming": upcoming,
            "includes_charts": have_dtpp,
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(SITE, "index.html"), "w") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>FAA change tracker</title>
<body style="font-family:system-ui;max-width:40em;margin:3em auto;padding:0 1em">
<h1>FAA change tracker</h1>
<p>{'Upcoming' if upcoming else 'Current'} changes: NASR cycle {old} &rarr; {new}.</p>
<p>Per-airport JSON: <code>latest/&lt;AIRPORT&gt;.json</code> (e.g. <a href="latest/DAB.json">DAB</a>),
list of changed airports: <a href="latest/index.json">latest/index.json</a>,
run info: <a href="latest/meta.json">latest/meta.json</a>.</p>
<p>Not for navigation. Always check official FAA publications and NOTAMs.</p></body>""")
    print(f"site built: {old} -> {new} ({'upcoming' if upcoming else 'current'})")


if __name__ == "__main__":
    main()