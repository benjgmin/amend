"""Turning piles of raw added/removed rows into the events a pilot would describe."""
import re
from collections import defaultdict

from . import glossary
from .diff import _canon, diff
from .english import PFR_LABELS, PROC_USE, freq_use, ils, ils_part, label, procedure_name, summarize
from .procedures import describe, split_code
from .rules import REMARK_FILES, base


def _rwy_num(rid):
    m = re.match(r"(\d{1,2})", rid or "")
    return int(m.group(1)) if m else None


def _one_apart(a, b):
    """runway numbers one apart (magnetic variation drift); 36 wraps to 01."""
    if a is None or b is None or a == b:
        return False
    d = abs(a - b)
    return min(d, 36 - d) == 1


def _new_or_removed_airport(apt, rs, kind):
    word = {"added": "new airport in FAA database",
            "removed": "airport removed from FAA database"}[kind]
    src = lambda r: base(r["source"])
    base_row = next(r for r in rs if src(r) == "APT_BASE" and r["kind"] == kind)
    name = base_row["row"].get("ARPT_NAME", "").title()
    rwys = [r["row"] for r in rs if src(r) == "APT_RWY" and r["kind"] == kind]
    rwy_txt = "; ".join(
        f"runway {w.get('RWY_ID', '?')} {w.get('RWY_LEN', '?')}x{w.get('RWY_WIDTH', '?')} ft "
        f"{w.get('SURFACE_TYPE_CODE', '').lower()}".strip() for w in rwys)
    ctaf = next((r["row"].get("FREQ") for r in rs if src(r) == "FRQ" and r["kind"] == kind
                 and "CTAF" in r["row"].get("FREQ_USE", "").upper()), None)
    bits = [b for b in (name, rwy_txt, f"CTAF {ctaf}" if ctaf else "") if b]
    used = [base_row["row"]] + rwys + [r["row"] for r in rs if src(r) == "FRQ" and r["kind"] == kind]
    return {"airport": apt, "source": "APT_BASE.csv", "kind": kind,
            "priority": "action" if kind == "removed" else "fyi",
            "summary_override": f"{word}: " + ", ".join(bits),
            "key": {"airport": apt}, "values": [v for row in used for v in row.values()]}


def _near(a, b):
    """the same runway number, or one apart (magnetic variation drift)."""
    return a is not None and b is not None and (a == b or _one_apart(a, b))


def _numbers_near(o_id, n_id):
    """an end number one apart or the same. either end counts: 01/19 -> 18/36 (01 -> 36, 19 ->
    18) is the FAA listing the ends the other way round."""
    ends = lambda rid: [_rwy_num(e) for e in (rid or "").split("/")]
    return any(_near(a, b) for a in ends(o_id) for b in ends(n_id))


def _same_size(o, n):
    return bool(o.get("RWY_LEN")) and (o.get("RWY_LEN"), o.get("RWY_WIDTH")) == (n.get("RWY_LEN"), n.get("RWY_WIDTH"))


def _ends(rs, kind, rid):
    """a runway's end rows (APT_RWY_END) added or removed with it."""
    return [r for r in rs if base(r["source"]) == "APT_RWY_END" and r["kind"] == kind
            and r["row"].get("RWY_ID") == rid]


def _same_heading(rs, o_id, n_id):
    """True if an old end and a new end list the same true alignment (within 2 degrees), False
    if they list others, None if either side lists none."""
    def headings(kind, rid):
        out = set()
        for r in _ends(rs, kind, rid):
            try:
                out.add(round(float(r["row"]["TRUE_ALIGNMENT"])) % 360)
            except (KeyError, ValueError):
                pass
        return out
    old, new = headings("removed", o_id), headings("added", n_id)
    if not old or not new:
        return None
    return any(min(abs(a - b), 360 - abs(a - b)) <= 2 for a in old for b in new)


