"""
Regression checks for the engine: a gold set of real FAA changes, and a snapshot of what the
engine says about one real cycle pair.

  python -m amend.gold                     score the gold set (tests/gold/cases.jsonl)
  python -m amend.gold -v                  ... and print every case that doesn't pass
  python -m amend.gold --snapshot          re-run the snapshot pair and diff it against the file
  python -m amend.gold --update-snapshot   rewrite the snapshot after a change you meant to make

The gold set needs nothing downloaded: every case carries the real FAA rows it came from, and
runs through the whole pipeline (diff, collapse, summaries) as a two-cycle zip of those rows.
The snapshot needs the two NASR zips in data/ (see tests/gold/README.md).
"""
import argparse
import contextlib
import csv
import difflib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile

from . import remarks
from .pipeline import run

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(HERE, "tests", "gold")
CASES = os.path.join(GOLD, "cases.jsonl")
SNAPSHOT_META = os.path.join(GOLD, "snapshot.json")
DATA = os.path.join(HERE, "data")

PRIORITIES = ("action", "ifr", "fyi", "hidden")
NEEDS_HUMAN = "claude, against the FAA source rows; needs human check"


@contextlib.contextmanager
def no_translations():
    """the engine reads remark_cache.json, which grows every cycle. regression runs use an
    empty cache so they only depend on the engine, never on what got translated since."""
    real = remarks.CACHE_FILE
    with tempfile.TemporaryDirectory() as d:
        remarks.CACHE_FILE = os.path.join(d, "cache.json")
        try:
            yield
        finally:
            remarks.CACHE_FILE = real


# ---------------------------------------------------------------- gold set

def load_cases(path=CASES):
    """every case in a .jsonl file, with the line number it came from."""
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith("//"):
                case = json.loads(line)
                case["_line"] = n
                out.append(case)
    return out


def problems(case):
    """what's wrong with a case's shape, as short strings. empty means it can run."""
    out = []
    for k in ("id", "source", "from_cycle", "cycle", "airport", "field", "old", "new",
              "kind", "rows", "expected", "verified_by"):
        if k not in case:
            out.append(f"missing {k}")
    exp = case.get("expected", {})
    if exp.get("priority") not in PRIORITIES:
        out.append(f"expected.priority must be one of {', '.join(PRIORITIES)}")
    if exp.get("priority") != "hidden" and not exp.get("category"):
        out.append("expected.category is required unless the change is hidden")
    rows = case.get("rows", {})
    header = rows.get("header") or []
    for side in ("old", "new"):
        for r in rows.get(side) or []:
            if len(r) != len(header):
                out.append(f"a {side} row has {len(r)} values for {len(header)} columns")
    if case.get("kind") in ("changed", "removed") and not rows.get("old"):
        out.append("no old row")
    if case.get("kind") in ("changed", "added") and not rows.get("new"):
        out.append("no new row")
    return out


def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r")      # FAA files use old-mac line endings
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


def run_case(case):
    """the engine's changes at the case's airport: [change, ...] in the public JSON shape."""
    rows = case["rows"]
    extra = {n: _csv(f["header"], f["rows"]) for n, f in case.get("extra_files", {}).items()}
    if case["source"].upper() != "APT_BASE.CSV" and "APT_BASE.csv" not in extra:
        # the site runs in all-airports mode, which takes the airport list from APT_BASE.
        # the same one-line APT_BASE in both cycles adds the airport without adding a change
        extra["APT_BASE.csv"] = _csv(["ARPT_ID"], [[case["airport"]]])
    with tempfile.TemporaryDirectory() as d, no_translations():
        old = os.path.join(d, f"{case['from_cycle']}_CSV.zip")
        new = os.path.join(d, f"{case['cycle']}_CSV.zip")
        _zip(old, {**extra, case["source"]: _csv(rows["header"], rows.get("old") or [])})
        _zip(new, {**extra, case["source"]: _csv(rows["header"], rows.get("new") or [])})
        # ids=None: all-airports mode, the way the site builds (a row is only about an airport
        # when its id column says so, not because some other column happens to match)
        result = run(old, new, None, log=lambda *_: None)
    return result["airports"].get(case["airport"], [])


