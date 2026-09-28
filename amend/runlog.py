"""
The processing log: one record for every time the engine diffs a cycle pair, written by
`python -m amend latest` and `python -m amend history`, committed by the workflow.

Every number in a record is read off the run itself (files on disk, rows parsed, changes
made, checks run). Nothing is estimated; a value the run couldn't know is null. The status,
accuracy and engine-health pages are meant to be built from these records, so the shape below
is a contract: add fields freely, but rename or remove one only with a RUNLOG_VERSION bump.

audit/runs/<cycle>.json, one file per FAA cycle in effect when the run started (so a file
covers 28 days of runs), oldest run first:

  {"runlog_version": 1, "cycle": "2026-09-03", "runs": [Run, ...]}

Run:
  runlog_version  int     shape of this record
  engine          string  amend.ENGINE_VERSION that made the changes
  engine_hash     string  sha256 (16 hex) of the engine source files (ENGINE_MODULES), to catch
                          an engine change shipped without an ENGINE_VERSION bump
  commit          string  git sha the run was built from (GITHUB_SHA), null locally
  run             object  {"id", "attempt", "trigger", "url"} of the GitHub Actions run;
                          trigger is the event (schedule, push, workflow_dispatch) or "local"
  hash_seed       string  PYTHONHASHSEED the run used, null if random. the diff's row pairing
                          still depends on set order, so output is only reproducible with the
                          same engine, the same FAA files and the same seed
  mode            string  "latest" (the site's current/upcoming diff) or "history" (one cycle
                          appended to history/)
  started_at, finished_at   ISO UTC timestamps; seconds: float, wall time
  from_cycle, to_cycle      ISO dates, null if the run failed before choosing them
  upcoming        bool    latest only: to_cycle hasn't taken effect yet (null in history)
  sources         array   one per FAA file used:
                          {"role": nasr_old|nasr_new|dtpp|airspace_old|airspace_new,
                           "url", "file", "bytes", "sha256",
                           "retrieved_at"   when amend downloaded it (a file kept in the Actions
                                            cache keeps its first time); null if it was cached
                                            before this log existed,
                           "last_modified", "etag"   what the FAA server said, or null}
  csv_rows        object  {"old": {file: rows}, "new": {file: rows}}: data rows in every NASR
                          CSV the engine reads (hidden files like FIX or CDR aren't read)
  airspace_shapes object  {"old": n, "new": n} class airspace shapes read, or null when the
                          shapefiles weren't used (not posted, or unreadable: see checks)
  changes         object  {"airports", "action", "ifr", "fyi", "hidden", "by_category": {}}
                          what the diff produced, before any gate
  remarks         object  {"texts": remarks needing plain English, "plain_english": shown
                           translated, "raw_fallback": shown as FAA text, "ai": model usage
                           if the remark code reports it, else null}
  checks          object  {"errors": [...], "warnings": [...], "error_count", "warning_count"}:
                          input checks + the release audit (amend/audit.py), lists capped at 100
  outcome         string  latest: "built" (site written, handed to verify/deploy)
                          history: "appended" (entries written to history/)
                          either: "blocked" (a check failed, nothing published),
                                  "failed" (the run crashed, e.g. the FAA server was down),
                                  "skipped" (history: the FAA archive doesn't have that cycle)
  error           string  what crashed or blocked it, else null
  verified        bool    latest only: `amend verify` passed on the built site; null until it runs
  published       bool    true once every check amend runs has passed and the output was handed
                          on (latest: built and verified, then deployed by the next job; history:
                          appended, then committed). false if blocked or failed, null while
                          waiting on verify. the live site's build.json names the run it came
                          from ("run"), which confirms a deploy actually landed
"""
import datetime as dt
import glob
import hashlib
import json
import os
from collections import Counter

from . import ENGINE_VERSION
from .cycles import airspace_path, airspace_url, csv_url, dtpp_url, in_effect, meta_path, zip_path
from .nasr import InputError

RUNLOG_VERSION = 1
RUNS = os.path.join("audit", "runs")
CAP = 100   # messages kept per list; the counts are always exact

