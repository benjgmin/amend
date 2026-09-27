"""
Named watchlists with their own link: amend.watch/list/<slug>

Each list is a JSON file in watchlists/ in this repo:

    {"name": "Club SVFR", "description": "Training area airports",
     "airports": ["DAB", "OMN", "DED", "VRB"]}

Only people who can push to the repo can create or change a list, so the owner is whoever
controls the repo. Edit the file (or use `python -m amend watchlist ...`), push, and the site
rebuilds.
"""
import json
import os
import re

DIR = "watchlists"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")      # 3-40 chars, lowercase, digits, dashes
ID = re.compile(r"^[A-Z0-9]{2,4}$")


def normalize_id(raw):
    a = raw.strip().upper()
    if len(a) == 4 and a.startswith("K") and a[1:].isalpha():
        a = a[1:]
    return a


def validate(slug, data):
    """list of problems (empty = fine)."""
    errs = []
    if not SLUG.match(slug):
        errs.append(f"'{slug}': link names are 3-40 lowercase letters, digits or dashes")
    if slug in ("latest", "history", "assets", "watch", "list", "about", "guide"):
        errs.append(f"'{slug}': that name is used by the site itself, pick another")
    if not str(data.get("name", "")).strip():
        errs.append(f"'{slug}': needs a name")
    apts = data.get("airports")
    if not isinstance(apts, list) or not apts:
        errs.append(f"'{slug}': needs a non-empty airports list")
    else:
        bad = [a for a in apts if not ID.match(normalize_id(str(a)))]
        if bad:
            errs.append(f"'{slug}': not airport ids: {', '.join(map(str, bad))}")
    return errs


def load_all(directory=DIR):
    """{slug: {"name", "description", "airports"}} for every valid list; prints problems and skips bad ones."""
    out = {}
    if not os.path.isdir(directory):
        return out
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        slug = fname[:-5]
        try:
            with open(os.path.join(directory, fname), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"  watchlist {fname}: can't read ({e}), skipping")
            continue
        errs = validate(slug, data)
        if errs:
            print("  " + "; ".join(errs) + ", skipping")
            continue
        apts = list(dict.fromkeys(normalize_id(str(a)) for a in data["airports"]))
        out[slug] = {"name": data["name"].strip(), "description": str(data.get("description", "")).strip(),
                     "airports": apts}
    return out


def save(slug, name, airports, description="", directory=DIR):
    data = {"name": name, "description": description,
            "airports": list(dict.fromkeys(normalize_id(a) for a in airports))}
    errs = validate(slug, data)
    if errs:
        raise SystemExit("\n".join(errs))
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{slug}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return data
