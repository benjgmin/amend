"""Writing results as the public JSON files (see SCHEMA.md)."""
import json
import os

from . import SCHEMA_VERSION
from .pipeline import counts

MIN = {"separators": (",", ":"), "ensure_ascii": False}


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, **MIN)


def write_diff(result, out_dir):
    """out_dir/<AIRPORT>.json for each changed airport, plus out_dir/index.json."""
    os.makedirs(out_dir, exist_ok=True)
    head = {"schema_version": SCHEMA_VERSION,
            "from_cycle": result["from_cycle"], "to_cycle": result["to_cycle"]}
    for apt, changes in result["airports"].items():
        dump({**head, "airport": apt, "counts": counts(changes), "changes": changes},
             os.path.join(out_dir, f"{apt}.json"))
    dump({**head, "airports": {a: counts(c) for a, c in sorted(result["airports"].items())}},
         os.path.join(out_dir, "index.json"))
    return len(result["airports"])
