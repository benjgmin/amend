"""
Is a rebuild needed, and is a fresh build safe to publish?

  python -m amend check    scheduled runs: build only if the FAA posted something new, the repo
                           changed since the last deploy, or the live data is getting old
  python -m amend verify   before deploying: refuse a site that's empty or half-built, so the
                           last good deploy stays up

check reads the live site (latest/meta.json, build.json) and pokes the FAA urls for a few bytes,
so it takes seconds, not the full download + diff. when it can't tell, it says build.
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re
import urllib.request

from .cycles import CYCLE, airspace_url, csv_url, dtpp_url, in_effect, probe

SITE_URL = os.environ.get("AMEND_SITE_URL", "https://amend.watch")
MAX_AGE = dt.timedelta(hours=20)   # rebuild at least this often (the site calls 36h stale)
# what the site is built from, besides FAA data. the build records a hash of these in
# build.json; a different hash in the repo means a merge (or a data commit) isn't live yet
INPUTS = ("amend/*.py", "amend/fonts/*", "watchlists/*.json", "history/*.json", "remark_cache.json")


def fingerprint(root="."):
    h = hashlib.sha256()
    for pattern in INPUTS:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            h.update(os.path.relpath(path, root).replace(os.sep, "/").encode() + b"\0")
            with open(path, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "amend", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def decide(now, meta, build, inputs, history_cycles, posted):
    """reasons to rebuild (empty list: the live site is current).
    meta/build: the live latest/meta.json and build.json (None if unreadable).
    posted(url) -> True / False / None (couldn't tell)."""
    if not meta:
        return ["couldn't read the live latest/meta.json"]
    why = []
    if not build or build.get("inputs") != inputs:
        why.append("the repo changed since the last deploy")
    cur = in_effect(now)
    if cur.isoformat() not in history_cycles:
        why.append(f"history doesn't have the {cur} cycle yet")
    nxt = posted(csv_url(cur + CYCLE))
    if nxt is None:
        why.append("couldn't tell whether the next cycle is posted")
    want = cur + CYCLE if nxt else cur
    if meta.get("to_cycle") != want.isoformat() or bool(meta.get("upcoming")) != (want > cur):
        why.append(f"live site shows {meta.get('to_cycle')}, FAA has {want}"
                   + (" (upcoming)" if want > cur else ""))
    elif not meta.get("includes_charts") and posted(dtpp_url(want)) is not False:
        why.append(f"d-TPP charts for {want} may be posted now")
    elif not meta.get("includes_airspace") and all(
            posted(airspace_url(d)) is not False for d in (want - CYCLE, want)):   # needs both
        why.append(f"airspace shapes for {want} may be posted now")
    try:
        age = now - dt.datetime.fromisoformat(meta["generated"])
        if age > MAX_AGE:
            why.append(f"last build was {age.total_seconds() / 3600:.0f}h ago")
    except (KeyError, TypeError, ValueError):
        why.append("live meta.json has no build time")
    return why


def check(output=None, now=None):
    """print why (or why not) to build; write build=true/false to $GITHUB_OUTPUT."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        try:
            meta = _get_json(f"{SITE_URL}/latest/meta.json")
        except Exception as e:
            print(f"  couldn't read the live site: {e}")
            meta = None
        try:
            build = _get_json(f"{SITE_URL}/build.json")
        except Exception:
            build = None
        try:
            with open(os.path.join("history", "cycles.json")) as f:
                history_cycles = json.load(f)["cycles"]
        except (OSError, ValueError, KeyError):
            history_cycles = []
        why = decide(now, meta, build, fingerprint(), history_cycles, probe)
    except Exception as e:   # never let the check itself be the reason the site goes stale
        why = [f"check failed ({type(e).__name__}: {e})"]
    print("build: " + ("; ".join(why) if why else "no, live site is current"))
    output = output or os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as f:
            f.write(f"build={'true' if why else 'false'}\n")
    return bool(why)


MIN_AIRPORTS = 5000    # airports.json has ~20k; anything near empty means a broken read


def verify(site="site", min_airports=MIN_AIRPORTS):
    """problems with a built site, as short strings. empty means it's fine to deploy."""
    out = []

    def load(rel):
        try:
            with open(os.path.join(site, rel), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            out.append(f"{rel}: {e}")
            return None

    try:
        if os.path.getsize(os.path.join(site, "index.html")) < 1000:
            out.append("index.html is nearly empty")
    except OSError:
        out.append("index.html missing")
    meta, index = load("latest/meta.json"), load("latest/index.json")
    if meta:
        try:
            frm, to = (dt.date.fromisoformat(meta[k]) for k in ("from_cycle", "to_cycle"))
            if to <= frm:
                out.append(f"meta.json compares {frm} to {to}")
        except (KeyError, TypeError, ValueError):
            out.append("meta.json has no valid from_cycle / to_cycle")
    if index is not None:
        apts = index.get("airports") or {}
        if not apts:
            out.append("latest/index.json lists no changed airports")
        if meta and meta.get("changed_airports") != len(apts):
            out.append(f"meta.json says {meta.get('changed_airports')} changed airports, index.json has {len(apts)}")
        if meta and (index.get("from_cycle"), index.get("to_cycle")) != (meta.get("from_cycle"), meta.get("to_cycle")):
            out.append("latest/index.json and meta.json are for different cycles")
        gone = [a for a in apts if not os.path.exists(os.path.join(site, "latest", f"{a}.json"))]
        if gone:
            out.append(f"{len(gone)} airports in latest/index.json have no file, e.g. {gone[0]}")
        nopage = [a for a in apts if re.fullmatch(r"[A-Z0-9]{2,4}", a)   # web.build's page rule
                  and not os.path.exists(os.path.join(site, a, "index.html"))]
        if nopage:
            out.append(f"{len(nopage)} changed airports have no page, e.g. {nopage[0]}")
    directory = load("airports.json")
    if directory is not None and len(directory.get("airports") or []) < min_airports:
        out.append(f"airports.json has {len(directory.get('airports') or [])} airports (expected {min_airports}+)")
    hist = load("history/index.json")
    if hist is not None and not hist.get("cycles"):
        out.append("history/index.json has no cycles")
    if not os.path.exists(os.path.join(site, "build.json")):
        out.append("build.json missing")
    return out
