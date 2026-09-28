"""Diffing two loaded cycles into raw change records."""
import difflib
import re
from collections import defaultdict

from .rules import (ACTION_COL_WORDS, ACTION_PREFIXES, ACTION_TEXT_WORDS, ATC_SERVICE_WORDS,
                    COL_CATEGORY, CONTEXT_COLS, DECLARED_ACTION_FT, DECLARED_ACTION_PCT,
                    DECLARED_DISTANCES, DECLINATION_COLS, DECLINATION_NAV_TYPES, FSS_OUTLET,
                    FSS_OUTLET_NOT, HIDDEN_FILES, HIDDEN_ONLY_COLS, ID_COLS, IFR_REMARK_FILES,
                    NON_ATCT_CONTROL, PAIR_KEYS, REWORD_ALIASES, REWORD_BLOCKERS, REWORD_PHRASES,
                    ROW_ACTION, ROW_FYI, ROW_TIER, SURVEY_REMARK_FILES, base, is_fyi_col,
                    is_helipad, is_hours_col, is_noise_col, small_change)


def keyed(fname, a):
    """true if this file has pair keys and the row has them: a key match is enough to pair."""
    keys = PAIR_KEYS.get(base(fname), ())
    return bool(keys) and all(k in a for k in keys)


def pair_rows(fname, removed, added):
    """[(old row, new row), ...]: removed and added rows that are one row edited.
    best match first across all rows, so an old row can't claim a new row another old row
    matches better; ties go to the earlier row in the (sorted) lists, never to set order.
    a pair needs its pair keys (rules.PAIR_KEYS) equal, and half its values equal or a pair
    key to match on. score: the share of columns with the same value in both rows."""
    # item sets computed once: route files (STAR_RTE, DP_RTE) can have 700 removed and 700
    # added rows at one airport when its procedures get a new version
    pk = PAIR_KEYS.get(base(fname), ())
    items = [frozenset(a.items()) for a in added]
    cands = []
    for i, r in enumerate(removed):
        ri, is_keyed = frozenset(r.items()), keyed(fname, r)
        must = [(k, r[k]) for k in pk if k in r]
        for j, a in enumerate(added):
            if any(a.get(k) != v for k, v in must):
                continue
            s = len(ri & items[j]) / max(len(r.keys() | a.keys()), 1)
            if s >= 0.5 or is_keyed:
                cands.append((-s, i, j))
    used_r, used_a, pairs = set(), set(), []
    for _, i, j in sorted(cands):
        if i not in used_r and j not in used_a:
            used_r.add(i)
            used_a.add(j)
            pairs.append((i, j))
    return [(removed[i], added[j]) for i, j in sorted(pairs)]


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
    if kind in ROW_FYI.get(b, ()):
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


def declination_cols(fname, old_row, new_row):
    """the magnetic variation columns of a VOR-family navaid whose variation changed: that's
    the declination its radials are aligned to, not survey noise (rules.DECLINATION_COLS)."""
    if base(fname) != "NAV_BASE" or new_row.get("NAV_TYPE") not in DECLINATION_NAV_TYPES:
        return set()
    if all(old_row.get(c, "") == new_row.get(c, "") for c in DECLINATION_COLS):
        return set()
    return {c for c in DECLINATION_COLS if c in new_row}


def empty_non_atct(fname, row):
    """an ATC_BASE row for a field with no tower that names no ATC service (P14)."""
    if base(fname) != "ATC_BASE" or row.get("FACILITY_TYPE", "").upper() != "NON-ATCT":
        return False
    return not any(v for c, v in row.items() if set(c.upper().split("_")) & ATC_SERVICE_WORDS)


def fss_outlet_note(fname, row):
    """a tower/ATC remark that only says which FSS talks on an outlet
    (T03 'COMMUNICATIONS PRVDD BY PRESCOTT RADIO ... (TUBA CITY RCO)')."""
    t = row.get("REMARK", "").upper()
    return (base(fname) == "ATC_RMK" and bool(re.search(FSS_OUTLET, t))
            and not re.search(FSS_OUTLET_NOT, t)
            and not any(re.search(rf"\b{re.escape(w)}\b", t) for w in ACTION_TEXT_WORDS))


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


