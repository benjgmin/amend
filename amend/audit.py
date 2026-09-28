"""
Sanity checks on a built cycle, before anything reaches pilots.

  errors    stop the build (the site keeps the last good version, the failure alert fires)
  warnings  let the build through, but show up in the Actions log, the run summary and
            audit/<cycle>.json, which the daily review routine reads

Also writes the review packet (audit/<cycle>.json): every action and IFR item at the
airports in named watchlists plus the busiest airports, next to its raw FAA text, so a
reviewer can read each one against the source.
"""
import datetime as dt
import glob
import json
import os
import re
import statistics
from collections import Counter

from .cycles import ANCHOR, CYCLE, cycle_on_or_before, dtpp_id, in_effect
from .remarks import problems
from .rules import REMARK_FILES

AUDIT = "audit"
PRIORITIES = ("action", "ifr", "fyi")

# FAA Core 30 plus the busiest other airline and GA fields. history/ ids, no K prefix
BUSIEST = ["ATL", "BOS", "BWI", "CLT", "DCA", "DEN", "DFW", "DTW", "EWR", "FLL", "HNL", "IAD",
           "IAH", "JFK", "LAS", "LAX", "LGA", "MCO", "MDW", "MEM", "MIA", "MSP", "ORD", "PHL",
           "PHX", "SAN", "SEA", "SFO", "SLC", "TPA", "AUS", "BNA", "DAL", "HOU", "MSY", "OAK",
           "PDX", "SJC", "SNA", "STL", "ANC", "PRC", "DVT", "VNY", "FFZ", "APA", "LGB", "DAB"]

# the action count is compared with the median of recent cycles. a real cycle has never
# been more than ~2x off; a broken classifier or a half-read zip is
ACT_WARN, ACT_FAIL = 2.5, 5.0
MIN_AIRPORTS = 100          # every cycle since 2024 changed 450+ airports

JUNK = re.compile(r"\b(None|nan|NaN|null|undefined)\b|Traceback|\{|\}|�|\?\?")
FREQ_FIELD = re.compile(r"^(FREQ|.*_FREQ|FREQ_.*)$")
RWY_END = re.compile(r"^(0?[1-9]|[12]\d|3[0-6])[LRC]?[WUT]?$|^[NSEW]{1,2}$|^H\d+[A-Z]?$|^[A-Z]\d{0,2}$")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _freq_ok(v):
    """a published frequency: MHz (military low band FM, VHF nav/com incl. military 138-150,
    UHF military) or kHz (NDB, HF). 88-108 is FM broadcast, nothing aviation lives there."""
    f = _num(v)
    return (f is None or 30 <= f < 88 or 108 <= f <= 152 or 225 <= f <= 400
            or 190 <= f <= 1750 or 2000 <= f <= 30000)


def _runway_ok(rwy):
    """'16/34', '09L/27R', '18', 'H1', 'N/S', 'NE/SW', 'B' (seaplane lanes and helipads too)."""
    ends = rwy.split("/")
    if not all(RWY_END.match(e) for e in ends):
        return False
    nums = [int(re.match(r"\d+", e).group()) for e in ends if re.match(r"\d", e)]
    if len(ends) == 2 and len(nums) == 2:   # reciprocal ends are 18 apart (magnetic rounding: 17-19)
        return 17 <= abs(nums[0] - nums[1]) <= 19
    return True


def _generated(change):
    """the summary minus FAA text it quotes: a NAME of 'NONE' prints as 'None' legitimately."""
    s = change["summary"]
    vals = [change.get("original") or ""] + [v for f in change.get("fields", []) for v in (f["old"], f["new"])]
    for v in sorted(filter(None, vals), key=len, reverse=True):
        s = s.replace(v, "").replace(v.title(), "")
    return s


