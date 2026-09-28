"""
The processing log: one record for every time the engine diffs a cycle pair, written by
`python -m amend latest` and `python -m amend history`, committed by the workflow.

Every number in a record is read off the run itself (files on disk, rows parsed, changes
made, checks run). Nothing is estimated; a value the run couldn't know is null. The status,
accuracy and engine-health pages are meant to be built from these records, so the shape below
is a contract: add fields freely, but rename or remove one only with a RUNLOG_VERSION bump.

audit/runs/<cycle>/<started>-<mode>-<run>.json, one file per record, so two builds never
write the same file. (a build that queued behind another checks out the branch when it
starts, so it has the other's data commit: update.yml.) <cycle> is the FAA cycle in effect
when the run started, <started> its start time (UTC, to the microsecond, so the files sort in
start order), <run> the Actions run id and attempt ("36415457140-1") or "local". Each file is
one Run.

Run:
  runlog_version  int     shape of this record
  engine          string  amend.ENGINE_VERSION that made the changes
  engine_hash     string  sha256 (16 hex) of the engine's code and verified glossary
                          (ENGINE_FILES), to catch an engine change shipped without an
                          ENGINE_VERSION bump
  commit          string  git sha the run was built from (AMEND_COMMIT, the branch tip the
                          workflow checked out; GITHUB_SHA if that isn't set), null locally
  run             object  {"id", "attempt", "trigger", "url"} of the GitHub Actions run;
                          trigger is the event (schedule, push, workflow_dispatch) or "local"
  hash_seed       string  PYTHONHASHSEED the run used, null if random. the diff sorts before it
                          pairs rows, so output shouldn't depend on it; the build pins it anyway
                          and records it, so a rebuild can be reproduced exactly
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
                           translated, "raw_fallback": shown as FAA text, "ai": what the
                           translator reported (remarks.STATS), else null: llm_calls,
                           input_tokens, output_tokens, est_cost_usd, sent, translated,
                           rejected (broke the no-guess check), sent_back (the answer was
                           the FAA text, for a remark with a contraction to expand; not kept,
                           asked again at the next ENGINE_VERSION), bad_batches, cache_retired,
                           rejects_skipped (not asked: this ENGINE_VERSION already rejected
                           their answer), llm_errors (calls that failed: no credit, bad key,
                           API down, timeout), llm_error (the first one's HTTP status and
                           message), llm_stopped (gave up after 3 failures in a row),
                           unanswered (left as FAA text because a call failed or its answer
                           was unreadable; asked again next build),
                           unknown_terms {contraction: count} with no verified meaning;
                           addresses and the ICAO and ARTCC ids NASR lists aren't counted}
  summary_checks  object  {"no_english": {"<file> <kind>": n}, "summary_value_mismatches": n}:
                          changes shown as FAA column names because no English template covers
                          them, and summaries that named a number or identifier the FAA record
                          doesn't have (those show the FAA values instead). null if not reported
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
import itertools
import json
import os
from collections import Counter

from . import ENGINE_VERSION
from .cycles import airspace_path, airspace_url, csv_url, dtpp_url, in_effect, meta_path, zip_path
from .nasr import InputError

RUNLOG_VERSION = 1
RUNS = os.path.join("audit", "runs")
CAP = 100   # messages kept per list; the counts are always exact

# the files that decide what a change says, how it's ranked and whether it shows up: the diff
# (pipeline.py) and every module it imports (a test checks), plus the verified glossary, which
# is data but decides what a remark's contractions may say in plain English
ENGINE_FILES = ("airspace.py", "collapse.py", "diff.py", "dtpp.py", "english.py", "fields.py",
                "glossary.py", "glossary.json", "nasr.py", "output.py", "pipeline.py", "procedures.py", "remarks.py",
                "rules.py")


def engine_hash():
    here = os.path.dirname(__file__)
    h = hashlib.sha256()
    for name in ENGINE_FILES:
        with open(os.path.join(here, name), "rb") as f:
            h.update(name.encode() + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()[:16]


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.isoformat(timespec="seconds")


def built_commit():
    """the commit the run built. the workflow checks out the branch when the run starts and
    records it as AMEND_COMMIT; GITHUB_SHA is the commit the run was queued on, older when a
    deploy's data commit landed while it waited. null locally"""
    return os.environ.get("AMEND_COMMIT") or os.environ.get("GITHUB_SHA") or None


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
            "commit": built_commit(), "run": _actions_run(), "mode": mode,
            "hash_seed": os.environ.get("PYTHONHASHSEED"),
            "started_at": _iso(self.t0), "finished_at": None, "seconds": None,
            "from_cycle": None, "to_cycle": None, "upcoming": None, "sources": [], "csv_rows": None,
            "airspace_shapes": None, "changes": None, "remarks": None, "summary_checks": None,
            "checks": None, "outcome": None, "error": None,
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
        self.rec["summary_checks"] = result.get("checks")

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
        migrate(self.dir)
        save(self.rec, self.cycle, self.t0, self.dir)


