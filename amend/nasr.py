"""Reading FAA NASR 28-day CSV zips."""
import csv
import io
import zipfile
from collections import defaultdict

from .rules import ATTRIB_COLS, HIDDEN_FILES, IGNORE_COLS, STRICT_FILES, base


def iter_csvs(zf):
    """yield (filename, bytes) for every csv in a zip, recursing into nested zips."""
    for name in zf.namelist():
        low = name.lower()
        if low.endswith(".csv"):
            yield name.split("/")[-1], zf.read(name)
        elif low.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                yield from iter_csvs(inner)


def decode(raw):
    """FAA csvs: maybe utf-8 with a BOM, maybe latin-1, old-mac or windows line endings."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def attribute(row, ids, fname="", strict=False):
    """which of our airports this row belongs to (list: a route belongs to both ends)."""
    if base(fname).startswith("PFR"):
        return sorted({row[c].upper() for c in ("Orig", "Dest", "ORIGIN_ID", "DSTN_ID")
                       if row.get(c, "").upper() in ids})
    for col in ATTRIB_COLS:
        if col in row and row[col].upper() in ids:
            return [row[col].upper()]
    if strict or base(fname).startswith(STRICT_FILES):
        return []  # row is about something else
    for v in row.values():
        if v.upper() in ids:
            return [v.upper()]
    return []


def airport_ids(zip_path):
    """every airport id in a cycle, from APT_BASE."""
    out = set()
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            if fname.upper() == "APT_BASE.CSV":
                for row in csv.DictReader(io.StringIO(decode(raw), newline="")):
                    a = (row.get("ARPT_ID") or "").strip().upper()
                    if a:
                        out.add(a)
                break
    return out


def load(zip_path, ids, strict=False):
    """return {filename: [(airport, row), ...]} for rows about the given airports."""
    out = defaultdict(list)
    seen = set()
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            up = fname.upper()
            if ("_CHG_RPT" in up or "DATA_STRUCTURE" in up or fname in seen
                    or base(fname).startswith(HIDDEN_FILES)):
                continue
            seen.add(fname)
            reader = csv.DictReader(io.StringIO(decode(raw), newline=""))
            try:
                for row in reader:
                    vals = {(v or "").strip().upper() for v in row.values() if isinstance(v, str)}
                    if not vals & ids:
                        continue
                    clean = {k.strip(): (v or "").strip() for k, v in row.items()
                             if k and k.strip() not in IGNORE_COLS}
                    for apt in attribute(clean, ids, fname, strict):
                        out[fname].append((apt, clean))
            except csv.Error as e:
                print(f"  warning: skipped rest of {fname}: {e}")
    return out