def value_problems(change):
    """impossible-looking new values. usually a column shift or a parse error upstream."""
    out = []
    for f in change.get("fields", []):
        name, new = f["field"], f["new"]
        if not new:
            continue
        if FREQ_FIELD.match(name) and not _freq_ok(new):
            out.append(f"{name} {new} is not a real frequency")
        elif name in ("RWY_ID",) and not _runway_ok(new):
            out.append(f"runway id {new!r} is not a real runway")
        elif name in ("RWY_END_ID",) and not _runway_ok(new):
            out.append(f"runway end {new!r} is not a real runway end")
        elif name in ("RWY_LEN", "RWY_WIDTH") and (_num(new) is None or not 1 <= _num(new) <= 25000):
            out.append(f"{name} {new} ft is impossible")
        elif name == "G_S_ANGLE" and (_num(new) is None or not 2 <= _num(new) <= 7):
            out.append(f"glide slope {new} degrees is impossible")
        elif name.endswith("ELEV") and _num(new) is not None and not -300 <= _num(new) <= 15000:
            out.append(f"{name} {new} ft is impossible")
    for m in re.finditer(r"\bfrequency (\d+\.?\d*)", change["summary"]):
        if not _freq_ok(m.group(1)):
            out.append(f"frequency {m.group(1)} is not a real frequency")
    return out


def translation_problems(change):
    """a remark shown in plain English must keep every number and known contraction of the
    FAA text it came from. remarks.py checks this before caching; this checks the output."""
    raw = change.get("original")
    if not raw or change["source"] not in REMARK_FILES + ("FRQ",) or change["summary"].endswith(raw):
        return []
    plain = change["summary"].split(": ", 1)[-1]
    return problems(raw, plain)


def check_changes(airports, to_cycle):
    """(errors, warnings) for every change in one cycle's output: {apt: [change, ...]}."""
    errors, warnings = [], []
    want_tpp = f"/d-tpp/{dtpp_id(dt.date.fromisoformat(to_cycle))}/"
    for apt, changes in sorted(airports.items()):
        ids, summaries = Counter(c.get("id") for c in changes), Counter(c.get("summary") for c in changes)
        for i, n in ids.items():
            if n > 1:
                errors.append(f"{apt}: change id {i} appears {n} times")
        for s, n in summaries.items():
            if n > 1:
                errors.append(f"{apt}: {s!r} listed {n} times")
        for c in changes:
            s = c.get("summary")
            where = f"{apt}: {s!r}"
            if not isinstance(s, str) or not s.strip():
                errors.append(f"{apt}: change {c.get('id')} has an empty summary")
                continue
            if c.get("priority") not in PRIORITIES:
                errors.append(f"{where} has priority {c.get('priority')!r}")
            if JUNK.search(_generated(c)):
                errors.append(f"{where} looks like a code bug (None/nan/braces)")
            pdf = c.get("chart", {}).get("pdf")
            if pdf and want_tpp not in pdf:
                errors.append(f"{where} links a chart from the wrong cycle: {pdf}")
            for p in translation_problems(c):
                errors.append(f"{where}: translation of {c['original']!r}: {p}")
            if c.get("priority") != "fyi":
                warnings += [f"{where}: {p}" for p in value_problems(c)]
    return errors, warnings


def check_cycles(from_cycle, to_cycle, today=None, gap_ok=False):
    """both dates on the FAA 28-day schedule, one cycle apart, and not in the future."""
    errors = []
    try:
        old, new = dt.date.fromisoformat(from_cycle), dt.date.fromisoformat(to_cycle)
    except ValueError:
        return [f"cycle dates {from_cycle!r} -> {to_cycle!r} aren't dates"]
    for d in (old, new):
        if (d - ANCHOR).days % 28:
            errors.append(f"{d} is not an FAA cycle date (off the 28-day schedule)")
    gap = (new - old).days
    if gap <= 0 or gap % 28 or (gap != 28 and not gap_ok):
        errors.append(f"{old} -> {new} is {gap} days, not one 28-day cycle")
    latest_allowed = (cycle_on_or_before(today) if today else in_effect()) + CYCLE
    if new > latest_allowed:
        errors.append(f"{new} is more than one cycle ahead (FAA posts ~3 weeks early, no more)")
    return errors