# "WHEN ATCT CLSD", "IF TWR CLSD", "WHEN CLOVER APCH CLSD": when a remark applies, not a closure.
# the FAA rewrote "FOR CD IF UNA TO CTC ON FSS FREQ, CTC <ARTCC>" as "FOR CD WHEN ATCT CLSD CTC
# <ARTCC>" at dozens of airports in the 2026-09-03 cycle; gaining the condition isn't news
WHEN_CLOSED = re.compile(r"\b(?:WHEN|IF|WHILE)\s+(?:[A-Z]+\s+){0,3}?"
                         r"(?:ATCT|TWR|TOWER|APCH|CTL|FSS|ARTCC|UNICOM|FAC)\s+(?:IS\s+)?(?:CLSD|CLOSED)\b")


def _words(s):
    s = WHEN_CLOSED.sub(" ", s)
    for phrase, short in REWORD_PHRASES.items():
        s = re.sub(rf"\b{phrase}\b", short, s)
    return {REWORD_ALIASES.get(w, w) for w in re.findall(r"[A-Z]+", s)}


def just_reworded(old, new):
    """same numbers/ids, mostly the same words, and no word that changes the meaning gained
    or lost (rules.REWORD_BLOCKERS) -> the FAA just reworded it."""
    old, new = _canon(old), _canon(new)
    nums = lambda s: set(re.findall(r"[A-Z]*\d+[A-Z0-9/]*", s))
    if nums(old) != nums(new):
        return False
    if (_words(old) ^ _words(new)) & REWORD_BLOCKERS:
        return False
    return difflib.SequenceMatcher(None, old, new).ratio() >= 0.6


# hours text: "OPR 1330Z-0530Z MON-THU, 1330Z-0130Z FRI, CLSD WEEKENDS, HOL" and
# "1330-0530Z MON-THU; 1330-0130Z FRI; CLSD WKENDS, HOLS" are the same schedule
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_DAY = "|".join(DAYS)
_HOURS_ALIASES = [(r"\bWEEKENDS?\b|\bWKENDS?\b", "SAT-SUN"), (r"\bWEEKDAYS\b|\bWKDAYS\b", "MON-FRI"),
                  (r"\bDAILY\b|\bDLY\b", "MON-SUN"), (r"\bHOLIDAYS\b|\bHOLS\b", "HOL"),
                  (r"\bEXCEPT\b|\bEXCP\b", "EXC"), (r"\bCLOSED\b", "CLSD"), (r"\bTHRU\b", "-"),
                  (r"\s*&\s*|\s+AND\s+", ", ")]
_HOURS_TOKEN = re.compile(
    r"(?P<time>(?:\d{4}|SR|SS|DUSK|DAWN)-(?:\d{4}|SR|SS|DUSK|DAWN)Z?\+*)"
    rf"|(?P<days>\b(?:{_DAY})(?:\s*-\s*(?:{_DAY}))?\b)|(?P<hol>\bHOL\b)|(?P<closed>\bCLSD\b|\bEXC\b)"
    r"|(?P<keep>\bCLASS [B-G]\b|\bPPR\b|\bO/R\b)|(?P<num>\d+)|(?P<word>[A-Z]+)")
# words that don't qualify a schedule ("OPR 0700-2100" = "0700-2100")
_HOURS_FILLER = {"OPR", "OPS", "OPEN", "SVC", "HRS", "HR", "FROM", "TO", "THE", "Z", "LCL"}


def _days(tok):
    a, _, b = (x.strip() for x in tok.partition("-"))
    i, j = DAYS.index(a), DAYS.index(b or a)
    return {DAYS[(i + k) % 7] for k in range((j - i) % 7 + 1)}