def _is_renumbering(rs, old, new):
    """one strip under a new number: the first number one apart (magnetic variation drift) or
    the same size, whatever the number (E70 16/34 -> 18/36, A34 05/23 -> 07/25 and 1NY3 18/36 ->
    16/34 kept their ends where they were). ends listed the other way round (01/19 -> 18/36)
    count when the FAA's true alignment shows the same heading: FSO 2026-03-19 yes, I34
    2024-07-11 no (18/36 at 180 degrees, a new, longer 01/19 at 186)."""
    o, n = old["row"], new["row"]
    o_id, n_id = o.get("RWY_ID"), n.get("RWY_ID")
    return (_one_apart(_rwy_num(o_id), _rwy_num(n_id)) or _same_size(o, n)
            or (_numbers_near(o_id, n_id) and _same_heading(rs, o_id, n_id) is True))


def _best_first(olds, news, score):
    """[(old, new), ...] by lowest score first (None: never paired); ties go to list order."""
    cands = []
    for i, o in enumerate(olds):
        for j, n in enumerate(news):
            s = score(o, n)
            if s is not None:
                cands.append((s, i, j))
    used_o, used_n, pairs = set(), set(), []
    for _, i, j in sorted(cands):
        if i not in used_o and j not in used_n:
            used_o.add(i)
            used_n.add(j)
            pairs.append((i, j))
    return [(olds[i], news[j]) for i, j in sorted(pairs)]


def _pair_runways(rs, removed, added):
    """renumberings first, a number one apart before the same size: two runways the same size
    renumbered together pair 09/27 -> 10/28 and 18/36 -> 01/19, never 09/27 -> 01/19 (TUS
    2023-11-30: 12/30 is the old 11L/29R, not 11R/29L). one runway left on each side after
    that was replaced or realigned."""
    def score(old, new):
        if not _is_renumbering(rs, old, new):
            return None
        o, n = old["row"], new["row"]
        return (not _numbers_near(o.get("RWY_ID"), n.get("RWY_ID")), not _same_size(o, n))
    pairs = _best_first(removed, added, score)
    left_o = [r for r in removed if all(r is not o for o, _ in pairs)]
    left_n = [r for r in added if all(r is not n for _, n in pairs)]
    if len(left_o) == 1 and len(left_n) == 1:
        pairs.append((left_o[0], left_n[0]))
    return pairs


def _end_changes(apt, rs, o_id, n_id):
    """a renumbered runway's ends, old against new under the new numbers (25 against 26), so
    what else changed on an end still says so: MRI 2026-09-03, runway 26 touchdown zone
    elevation 137.3 -> 143.1 ft. ends pair by number, else by their place in the runway id."""
    place = lambda row: (row.get("RWY_ID", "").split("/").index(row.get("RWY_END_ID"))
                         if row.get("RWY_END_ID") in row.get("RWY_ID", "").split("/") else None)

    def score(old, new):
        o, n = _rwy_num(old["row"].get("RWY_END_ID")), _rwy_num(new["row"].get("RWY_END_ID"))
        if o is not None and o == n:
            return 0
        if _one_apart(o, n):
            return 1
        return 2 if place(old["row"]) is not None and place(old["row"]) == place(new["row"]) else None
    out = []
    for old, new in _best_first(_ends(rs, "removed", o_id), _ends(rs, "added", n_id), score):
        was = dict(old["row"], RWY_ID=new["row"]["RWY_ID"], RWY_END_ID=new["row"].get("RWY_END_ID", ""))
        out += [r for r in diff({old["source"]: [(apt, was)]}, {new["source"]: [(apt, new["row"])]})
                if r.get("fields")]
    return out