def _run_key(run):
    """"36415457140-1" (Actions run id and attempt), or "local"."""
    return "-".join(x for x in (run.get("id"), run.get("attempt")) if x) or "local"


def save(rec, cycle, started, log_dir=RUNS):
    """write one record to a new file of its own and return its path. never touches another
    record's file, so records from two runs can't conflict when the workflow pushes them."""
    folder = os.path.join(log_dir, cycle)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.join(folder, f"{started:%Y%m%dT%H%M%S.%f}Z-{rec['mode']}-{_run_key(rec['run'])}")
    for n in itertools.count(1):
        path = stem + (f"-{n}" if n > 1 else "") + ".json"
        try:
            with open(path, "x", encoding="utf-8") as f:
                _dump(rec, f)
            return path
        except FileExistsError:
            continue


def migrate(log_dir=RUNS):
    """split files in the first layout (audit/runs/<cycle>.json holding {"runs": [...]}) into
    one file per record. file names come from each record, so two builds that both migrate
    write identical files and their pushes still agree."""
    for path in sorted(glob.glob(os.path.join(log_dir, "*.json"))):
        doc = _read(path)
        if not (isinstance(doc, dict) and isinstance(doc.get("runs"), list)):
            continue
        cycle = os.path.basename(path)[:-len(".json")]
        for rec in doc["runs"]:
            save(rec, cycle, dt.datetime.fromisoformat(rec["started_at"]), log_dir)
        os.remove(path)


def _dump(rec, f):
    json.dump(rec, f, indent=1, ensure_ascii=False)
    f.write("\n")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def files(log_dir=RUNS, last_cycles=None):
    """record files, oldest first (only the newest `last_cycles` cycle folders if given)."""
    folders = sorted(d for d in glob.glob(os.path.join(log_dir, "*")) if os.path.isdir(d))
    if last_cycles:
        folders = folders[-last_cycles:]
    return [p for d in folders for p in sorted(glob.glob(os.path.join(d, "*.json")))]


def runs(log_dir=RUNS, last_cycles=None):
    """every record, oldest first."""
    return [r for r in map(_read, files(log_dir, last_cycles)) if r]


def last_run(log_dir=RUNS):
    for path in reversed(files(log_dir, last_cycles=2)):
        rec = _read(path)
        if rec:
            return rec
    return None


def mark_verified(ok, problems=(), log_dir=RUNS):
    """record `amend verify`'s result on this Actions run's site build record (the newest
    "built" latest record of this run and attempt). False if there's none."""
    run = _actions_run()
    pattern = os.path.join(log_dir, "*", f"*-latest-{_run_key(run)}*.json")
    for path in sorted(glob.glob(pattern), key=os.path.basename, reverse=True):
        rec = _read(path)
        if rec and rec["outcome"] == "built" and (rec["run"]["id"], rec["run"]["attempt"]) == (run["id"], run["attempt"]):
            rec["verified"] = rec["published"] = bool(ok)
            if not ok:
                rec["error"] = "verify: " + "; ".join(problems)[:1000]
            with open(path, "w", encoding="utf-8") as f:
                _dump(rec, f)
            return True
    return False
