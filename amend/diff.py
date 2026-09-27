"""Diffing two loaded cycles into raw change records."""
import difflib
import re
from collections import defaultdict

from .rules import (ACTION_COL_WORDS, ACTION_PREFIXES, ACTION_TEXT_WORDS, CONTEXT_COLS,
                    DECLARED_ACTION_FT, DECLARED_ACTION_PCT, DECLARED_DISTANCES,
                    HIDDEN_FILES, HIDDEN_ONLY_COLS, ID_COLS, IFR_REMARK_FILES, PAIR_KEYS,
                    ROW_ACTION, base, is_fyi_col, is_noise_col, small_change)


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


def priority(fname, kind, cols, values, soft=()):
    """'action', 'fyi' or 'hidden' for a change touching these columns / values.
    soft: columns whose change was too small to matter (see rules.SMALL_CHANGE)."""
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
    if cols and all(is_fyi_col(c) or c in HIDDEN_ONLY_COLS or c in soft for c in cols):
        return "fyi"
    if b.startswith(ACTION_PREFIXES):
        return "action"
    if kind in ROW_ACTION.get(b, ()):
        return "action"
    # column words only mean something on an edit: every added row has a NAV_ID or LGT column
    for c in cols if kind == "changed" else ():
        if not is_fyi_col(c) and c not in soft and set(c.upper().split("_")) & ACTION_COL_WORDS:
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
        if not new_row.get(c):   # the FAA stopped listing it; that's not a shorter runway
            continue
        try:
            o, n = float(old_row.get(c) or 0), float(new_row.get(c))
        except ValueError:
            continue
        if o > 0 and n < o and (o - n >= DECLARED_ACTION_FT or (o - n) / o >= DECLARED_ACTION_PCT):
            return True
    return False


def _canon(s):
    """FAA spelling variants that mean the same thing: RY/RYS/RWYS -> RWY, THLD -> THR,
    '.2' -> '0.2', runway '9' -> '09', runs of spaces."""
    t = s.upper()
    t = re.sub(r"\bRYS?\b|\bRWYS\b", "RWY", t)
    t = re.sub(r"\bTHLD\b", "THR", t)
    t = re.sub(r"(?<![\d.])\.(\d)", r"0.\1", t)
    t = re.sub(r"\b(RWY )(\d)\b", r"\g<1>0\2", t)
    return " ".join(t.split())


def just_reworded(old, new):
    """same numbers/ids and mostly the same words -> the FAA just reworded it."""
    old, new = _canon(old), _canon(new)
    nums = lambda s: set(re.findall(r"[A-Z]*\d+[A-Z0-9/]*", s))
    if nums(old) != nums(new):
        return False
    return difflib.SequenceMatcher(None, old, new).ratio() >= 0.6


# pilot-controlled lighting: "HIRL RWY 01/19 PRESET LOW SS-SR; TO INCR INTST & ACTVT REIL RWY 19 - CTAF."
LIGHTS = {"HIRL", "MIRL", "LIRL", "REIL", "PAPI", "VASI", "VASIS", "PVASI", "APAP", "MALS", "MALSR",
          "MALSF", "SALS", "SSALS", "SSALR", "SSALF", "ALSF-1", "ALSF-2", "ODALS", "RLLS", "RAIL",
          "TDZL", "RCLS", "TDZ/CL", "LDIN"}
RWY = re.compile(r"\d{1,2}[LRC]?(/\d{1,2}[LRC]?)?")


ALWAYS_ON = re.compile(r"\bCONSLY\b|\bCONTINUOUSLY\b|\bCONT\b|\bOPER DRNG\b")


def _ends(tok):
    """'07/25' -> {'07', '25'}; '9' -> {'09'}. so '07 & 25' and '07/25' are the same lights."""
    return {e.zfill(2) if e[:1].isdigit() and not e[1:2].isdigit() else e for e in tok.split("/")}


def _pcl(text):
    """(set of (light, runway end), set of keying frequencies) for a pilot-controlled lighting
    remark, or None if the text isn't one. lights the remark says are always on
    ('PAPI RWY 18 & 36 OPR CONSLY') aren't pilot controlled, so they don't count."""
    t = _canon(text)
    freqs = set(re.findall(r"-\s*(CTAF|1\d\d\.\d+)", t))
    if not freqs or not re.search(r"\bACTVT\b|\bINCR\b", t):
        return None
    pairs = set()
    for clause in re.split(r"\.\s+|;", t):
        if ALWAYS_ON.search(clause):
            continue
        light = None
        for tok in re.findall(r"[A-Z0-9/.\-]+", clause):
            if tok in LIGHTS or (tok.endswith("S") and tok[:-1] in LIGHTS):   # REILS, PAPIS
                light = tok if tok in LIGHTS else tok[:-1]
            elif light and RWY.fullmatch(tok):
                pairs |= {(light, e) for e in _ends(tok)}
    return (pairs, freqs) if pairs else None


def pcl_priority(old, new):
    """a lighting remark only matters if you now key a different frequency or a light no longer
    comes on. more lights on the same frequency is fyi. None: not a lighting remark, or it
    says something else that needs the normal rules (closed, PPR...)."""
    o, n = _pcl(old), _pcl(new)
    if not (o and n):
        return None
    words = [w for w in ACTION_TEXT_WORDS if w != "CTAF"]
    if any(re.search(rf"\b{re.escape(w)}\b", v.upper()) for v in (old, new) for w in words):
        return None
    return "action" if o[1] != n[1] or not o[0] <= n[0] else "fyi"


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
                              and not c.startswith("_")
                              and small_change(c, r.get(c), best.get(c)) != "drop")
                soft = {c for c in cols if small_change(c, r.get(c), best.get(c)) == "fyi"}
                vals = [r.get(c, "") for c in cols] + [best.get(c, "") for c in cols]
                pri = priority(fname, "changed", cols, vals, soft)
                if cols == ["REMARK"] and just_reworded(r["REMARK"], best["REMARK"]):
                    pri = "fyi"
                if cols == ["REMARK"]:
                    pri = pcl_priority(r["REMARK"], best["REMARK"]) or pri
                if base(fname) in IFR_REMARK_FILES and pri == "action":
                    pri = "ifr"
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
                    if base(fname) in IFR_REMARK_FILES and pri == "action":
                        pri = "ifr"
                    records.append({
                        "airport": apt, "source": fname, "kind": kind, "priority": pri,
                        "row": {k: v for k, v in r.items()
                                if v and k not in ID_COLS and not is_noise_col(k)},
                    })
    return records