def _runway_changes(apt, rs):
    """pair removed+added runways that are the same strip renumbered or rebuilt.
    returns (new records, ids of raw records they replace)."""
    src = lambda r: base(r["source"])
    removed = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "removed"]
    added = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "added"]
    pairs = _pair_runways(rs, removed, added)

    out, drop = [], set()
    for old, new in pairs:
        o, n = old["row"], new["row"]
        o_id, n_id = o.get("RWY_ID", "?"), n.get("RWY_ID", "?")
        extra = []
        if (o.get("RWY_LEN"), o.get("RWY_WIDTH")) != (n.get("RWY_LEN"), n.get("RWY_WIDTH")):
            extra.append(f"{o.get('RWY_LEN', '?')}x{o.get('RWY_WIDTH', '?')} -> "
                         f"{n.get('RWY_LEN', '?')}x{n.get('RWY_WIDTH', '?')} ft")
        if o.get("SURFACE_TYPE_CODE") != n.get("SURFACE_TYPE_CODE"):
            extra.append(f"surface {o.get('SURFACE_TYPE_CODE', '?').lower()} -> "
                         f"{n.get('SURFACE_TYPE_CODE', '?').lower()}")
        tail = f" ({'; '.join(extra)})" if extra else ""
        renumbered = _is_renumbering(rs, old, new)
        s = (f"runway {o_id} -> {n_id} (renumbered){tail}" if renumbered
             else f"runway {o_id} -> {n_id} (new runway){tail}")
        out.append({"airport": apt, "source": "APT_RWY.csv", "kind": "changed", "priority": "action",
                    "summary_override": s,
                    "fields": [{"field": "RWY_ID", "old": o_id, "new": n_id}],
                    "values": list(o.values()) + list(n.values())})
        if renumbered:     # the same strip: what changed on its ends still counts
            out += _end_changes(apt, rs, o_id, n_id)
        drop |= {id(old), id(new)}
        ids = set(o_id.split("/")) | {o_id} | set(n_id.split("/")) | {n_id}
        for r in rs:  # the runway-end rows are covered by the one line
            if src(r) == "APT_RWY_END" and r["kind"] in ("added", "removed"):
                if r["row"].get("RWY_ID", "") in ids:
                    drop.add(id(r))
    return out, drop


def _procedures(apt, procs, route_tables=None):
    names = [(procedure_name(r), r["kind"]) for r in procs]
    new_names = sorted({n for n, k in names if k != "removed"})
    gone = sorted({n for n, k in names if k == "removed"} - set(new_names))
    stem = lambda n: re.sub(r"\d+$", "", n)
    # TTHOR2 -> TTHOR3 is a new version, not a removal
    was = {stem(g): g for g in gone}
    # a row the diff paired as "changed" (TTHOR2 -> TTHOR3 in place) is a version bump too
    for r in procs:
        for f in r.get("fields", []):
            if f["field"].endswith("COMPUTER_CODE") and f["old"] and f["new"]:
                o, n = split_code(f["old"])[0], split_code(f["new"])[0]
                if o != n and stem(o) == stem(n):
                    was[stem(n)] = o
    labels = [f"{was[stem(n)]} -> {n}" if stem(n) in was else n for n in new_names]
    gone = [g for g in gone if stem(g) not in {stem(n) for n in new_names}]
    s = f"arrival/departure procedures new or updated: {', '.join(labels) or 'none'}"
    if gone:
        s += f"; removed: {', '.join(gone)}"
    rec = {"airport": apt, "source": "STAR/DP", "kind": "changed", "priority": "ifr",
           "summary_override": s, "procedures": {"updated": new_names, "removed": gone},
           "values": sorted(was.values())}
    if route_tables:  # waypoint-level detail, one line per procedure
        old_routes, new_routes = route_tables
        prev = lambda n: was.get(stem(n)) or (n if n in old_routes else None)
        rec["details"] = [describe(n, prev(n), old_routes, new_routes) for n in new_names]
        rec["details"] += [f"{g}: removed" for g in gone]
    return rec


def _routes(apt, routes):
    counts = defaultdict(int)
    for r in routes:
        counts[r["kind"]] += 1
    parts = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
    ends = lambda r: [r.get("row") or r.get("context") or {}]
    key = sorted([r["kind"]] + [e.get(c, "") for e in ends(r) for c in ("Orig", "Dest", "Type", "Route String")]
                 for r in routes)
    return {"airport": apt, "source": "PFR", "kind": "changed", "priority": "ifr",
            "summary_override": f"preferred IFR routes: {parts}",
            "key": key, "values": [str(n) for n in counts.values()],
            "details": _route_lines(routes)}


# what tells two preferred routes between the same airports apart when their lines would read
# the same: LAX -> F70 has one routing for M class jets and one for P and Q class (Area,
# Altitude), SWF -> ACK one per route type (L and TEC). shown as the FAA wrote them
ROUTE_TELL_APART = ("Type", "Area", "Altitude", "Aircraft", "Direction", "Hours1")


