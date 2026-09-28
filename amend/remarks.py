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
STATS = {}

PROMPT = (
    "Decode each FAA airport/ATC remark below into plain English a student pilot can read. Stay close "
    "to the FAA text: keep its order, spell out each contraction with its listed meaning, and add "
    "nothing. A short phrase is fine; it doesn't have to be a full sentence.\n"
    "Rules:\n"
    "- Expand a contraction ONLY to the meaning listed for it under Meanings. Copy every other "
    "contraction, abbreviation, code and name exactly as written, even if you think you know "
    "what it means. A wrong expansion is dangerous.\n"
    "- If a listed meaning doesn't fit the remark, copy that contraction exactly as written instead.\n"
    "- Use only what the remark says. Don't add a subject, place, object or verb it doesn't state, "
    "like 'the runway', 'the airport', 'fuel', 'aircraft', 'is available', 'contact', 'report', 'high', "
    "'tall', 'deep' or 'away', and don't add 'only', 'must' or 'should'.\n"
    "- Keep the remark's own plain English words (ONLY, EXCEPT, PRIOR, BELOW); don't swap them for "
    "others, and don't say a word more times than the remark does.\n"
    "- Keep all numbers, times, runway ids, frequencies and phone numbers exactly, in the remark's "
    "order, as many times as the remark has them. Never add a number, or a unit (feet, degrees) "
    "after a number that has none.\n"
    "- Copy codes of letters and digits exactly, with their letters: D523-4244, C850-283-4244, "
    "100LL, H1, 24U, BAK-12B.\n"
    "- Keep a + or - in front of a height: '+22 FT FENCE' is '+22 foot fence', never '22-foot fence', "
    "'plus 22' or '22 feet high'. Keep '++' after a time exactly as written.\n"
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
    meanings, copy = {}, set()
    for raw in batch:
        for term in terms(raw):
            if term in PLAIN_WORDS or term in NEGATIONS:
                continue
            entry = glossary.lookup(term)
            if entry and entry["verified"] and entry["prompt"]:
                meanings[term] = entry["expansion"]
        copy.update(unverified(raw))
    text = PROMPT
    if meanings:
        text += ("Meanings (from the FAA Chart Supplement and FAA Order JO 7340.2):\n"
                 + "\n".join(f"{t} = {m}" for t, m in sorted(meanings.items())) + "\n")
    if copy:
        text += "These have no verified meaning; copy them exactly as written: " + ", ".join(sorted(copy)) + "\n"
    return text + "\nRemarks:\n" + json.dumps(batch, indent=1)


def translate_remarks(texts, use_llm):
    """map raw FAA remark -> plain English. cached on disk; falls back to raw text.

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
    kept = {t: o for t, o in cache.items() if faithful(t, o)}
    STATS["cache_retired"] = len(cache) - len(kept)
    cache = kept
    STATS["unknown_terms"] = dict(Counter(t for raw in {x for x in texts if x} for t in set(unverified(raw))).most_common())
    rejects = _load(_rejects_file(), {})
    rejects = rejects.get("remarks", {}) if rejects.get("engine") == ENGINE_VERSION else {}
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
        good = {t: o for t, o in zip(batch, out) if faithful(t, o)}
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
    outlives its cache entry there: put the FAA text back in its place. run it whenever the checks
    get stricter, in the same change. ids stay as stored, so nothing shows as new, and only files
    that change are rewritten. returns (summaries, airport files) changed."""
    from .output import dump    # output imports pipeline, which imports this module
    fixed = files = 0
    for path in sorted(glob.glob(os.path.join(hist_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        n = 0
        for e in h.get("entries", []):
            raw = e.get("original")
            head, sep, plain = e["summary"].partition(": ")
            if raw and sep and e.get("source") in REMARK_FILES + ("FRQ",) and not faithful(raw, plain):
                e["summary"] = f"{head}: {raw}"
                n += 1
        if n:
            dump(h, path)
            fixed, files = fixed + n, files + 1
    return fixed, files


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
# "non-standard"), and so does a contraction whose FAA meaning is one (NA, NLT, NSTD)
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


def problems(raw, plain):
    """what's wrong with a translation, as short strings. empty means it's fine."""
    if not isinstance(plain, str):
        return ["translation is not text"]
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
        if term in PLAIN_WORDS or _kept(term, plain) or _inflected(term, words):
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
    out = []
    for t in terms(raw):
        if t in PLAIN_WORDS or t in NEGATIONS or len(t) == 1 or re.fullmatch(r"[IVX]+", t):
            continue
        entry = glossary.lookup(t)
        if entry and entry.get("english"):
            continue
        if (entry and not entry["verified"]) or (not entry and _looks_contracted(t)):
            out.append(t)
    return out


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
    return k == len(want) or (_close(want, have) and want[k:] in ENDINGS)


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
            or (len(a) >= 5 and b.endswith(a)))


def _negations(raw, plain):
    """(fewest, most) negations a translation may say, and how many it does. NOT, NO, UNAVBL and
    'unmarked' count wherever they are. a contraction whose FAA meaning is a negation (NA is 'not
    authorized', U/S is 'unserviceable') may be said with one or not ('out of service'): the check
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


def _mark_problems(raw, plain):
    r, p = ADDRESS.sub(" ", raw), ADDRESS.sub(" ", plain)
    out = ["dropped ++"] if r.count("++") > p.count("++") else []
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