def judge(case, changes):
    """(passed, engine priority, why) for one case. the engine's priority is 'hidden' when it
    said nothing at the airport."""
    exp = case["expected"]
    if exp["priority"] == "hidden":
        if not changes:
            return True, "hidden", ""
        c = changes[0]
        return False, c["priority"], f"expected nothing, engine said [{c['priority']}] {c['summary']}"
    if not changes:
        return False, "hidden", "engine said nothing"
    c = changes[0]   # the highest-ranked change; expected.count pins how many when it matters
    why = []
    if c["priority"] != exp["priority"]:
        why.append(f"priority {c['priority']} (expected {exp['priority']})")
    if c["category"] != exp["category"]:
        why.append(f"category {c['category']} (expected {exp['category']})")
    for s in exp.get("summary_contains", []):
        if s not in c["summary"]:
            why.append(f"summary lacks {s!r}")
    for s in exp.get("summary_lacks", []):
        if s in c["summary"]:
            why.append(f"summary has {s!r}")
    if exp.get("count") and len(changes) != exp["count"]:
        why.append(f"{len(changes)} changes (expected {exp['count']})")
    if why:
        why.append(f"engine said: {c['summary']!r}")
    return not why, c["priority"], "; ".join(why)


def score(cases):
    """run every case. returns {"total", "passed", "false_action", "missed_action",
    "known_failures", "fixed", "results": [...]}.
    false action: the engine says act where the gold set doesn't. missed action: the other way."""
    results = []
    for case in cases:
        bad = problems(case)
        if bad:
            results.append({"case": case, "passed": False, "engine": None,
                            "why": "bad case: " + "; ".join(bad)})
            continue
        changes = run_case(case)
        ok, got, why = judge(case, changes)
        results.append({"case": case, "passed": ok, "engine": got, "why": why, "changes": changes})
    exp = lambda r: r["case"].get("expected", {}).get("priority")
    return {
        "total": len(results),
        "passed": sum(r["passed"] for r in results),
        "false_action": sum(r["engine"] == "action" and exp(r) != "action" for r in results),
        "missed_action": sum(r["engine"] not in (None, "action") and exp(r) == "action"
                             for r in results),
        # cases that fail today on purpose (candidate engine bugs), and ones that now pass
        "known_failures": sum(bool(r["case"].get("known_failure")) and not r["passed"] for r in results),
        "fixed": [r["case"]["id"] for r in results if r["case"].get("known_failure") and r["passed"]],
        "results": results,
    }


def report(s, verbose=False, out=sys.stdout):
    unexpected = [r for r in s["results"] if not r["passed"] and not r["case"].get("known_failure")]
    print(f"gold set: {s['passed']} / {s['total']} passed "
          f"({s['known_failures']} known failures, {len(unexpected)} unexpected)", file=out)
    print(f"  false action: {s['false_action']}   missed action: {s['missed_action']}", file=out)
    human = sum("needs human check" not in r["case"].get("verified_by", "needs human check")
                for r in s["results"])
    print(f"  hand-checked by a person: {human} / {s['total']}", file=out)
    for r in s["results"]:
        if r["passed"] and not (verbose and r["case"].get("known_failure")):
            continue
        if not verbose and r["case"].get("known_failure"):
            continue
        c = r["case"]
        tag = "known" if c.get("known_failure") else "FAIL"
        print(f"  {tag} {c.get('id')} {c.get('airport')} {c.get('source')} {c.get('field')}: "
              f"{r['why']}", file=out)
    for cid in s["fixed"]:
        print(f"  FIXED {cid}: passes now; drop its known_failure flag", file=out)
    return not unexpected and not s["fixed"]


# ---------------------------------------------------------------- snapshot

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot_meta(path=SNAPSHOT_META):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def snapshot_inputs(meta, data=DATA):
    """(old zip, new zip), or raise FileNotFoundError / ValueError saying what's wrong."""
    paths = []
    for side in ("from", "to"):
        z = meta["zips"][side]
        p = os.path.join(data, z["file"])
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        got = sha256(p)
        if got != z["sha256"]:
            raise ValueError(f"{p} is not the FAA file the snapshot was made from "
                             f"(sha256 {got[:12]}..., expected {z['sha256'][:12]}...)")
        paths.append(p)
    return tuple(paths)