def _route_lines(routes):
    """one line per route, so the lines add up to the counts in the summary. lines that would
    read the same get what tells them apart; rows that differ in nothing a pilot sees (only
    the FAA's sequence number) share a line that says so."""
    groups = defaultdict(list)
    for r in routes:
        groups[summarize(r, {})].append(r)
    lines = []
    for line, rs in groups.items():
        if len(rs) > 1:
            full = lambda r: r.get("row") or r.get("_row") or {}
            cols = [c for c in ROUTE_TELL_APART if len({full(r).get(c, "") for r in rs}) > 1]
            for r in rs:
                r["_tag"] = ", ".join(f"{PFR_LABELS.get(c, label(c))} {full(r).get(c) or 'none'}" for c in cols)
            same = defaultdict(int)
            for r in rs:
                same[summarize(r, {})] += 1
            lines += [f"{t} (listed {n} times)" if n > 1 else t for t, n in same.items()]
        else:
            lines.append(line)
    return sorted(lines)


RANK = {"fyi": 0, "ifr": 1, "action": 2}

# columns that repeat the airport's own name on its tower and frequency rows
SAME_NAME_COLS = ("FACILITY_NAME", "FAC_NAME", "SERVICED_FAC_NAME")


def _top(rs):
    return max((r["priority"] for r in rs), key=lambda p: RANK.get(p, 0))


def _rcag_meaning():
    """'RCAG: remote center air to ground facility', from the glossary's verified entry."""
    e = glossary.lookup("RCAG")
    return f"an RCAG is a {e['expansion'].lower()}" if e and e.get("verified") else "RCAG"


def _freqs(rows):
    """'125.2, 372.0' in the FAA's order, each once."""
    return ", ".join(dict.fromkeys(r.get("FREQ", "") for r in rows if r.get("FREQ")))


def _site(name, rows):
    """'Bethel RCAG 125.2, 372.0 (low altitude)'. for an RCAG the layout's SECTORIZATION is the
    frequency's altitude: Low, High, Low/High or Ultra-High."""
    alts = {r.get("SECTORIZATION", "").strip().lower() for r in rows} - {""}
    alt = f" ({alts.pop()} altitude)" if len(alts) == 1 else ""
    return f"{name.title()} RCAG {_freqs(rows)}{alt}"


def _rcag_name(use):
    """'RED BLUFF RCAG' -> 'Red Bluff RCAG'"""
    return re.sub(r"\s*RCAG$", "", use).title() + " RCAG"


def _faa_line(r):
    """one grouped FRQ row as the FAA wrote it: 'removed: 125.2 BETHEL RCAG (LOW)'."""
    row = r["row"]
    sect = f" ({row['SECTORIZATION']})" if row.get("SECTORIZATION") else ""
    return f"{r['kind']}: {row.get('FREQ', '')} {row.get('FREQ_USE', '')}{sect}"


