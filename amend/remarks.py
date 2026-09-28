"""Translating FAA remark contractions to plain English with Claude, plus API key handling.

The no-guess rule is enforced here in code, not just asked for in the prompt. A translation
may expand a contraction only to its meaning in the verified glossary (glossary.py, copied from
the FAA's own lists). Any other contraction has to appear exactly as written, or problems()
rejects the translation and the FAA text is shown instead.
"""
import functools
import glob
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter

from . import ENGINE_VERSION, glossary
from .rules import REMARK_FILES

LLM_MODEL = "claude-haiku-4-5-20251001"
CACHE_FILE = "remark_cache.json"
# remarks whose answer broke the checks, with why: {"engine": ENGINE_VERSION, "remarks": {raw: [...]}}
REJECTS_FILE = "remark_rejects.json"
BATCH = 30
FAIL_LIMIT = 3      # failed calls in a row before a build stops asking
PRICE_PER_MTOK = (1.00, 5.00)   # LLM_MODEL's list price in dollars: input, output

# what the last translate_remarks() did, for the processing log. unknown_terms is the review
# queue: contractions in this run's remarks that have no verified meaning and stay as written
# (review_terms: names from NASR's own lists and addresses aren't counted)
STATS = {}

PROMPT = (
    "Decode each FAA airport/ATC remark below into plain English a student pilot can read. Stay close "
    "to the FAA text: keep its order, spell out each contraction with its listed meaning, and add "
    "nothing. A short phrase is fine; it doesn't have to be a full sentence, but it has to read as "
    "English: a listed meaning may change its form to fit, and small grammar words (is, are, the, on) "
    "may be added: 'WHEN TWR HR EXTN' is 'when tower hours are extended', not 'when tower hour "
    "extension', and 'WHILE PRK' is 'while parked', not 'while park'. Write it in normal sentence "
    "case: the FAA writes everything in capitals, but only codes, identifiers and the contractions "
    "you copy stay in capitals.\n"
    "Rules:\n"
    "- Expand a contraction ONLY to the meaning listed for it under Meanings. Copy every other "
    "contraction, abbreviation, code and name exactly as written, even if you think you know "
    "what it means. A wrong expansion is dangerous.\n"
    "- If a listed meaning doesn't fit the remark, copy that contraction exactly as written instead.\n"
    "- Use only what the remark says. Don't add a subject, place, object or verb it doesn't state, "
    "like 'the runway', 'the airport', 'fuel', 'aircraft', 'is available', 'contact', 'report', 'high', "
    "'tall', 'deep' or 'away', and don't add 'only', 'must' or 'should'.\n"
    "- Keep the remark's own plain English words (ONLY, EXCEPT, PRIOR, BELOW are 'only', 'except', "
    "'prior', 'below'); don't swap them for others, and don't say a word more times than the remark does.\n"
    "- Keep all numbers, times, runway ids, frequencies and phone numbers exactly, in the remark's "
    "order, as many times as the remark has them. Never add a number, or a unit (feet, degrees) "
    "after a number that has none.\n"
    "- Copy codes of letters and digits exactly, with their letters: D523-4244, C850-283-4244, "
    "100LL, H1, 24U, BAK-12B. A runway keeps its side letter: 'RWY 33C' is 'runway 33C' and "
    "'RWY 15C/33C' is 'runway 15C/33C', never '33 center'.\n"
    "- Keep a + or - in front of a height: '+22 FT FENCE' is '+22 foot fence', never '22-foot fence', "
    "'plus 22' or '22 feet high'. Keep '++' after a time exactly as written; it's decoded for you.\n"
    "- FT is 'foot' only right before the thing it measures ('+22 foot fence'); anywhere else it's "
    "'feet': 'BLW 3200 FT' is 'below 3200 feet', '1225 FT DIST' is '1225 feet distance'.\n"
    "- Keep OR as 'or'. Keep every regulatory reference (Part 121, Part 135, Part 380, FAR, etc.) "
    "exactly as written.\n"
    "- PCR VALUE lines like '350/F/A/X/T' are a pavement strength code: keep the value and "
    "letters exactly and do not explain them.\n"
    "- A lighting remark ending in '- CTAF' or '- <frequency>' is pilot-controlled lighting: "
    "say 'click the mic on CTAF' (or that frequency), never 'contact CTAF', because nobody answers.\n"
    "Return ONLY a JSON array of strings, same order and same length as the input.\n")


def prompt_for(batch):
    """PROMPT plus the verified meanings of the contractions in this batch, and the ones that
    have none and must be copied."""
    meanings, copy, where = {}, set(), {}
    for raw in batch:
        for term in terms(raw):
            if term in PLAIN_WORDS or term in NEGATIONS:
                continue
            entry = glossary.lookup(term)
            if entry and entry["verified"] and entry["prompt"]:
                meanings[term] = entry["expansion"]
            n, side, rule = _context(term, raw)
            if n:
                where[term] = _where(side, rule)
                meanings[f"{term} {where[term]}"] = rule["meaning"]
        copy.update(unverified(raw))
    text = PROMPT
    if meanings:
        text += ("Meanings (from the FAA Chart Supplement and FAA Order JO 7340.2):\n"
                 + "\n".join(f"{t} = {m}" for t, m in sorted(meanings.items())) + "\n")
    if copy:
        text += "These have no verified meaning; copy them exactly as written: " + ", ".join(
            f"{t} (anywhere but {where[t]})" if t in where else t for t in sorted(copy)) + "\n"
    return text + "\nRemarks:\n" + json.dumps(batch, indent=1)