def _schedule(text):
    """what an hours text says, order and spelling aside: {(days, time range, qualifier
    words)} when open, the days/holidays/times after CLSD or EXC, and every other token
    (numbers, airspace class, PPR, CLSD itself, any word that isn't filler) wherever it is.
    a word that comes or goes is never a reformat: "0700-2100" -> "0700-2100 CLSD" is a
    tower closing, "MAY-SEP" -> "JUN-AUG" a season moving."""
    t = _canon(text)
    t = re.sub(r"\b(\d{4})Z\s*-\s*(\d{4})Z", r"\1-\2Z", t)   # 1330Z-0530Z -> 1330-0530Z
    for pat, rep in _HOURS_ALIASES:
        t = re.sub(pat, rep, t)
    is_open, closed, rest = set(), set(), set()
    for sentence in re.split(r";|\.(?:\s|$)", t):
        closing = False
        for seg in sentence.split(","):
            toks = [(m.lastgroup, m.group()) for m in _HOURS_TOKEN.finditer(seg)]
            # a new time before any CLSD/EXC starts an open part again: "CLSD SAT, 0900-1700 SUN"
            first = next((k for k, _ in toks if k in ("time", "closed")), None)
            if first == "time":
                closing = False
            days, times, words = set(), [], set()
            for kind, tok in toks:
                if kind == "closed":
                    closing = True
                    rest.add(tok)
                elif kind in ("num", "keep"):     # NGW "OTHER TIMES CLASS E" -> "CLASS G"
                    rest.add(tok)
                elif kind == "word" and tok not in _HOURS_FILLER:
                    rest.add(tok)
                    if not closing:
                        words.add(tok)
                elif closing:
                    if kind == "days":
                        closed |= _days(tok)
                    elif kind in ("hol", "time"):
                        closed.add(tok)
                elif kind == "days":
                    days |= _days(tok)
                elif kind == "hol":
                    days.add("HOL")
                elif kind == "time":
                    times.append(tok)
            for tm in times:
                is_open.add((frozenset(days or DAYS), tm, frozenset(words)))
            if days and not times:
                is_open.add((frozenset(days), None, frozenset()))
    return is_open, closed, rest


def same_hours(old, new):
    """true if two hours texts give the same schedule (LUF, MTC: rewritten, same times).
    text with no time range in it ("SEE RMK", "ON REQUEST") is never the same schedule."""
    a, b = _schedule(old), _schedule(new)
    has_time = lambda sch: any(tm for _, tm, _ in sch[0])
    return has_time(a) and has_time(b) and a == b


# pilot-controlled lighting: "HIRL RWY 01/19 PRESET LOW SS-SR; TO INCR INTST & ACTVT REIL RWY 19 - CTAF."
LIGHTS = {"HIRL", "MIRL", "LIRL", "REIL", "PAPI", "VASI", "VASIS", "PVASI", "APAP", "MALS", "MALSR",
          "MALSF", "SALS", "SSALS", "SSALR", "SSALF", "ALSF-1", "ALSF-2", "ODALS", "RLLS", "RAIL",
          "TDZL", "RCLS", "TDZ/CL", "LDIN"}
RWY = re.compile(r"\d{1,2}[LRC]?(/\d{1,2}[LRC]?)?")


ALWAYS_ON = re.compile(r"\bCONSLY\b|\bCONTINUOUSLY\b|\bCONT\b|\bOPER DRNG\b")
# "PAPI RWY 02 AND 20 - OPER CONT DUSK-2200; AFTER 2200 ACTVT - CTAF": on part of the night,
# pilot controlled the rest, so it still comes on when you key it
PART_TIME = re.compile(r"\b(?:\d{4}|DUSK|DAWN|SS|SR)-(?:\d{4}|DUSK|DAWN|SS|SR)\b|\bUNTIL\b|\bTIL\b")


def _ends(tok):
    """'07/25' -> {'07', '25'}; '9' -> {'09'}. so '07 & 25' and '07/25' are the same lights."""
    return {e.zfill(2) if e[:1].isdigit() and not e[1:2].isdigit() else e for e in tok.split("/")}