def _rcag_changes(apt, rs):
    """a center's frequencies at an airport come from RCAG sites (FRQ FACILITY_TYPE RCAG, with the
    ARTCC in ARTCC_OR_FSS_ID). one site's frequencies going and another's arriving for the same
    center is one change, and every frequency of a site is one line. returns (records, ids)."""
    src = lambda r: base(r["source"])
    groups = defaultdict(list)
    for r in rs:
        if (src(r) == "FRQ" and r["kind"] in ("added", "removed")
                and r["row"].get("FACILITY_TYPE") == "RCAG"):
            groups[r["row"].get("ARTCC_OR_FSS_ID", "")].append(r)
    out, drop = [], set()
    for artcc, group in groups.items():
        sites = {"removed": defaultdict(list), "added": defaultdict(list)}
        for r in group:
            name = r["row"].get("FACILITY") or r["row"].get("FAC_NAME") or "?"
            sites[r["kind"]][name].append(r["row"])
        said = {k: " and ".join(_site(n, rows) for n, rows in v.items()) for k, v in sites.items()}
        center = f"center (ARTCC {artcc})" if artcc else "center"
        if said["removed"] and said["added"]:
            kind, s = "changed", f"{center} frequencies: {said['removed']} -> {said['added']}"
        elif said["added"]:
            kind, s = "added", f"new {center} frequencies: {said['added']}"
        else:
            kind, s = "removed", f"{center} frequencies discontinued: {said['removed']}"
        out.append({"airport": apt, "source": "FRQ.csv", "kind": kind, "priority": _top(group),
                    "summary_override": f"{s}; {_rcag_meaning()}",
                    "folded": [{"source": "FRQ", "row": r["row"]} for r in group],
                    "details": [_faa_line(r) for r in group]})
        drop |= {id(r) for r in group}

    # the same frequencies now through another site: FREQ_USE 'RED BLUFF RCAG' -> 'UKIAH RCAG'
    moved = defaultdict(list)
    for r in rs:
        f = {x["field"]: x for x in r.get("fields", [])}
        use = f.get("FREQ_USE")
        if (src(r) == "FRQ" and r["kind"] == "changed" and use
                and all(re.fullmatch(r".+ RCAG", use[k]) for k in ("old", "new"))):
            moved[(use["old"], use["new"])].append(r)
    for (old, new), group in moved.items():
        freqs = _freqs([r.get("context", {}) for r in group])
        out.append({"airport": apt, "source": "FRQ.csv", "kind": "changed", "priority": _top(group),
                    "summary_override": f"center frequencies {freqs}: now through the {_rcag_name(new)} "
                                        f"instead of the {_rcag_name(old)}; {_rcag_meaning()}",
                    "fields": [{"field": "FREQ_USE", "old": old, "new": new}],
                    "key": {"FREQ": freqs},
                    "values": [v for r in group for x in r["fields"] for v in (x["old"], x["new"])]
                              + [v for r in group for v in r.get("context", {}).values()]})
        drop |= {id(r) for r in group}
    return out, drop


def _use_moves(apt, rs):
    """a use leaving one frequency and arriving on another is one change: CTAF 123.05 -> 120.425.
    only when exactly one frequency lost it and exactly one gained it. returns (records, ids)."""
    lost, gained = defaultdict(list), defaultdict(list)
    for r in rs:
        if base(r["source"]) != "FRQ":
            continue
        f = r.get("fields", [])
        if r["kind"] == "removed":
            lost[r["row"].get("FREQ_USE", "")].append((r, r["row"].get("FREQ", "")))
        elif r["kind"] == "added":
            gained[r["row"].get("FREQ_USE", "")].append((r, r["row"].get("FREQ", "")))
        elif (r["kind"] == "changed" and len(f) == 1 and f[0]["field"] == "FREQ_USE"
              and f[0]["old"] and not f[0]["new"]):
            lost[f[0]["old"]].append((r, r.get("context", {}).get("FREQ", "")))
    out, drop = [], set()
    for use in lost.keys() & gained.keys():
        if not use or len(lost[use]) != 1 or len(gained[use]) != 1:
            continue
        (a, old), (b, new) = lost[use][0], gained[use][0]
        if not old or not new or old == new or "RCAG" in use or PROC_USE.fullmatch(use):
            continue
        u = freq_use(use, b.get("row"))
        what = f"{u[0]} frequency ({u[1] + '; ' if u[1] else ''}FAA: {use})" if u else f"{use} frequency"
        out.append({"airport": apt, "source": "FRQ.csv", "kind": "changed", "priority": _top([a, b]),
                    "summary_override": f"{what}: {old} -> {new}",
                    "fields": [{"field": "FREQ", "old": old, "new": new}],
                    "context": {"FREQ_USE": use}})
        drop |= {id(a), id(b)}
    return out, drop