def translate_remarks(texts, use_llm, ids=frozenset(), states=frozenset()):
    """map raw FAA remark -> plain English. cached on disk; falls back to raw text. ids and
    states are the names NASR lists, which the review queue doesn't count (review_terms).

    the model never decides whether a build ships: a failed call (no credit, a bad key, the API
    down, a timeout) leaves that batch as FAA text, counts in STATS for the run log and shows as
    a warning on the Actions run, and after FAIL_LIMIT failures in a row the rest of the run shows
    FAA text too, so an outage can't hold a build past its time limit. those remarks are asked
    again next build. a remark whose answer broke the checks isn't asked again until
    ENGINE_VERSION changes (REJECTS_FILE), so a remark the model keeps getting wrong doesn't cost
    a call every build."""
    STATS.clear()
    STATS.update(llm_calls=0, input_tokens=0, output_tokens=0, est_cost_usd=0.0, sent=0,
                 translated=0, rejected=0, bad_batches=0, cache_retired=0, rejects_skipped=0,
                 llm_errors=0, llm_error=None, llm_stopped=False, unanswered=0, unknown_terms={})
    cache = _load(CACHE_FILE, {})
    # re-check old entries too, so tightening faithful() retires translations made before it
    kept = {t: readable(t, o) for t, o in cache.items() if faithful(t, o)}
    STATS["cache_retired"] = len(cache) - len(kept)
    cache = kept
    STATS["unknown_terms"] = dict(Counter(t for raw in {x for x in texts if x}
                                          for t in set(review_terms(raw, ids, states))).most_common())
    rejects = rejected()
    todo = sorted({t for t in texts if t and t not in cache})
    STATS["rejects_skipped"] = sum(1 for t in todo if t in rejects)
    todo = [t for t in todo if t not in rejects]
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (use_llm and todo):
        return cache
    if not key:
        print("  warning: --llm set but ANTHROPIC_API_KEY missing, using raw remarks")
        return cache
    if len(todo) > BATCH:
        print(f"  translating {len(todo)} remarks with Claude ...")
    failed = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        if len(todo) > 300 and i % 300 == 0:
            print(f"    {i}/{len(todo)}")
        try:
            out = _call_claude(key, prompt_for(batch))
        except Exception as e:      # no credit, bad key, API down, timeout
            failed += 1
            STATS["llm_errors"] += 1
            STATS["llm_error"] = STATS["llm_error"] or _why(e)
            STATS["unanswered"] += len(batch)
            print(f"  warning: llm call failed ({_why(e)}), showing the FAA text for {len(batch)} remarks")
            if failed == FAIL_LIMIT:
                STATS["llm_stopped"] = True
                STATS["unanswered"] += len(todo) - i - len(batch)
                print(f"  warning: {FAIL_LIMIT} llm calls failed in a row; the FAA text stays for the rest of this run")
                break
            continue
        failed = 0
        if not isinstance(out, list) or len(out) != len(batch):
            STATS["bad_batches"] += 1
            STATS["unanswered"] += len(batch)
            print("  warning: llm returned the wrong shape, skipping batch")
            continue
        STATS["sent"] += len(batch)
        good = {t: readable(t, o) for t, o in zip(batch, out) if faithful(t, o)}
        STATS["translated"] += len(good)
        STATS["rejected"] += len(batch) - len(good)
        cache.update(good)
        rejects.update({t: problems(t, o)[:3] for t, o in zip(batch, out) if t not in good})
    if STATS["rejected"]:
        print(f"  {STATS['rejected']} translations broke the no-guess check; showing the FAA text for those")
    if STATS["llm_errors"]:
        print(f"::warning title=remark translation::{STATS['llm_errors']} of {STATS['llm_calls'] + STATS['llm_errors']} "
              f"calls failed ({STATS['llm_error']}); {STATS['unanswered']} remarks show the FAA text until a later build")
    _save(CACHE_FILE, cache)
    _save(_rejects_file(), {"engine": ENGINE_VERSION, "remarks": dict(sorted(rejects.items()))})
    return cache


def rejected():
    """{raw: why} for the remarks whose answer broke the checks under this ENGINE_VERSION"""
    r = _load(_rejects_file(), {})
    return r.get("remarks", {}) if r.get("engine") == ENGINE_VERSION else {}


def untranslated(raw, plain=None, why=(), ids=frozenset(), states=frozenset()):
    """a line for the reader when a remark shows the FAA's words, or None. plain is its checked
    translation (the FAA text itself when the model gave that back), why the problems of an answer
    the checks rejected (rejected()). a translation gets a line only for a term it keeps that remarks
    use more than one way (glossary remarks_use): 'NA is left as the FAA wrote it: it can mean not
    authorized or not available, and Amend doesn't guess which.' ids and states: review_terms"""
    if not raw:
        return None
    if plain and plain != raw:
        kept = [t for t in dict.fromkeys(unverified(raw)) if _uses(t)]
        return " ".join(f"{t} is left as the FAA wrote it: it {_can_mean(t)}." for t in kept) or None
    if plain is None and not why:
        return "Kept in the FAA's words until it's translated."
    unknown, misread = [], []
    for p in why:
        if m := re.match(r"(\S+) (?:has no verified meaning|is not in the verified glossary)", p):
            unknown.append(m[1])
        elif m := re.match(r"(\S+) is '(.+?)' \(.*\), not what the translation says$", p):
            misread.append((m[1], m[2].lower()))
    if plain == raw:        # the model gave the FAA text back: say what in it has no verified meaning
        unknown = review_terms(raw, ids, states)
        if not unknown:
            return None
    unknown = list(dict.fromkeys(unknown))
    parts = [f"{t} {_can_mean(t)}" for t in unknown if _uses(t)]
    if other := [t for t in unknown if not _uses(t)][:3]:
        parts.append(f"Amend has no verified meaning for {_either(other, 'and')}")
    if misread:
        said = _either([f"{t} ({m})" for t, m in dict.fromkeys(misread[:3])], "and")
        parts.append(f"the plain-English version didn't use the verified meaning for {said}")
    return "Kept in the FAA's words: " + ("; ".join(parts) or "the plain-English version didn't pass Amend's checks") + "."


def _uses(term):
    return (glossary.lookup(term) or {}).get("remarks_use")


def _can_mean(term):
    return f"can mean {_either(_uses(term))}, and Amend doesn't guess which"


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=1)


def _rejects_file():
    """next to the cache, so a test that moves the cache moves this too"""
    return os.path.join(os.path.dirname(CACHE_FILE), REJECTS_FILE)


def _why(e):
    """why a call failed, for the run log: the HTTP status and the API's own message ('Your credit
    balance is too low...'). never the request, so never the key"""
    if isinstance(e, urllib.error.HTTPError):
        try:
            msg = json.loads(e.read() or b"{}").get("error", {}).get("message")
        except Exception:
            msg = None
        text = f"HTTP {e.code}: {msg or e.reason}"
    else:
        text = f"{type(e).__name__}: {e}"
    return re.sub(r"sk-[\w-]+", "sk-...", " ".join(text.split()))[:200]


