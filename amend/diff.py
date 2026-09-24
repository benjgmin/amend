"""Diffing two loaded cycles into raw change records."""
import difflib
import re
from collections import defaultdict

from .rules import (ACTION_COL_WORDS, ACTION_PREFIXES, ACTION_TEXT_WORDS, CONTEXT_COLS,
                    DECLARED_ACTION_FT, DECLARED_ACTION_PCT, DECLARED_DISTANCES,
                    FYI_ONLY_COLS, HIDDEN_FILES, HIDDEN_ONLY_COLS, ID_COLS, NAME_COLS,
                    PAIR_KEYS, base, is_noise_col)


def similarity(a, b):
    keys = set(a) | set(b)
    return sum(a.get(k) == b.get(k) for k in keys) / max(len(keys), 1)


def can_pair(fname, a, b):
    for k in PAIR_KEYS.get(base(fname), ()):
        if k in a and a.get(k) != b.get(k):
            return False
    return True


def keyed(fname, a):
    """true if this file has pair keys and the row has them: a key match is enough to pair."""
    keys = PAIR_KEYS.get(base(fname), ())
    return bool(keys) and all(k in a for k in keys)


def priority(fname, kind, cols, values):
    """'action', 'fyi' or 'hidden' for a change touching these columns / values."""
    b = base(fname)
    cols = [c for c in cols if c not in ID_COLS]
    if b.startswith(HIDDEN_FILES):
        return "hidden"
    if kind == "changed" and not cols:
        return "hidden"
    if cols and all(c in HIDDEN_ONLY_COLS for c in cols):
        return "hidden"
    if any("PCR VALUE" in v.upper() for v in values):
        return "hidden"
    if cols and all(c in NAME_COLS or c in FYI_ONLY_COLS or c in HIDDEN_ONLY_COLS for c in cols):
        return "fyi"
    if b.startswith(ACTION_PREFIXES):
        return "action"
    for c in cols:
        if set(c.upper().split("_")) & ACTION_COL_WORDS:
            return "action"
    # routes and procedures are never action (long strings full of fix names)
    if b.startswith(("PFR", "STAR", "DP")):
        return "fyi"
    for v in values:
        if any(re.search(rf"\b{re.escape(w)}\b", v.upper()) for w in ACTION_TEXT_WORDS):
            return "action"
    return "fyi"


def declared_distance_cut(old_row, new_row, cols):
    """true if a declared distance (TORA/TODA/ASDA/LDA) got meaningfully shorter."""
    for c in cols:
        if c not in DECLARED_DISTANCES:
            continue
        try:
            o, n = float(old_row.get(c) or 0), float(new_row.get(c) or 0)
        except ValueError:
            continue
        if o > 0 and n < o and (o - n >= DECLARED_ACTION_FT or (o - n) / o >= DECLARED_ACTION_PCT):
            return True
    return False


def just_reworded(old, new):
    """same numbers/ids and mostly the same words -> the FAA just reworded it."""
    nums = lambda s: set(re.findall(r"[A-Z]*\d+[A-Z0-9/]*", s.upper()))
    if nums(old) != nums(new):
        return False
    return difflib.SequenceMatcher(None, old.upper(), new.upper()).ratio() >= 0.6


def diff(old, new):
    """old/new: output of nasr.load(). returns a list of raw change records."""
    records = []
    for fname in sorted(set(old) | set(new)):
        o, n = defaultdict(dict), defaultdict(dict)
        for apt, r in old.get(fname, []):
            o[apt][tuple(sorted(r.items()))] = r
        for apt, r in new.get(fname, []):
            n[apt][tuple(sorted(r.items()))] = r

        for apt in sorted(set(o) | set(n)):
            removed = [o[apt][k] for k in o[apt].keys() - n[apt].keys()]
            added = [n[apt][k] for k in n[apt].keys() - o[apt].keys()]

            # pair removed/added rows that are really the same thing edited
            for r in list(removed):
                best, score = None, 0.0
                for a in added:
                    if not can_pair(fname, r, a):
                        continue
                    s = similarity(r, a)
                    if best is None or s > score:
                        best, score = a, s
                if best is None or (score < 0.5 and not keyed(fname, r)):
                    continue
                removed.remove(r)
                added.remove(best)
                cols = sorted(c for c in set(r) | set(best)
                              if r.get(c, "") != best.get(c, "") and not is_noise_col(c)
                              and not c.startswith("_"))
                vals = [r.get(c, "") for c in cols] + [best.get(c, "") for c in cols]
                pri = priority(fname, "changed", cols, vals)
                if cols == ["REMARK"] and just_reworded(r["REMARK"], best["REMARK"]):
                    pri = "fyi"
                if cols and all(c in DECLARED_DISTANCES for c in cols):
                    pri = "action" if declared_distance_cut(r, best, cols) else "fyi"
                records.append({
                    "airport": apt, "source": fname, "kind": "changed", "priority": pri,
                    "fields": [{"field": c, "old": r.get(c, ""), "new": best.get(c, "")} for c in cols],
                    "context": {c: best[c] for c in CONTEXT_COLS if best.get(c)},
                })

            still_there = {r.get("FREQ") for r in n[apt].values()}
            existed = {r.get("FREQ") for r in o[apt].values()}
            for kind, rows in (("removed", removed), ("added", added)):
                for r in rows:
                    # a frequency that still exists just lost one of its listed uses
                    if base(fname) == "FRQ" and kind == "removed" and r.get("FREQ") in still_there:
                        records.append({
                            "airport": apt, "source": fname, "kind": "changed", "priority": "fyi",
                            "fields": [{"field": "FREQ_USE", "old": r.get("FREQ_USE", ""), "new": ""}],
                            "context": {"FREQ": r.get("FREQ", "")}})
                        continue
                    pri = priority(fname, kind, [k for k in r if not k.startswith("_")],
                                   list(r.values()))
                    # same freq with a new label, procedure listings, FSS outlets: not alerts
                    if base(fname) == "FRQ" and (
                            (kind == "added" and r.get("FREQ") in existed)
                            or re.search(r"\b(STAR|SID|DP|RCO)\b", r.get("FREQ_USE", "").upper())):
                        pri = "fyi"
                    records.append({
                        "airport": apt, "source": fname, "kind": kind, "priority": pri,
                        "row": {k: v for k, v in r.items()
                                if v and k not in ID_COLS and not is_noise_col(k)},
                    })
    return records