def _proc_listings(apt, rs):
    """'frequency 118.4: also listed for ALLLN STAR', one per procedure and frequency -> one line
    per airport. returns (records, ids)."""
    group = [r for r in rs if base(r["source"]) == "FRQ" and r["kind"] == "added"
             and r["priority"] == "fyi" and PROC_USE.fullmatch(r["row"].get("FREQ_USE", ""))]
    if not group:
        return [], set()
    by_freq = defaultdict(list)
    for r in group:
        by_freq[r["row"].get("FREQ", "")].append(PROC_USE.fullmatch(r["row"]["FREQ_USE"]))
    kinds = {m[2] for ms in by_freq.values() for m in ms}
    what = ("arrivals (STARs)" if kinds == {"STAR"} else "departures (DPs)" if kinds == {"DP"}
            else "arrivals and departures (STARs and DPs)")
    def names(ms):
        n = list(dict.fromkeys(m[1] if kinds != {"STAR", "DP"} else f"{m[1]} {m[2]}" for m in ms))
        return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]
    parts = "; ".join(f"{f} for {names(ms)}" for f, ms in by_freq.items())
    return [{"airport": apt, "source": "FRQ.csv", "kind": "added", "priority": "fyi",
             "summary_override": f"frequencies now also listed for {what}: {parts}",
             "folded": [{"source": "FRQ", "row": r["row"]} for r in group],
             "details": [_faa_line(r) for r in group]}], {id(r) for r in group}


def is_frq_remark(r):
    """an FRQ row where only the REMARK column changed: a remark, not a frequency change."""
    f = r.get("fields", [])
    return (base(r["source"]) == "FRQ" and r["kind"] == "changed"
            and [x["field"] for x in f] == ["REMARK"])


def _norm(t):
    """remark text for 'is this the same remark': RY/RWY spelling, spacing, final period."""
    return _canon(t or "").rstrip(" .")