def scrub_history(hist_dir="history"):
    """history/ keeps each summary as it was written, so a translation the checks now reject
    outlives its cache entry there: put the FAA text back in its place, with the reason
    (untranslated). a translation that passes is said the way readable() says it now (a runway
    side, ++), with a line for a term it leaves as written. run it whenever the checks or readable()
    change, in the same change. ids stay as stored, so nothing shows as new, and only files that
    change are rewritten. returns (FAA text put back, translations reworded, airport files changed)."""
    from .output import dump    # output imports pipeline, which imports this module
    back = reworded = files = 0
    for path in sorted(glob.glob(os.path.join(hist_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        n = 0
        for e in h.get("entries", []):
            raw = e.get("original")
            head, sep, plain = e["summary"].partition(": ")
            if not (raw and sep and plain != raw and e.get("source") in REMARK_FILES + ("FRQ",)):
                continue
            if not faithful(raw, plain):
                why = untranslated(raw, None, problems(raw, plain)[:3])
                e["summary"], back = f"{head}: {raw}", back + 1
            else:
                now = readable(raw, plain)
                why = untranslated(raw, now)
                if now == plain and why == e.get("untranslated"):
                    continue
                e["summary"], reworded = f"{head}: {now}", reworded + (now != plain)
            e.pop("untranslated", None)
            if why:
                e["untranslated"] = why
            n += 1
        if n:
            dump(h, path)
            files += 1
    return back, reworded, files


# lighting you turn on from the cockpit: "ACTVT MIRL RWY 17/35 - CTAF." nobody answers on
# that frequency, so a translation telling pilots to contact it is wrong
PCL = re.compile(r"(ACTVT|INCR|INTST).*-\s*(CTAF|\d{3}\.\d+)")
CALL_PCL = re.compile(r"\b(contact|call)\w*\s+(the\s+)?(ctaf|\d{3}\.\d)")

TOKEN = re.compile(r"[A-Z0-9]+(?:[-/][A-Z0-9]+)*")
# addresses aren't words: ORG in "OPS@X.ORG" is not a contraction
ADDRESS = re.compile(r"\S+@\S+|\b(?:HTTPS?://|WWW\.)\S+", re.I)
# a pavement code, "PCR VALUE: 56/F/B/X/T" or "ACN 32 R/B/X/T": copied exactly, never explained
PCR_CODE = re.compile(r"\b[A-Z](?:/[A-Z]){3}\b")
# "1900 FT X 55 FT": a dimension, not the contraction X (cross)
DIMENSION = re.compile(r"(?<=\d|T)\s+X\s*(?=\d)|(?<=\d)X(?=\d)")
# words with no meaning of their own; a translation may drop or reword them. MISC heads a remark
# as a label ("MISC: RWY 03L MKD 150 FT WIDE") and says nothing about it
PLAIN_WORDS = {"A", "AN", "THE", "OF", "TO", "IN", "ON", "AT", "BY", "FOR", "WITH", "FROM", "INTO",
               "ONTO", "AND", "OR", "AS", "IS", "ARE", "BE", "BEEN", "BEING", "WAS", "WERE", "IT",
               "ITS", "THIS", "THAT", "THESE", "THOSE", "THEN", "THAN", "THERE", "WHICH", "WHO",
               "IF", "SO", "HAS", "HAVE", "HAD", "DO", "DOES", "WILL", "SHALL", "ALSO", "PLEASE",
               "MISC"}
# negations may be reworded ("NOT AVBL" -> "unavailable", "NO FUEL" -> "fuel not available"), but a
# translation has to say as many as the FAA text does: "RWY NOT CLSD" isn't "runway closed", and
# "TWY A LGTD" isn't "taxiway A is not lighted". UN- and NON- words count (UNAVBL, "unmarked",
# "non-standard"), and so does a contraction whose FAA meaning is one (NLT, NSTD, U/S)
NEGATIONS = {"NOT", "NO", "NON", "NONE", "NEVER", "CANNOT", "WITHOUT", "NOR", "UNLESS"}
NOT_NEGATIVE = ("UNDER", "UNTIL", "UNIT", "UNICOM", "UNION", "UNIFORM", "UNIFIED", "UNIVERS", "UNIQUE")
# except NO before a case number: "SEE AIRSPACE CASE NO. 2024-ASW-7785-NRA"
NUMBER_NO = re.compile(r"\bNO\.\s*(?:[A-Z]+:\s*)?\d", re.I)
SAYS_NOT = re.compile(r"\b(not|no|non|none|never|cannot|without)\b|n['’]t\b")
STOP = {"of", "the", "and", "or", "to", "a", "an", "in", "on", "at", "by", "for", "with"}


def faithful(raw, plain):
    """false if the translation guessed at a contraction, dropped a word or changed a number.
    the raw text is shown instead, and the remark isn't asked again until ENGINE_VERSION changes."""
    return isinstance(plain, str) and not problems(raw, plain)


def readable(raw, plain):
    """a checked translation said the same way every time: each ++ after a UTC time the way the Chart
    Supplement's legend explains it (see DAYLIGHT), a runway side the way the FAA writes it (see
    runway_sides), and a term copied where a glossary rule gives it a meaning with that meaning (see
    in_context). the model copies ++; code says what it means. an answer that is the FAA text itself
    stays the FAA text"""
    if plain == raw:
        return plain
    return in_context(raw, runway_sides(raw, ZPLUS.sub(lambda m: DAYLIGHT + (" " if m[1] else ""), plain)))


def in_context(raw, plain):
    """a term the translation copied where a glossary rule gives it a meaning, said with it: 'TRANS
    alert' is 'transient alert' where the remark writes TRANS ALERT (glossary.BEFORE), 'high PER' is
    'high performance' (glossary.AFTER). only while the translation has the term and its meaning
    there no more often than the remark has the term there"""
    for term in dict.fromkeys(terms(raw)):
        n, side, rule = _context(term, raw)
        copied = n and _context_re(term, side, rule, copied=True)
        if not copied or not 0 < len(copied.findall(plain)) + len(_context_re(term, side, rule).findall(plain)) <= n:
            continue
        def said(m):       # 'TRANS ALERT: ...' copied in capitals is 'Transient alert: ...'
            start = m.start() == 0 or re.search(r"[.!?]\s+$", plain[:m.start()])
            meaning = rule["meaning"][0].upper() + rule["meaning"][1:] if start else rule["meaning"]
            return m[1] + meaning if side == "after" else meaning + (m[2].lower() if m[2].isupper() else m[2])
        plain = copied.sub(said, plain)
    return plain


# a runway's side the way the FAA writes it, "runway 33C" and "runway 15C/33C": translations said
# it four ways ("33 Left", "33 left", "33 Center", "33C"). only a runway number the remark writes
# with its side letter, only after "runway" in the translation, and never a number the remark also
# writes with a word after it: "RWY 6 RIGHT TFC" is right traffic, "20 L OF CNTRLN" 20 feet left
SIDE_CODE = re.compile(r"(?<![A-Z0-9])(\d{1,2})([LRC])(?![A-Z0-9])")
SIDE_APART = re.compile(r"(?<![A-Z0-9])(\d{1,2})\s+(?:L|R|C|LEFT|RIGHT|CENTER|CENTRE|CNTR|CTR)\b")
RUNWAYS = re.compile(r"\b(?:runways?|rwys?)\s+(?:\d{1,2}(?:\s*(?:left|right|cent(?:er|re)|[lrc]))?\b"
                     r"(?:\s*(?:/|-|,|&|\band\b|\bor\b)\s*(?=\d))?)+", re.I)
SAID_SIDE = re.compile(r"(?<![\d.])(\d{1,2})\s*(left|right|cent(?:er|re)|[lrc])\b", re.I)


def runway_sides(raw, plain):
    """'runway 33 Center', 'runways 33 left and 33c' -> 'runway 33C', 'runways 33L and 33C', with the
    remark's own code (09L stays 09L)"""
    up = raw.upper()
    apart = {int(m[1]) for m in SIDE_APART.finditer(up)}
    code = {}
    for m in SIDE_CODE.finditer(up):
        code.setdefault((int(m[1]), m[2]), m[0])

    def side(m):
        n = int(m[1])
        return code.get((n, m[2][0].upper()), m[0]) if n not in apart else m[0]
    return RUNWAYS.sub(lambda m: SAID_SIDE.sub(side, m[0]), plain)


def problems(raw, plain):
    """what's wrong with a translation, as short strings. empty means it's fine."""
    if not isinstance(plain, str):
        return ["translation is not text"]
    plain = SAID_DAYLIGHT.sub("++", plain)      # readable()'s words for ++ are the ++ itself
    if plain == raw:
        return []
    low = plain.lower()
    words = re.findall(r"[a-z]+", low)
    words += [w[2:] for w in words if w.startswith("un") and len(w) > 5]   # "unlighted" says "lighted"
    words += [w[3:] for w in words if w.startswith("non") and len(w) > 6]  # "nonstandard" says "standard"
    pairs = [a + b for a, b in zip(words, words[1:])]                      # "center line" says "centerline"
    ts = terms(raw)
    joined = {}                                                            # RAIL ROAD said as "railroad"
    for a, b in zip(ts, ts[1:]):
        joined.setdefault(a, set()).add((a + b).lower())
        joined.setdefault(b, set()).add((a + b).lower())
    out = []
    for term in dict.fromkeys(ts):
        if term in PLAIN_WORDS:
            continue
        n, side, rule = _context(term, raw)
        if n:       # each time the remark has it there, copied or said with the rule's meaning; elsewhere copied
            total, copied = ts.count(term), len(_kept_re(term).findall(plain))
            if copied + min(len(_context_re(term, side, rule).findall(plain)), n) >= total:
                continue    # HI PER said as 'high performance', TRANS ALERT as 'transient alert'
            if copied >= total - n:
                out.append(f"{term} is {rule['meaning']!r} ({rule['source']}, {_where(side, rule)}), "
                           "not what the translation says")
                continue
        elif _kept(term, plain) or _inflected(term, words):
            continue
        if term in NEGATIONS:       # counted below; a case NO. has to stay a number
            numbered = term == "NO" and not re.search(r"\bNO\b", NUMBER_NO.sub(" ", raw.upper()))
            if numbered and "number" not in words:
                out.append(f"dropped {term}")
            continue
        entry = glossary.lookup(term)
        english = (entry or {}).get("english")
        if english:
            entry = None
        if entry and entry["verified"]:
            if not _says(entry, low, words, pairs):
                out.append(f"{term} is {entry['expansion']!r} ({entry['source']}), not what the translation says")
        elif entry:
            out.append(f"{term} has no verified meaning ({entry.get('note') or 'unverified'}); it must stay as written")
        elif not english and _looks_contracted(term):
            out.append(f"{term} is not in the verified glossary; it must stay as written")
        elif not _reworded(term, words + pairs, joined.get(term, ())):
            out.append(f"dropped {term}")
    least, most, said = _negations(raw, plain)
    if not least <= said <= most:
        out.append(f"{'dropped' if said < least else 'added'} a negation: the FAA text has "
                   f"{least if said < least else most}, the translation {said}")
    for code in PCR_CODE.findall(raw.upper()):
        if code.lower() not in low.replace(" / ", "/"):
            out.append(f"changed the pavement code {code}")
    if PCL.search(raw) and CALL_PCL.search(low):
        out.append("says to contact the frequency; pilot-controlled lighting means click the mic")
    have, want = _numbers(plain), _numbers(raw)
    out += [f"lost number {n}" for n in sorted(want - have)]
    out += [f"added number {n}" for n in sorted(have - want)]
    if have == want and not _same_order(raw, plain):
        out.append("numbers moved, dropped or repeated: " + " ".join(_sequence(plain)))
    if re.search(r"\bOR\b", raw.upper()) and not re.search(r"\bor\b", low):
        out.append("dropped OR")
    out += _code_problems(raw, plain, low, words, pairs)
    out += _mark_problems(raw, plain)
    out += _added(raw, plain)
    return out


def terms(raw):
    """the words of a remark a translation has to account for, numbers and ids aside.
    SS-SR stays whole when the glossary knows it; ARR/DEP splits into ARR and DEP."""
    out = []
    text = PCR_CODE.sub(" ", ADDRESS.sub(" ", raw.upper()))
    for tok in TOKEN.findall(DIMENSION.sub(" ", text)):
        if re.fullmatch(r"[A-Z]+", tok) or glossary.lookup(tok):
            out.append(tok)
        else:
            out += [p for p in re.split(r"[-/]", tok) if re.fullmatch(r"[A-Z]+", p)]
    return out


def unverified(raw):
    """contractions in a remark that a translation must leave as written: the review queue.
    single letters and roman numerals are names here (TWY C, PHASE II), not contractions."""
    out, ts = [], terms(raw)
    for t in ts:
        if t in PLAIN_WORDS or t in NEGATIONS or len(t) == 1 or re.fullmatch(r"[IVX]+", t):
            continue
        entry = glossary.lookup(t)
        if entry and entry.get("english"):
            continue
        if (entry and not entry["verified"]) or (not entry and _looks_contracted(t)):
            if _context(t, raw)[0] < ts.count(t):      # every TRANS a TRANS ALERT: it has a meaning
                out.append(t)
    return out


def _context(term, raw):
    """(how many times, 'after' or 'before', the rule): the remark has the term right after or right
    before the words its glossary rule names, where the term takes the rule's meaning. PER right after
    HI, HIGH or LOW is performance (glossary.AFTER), TRANS right before ALERT transient (glossary.BEFORE)"""
    entry = glossary.lookup(term) or {}
    side = next((s for s in ("after", "before") if s in entry), None)
    if not side:
        return 0, None, None
    near, t = "|".join(map(re.escape, entry[side]["words"])), re.escape(term)
    pat = rf"\b(?:{near})\s+{t}\b" if side == "after" else rf"\b{t}\s+(?:{near})\b"
    return len(re.findall(pat, raw.upper())), side, entry[side]


def _where(side, rule):
    return f"right {side} {_either(rule['words'])}"


def _context_re(term, side, rule, copied=False):
    """the rule's place in a translation: the words next to the term as a translation says them
    ('high' for HI), with the rule's meaning ('high performance', 'transient alert') or the term
    copied as written ('high PER', 'TRANS alert'). groups: (near words, term) for a rule on the
    'after' side, (term, near words) for one on the 'before' side"""
    near = {w.lower() for w in rule["words"]}
    for w in rule["words"]:
        e = glossary.lookup(w)
        if e and e["verified"] and not e.get("english"):
            near.update(m.lower() for m in e.get("meanings") or [e["expansion"]])
    near = "(?:" + "|".join(map(re.escape, sorted(near, key=len, reverse=True))) + ")"
    word = re.escape(term) if copied else r"[\s-]+".join(map(re.escape, rule["meaning"].split()))
    if side == "after":
        return re.compile(rf"(?<![A-Za-z])({near}[\s-]+)({word})(?![A-Za-z])", re.I)
    return re.compile(rf"(?<![A-Za-z])({word})([\s-]+{near}s?)(?![A-Za-z])", re.I)


def _either(words, conj="or"):
    return ", ".join(words[:-1]) + f" {conj} " + words[-1] if len(words) > 1 else words[0]


# the review queue leaves out the parts of a postal address: they're names, not contractions.
# "ARPT PHYS ADS: 38550 JET CENTER DR, WILLOUGHBY, OH 44094-8174." a translation still copies them
STREET_WORDS = "AVE|BLVD|CIR|CT|DR|HWY|LN|PKWY|PL|RD|ST|TER|TRL|WAY"
# a house number starts a street, a measurement or a runway doesn't: "25 FT RD", "RWY 18 ACCESS RD"
NOT_A_STREET = r"FT|FEET|FOOT|NM|SM|MI|MILES?|IN|LBS?|KTS?|DEGS?|MINS?|HRS?|M|YDS?|AGL|MSL|X|OF|AND|TO|FM|FROM|ON|AT"


@functools.lru_cache(maxsize=None)
def _address_rules(states):
    st = "|".join(sorted(states))
    return (
        # "WILLOUGHBY, OH 44094", "WASHINGTON, TX" at the end: a state after a city
        re.compile(r"(?<=[A-Z.]),\s*(" + st + r")\.?(?=\s+\d{5}|\s*\.?\s*$)"),
        # "KODIAK AK 99615": a state before a ZIP code
        re.compile(r"(?<=[A-Z])\s+(" + st + r")\s+\d{5}(?:-\d{4})?(?!\d)"),
        # "7400 E OSBORN RD SCOTTSDALE, AZ", "1508 INDUS BLVD.": a house number, a name, a street
        # word, then a comma, the end, or a city and state
        re.compile(r"(?<![A-Z0-9/.+-])(?<!RWY )(?<!RY )(?<!TWY )[NSEW]?\d{1,6}[A-Z]?\s+(?:[NSEW]\.?\s+)?"
                   r"(?:(?!(?:" + NOT_A_STREET + r")\b)(?:[A-Z][A-Z'.-]+|\d+(?:ST|ND|RD|TH))\s+){1,3}?"
                   r"(" + STREET_WORDS + r")\b\.?(?=\s*[,;]|\s*$|\s+[A-Z]+(?:\s+[A-Z]+){0,2},?\s+(?:" + st + r")\b)"),
    )


def review_terms(raw, ids=frozenset(), states=frozenset()):
    """unverified(raw) less the names in it, for the review queue: an ARTCC or ICAO airport id
    NASR lists (ids: 'OAKLAND ARTCC (ZOA)', 'WITHIN 95 NM OF KSPS') and the street word and state
    of a postal address (states: the state codes NASR lists). a translation still has to copy
    them as written; they just aren't gaps in the glossary."""
    text = raw.upper()
    if states:
        for a, b in [m.span(1) for rule in _address_rules(frozenset(states)) for m in rule.finditer(text)]:
            text = text[:a] + " " * (b - a) + text[b:]
    return [t for t in unverified(text) if t not in ids or glossary.lookup(t)]


def _looks_contracted(term):
    """no vowels (THLD, PRVDD) or a short all-caps code (OT, AP): not a plain English word."""
    return len(term) <= 3 or glossary.contracted(term)


def _kept(term, plain):
    """copied as written, maybe made plural or joined to its number: 'MIRL' -> 'MIRLs', 'E-MAIL' ->
    'email', 'US' -> 'U.S.', '100 LL' -> '100LL'"""
    return _kept_re(term).search(plain) is not None


@functools.lru_cache(maxsize=None)
def _kept_re(term):
    spelled = re.escape(term).replace(r"\-", "[- ]?")
    if term.isalpha() and len(term) <= 3:
        spelled = r"\.?".join(term)
    return re.compile(r"(?<![A-Za-z])" + spelled + r"(?:'?s|es)?(?![A-Za-z0-9])", re.I)


def _inflected(term, words):
    """the same word with an ending: 'CALL' -> 'calling', 'USE' -> 'used', 'STOP' -> 'stopped'."""
    t = term.lower()
    if len(t) < 3:
        return False
    forms = {t + e for e in ("s", "es", "ed", "d", "ing", "er", "ers", "ly")}
    forms |= {t + t[-1] + e for e in ("ed", "ing", "er")}
    if t.endswith("e"):
        forms |= {t[:-1] + e for e in ("ing", "ed")}
    return any(w in forms for w in words)


def _says(entry, low, words, pairs):
    """does the translation use one of this entry's FAA meanings? every content word of the
    meaning has to show up, allowing for word endings: 'lights' says 'light'."""
    if any(re.search(p, low) for p in entry.get("accept", [])):
        return True
    if entry.get("parts"):      # SS-SR: only the accept patterns know the order
        return False
    for meaning in entry.get("meanings") or [entry["expansion"]]:
        if any(_says_sense(sense, low, words, pairs) for sense in glossary.senses_of(meaning)):
            return True
    return False


def _says_sense(sense, low, words, pairs):
    mw = glossary.words(sense)
    need = [w for w in mw if w not in STOP] or mw
    if not need:
        return False
    ok = [any(_same(w, p) for p in words + pairs) for w in need]
    for i in range(len(need) - 1):          # "fire fighting" said as "firefighting", "north-north east" as "north-northeast"
        joined = need[i] + need[i + 1]
        if any(p.startswith(joined) and len(p) <= len(joined) + 3 for p in words + pairs):
            ok[i] = ok[i + 1] = True
    for i, w in enumerate(need):            # "unavailable" said as "not available"
        if not ok[i] and w.startswith("un") and len(w) > 5 and SAYS_NOT.search(low):
            ok[i] = any(_same(w[2:], p) for p in words)
    return all(ok)


# how a word of an FAA meaning may end differently in a translation: 'lighting' said as 'lights',
# 'arrive' as 'arrival', 'closed' as 'closure', 'operation' as 'operate'
ENDINGS = {"e", "s", "y", "d", "t", "al", "ce", "ed", "er", "ic", "le", "ly", "nt", "on", "ty",
           "ies", "ing", "ion", "ity", "ive", "ons"}


def _same(want, have):
    """a word of an FAA meaning, give or take its ending. not 'transient' said as 'transition',
    'expect' as 'experimental', or 'heliport' as 'helipad'."""
    k = len(os.path.commonprefix([want, have]))
    return k == len(want) or (_close(want, have) and want[k:] in ENDINGS) or _family(want, have)


# a noun in -sion and the verb it's made from, so a translation can read as English: EXTN
# ('extension') in 'WHEN TWR HR EXTN' said as 'when tower hours are extended', PERMISSION as
# 'permitted', DIVISION as 'divided'. at least 3 letters before the ending, so not 'tension' and 'tend'
SION = (("nsion", "nd"), ("ssion", "t"), ("rsion", "rt"), ("sion", "de"), ("sion", "se"))


def _family(a, b):
    return (a.endswith("sion") and _verb_of(a, b)) or (b.endswith("sion") and _verb_of(b, a))


def _verb_of(noun, word):
    """is word the verb noun is made from, in any form: 'extension' and 'extends', 'extended'"""
    for end, verb in SION:
        if noun.endswith(end) and len(noun) - len(end) >= 3:
            stem = noun[:-len(end)] + verb
            if word == stem or _inflected(stem, [word]):
                return True
    return False


def _close(want, have):
    """same word, give or take the ending: 'operations' and 'operating', not 'contact' and 'control'."""
    n = len(want)
    need = n if n <= 4 else max(4, n - 2) if n <= 7 else n - 3
    return len(os.path.commonprefix([want, have])) >= need


# endings a plain word may trade for another: REQUIRED said as 'requires', CONTROLLING as
# 'controlled', OPERATIONS as 'operating'
WORD_ENDINGS = {"", "e", "s", "es", "d", "ed", "ing", "ings", "er", "ers", "ly", "y", "ies", "ied", "al",
                "ion", "ions", "ation", "ations", "ment", "ments", "ance", "ence", "ity", "ive"}


def _reworded(term, words, joined=()):
    """a plain word the translation changed the ending of, split, or joined to its neighbor:
    REQUIRED -> 'requires', DROPOFF -> 'drop-off', RAIL ROAD -> 'railroad'. not a contraction
    filled out: COMM isn't 'commercial', APPROX isn't 'approach'."""
    t = term.lower()
    return len(t) >= 4 and any(_one_word(x, w) for x in (t, *joined) for w in words)


def _one_word(a, b):
    """the same word with different endings (a shared stem, and only an ending after it on each
    side), or the end of a longer one: PHONE in 'telephone', STRIP in 'airstrip'."""
    k = len(os.path.commonprefix([a, b]))
    return (any(a[i:] in WORD_ENDINGS and b[i:] in WORD_ENDINGS for i in range(max(k - 2, 3), k + 1))
            or (len(a) >= 5 and b.endswith(a)) or _family(a, b))


def _negations(raw, plain):
    """(fewest, most) negations a translation may say, and how many it does. NOT, NO, UNAVBL and
    'unmarked' count wherever they are. a contraction whose FAA meaning is a negation (NLT is 'not
    later than', U/S is 'unserviceable') may be said with one or not ('out of service'): the check
    of its meaning covers it."""
    ts = terms(NUMBER_NO.sub(" ", raw.upper()))
    least = sum(map(_negative, ts))
    most = least + sum(1 for t in ts if not _negative(t) and _negates(t))
    words = re.findall(r"[a-z]+", NUMBER_NO.sub(" ", plain).lower())
    said = sum(_negative(w.upper()) for w in words) + len(re.findall(r"[a-z]n['’]t\b", plain.lower()))
    return least, most, said


def _negates(term):
    entry = glossary.lookup(term)
    return bool(entry and entry["verified"] and not entry.get("english") and entry.get("expansion")
                and any(map(_negative, re.findall(r"[A-Z]+", entry["expansion"].upper()))))


def _negative(word):
    """1 for NOT, NONE, WITHOUT, UNAVBL, UNMARKED, NONSTANDARD, PROHIBITED; 0 for UNDER, UNTIL, UNICOM."""
    if word in NEGATIONS or (word.startswith("NON") and len(word) > 3) or word.startswith("PROHIB"):
        return 1
    return int(word.startswith("UN") and len(word) >= 4 and not word.startswith(NOT_NEGATIVE))


def _numbers(text):
    """the numbers in a remark, so '1,200' == '1200', '.25' == '0.25', '03' == '3'."""
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return {n.lstrip("0") or "0" for n in re.findall(r"\d*\.\d+|\d+", text)}


# ---------------------------------------------------------------- codes, marks, order, added words
# a code of letters and digits (D523-4244, 18R, 100LL, H1, 24U) has to be copied as written: its
# letters aren't words, and the word check can't see them. an FAA source gives a few of them a
# reading a translation may use instead: runway sides (JO 7340.2: L, R, C), a unit after a number
# (99FT as 99 feet), Z and L after a time (Chart Supplement legend: hours "are expressed in
# Coordinated Universal Time (UTC) and shown as "Z" time"; CS: L = Local Time), and the phone
# prefixes C (CS: Commercial Circuit) and V (CS: Defense Switching Network). no FAA list gives
# D as a phone prefix, so "D523-4244" stays as written
CODE = re.compile(r"(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+")
SIDES = {"L": "left", "R": "right", "C": "cent(?:er|re)"}
ZONES = {"Z": r"z\b|utc\b|zulu\b|coordinated universal time", "L": r"l\b|local\b"}
UNITS = {"FT", "HR", "HRS", "KT", "KTS", "LB", "LBS", "NM", "SM", "MI", "DEG", "DEGS", "MIN", "MINS", "IN"}
PHONE_PREFIX = {"C": r"\bcommercial\b", "V": r"\bdsn\b|\bdefense switching network\b"}
CODE_WORDS = {"L": ["left", "local", "time"], "R": ["right"], "C": ["center", "centre", "commercial"],
              "Z": ["utc", "zulu", "coordinated", "universal", "time"], "V": ["dsn", "defense", "switching", "network"]}


def codes(raw):
    """the letter-and-digit codes in a remark, with the token each is in: [("D523", "D523-4244/4245")]"""
    text = DIMENSION.sub(" ", PCR_CODE.sub(" ", ADDRESS.sub(" ", raw.upper())))
    out = []
    for tok in TOKEN.findall(text):
        if not glossary.lookup(tok):                            # H24 is in the glossary
            out += [(p, tok) for p in re.split(r"[-/]", tok) if CODE.fullmatch(p) and not glossary.lookup(p)]
    return out


def _code_problems(raw, plain, low, words, pairs):
    bad = [code for code, tok in codes(raw) if not _code_said(code, tok, plain, low, words, pairs)]
    return [f"changed {code}; a code of letters and digits stays as written" for code in dict.fromkeys(bad)]


def _code_said(code, tok, plain, low, words, pairs):
    parts = re.findall(r"[A-Z]+|\d+", code)
    if re.search(r"(?<![A-Za-z0-9])" + r"[- ]?".join(parts) + r"(?:'?s)?(?![A-Za-z0-9])", plain, re.I):
        return True
    m = re.fullmatch(r"(\d{1,2})([LRC])", code)                 # RWY 18R: runway 18 right
    if m and re.search(rf"(?<![\d.])0?{int(m[1])}\s*(?:{SIDES[m[2]]})\b", low):
        return True
    m = re.fullmatch(r"(\d{4})([ZL])", code)                    # 1300Z: 1300 UTC
    if m and re.search(rf"(?<!\d){m[1]}\s*(?:{ZONES[m[2]]})", low):
        return True
    m = re.fullmatch(r"(\d+)([A-Z]+)", code)                    # 99FT TREES: 99-foot trees
    if m and m[2] in UNITS and _said(m[2], low, words, pairs):
        return True
    m = re.fullmatch(r"([A-Z]{2,})(\d+)", code)                 # RWY12: runway 12
    if m and _said(m[1], low, words, pairs):
        return True
    m = re.fullmatch(r"([CV])\d{3}", code)                      # C850-283-4244: commercial 850-283-4244
    return bool(m and re.search(rf"(?<![A-Z0-9]){code}-\d{{3}}", tok) and re.search(PHONE_PREFIX[m[1]], low))


def _said(term, low, words, pairs):
    entry = glossary.lookup(term)
    return bool(entry and entry["verified"] and not entry.get("english") and _says(entry, low, words, pairs))


# marks that change what a remark says, kept as written: ++ after a time (the Chart Supplement
# prints a ‡ there, and its legend says that during daylight saving time "effective hours will be
# one hour earlier than shown"), the sign of a height (+22 FT FENCE, -1 FT DITCH: NASR gives
# obstruction heights "above runway"), and the # and * of a gate code. a dash after a number may be
# a range instead: "125 -150 FT" can be said as 125 to 150 feet, but "RY 17 -3 FT DITCH" keeps -3
SIGNED = re.compile(r"(?:^|(?<=[\s(;,:]))(\+\s?|-)(\d+)(?!\d*-\d{3})")
# NASR writes the Chart Supplement's ‡ as ++: the CS prints "Navy Cabaniss Tower 119.65 299.6
# (Mon–Thu 1400–0500Z‡, Fri 1400–0100Z‡)" and "Shell Tower 139.125 244.5 (1230–0000Z‡ Mon–Fri, exc
# hol)" where NASR has "1400-0500Z++ MON-THU; 1400-0100Z++ FRI; (DT 1300-0400Z MON-THU; 1300-0000Z
# FRI)" and "1230-0000Z++MON-FRI EXC HOL". only after a UTC time: "0200-0700++" has no Z and stays
DAYLIGHT = " (one hour earlier during daylight saving time)"
ZPLUS = re.compile(r"(?<=\d{4}Z)\+\+(?=([A-Za-z0-9])?)")
SAID_DAYLIGHT = re.compile(r"(?<=\d{4}Z)" + re.escape(DAYLIGHT), re.I)


def _mark_problems(raw, plain):
    r, p = ADDRESS.sub(" ", raw), ADDRESS.sub(" ", plain)
    out = ["dropped ++"] if r.count("++") > p.count("++") else []
    out += ["added ++"] if p.count("++") > r.count("++") else []
    text = r.replace("++", " ")
    for m in SIGNED.finditer(text):
        sign, num = m[1].strip(), m[2]
        if re.search((r"\+" if sign == "+" else r"[-−–]") + r"\s?" + num + r"(?!\d)", p):
            continue
        before = re.search(r"(\d+)\s$", text[:m.start()])
        if sign == "-" and before and re.search(rf"(?<![\d.]){before[1]}\s*(?:-|–|to|through)\s*{num}(?!\d)", p, re.I):
            continue
        out.append(f"dropped the sign of {sign}{num}")
    out += [f"dropped {ch}" for ch in "#*" if r.count(ch) > p.count(ch)]
    out += [f"dropped {ch}" for ch, word in (("$", "dollar"), ("%", "percent"))
            if ch in r and ch not in p and word not in p.lower()]
    return list(dict.fromkeys(out))


# numbers keep their order and count: "+22 FT FENCE 62 FT R" isn't "a 62-foot fence 22 feet
# away", and "RWY 35, 21 INCH LIGHT BASES" isn't "runways 35 and 21". a phone number with a second
# ending (901-368-8453/8449) may be said as two numbers
PHONE_PAIR = re.compile(r"(?<!\d)(\d{3}-(?:\d{3}-)?)(\d{4})/(\d{4})\b")


def _sequence(text):
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return [n.lstrip("0") or "0" for n in re.findall(r"\d*\.\d+|\d+", text)]


def _same_order(raw, plain):
    have = _sequence(plain)
    return have in (_sequence(raw), _sequence(PHONE_PAIR.sub(lambda m: f"{m[1]}{m[2]} {m[1]}{m[3]}", raw)))


# every word of a translation has to come from somewhere: the remark itself, the FAA meaning of one
# of its contractions, or grammar that can't add a fact. "OTS UFN" isn't "runway threshold lights
# are out of service", "PERSONAL USE" isn't "for personal use only", and "PPR" isn't "require prior
# permission required". a few words are allowed by context: a range (MON-FRI as "Monday through
# Friday"), a phone number, address or frequency ("call"), pilot-controlled lighting ("click the
# mic"), a foot mark (60' as "60 feet"), two phone numbers or emails ("call A or B"), a keypad
# code. negations are counted on their own
GLUE = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "do",
        "does", "did", "it", "its", "this", "that", "these", "those", "there", "their", "they", "them",
        "you", "your", "which", "who", "of", "to", "in", "on", "at", "by", "for", "with", "via", "from",
        "into", "onto", "as", "and", "s", "t", "located", "present", "exists", "exist", "existing",
        "occurs", "occur", "occurring", "becomes", "become", "applies", "apply"}
PHONE = r"(?<!\d)\d{3}-\d{4}(?!\d)"          # 555-1234, not the 600-1800 of 0600-1800
FREQUENCY = r"\b1[1-3]\d\.\d"
IN_CONTEXT = [
    (re.compile(r"[A-Z0-9]\s?-\s?[A-Z0-9]|\b(THRU|TO|TIL|UNTIL)\b"), {"through", "thru", "until", "till", "between"}),
    (re.compile(rf"\bOR\b|/|(?:{PHONE}|@).*(?:{PHONE}|@)"), {"or"}),     # two contacts: "call A or B"
    (re.compile(rf"{PHONE}|@|{FREQUENCY}"), {"call", "calling", "contact", "phone", "telephone", "number", "email"}),
    (re.compile(FREQUENCY), {"frequency", "frequencies"}),
    (PCL, {"click", "mic", "microphone", "key", "keying", "times", "via", "your", "you"}),
    (re.compile(r"\d\s?'"), {"feet", "foot"}),
    (re.compile(r'\d\s?"'), {"inch", "inches"}),
    (re.compile(r"%"), {"percent"}),
    (re.compile(r"\$"), {"dollar", "dollars"}),
    (re.compile(r"\b\d(?:-\d){2,}\b|#"), {"code"}),                    # GATE ACES: 1-2-3-4
]


def _added(raw, plain):
    """words the translation adds, and FAA words it says more times than the remark does ("require
    prior permission required"): the remark doesn't account for them."""
    src = _sources(raw)
    free = GLUE.union(*(ws for pat, ws in IN_CONTEXT if pat.search(raw.upper())))
    used, out = Counter(), []
    for w in _split(_words(plain), src):
        if w in free or _negative(w.upper()):
            continue
        hits = _hits(src, w)
        if not hits:
            out.append(f"added '{w}'")
            continue
        # the same word before a look-alike: 'service' is SVC's, not SERVE's; 'permission' is PPR's
        s = max(hits, key=lambda h: (src[h] > used[h], w in (h.lstrip("+"), h.lstrip("+") + "s"), src[h] - used[h]))
        used[s] += 1
        if used[s] > src[s] and len(w) > 1:     # a code letter may repeat: C502-898-2508/3553
            out.append(f"repeated '{w}'")
    return list(dict.fromkeys(out))


def _hits(src, word):
    """the words of the remark that account for a word of the translation. a joined pair ('+takeoff'
    from 'take-off') accounts only for itself, not for 'off'"""
    return [s for s in src if (word in (s[1:], s[1:] + "s") if s[0] == "+" else _from(s, word))]


def _split(words, src):
    """a translation's words as the remark has them: 'take-off' is TKOF's 'take-off' or TAKEOFF,
    'self-service' is SELF and SVC's 'service', and 'north side' is NORTHSIDE"""
    found = lambda w: bool(_hits(src, w))
    whole = lambda w: any(w in (s.lstrip("+"), s.lstrip("+") + "s") for s in src)     # no other endings
    parts = []
    for w in words:
        parts += [w.replace("-", "")] if whole(w.replace("-", "")) else w.split("-")
    out, i = [], 0
    while i < len(parts):
        pair = "".join(parts[i:i + 2])
        if i + 1 < len(parts) and not (found(parts[i]) and found(parts[i + 1])) and whole(pair):
            out.append(pair)
            i += 2
        else:
            out.append(parts[i])
            i += 1
    return out


def _words(text):
    text = _spelling(_initials(ADDRESS.sub(" ", text)).lower().replace("’", "'"))
    text = re.sub(r"n't\b", " not", text.replace("can't", "cannot").replace("won't", "will not"))
    return re.findall(r"[a-z]+(?:-[a-z]+)*", text)     # "go's" is go and s


def _initials(text):
    """U.S. and P.O. are the words US and PO"""
    return re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m[0].replace(".", ""), text)


def _vocab(text):
    """the words of a text, and each word joined to the next, marked '+': 'take-off' gives '+takeoff'
    too, and CALL-OUT '+callout', since a translation may write either"""
    ws = re.findall(r"[a-z]+", _spelling(text.lower()))
    return ws + ["+" + a + b for a, b in zip(ws, ws[1:])]


def _spelling(text):
    """JO 7340.2 copies ICAO's 'centre line'; translations say 'centerline' (as glossary.words does)"""
    return text.replace("centre", "center").replace("metre", "meter")


def _sources(raw):
    """{word: how many times the remark accounts for it}: its own words and the FAA meanings of its terms."""
    src = Counter(_vocab(_initials(ADDRESS.sub(" ", raw))))
    found = terms(raw)
    for code, tok in codes(raw):
        found += re.findall(r"[A-Z]{2,}", code)
        for letter in set(re.findall(r"[A-Z]", code)) & set(CODE_WORDS):
            src.update(CODE_WORDS[letter])
    for term in found:
        entry = glossary.lookup(term)
        if not entry or not entry["verified"] or entry.get("english"):
            continue
        texts = list(entry.get("meanings") or [entry["expansion"]])
        texts += [re.sub(r"\\[a-zA-Z]", " ", p) for p in entry.get("accept", [])]
        texts += [(glossary.lookup(p) or {}).get("expansion") or "" for p in entry.get("parts", [])]
        most = Counter()
        for t in texts:
            most |= Counter(_vocab(t))      # 'south-south west' has two souths
        src.update(most)
    for term in set(terms(raw)):    # HI PER: 'performance', TRANS ALERT: 'transient', once each time
        n, side, rule = _context(term, raw)
        for _ in range(n):
            src.update(_vocab(rule["meaning"]))
    return src


def _from(src, word):
    """the same word, maybe with another ending: 'required' from REQUIRED or RQRD, 'lighting' from
    'light'. not 'airport' from AIR."""
    if word in (src, src + "s", src + "es"):
        return True
    if min(len(src), len(word)) < 3:
        return False
    if src[:3] != word[:3] and not word.endswith(src) and not src.endswith(word):
        return False        # every match below shares the first 3 letters or is the end of the other word
    return _one_word(src, word) or _one_word(word, src) or (len(src) >= 5 and _same(src, word))


def _call_claude(key, prompt):
    body = json.dumps({"model": LLM_MODEL, "max_tokens": 4000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    usage = data.get("usage") or {}
    tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    STATS["llm_calls"] = STATS.get("llm_calls", 0) + 1
    STATS["input_tokens"] = STATS.get("input_tokens", 0) + tin
    STATS["output_tokens"] = STATS.get("output_tokens", 0) + tout
    STATS["est_cost_usd"] = round(STATS.get("est_cost_usd", 0)
                                  + (tin * PRICE_PER_MTOK[0] + tout * PRICE_PER_MTOK[1]) / 1e6, 4)
    text = "".join(b.get("text", "") for b in data.get("content", []))
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        return json.loads(text)
    except ValueError:          # cut off or not JSON: a bad batch, not a failed call
        return None


def load_env(path=".env"):
    """read KEY=value lines from .env into the environment (real env vars win)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def set_key():
    """prompt for the API key without echoing it, save to .env, make sure git ignores it."""
    import getpass
    key = getpass.getpass("paste your Anthropic API key (it won't show while typing): ").strip()
    if not key.startswith("sk-"):
        print("that doesn't look like an Anthropic key (should start with sk-). nothing saved.")
        return
    lines = []
    if os.path.exists(".env"):
        with open(".env") as f:
            lines = [l for l in f if not l.startswith("ANTHROPIC_API_KEY=")]
    lines.append(f"ANTHROPIC_API_KEY={key}\n")
    with open(".env", "w") as f:
        f.writelines(lines)
    os.chmod(".env", 0o600)
    ignore = set()
    if os.path.exists(".gitignore"):
        with open(".gitignore") as f:
            ignore = {l.strip() for l in f}
    missing = [x for x in (".env", ".venv/", "__pycache__/") if x not in ignore]
    if missing:
        with open(".gitignore", "a") as f:
            f.write("\n".join(missing) + "\n")
    print("saved to .env (and .env is in .gitignore). you can now use --llm.")