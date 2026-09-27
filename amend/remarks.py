"""Translating FAA remark contractions to plain English with Claude, plus API key handling."""
import json
import os
import re
import urllib.request

LLM_MODEL = "claude-haiku-4-5-20251001"
CACHE_FILE = "remark_cache.json"
BATCH = 30

# contraction -> (expansion for the prompt, patterns the translation must contain one of).
# every entry here came back wrong at least once in the real cache, e.g. PLINE as
# "pipeline", PAEW as "parachute jumping activity", CD as "crowd density", AER as
# "aerodrome", SS-SR as "steady-state to steady-red". a translation that keeps the
# contraction as written also passes: leaving it alone is allowed, guessing isn't.
MUST_KEEP = {
    "AER": ("approach end of runway", ["approach end"]),
    "DER": ("departure end of runway", ["departure end"]),
    "DTHR": ("displaced threshold", ["displaced"]),
    "DSPLCD": ("displaced", ["displaced"]),
    "OVRN": ("overrun", ["overrun"]),
    "PLINE": ("power line", ["power line", "powerline", "power-line"]),
    "PLINES": ("power lines", ["power line", "powerline", "power-line"]),
    "NRS": ("numbers (runway numbers)", ["number"]),
    "CD": ("clearance delivery", ["clearance"]),
    "LIRL": ("low intensity runway lights", ["low intensity", "low-intensity"]),
    "MALSR": ("medium intensity approach lighting system with runway alignment indicator lights",
              ["approach light"]),
    "MALSF": ("medium intensity approach lighting system with sequenced flashers", ["approach light"]),
    "RLLS": ("runway lead-in light system", ["lead-in", "lead in"]),
    "PAEW": ("personnel and equipment working", ["personnel and equipment"]),
    "ARNG": ("Army National Guard", ["army national guard"]),
    "OT": ("other times", ["other", "outside", "after hours"]),
    "TPA": ("traffic pattern altitude", ["pattern altitude"]),
    "OFFL": ("official", ["official"]),
    "TXL": ("taxilane", ["taxilane", "taxi lane"]),
    "SLP": ("slope", ["slope"]),
    "PSBL": ("possible", ["possib"]),
    "DALGT": ("daylight", ["daylight"]),
    "PMT": ("permit", ["permit"]),
    "RR": ("railroad", ["railroad", "railway"]),
    "BT": ("back taxi", ["back"]),
    "PN": ("prior notice", ["notice"]),
    "INTMT": ("intermittent", ["intermittent"]),
    "PCR": ("pavement classification rating", ["pavement classification"]),
    "REIL": ("runway end identifier lights", ["end identif"]),
    # order matters: SS-SR has come back as "sunrise to sunset", the opposite window
    "SS-SR": ("sunset to sunrise", [r"sunset\b.{0,20}\bsunrise"]),
    "SR-SS": ("sunrise to sunset", [r"sunrise\b.{0,20}\bsunset"]),
}

# contractions the model is allowed to expand. anything not here and not certain stays as-is.
GLOSSARY = ("ACFT=aircraft, ACR=air carrier, AP=airport, "
            "APCH/APRCH=approach, ARPT=airport, ARR=arrival, "
            "AVBL=available, CK=check, CLSD=closed, CTC=contact, CTN=caution, DEP=departure, "
            "DTLS=details, HOL=holidays, INVOF=in vicinity of, LGTD=lighted, "
            "MNT/MNTD=monitored, MRKGS=markings, NA=not authorized, OPS=operations, "
            "PAX=passengers, PPR=prior permission required, RSCD=runway surface condition, "
            "RWY=runway, SKED=scheduled, TWY=taxiway, UNSKED=unscheduled, WKEND=weekend, "
            "WX=weather, M-F=Monday through Friday, ACTVT=activate, INCR=increase, INTST=intensity, "
            "CONSLY=continuously, OPR/OPRS=operate(s), HIRL=high intensity runway lights, "
            "MIRL=medium intensity runway lights, "
            "PAPI=precision approach path indicator, VASI=visual approach slope indicator, "
            "OTS=out of service, INT=intersection, ANG=Air National Guard, UNMON=unmonitored, "
            "SBP=sport parachuting, "            "TGL=touch-and-go landings, NSTD=nonstandard, AMGR=airport manager, "
            + ", ".join(f"{c}={e}" for c, (e, _) in MUST_KEEP.items()) + ". "
            "PCR VALUE lines like '350/F/A/X/T' are a pavement strength code: keep the value and "
            "letters exactly and do not explain them. A lighting remark ending in '- CTAF' or "
            "'- <frequency>' is pilot-controlled lighting: say 'click the mic on CTAF' (or that "
            "frequency), never 'contact CTAF', because nobody answers")