def collapse(records, route_tables=None):
    by_apt = defaultdict(list)
    for r in records:
        by_apt[r["airport"]].append(r)
    out = []
    for apt, rs in by_apt.items():
        src = lambda r: base(r["source"])

        # 1. brand new / removed airport: one line instead of every field
        for kind in ("added", "removed"):
            if any(src(r) == "APT_BASE" and r["kind"] == kind for r in rs):
                out.append(_new_or_removed_airport(apt, rs, kind))
                rs = [r for r in rs if r["kind"] != kind]

        # 2. renumbered / replaced runways
        rwy_records, drop = _runway_changes(apt, rs)
        out.extend(rwy_records)

        # 3. identical remark text "removed" and "added" (FAA just re-filed it)
        texts = defaultdict(list)
        for r in rs:
            if src(r) in REMARK_FILES and r["kind"] in ("added", "removed"):
                texts[r["row"].get("REMARK", "")].append(r)
        for t, group in texts.items():
            if t and {r["kind"] for r in group} == {"added", "removed"}:
                drop |= {id(r) for r in group}

        # 3f. an airport renamed: the tower and frequency rows carrying the same name say it again
        renamed = {(f["old"], f["new"]) for r in rs if src(r) == "APT_BASE" and r["kind"] == "changed"
                   for f in r.get("fields", []) if f["field"] == "ARPT_NAME"}
        for r in rs:
            if renamed and r["kind"] == "changed" and src(r) != "APT_BASE" and id(r) not in drop:
                keep = [f for f in r.get("fields", []) if not (
                    f["field"] in SAME_NAME_COLS and (f["old"], f["new"]) in renamed)]
                if not keep:
                    drop.add(id(r))
                elif len(keep) < len(r["fields"]):
                    r["fields"] = keep

        # 3b. the CTAF row in FRQ carries the same lighting remark as APT_RMK: say it once
        said = {r["row"].get("REMARK") for r in rs if src(r) in REMARK_FILES and r.get("row")}
        said |= {f["new"] for r in rs if src(r) in REMARK_FILES
                 for f in r.get("fields", []) if f["field"] == "REMARK"}
        said = {_norm(t) for t in said if t}
        for r in rs:
            if is_frq_remark(r):
                t = _norm(r["fields"][0]["new"])
                # already said by a remark file, or by another frequency row (122.7 and 122.8
                # both carrying the same CTAF lighting remark)
                if t in said:
                    drop.add(id(r))
                    # the line that stays keeps the higher rank: a CTAF lighting change can be
                    # act on the frequency row and fyi on the airport remark
                    for x in rs:
                        if (x is not r and id(x) not in drop and RANK.get(r["priority"], 0) > RANK.get(x["priority"], 0)
                                and (src(x) in REMARK_FILES or is_frq_remark(x))
                                and t in {_norm(v) for v in [(x.get("row") or {}).get("REMARK", "")]
                                          + [f["new"] for f in x.get("fields", []) if f["field"] == "REMARK"] if v}):
                            x["priority"] = r["priority"]
                elif t:
                    said.add(t)

        # 3c. a runway added or removed outright: its runway-end rows are the same news
        whole = {rid for r in rs if src(r) == "APT_RWY" and r["kind"] in ("added", "removed")
                 and id(r) not in drop for rid in [r["row"].get("RWY_ID", "")]}
        for r in rs:
            if (src(r) == "APT_RWY_END" and r["kind"] in ("added", "removed")
                    and r["row"].get("RWY_ID", "") in whole):
                drop.add(id(r))

        # 3d. a whole ILS added or removed: its glideslope, DME and markers are the same news,
        # and so are the remarks of one that's gone
        ils_key = lambda r: (r["row"].get("RWY_END_ID", ""), r["row"].get("ILS_LOC_ID", ""))
        for r in rs:
            if src(r) != "ILS_BASE" or r["kind"] not in ("added", "removed") or id(r) in drop:
                continue
            parts = [x for x in rs if src(x) in ("ILS_GS", "ILS_DME", "ILS_MKR")
                     and x["kind"] == r["kind"] and ils_key(x) == ils_key(r) and id(x) not in drop]
            gone_rmks = [x for x in rs if src(x) == "ILS_RMK" and r["kind"] == x["kind"] == "removed"
                         and ils_key(x) == ils_key(r)]
            if not parts and not gone_rmks:
                continue
            order = {"ILS_GS": 0, "ILS_DME": 1, "ILS_MKR": 2}
            parts.sort(key=lambda x: (order[src(x)], x["row"].get("ILS_COMP_TYPE_CODE", "")))
            r["summary_override"] = ils(r["kind"], r["row"], [ils_part(src(x), x["row"]) for x in parts])
            r["folded"] = [{"source": base(x["source"]), "row": x["row"]} for x in parts + gone_rmks]
            if any(x["priority"] == "action" for x in parts):
                r["priority"] = "action"
            drop |= {id(x) for x in parts + gone_rmks}

        # 3e. center frequencies through RCAG sites, and frequencies listed for new procedures
        for group in (_rcag_changes, _use_moves, _proc_listings):
            recs, ids = group(apt, [r for r in rs if id(r) not in drop])
            out.extend(recs)
            drop |= ids

        rest = [r for r in rs if id(r) not in drop]

        # 4. STAR/DP rows -> one IFR record; preferred routes -> one IFR record
        procs = [r for r in rest if src(r).startswith(("STAR", "DP"))]
        routes = [r for r in rest if src(r).startswith("PFR")]
        rest = [r for r in rest if r not in procs and r not in routes]
        if procs:
            rest.append(_procedures(apt, procs, route_tables))
        if routes:
            rest.append(_routes(apt, routes))
        out.extend(rest)
    return out


def merge_freq_uses(records):
    """several 'freq X use renamed/dropped' records for one frequency -> one record."""
    groups, rest = defaultdict(list), []
    for r in records:
        f = r.get("fields", [])
        if (base(r["source"]) == "FRQ" and r["kind"] == "changed" and len(f) == 1
                and f[0]["field"] == "FREQ_USE"):
            groups[(r["airport"], r.get("context", {}).get("FREQ", ""))].append(r)
        else:
            rest.append(r)
    for (apt, freq), rs in groups.items():
        if len(rs) == 1:
            rest.append(rs[0])
            continue
        old = sorted({r["fields"][0]["old"] for r in rs if r["fields"][0]["old"]})
        new = sorted({r["fields"][0]["new"] for r in rs if r["fields"][0]["new"]})
        rest.append({"airport": apt, "source": "FRQ.csv", "kind": "changed", "priority": "fyi",
                     "fields": [{"field": "FREQ_USE", "old": ", ".join(old), "new": ", ".join(new)}],
                     "context": {"FREQ": freq}})
    return rest