# the files that decide what a change says, how it's ranked and whether it shows up
ENGINE_MODULES = ("airspace", "collapse", "diff", "dtpp", "english", "nasr", "pipeline",
                  "procedures", "remarks", "rules")


def engine_hash():
    here = os.path.dirname(__file__)
    h = hashlib.sha256()
    for m in ENGINE_MODULES:
        with open(os.path.join(here, f"{m}.py"), "rb") as f:
            h.update(m.encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.isoformat(timespec="seconds")


def _actions_run():
    env = os.environ.get
    rid = env("GITHUB_RUN_ID")
    url = (f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{env('GITHUB_REPOSITORY')}/actions/runs/{rid}"
           if rid and env("GITHUB_REPOSITORY") else None)
    return {"id": rid, "attempt": env("GITHUB_RUN_ATTEMPT"),
            "trigger": env("GITHUB_EVENT_NAME") or "local", "url": url}


def file_info(role, url, path):
    """(source record, problems) for one FAA file the run used, read off the file itself."""
    sha, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
            size += len(chunk)
    info = {"role": role, "url": url, "file": os.path.basename(path), "bytes": size,
            "sha256": sha.hexdigest(), "retrieved_at": None, "last_modified": None, "etag": None}
    problems = []
    try:
        with open(meta_path(path)) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = None
    if meta:
        if meta.get("sha256") != info["sha256"] or meta.get("url") != url:
            problems.append(f"{info['file']} isn't the file that was downloaded from {meta.get('url')} "
                            f"(sha256 {str(meta.get('sha256'))[:12]}, now {info['sha256'][:12]})")
        else:
            info.update({k: meta.get(k) for k in ("retrieved_at", "last_modified", "etag")})
    return info, problems


def changes_summary(result):
    ch = [c for cs in result["airports"].values() for c in cs]
    pri = Counter(c["priority"] for c in ch)
    return {"airports": len(result["airports"]),
            **{p: pri.get(p, 0) for p in ("action", "ifr", "fyi")},
            "hidden": sum(result.get("hidden", {}).values()),
            "by_category": dict(sorted(Counter(c["category"] for c in ch).items()))}


class Run:
    """one processing record. use as a context manager around one cycle pair's work: the record
    is written on the way out, whatever happens, and exceptions still propagate.

        with Run("latest") as r:
            r.cycles(old, new, upcoming=True)
            r.source("nasr_old", url, path) ...
            r.result(result)
            r.checks(report)          # after this, a failed gate: r.block(msg); raise ...
            r.done()                  # built / appended
    """

    def __init__(self, mode, log_dir=RUNS):
        self.dir, self.problems = log_dir, []
        self.t0 = _now()
        self.cycle = in_effect(self.t0).isoformat()
        self.rec = {
            "runlog_version": RUNLOG_VERSION, "engine": ENGINE_VERSION, "engine_hash": engine_hash(),
            "commit": os.environ.get("GITHUB_SHA") or None, "run": _actions_run(), "mode": mode,
            "hash_seed": os.environ.get("PYTHONHASHSEED"),
            "started_at": _iso(self.t0), "finished_at": None, "seconds": None,
            "from_cycle": None, "to_cycle": None, "upcoming": None, "sources": [], "csv_rows": None,
            "airspace_shapes": None,
            "changes": None, "remarks": None, "checks": None, "outcome": None, "error": None,
            "verified": None, "published": None}

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is not None and self.rec["outcome"] is None:
            msg = str(ev) if issubclass(et, (SystemExit, InputError)) else f"{et.__name__}: {ev}"
            if issubclass(et, InputError):    # an FAA file that can't be read fully is a failed check
                self.rec["outcome"] = "blocked"
                self.checks({"errors": [msg], "warnings": []})
                print(f"::error title=input check::{msg}")
            else:
                self.rec["outcome"] = "failed"
            self.rec["error"] = msg
        if self.rec["outcome"] in ("blocked", "failed"):
            self.rec["published"] = False
        if self.rec["outcome"] is not None:
            self.write()
        return False

    def cycles(self, old, new, upcoming=None):
        self.rec.update(from_cycle=old and str(old), to_cycle=new and str(new), upcoming=upcoming)

    def faa_sources(self, old, new, dtpp=None, airspace=None):
        """every FAA file one cycle-pair diff reads (cycles.py paths and urls)."""
        self.source("nasr_old", csv_url(old), zip_path(old))
        self.source("nasr_new", csv_url(new), zip_path(new))
        if dtpp:
            self.source("dtpp", dtpp_url(new), dtpp)
        if airspace:
            self.source("airspace_old", airspace_url(old), airspace_path(old))
            self.source("airspace_new", airspace_url(new), airspace_path(new))

    def source(self, role, url, path):
        """record an FAA file the run used. a file that no longer matches its download record
        (the Actions cache kept a different file) is a problem the gate must stop on."""
        info, problems = file_info(role, url, path)
        self.rec["sources"].append(info)
        self.problems += problems

    def result(self, result):
        self.rec["csv_rows"] = result.get("csv_rows")
        self.rec["airspace_shapes"] = result.get("airspace_shapes")
        self.rec["changes"] = changes_summary(result)
        rm = result.get("remarks")
        if rm:
            from . import remarks
            stats = getattr(remarks, "STATS", None)
            self.rec["remarks"] = {**rm, "raw_fallback": rm["texts"] - rm["plain_english"],
                                   "ai": dict(stats) if isinstance(stats, dict) else None}

    def checks(self, report):
        """report: {"errors", "warnings"}, the gate's full verdict. the caller adds
        self.problems (cached files that don't match their download) to its errors."""
        e, w = report["errors"], report["warnings"]
        self.rec["checks"] = {"errors": e[:CAP], "warnings": w[:CAP],
                              "error_count": len(e), "warning_count": len(w)}

    def engine_warning(self):
        """a warning if the engine code differs from the last logged run's under the same
        ENGINE_VERSION: someone changed the engine and forgot the bump."""
        last = last_run(self.dir)
        if last and last.get("engine") == ENGINE_VERSION and last.get("engine_hash") != self.rec["engine_hash"]:
            return [f"engine code changed since the last run (commit {str(last.get('commit'))[:7]}) "
                    f"but ENGINE_VERSION is still {ENGINE_VERSION}. if output can change, bump it in amend/__init__.py"]
        return []

    def block(self, msg):
        self.rec.update(outcome="blocked", error=msg)

    def skip(self, msg):
        self.rec.update(outcome="skipped", error=msg)

    def done(self):
        self.rec["outcome"] = "built" if self.rec["mode"] == "latest" else "appended"
        if self.rec["mode"] == "history":
            self.rec["published"] = True

    def write(self):
        end = _now()
        self.rec.update(finished_at=_iso(end), seconds=round((end - self.t0).total_seconds(), 1))
        append(self.rec, self.cycle, self.dir)


def _path(cycle, log_dir):
    return os.path.join(log_dir, f"{cycle}.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _write(doc, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


def append(rec, cycle, log_dir=RUNS):
    path = _path(cycle, log_dir)
    doc = _read(path) or {"runlog_version": RUNLOG_VERSION, "cycle": cycle, "runs": []}
    doc["runs"].append(rec)
    _write(doc, path)
    return path


def files(log_dir=RUNS):
    return sorted(glob.glob(os.path.join(log_dir, "*.json")))


def runs(log_dir=RUNS, last_files=None):
    """every record, oldest first (only the newest `last_files` files if given)."""
    out = []
    for path in files(log_dir)[-last_files:] if last_files else files(log_dir):
        out += (_read(path) or {}).get("runs", [])
    return out


def last_run(log_dir=RUNS):
    rs = runs(log_dir, last_files=2)
    return rs[-1] if rs else None


def mark_verified(ok, problems=(), log_dir=RUNS):
    """record `amend verify`'s result on this Actions run's latest record. False if there's none."""
    rid = os.environ.get("GITHUB_RUN_ID")
    for path in reversed(files(log_dir)[-2:]):
        doc = _read(path)
        for rec in reversed(doc["runs"]):
            if rec["mode"] == "latest" and rec["run"].get("id") == rid and rec["outcome"] == "built":
                rec["verified"] = rec["published"] = bool(ok)
                if not ok:
                    rec["error"] = "verify: " + "; ".join(problems)[:1000]
                _write(doc, path)
                return True
    return False