def _pcl(text):
    """(pilot-controlled (light, runway end) pairs, always-on pairs, keying frequencies) for a
    pilot-controlled lighting remark, or None if the text isn't one. lights the remark says
    are on all night ('PAPI RWY 18 & 36 OPR CONSLY') aren't pilot controlled; lights on
    continuously only part of the night ('OPER CONT DUSK-2200') still are."""
    t = _canon(text)
    freqs = set(re.findall(r"-\s*(CTAF|1\d\d\.\d+)", t))
    if not freqs or not re.search(r"\bACTVT\b|\bINCR\b", t):
        return None
    pairs, always = set(), set()
    for clause in re.split(r"\.\s+|;", t):
        on = always if ALWAYS_ON.search(clause) and not PART_TIME.search(clause) else pairs
        light = None
        for tok in re.findall(r"[A-Z0-9/.\-]+", clause):
            if tok in LIGHTS or (tok.endswith("S") and tok[:-1] in LIGHTS):   # REILS, PAPIS
                light = tok if tok in LIGHTS else tok[:-1]
            elif light and RWY.fullmatch(tok):
                on |= {(light, e) for e in _ends(tok)}
    return (pairs, always, freqs) if pairs else None


def _renumbered(old_pairs, new_pairs):
    """old (light, end) pairs with runway ends renamed the way a renumbering does it: each end
    that's gone maps to the one new end one number away with the same L/R/C (MRI 07/25 ->
    08/26, 16/34 -> 17/35). ends that can't be mapped one to one stay as they are."""
    o = {e for _, e in old_pairs}
    n = {e for _, e in new_pairs}
    num = lambda e: (int(e[:2]), e[2:]) if e[:2].isdigit() else (None, e)
    def near(a, b):
        (x, sx), (y, sy) = num(a), num(b)
        return x is not None and y is not None and sx == sy and min(abs(x - y), 36 - abs(x - y)) == 1
    gone, new = sorted(o - n), sorted(n - o)
    move = {}
    for e in gone:
        cands = [f for f in new if near(e, f)]
        if len(cands) == 1 and sum(near(g, cands[0]) for g in gone) == 1:
            move[e] = cands[0]
    return {(light, move.get(e, e)) for light, e in old_pairs}


def pcl_priority(old, new):
    """a lighting remark only matters if you now key a different frequency or a light no longer
    comes on when you key it. more lights on the same frequency, lights now on all night, or
    the same lights after a runway renumbering, is fyi. None: not a lighting remark, or it
    says something else that needs the normal rules (closed, PPR...)."""
    o, n = _pcl(old), _pcl(new)
    if not (o and n):
        return None
    # a sentence with an act word in it ('WHEN ATCT CLSD CTC MERRILL WX') is left to the
    # normal rules, unless it reads the same before and after
    words = [w for w in ACTION_TEXT_WORDS if w != "CTAF"]
    said = lambda v: {c.strip(" .") for c in re.split(r"\.\s+|;", _canon(v))
                      if any(re.search(rf"\b{re.escape(w)}\b", c) for w in words)}
    if said(old) != said(new):
        return None
    (o_pcl, o_on, o_f), (n_pcl, n_on, n_f) = o, n
    now = n_pcl | n_on
    # an always-on light the remark stops mentioning (JWY) isn't known to be gone, and one
    # that now comes on with the rest when you key the frequency (EAN, M44) isn't lost either
    lost = _renumbered(o_pcl, now) - now
    return "action" if o_f != n_f or lost else "fyi"


def schedule_text(rows):
    """an airport's attendance schedule (APT_ATT rows) as the FAA wrote it, one part per row in
    SKED_SEQ_NO order: 'MON-FRI 0800-1700; SAT 0800-1200'. ALL is left out of a part unless
    the whole part is ALL."""
    def seq(r):
        try:
            return float(r.get("SKED_SEQ_NO") or 0)
        except ValueError:
            return 0
    parts = []
    for r in sorted(rows, key=lambda r: (seq(r), sorted(r.items()))):
        vals = [r.get(c, "").strip() for c in ("MONTH", "DAY", "HOUR")]
        vals = [v for i, v in enumerate(vals) if v not in vals[:i]]   # 'ON CALL' in all three
        part = " ".join(v for v in vals if v and v != "ALL") or ("ALL" if any(vals) else "")
        if part and part not in parts:
            parts.append(part)
    return "; ".join(parts)


