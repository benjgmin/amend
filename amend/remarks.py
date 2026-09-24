"""Translating FAA remark contractions to plain English with Claude, plus API key handling."""
import json
import os
import re
import urllib.request

LLM_MODEL = "claude-haiku-4-5-20251001"
CACHE_FILE = "remark_cache.json"
BATCH = 30

# contractions the model is allowed to expand. anything not here and not certain stays as-is.
GLOSSARY = ("ACFT=aircraft, ACR=air carrier, AP=airport, ARPT=airport, ARR=arrival, "
            "AVBL=available, CK=check, CLSD=closed, CTC=contact, CTN=caution, DEP=departure, "
            "DTLS=details, HOL=holidays, INVOF=in vicinity of, LGTD=lighted, "
            "MNT/MNTD=monitored, MRKGS=markings, NA=not authorized, OPS=operations, "
            "PAX=passengers, PPR=prior permission required, RSCD=runway surface condition, "
            "RWY=runway, SKED=scheduled, TWY=taxiway, UNSKED=unscheduled, WKEND=weekend, "
            "WX=weather, M-F=Monday through Friday")

PROMPT = (
    "Translate each FAA airport/ATC remark below into ONE short plain-English "
    "sentence a student pilot would understand.\n"
    "Rules:\n"
    "- Expand ONLY abbreviations listed in the glossary or ones you are certain of.\n"
    "- If you are not certain what an abbreviation or acronym means, leave it "
    "exactly as written. Never guess an expansion. A wrong expansion is dangerous.\n"
    "- Keep all numbers, times, runway ids, frequencies and phone numbers exactly.\n"
    "- Do not add or remove information. Keep every regulatory reference "
    "(Part 121, Part 135, Part 380, FAR, etc.) exactly as written.\n"
    "Glossary: " + GLOSSARY + "\n"
    "The input is a JSON object of id -> remark. Return ONLY a JSON object with the same "
    "ids, each mapped to its translation.\n\n")


def _numbers(s):
    return set(re.findall(r"\d+", s.replace(",", "")))


def faithful(raw, plain):
    """false if the translation lost or changed a number (a time, weight, runway, frequency,
    phone number...). a dropped '12500 LB' limit is exactly the mistake we can't ship."""
    return isinstance(plain, str) and bool(plain.strip()) and _numbers(raw) <= _numbers(plain)


def translate_remarks(texts, use_llm):
    """map raw FAA remark -> plain English. cached on disk; falls back to raw text.
    translations that fail faithful() are never returned, even from an old cache."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    todo = sorted({t for t in texts if t and t not in cache})
    key = os.environ.get("ANTHROPIC_API_KEY")
    if use_llm and todo and not key:
        print("  warning: --llm set but ANTHROPIC_API_KEY missing, using raw remarks")
    if use_llm and todo and key:
        if len(todo) > BATCH:
            print(f"  translating {len(todo)} remarks with Claude ...")
        rejected = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            if len(todo) > 300 and i % 300 == 0:
                print(f"    {i}/{len(todo)}")
            try:
                out = _call_claude(key, PROMPT + json.dumps(
                    {str(j): t for j, t in enumerate(batch)}, indent=1))
            except Exception as e:
                print(f"  warning: llm call failed ({e}), using raw remarks")
                continue
            if not isinstance(out, dict):
                print("  warning: llm didn't return an object, skipping batch")
                continue
            for j, raw in enumerate(batch):
                plain = out.get(str(j))
                if plain is None:
                    continue  # not answered: try again next run
                if not faithful(raw, plain):
                    rejected += 1
                    plain = raw  # cache the rejection so we don't pay for it again
                cache[raw] = plain
        if rejected:
            print(f"  {rejected} translation(s) changed a number, kept the FAA text instead")
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
    return {raw: plain for raw, plain in cache.items() if faithful(raw, plain)}


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