def baseline(history_dir, exclude, last=13):
    """action counts per cycle over the last `last` cycles in history/, minus `exclude`."""
    per = Counter()
    for path in glob.glob(os.path.join(history_dir, "*.json")):
        if os.path.basename(path) in ("index.json", "cycles.json"):
            continue
        with open(path, encoding="utf-8") as f:
            for e in json.load(f).get("entries", []):
                if e["cycle"] != exclude:
                    per[e["cycle"]] += e["priority"] == "action"
    return [per[c] for c in sorted(per)[-last:]]


def check_counts(airports, past_actions):
    errors, warnings = [], []
    n_apt = len(airports)
    act = sum(c["priority"] == "action" for ch in airports.values() for c in ch)
    if n_apt < MIN_AIRPORTS:
        errors.append(f"only {n_apt} airports changed (every cycle since 2024 had 450+): "
                      f"probably a truncated or half-read FAA file")
    if not act:
        errors.append("no action items at all")
    if len(past_actions) >= 3 and act:
        med = statistics.median(past_actions)
        ratio = act / med
        msg = f"{act} action items vs a median of {med:.0f} over the last {len(past_actions)} cycles"
        if ratio > ACT_FAIL or ratio < 1 / ACT_FAIL:
            errors.append(msg)
        elif ratio > ACT_WARN or ratio < 1 / ACT_WARN:
            warnings.append(msg)
    return errors, warnings


def audit(result, history_dir="history", today=None, gap_ok=False):
    """everything above for one pipeline.run() result."""
    frm, to = result["from_cycle"], result["to_cycle"]
    errors = check_cycles(frm, to, today, gap_ok)
    if errors:      # the rest assumes real dates
        return {"errors": errors, "warnings": []}
    e1, w1 = check_changes(result["airports"], to)
    e2, w2 = check_counts(result["airports"], baseline(history_dir, exclude=to))
    return {"errors": e1 + e2, "warnings": w1 + w2}


def review_airports(watchlists):
    apts = {a for w in watchlists.values() for a in w["airports"]}
    return sorted(apts | set(BUSIEST))


def packet(result, report, watchlists):
    """what the daily review reads: automated findings + action/IFR items at airports people
    watch, each with the FAA text it came from. no timestamps, so an unchanged cycle makes an
    unchanged file (and no commit)."""
    items = {}
    for apt in review_airports(watchlists):
        keep = [c for c in result["airports"].get(apt, []) if c["priority"] in ("action", "ifr")]
        if keep:
            items[apt] = keep
    return {"from_cycle": result["from_cycle"], "to_cycle": result["to_cycle"],
            "errors": report["errors"], "warnings": report["warnings"],
            "watchlists": {slug: w["airports"] for slug, w in sorted(watchlists.items())},
            "airports": items}


def write_packet(pkt, out_dir=AUDIT):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{pkt['to_cycle']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pkt, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return path


def report_to_actions(report, label):
    """GitHub Actions annotations + run summary, so problems are visible without digging."""
    for e in report["errors"]:
        print(f"::error title=audit {label}::{e}")
    for w in report["warnings"]:
        print(f"::warning title=audit {label}::{w}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### audit {label}: {len(report['errors'])} errors, "
                    f"{len(report['warnings'])} warnings\n\n")
            for kind in ("errors", "warnings"):
                for line in report[kind][:50]:
                    f.write(f"- {'**error**' if kind == 'errors' else 'warning'}: {line}\n")
                if len(report[kind]) > 50:
                    f.write(f"- ... and {len(report[kind]) - 50} more {kind}\n")
            f.write("\n")
    print(f"audit {label}: {len(report['errors'])} errors, {len(report['warnings'])} warnings")