# the engine's output used to depend on Python's string hash seed (diff.py paired rows in set
# order). it doesn't anymore, so the snapshot runs under a random seed: every run on the real
# zips is also a check that the same FAA files give the same output.
HASH_SEED = "random"
MARK = "\n@@snapshot@@"


def make_snapshot(meta, data=DATA):
    """the engine's output for the snapshot airports, the way the site builds it: every airport
    at once (all-airports mode), then only the snapshot's airports kept."""
    old, new = snapshot_inputs(meta, data)
    env = {**os.environ, "PYTHONHASHSEED": HASH_SEED}
    p = subprocess.run([sys.executable, "-c", "import sys; from amend import gold; gold._child(sys.argv[1:])",
                        old, new, *meta["airports"]], cwd=HERE, env=env, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"snapshot run failed:\n{p.stderr[-3000:]}")
    return json.loads(p.stdout.rsplit(MARK, 1)[1])   # the engine prints warnings to stdout too


def _child(argv):
    old, new, *apts = argv
    with no_translations():
        result = run(old, new, None, log=lambda *_: None)
    print(MARK + json.dumps({"from_cycle": result["from_cycle"], "to_cycle": result["to_cycle"],
                      "airports": {a: result["airports"].get(a, []) for a in sorted(apts)},
                      "hidden": {a: result["hidden"].get(a, 0) for a in sorted(apts)}}))


def snapshot_path(meta):
    return os.path.join(GOLD, f"snapshot_{meta['from_cycle']}_{meta['to_cycle']}.json")


def dumps(obj):
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def snapshot_diff(expected, got):
    """readable lines saying what changed, per airport, empty if nothing did."""
    out = []
    for apt in sorted(set(expected["airports"]) | set(got["airports"])):
        line = lambda c: f"[{c['priority']}] {c['category']}: {c['summary']}"
        a = [line(c) for c in expected["airports"].get(apt, [])]
        b = [line(c) for c in got["airports"].get(apt, [])]
        if a != b:
            out.append(f"--- {apt}")
            out += [f"  {l}" for l in difflib.unified_diff(a, b, lineterm="", n=0)
                    if not l.startswith(("---", "+++", "@@"))]
        ha, hb = expected["hidden"].get(apt, 0), got["hidden"].get(apt, 0)
        if ha != hb:
            out.append(f"--- {apt}: hidden noise {ha} -> {hb}")
    if not out and dumps(expected) != dumps(got):
        out.append("same summaries, but other fields differ (ids, fields, details): "
                   "diff the snapshot file after --update-snapshot to see them")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m amend.gold", description=__doc__.split("\n\n")[0])
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--cases", default=CASES)
    p.add_argument("--snapshot", action="store_true", help="diff the snapshot pair too")
    p.add_argument("--update-snapshot", action="store_true", help="rewrite the snapshot file")
    p.add_argument("--data", default=DATA, help="where the snapshot's NASR zips are")
    a = p.parse_args(argv)

    if a.snapshot or a.update_snapshot:
        meta = snapshot_meta()
        try:
            got = make_snapshot(meta, a.data)
        except (FileNotFoundError, ValueError) as e:
            sys.exit(f"snapshot: {e}")
        path = snapshot_path(meta)
        if a.update_snapshot:
            with open(path, "w", encoding="utf-8") as f:
                f.write(dumps(got))
            print(f"wrote {path}: {sum(map(len, got['airports'].values()))} changes at "
                  f"{sum(bool(v) for v in got['airports'].values())} airports")
            return
        with open(path, encoding="utf-8") as f:
            diff = snapshot_diff(json.load(f), got)
        print("snapshot: unchanged" if not diff else "snapshot changed:\n" + "\n".join(diff))
        if diff:
            sys.exit(1)

    ok = report(score(load_cases(a.cases)), a.verbose)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