def attendance(apt, fname, old_rows, new_rows):
    """an airport's attendance schedule, old vs new, as one record. its rows are numbered parts
    of one schedule, so a row added, dropped or renumbered only means something next to the
    others: the FAA dropping 'SAT-SUN 0700-1900' and adding 'SAT- SUN 0700-1900' is nothing."""
    old, new = schedule_text(old_rows), schedule_text(new_rows)
    if old == new:
        return None
    if not old and new == "UNATNDD":
        pri = "fyi"      # newly listed as unattended: nothing you could count on went away
    elif old and new and same_hours(old, new):
        pri = "fyi"
    else:
        pri = priority(fname, "changed", ["MONTH", "DAY", "HOUR"], [old, new])
    kind = "added" if not old else "removed" if not new else "changed"
    return {"airport": apt, "source": fname, "kind": kind, "priority": pri,
            "fields": [{"field": "ATTENDANCE", "old": old, "new": new}]}


def row_priority(fname, kind, r, pri):
    """tier for a whole row added or removed, after the file-wide rules (rules.ROW_TIER)."""
    b = base(fname)
    if pri == "hidden":
        return pri
    if b in SURVEY_REMARK_FILES and r.get("REF_COL_NAME", "").endswith("_SOURCE_CODE"):
        return "hidden"
    if b in ("APT_RWY", "APT_RWY_END") and is_helipad(r.get("RWY_ID")):
        return "fyi"     # a helipad at a hospital or ranch: not a runway you'd plan around
    if b == "ATC_BASE" and r.get("FACILITY_TYPE", "").upper() == "NON-ATCT" and not empty_non_atct(fname, r):
        return NON_ATCT_CONTROL
    return ROW_TIER.get((b, kind), pri)


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
            if base(fname) == "APT_ATT":
                rec = attendance(apt, fname, list(o[apt].values()), list(n[apt].values()))
                if rec:
                    records.append(rec)
                continue
            # sorted, never set order: the output must not depend on Python's hash seed or on
            # the order the FAA happened to write the rows in
            removed = [o[apt][k] for k in sorted(o[apt].keys() - n[apt].keys())]
            added = [n[apt][k] for k in sorted(n[apt].keys() - o[apt].keys())]

            # pair removed/added rows that are really the same thing edited
            for r, best in pair_rows(fname, removed, added):
                removed.remove(r)
                added.remove(best)
                keep = declination_cols(fname, r, best)
                cols = sorted(c for c in set(r) | set(best)
                              if r.get(c, "") != best.get(c, "")
                              and (not is_noise_col(c) or c in keep)
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
                if (pri == "action" and cols and all(is_hours_col(c) for c in cols)
                        and all(same_hours(r.get(c, ""), best.get(c, "")) for c in cols)):
                    pri = "fyi"     # same schedule, written differently
                if keep & set(cols):
                    pri = "action"  # a VOR realigned: every radial moved
                rec = {
                    "airport": apt, "source": fname, "kind": "changed", "priority": pri,
                    "fields": [{"field": c, "old": r.get(c, ""), "new": best.get(c, "")} for c in cols],
                    "context": {c: best[c] for c in CONTEXT_COLS if best.get(c)},
                }
                cats = {COL_CATEGORY.get(c) for c in cols}
                if len(cats) == 1 and None not in cats:
                    rec["category"] = cats.pop()
                records.append(rec)

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
                    if pri == "action" and (empty_non_atct(fname, r) or fss_outlet_note(fname, r)):
                        pri = "fyi"
                    pri = row_priority(fname, kind, r, pri)
                    if base(fname) in IFR_REMARK_FILES and pri == "action":
                        pri = "ifr"
                    records.append({
                        "airport": apt, "source": fname, "kind": kind, "priority": pri,
                        "row": {k: v for k, v in r.items()
                                if v and k not in ID_COLS and not is_noise_col(k)},
                    })
    return records