PROMPT = (
    "Translate each FAA airport/ATC remark below into ONE short plain-English "
    "sentence a student pilot would understand.\n"
    "Rules:\n"
    "- Expand ONLY abbreviations listed in the glossary or ones you are certain of.\n"
    "- If you are not certain what an abbreviation or acronym means, leave it "
    "exactly as written. Never guess an expansion. A wrong expansion is dangerous.\n"
    "- Keep all numbers, times, runway ids, frequencies and phone numbers exactly. "
    "Never add a number that is not in the remark.\n"
    "- Do not add or remove information. Keep every regulatory reference "
    "(Part 121, Part 135, Part 380, FAR, etc.) exactly as written.\n"
    "Glossary: " + GLOSSARY + "\n"
    "Return ONLY a JSON array of strings, same order and same length as the input.\n\n")


def translate_remarks(texts, use_llm):
    """map raw FAA remark -> plain English. cached on disk; falls back to raw text."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    # re-check old entries too, so tightening faithful() retires translations made before it
    cache = {t: o for t, o in cache.items() if faithful(t, o)}
    todo = sorted({t for t in texts if t and t not in cache})
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not (use_llm and todo):
        return cache
    if not key:
        print("  warning: --llm set but ANTHROPIC_API_KEY missing, using raw remarks")
        return cache
    if len(todo) > BATCH:
        print(f"  translating {len(todo)} remarks with Claude ...")
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        if len(todo) > 300 and i % 300 == 0:
            print(f"    {i}/{len(todo)}")
        try:
            out = _call_claude(key, PROMPT + json.dumps(batch, indent=1))
            if len(out) == len(batch):
                cache.update({t: o for t, o in zip(batch, out) if faithful(t, o)})
            else:
                print("  warning: llm returned wrong number of remarks, skipping batch")
        except Exception as e:
            print(f"  warning: llm call failed ({e}), using raw remarks")
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=1)
    return cache


# lighting you turn on from the cockpit: "ACTVT MIRL RWY 17/35 - CTAF." nobody answers on
# that frequency, so a translation telling pilots to contact it is wrong
PCL = re.compile(r"(ACTVT|INCR|INTST).*-\s*(CTAF|\d{3}\.\d+)")
CALL_PCL = re.compile(r"\b(contact|call)\w*\s+(the\s+)?(ctaf|\d{3}\.\d)")


def faithful(raw, plain):
    """false if the translation got a known contraction wrong or changed a number.
    the raw text is shown instead and the remark is retried next run."""
    return not problems(raw, plain)


def problems(raw, plain):
    """what's wrong with a translation, as short strings. empty means it's fine."""
    if plain == raw:
        return []
    low = plain.lower()
    out = [f"{code} not translated as {expansion!r}"
           for code, (expansion, words) in MUST_KEEP.items()
           if _word(code).search(raw.upper()) and not _word(code).search(plain)
           and not any(re.search(w, low) for w in words)]
    if PCL.search(raw) and CALL_PCL.search(low):
        out.append("says to contact the frequency; pilot-controlled lighting means click the mic")
    have, want = _numbers(plain), _numbers(raw)
    out += [f"lost number {n}" for n in sorted(want - have)]
    out += [f"added number {n}" for n in sorted(have - want)]
    return out


def _word(code):
    return re.compile(r"(?<![A-Z0-9-])" + re.escape(code) + r"(?![A-Z0-9-])")


def _numbers(text):
    """the numbers in a remark, so '1,200' == '1200', '.25' == '0.25', '03' == '3'."""
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return {n.lstrip("0") or "0" for n in re.findall(r"\d*\.\d+|\d+", text)}


def _call_claude(key, prompt):
    body = json.dumps({"model": LLM_MODEL, "max_tokens": 4000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    text = "".join(b.get("text", "") for b in data.get("content", []))
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    return json.loads(text)


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