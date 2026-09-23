"""Turning piles of raw added/removed rows into the events a pilot would describe."""
import re
from collections import defaultdict

from .english import procedure_name, summarize
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
    word = {"added": "new airport added to FAA database",
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
    return {"airport": apt, "source": "APT_BASE.csv", "kind": kind,
            "priority": "action" if kind == "removed" else "fyi",
            "summary_override": f"{word}: " + ", ".join(bits)}


def _runway_changes(apt, rs):
    """pair removed+added runways that are the same strip renumbered or rebuilt.
    returns (new records, ids of raw records they replace)."""
    src = lambda r: base(r["source"])
    removed = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "removed"]
    added = [r for r in rs if src(r) == "APT_RWY" and r["kind"] == "added"]
    pairs = []
    for old in removed:
        for new in added:
            o, n = old["row"], new["row"]
            same_size = (o.get("RWY_LEN") and o.get("RWY_LEN") == n.get("RWY_LEN")
                         and o.get("RWY_WIDTH") == n.get("RWY_WIDTH"))
            if same_size or _one_apart(_rwy_num(o.get("RWY_ID")), _rwy_num(n.get("RWY_ID"))):
                pairs.append((old, new))
                added.remove(new)
                break
    # exactly one runway gone and one new one left over -> it was replaced/realigned
    left = [r for r in removed if all(r is not o for o, _ in pairs)]
    if len(left) == 1 and len(added) == 1:
        pairs.append((left[0], added.pop()))

    out, drop = [], set()
    for old, new in pairs:
        o, n = old["row"], new["row"]
        o_id, n_id = o.get("RWY_ID", "?"), n.get("RWY_ID", "?")
        extra = []
        if (o.get("RWY_LEN"), o.get("RWY_WIDTH")) != (n.get("RWY_LEN"), n.get("RWY_WIDTH")):
            extra.append(f"now {n.get('RWY_LEN', '?')}x{n.get('RWY_WIDTH', '?')} ft, "
                         f"was {o.get('RWY_LEN', '?')}x{o.get('RWY_WIDTH', '?')}")
        if o.get("SURFACE_TYPE_CODE") != n.get("SURFACE_TYPE_CODE"):
            extra.append(f"surface now {n.get('SURFACE_TYPE_CODE', '?').lower()}")
        tail = f" ({'; '.join(extra)})" if extra else ""
        renumbered = (_one_apart(_rwy_num(o_id), _rwy_num(n_id)) or
                      (o.get("RWY_LEN") == n.get("RWY_LEN") and o.get("RWY_WIDTH") == n.get("RWY_WIDTH")))
        s = (f"runway {o_id} renumbered to {n_id}{tail}" if renumbered
             else f"runway {o_id} replaced by runway {n_id}{tail}")
        out.append({"airport": apt, "source": "APT_RWY.csv", "kind": "changed", "priority": "action",
                    "summary_override": s,
                    "fields": [{"field": "RWY_ID", "old": o_id, "new": n_id}]})
        drop |= {id(old), id(new)}
        ids = set(o_id.split("/")) | {o_id} | set(n_id.split("/")) | {n_id}
        for r in rs:  # the runway-end rows are covered by the one line
            if src(r) == "APT_RWY_END" and r["kind"] in ("added", "removed"):
                if r["row"].get("RWY_ID", "") in ids:
                    drop.add(id(r))
    return out, drop


def _procedures(apt, procs):
    names = [(procedure_name(r), r["kind"]) for r in procs]
    new_names = sorted({n for n, k in names if k != "removed"})
    gone = sorted({n for n, k in names if k == "removed"} - set(new_names))
    stem = lambda n: re.sub(r"\d+$", "", n)
    # TTHOR2 -> TTHOR3 is a new version, not a removal
    was = {stem(g): g for g in gone}
    labels = [f"{n} (was {was[stem(n)]})" if stem(n) in was else n for n in new_names]
    gone = [g for g in gone if stem(g) not in {stem(n) for n in new_names}]
    s = f"arrival/departure procedures new or updated: {', '.join(labels) or 'none'}"
    if gone:
        s += f"; removed: {', '.join(gone)}"
    return {"airport": apt, "source": "STAR/DP", "kind": "changed", "priority": "ifr",
            "summary_override": s, "procedures": {"updated": new_names, "removed": gone}}


def _routes(apt, routes):
    counts = defaultdict(int)
    for r in routes:
        counts[r["kind"]] += 1
    parts = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
    return {"airport": apt, "source": "PFR", "kind": "changed", "priority": "ifr",
            "summary_override": f"preferred IFR routes: {parts}",
            "details": sorted({summarize(r, {}) for r in routes})}


def collapse(records):
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

        rest = [r for r in rs if id(r) not in drop]

        # 4. STAR/DP rows -> one IFR record; preferred routes -> one IFR record
        procs = [r for r in rest if src(r).startswith(("STAR", "DP"))]
        routes = [r for r in rest if src(r).startswith("PFR")]
        rest = [r for r in rest if r not in procs and r not in routes]
        if procs:
            rest.append(_procedures(apt, procs))
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
