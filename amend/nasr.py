"""Reading FAA NASR 28-day CSV zips."""
import csv
import io
import math
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


# navaids have no airport column. in all-airports mode they're matched to the public
# airports within NEAR_NM (closest MAX_NEAR), so a decommissioned VOR shows up where it matters.
NEAR_NM = 10
MAX_NEAR = 5


class NearIndex:
    """public airports bucketed on a 0.5 degree grid for fast "what's near this navaid"."""

    def __init__(self, airports):
        self.grid = {}
        for apt, lat, lon in airports:
            self.grid.setdefault((int(lat // 0.5), int(lon // 0.5)), []).append((apt, lat, lon))

    @classmethod
    def from_zip(cls, zip_path):
        pts = []
        with zipfile.ZipFile(zip_path) as zf:
            for fname, raw in iter_csvs(zf):
                if fname.upper() != "APT_BASE.CSV":
                    continue
                for row in csv.DictReader(io.StringIO(decode(raw), newline="")):
                    g = lambda k: (row.get(k) or "").strip().upper()
                    public = (g("FACILITY_USE_CODE") == "PU") if "FACILITY_USE_CODE" in row else bool(g("ICAO_ID"))
                    if g("SITE_TYPE_CODE") not in ("A", "") or not public:
                        continue
                    try:
                        pts.append((g("ARPT_ID"), float(g("LAT_DECIMAL")), float(g("LONG_DECIMAL"))))
                    except ValueError:
                        continue
                break
        return cls(pts)

    def near(self, lat, lon):
        """[(airport, nm), ...] closest first, within NEAR_NM."""
        gy, gx = int(lat // 0.5), int(lon // 0.5)
        hits = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for apt, alat, alon in self.grid.get((gy + dy, gx + dx), []):
                    nm = _nm(lat, lon, alat, alon)
                    if nm <= NEAR_NM:
                        hits.append((nm, apt))
        return [(apt, nm) for nm, apt in sorted(hits)[:MAX_NEAR]]


def _nm(lat1, lon1, lat2, lon2):
    """great-circle distance in nautical miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(math.sqrt(a))


def load(zip_path, ids, strict=False, near=None, proc_airports=None):
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
                    is_route = base(fname) in ("STAR_RTE", "DP_RTE")
                    if not vals & ids and not (near and base(fname).startswith("NAV")) and not is_route:
                        continue
                    clean = {k.strip(): (v or "").strip() for k, v in row.items()
                             if k and k.strip() not in IGNORE_COLS}
                    apts = attribute(clean, ids, fname, strict)
                    if is_route:
                        # route points never name the airport; use the procedure's airport list
                        from .procedures import split_code
                        code = clean.get("STAR_COMPUTER_CODE") or clean.get("DP_COMPUTER_CODE") or ""
                        apts = sorted((proc_airports or {}).get(split_code(code)[0], set()) & ids)
                    if apts:
                        for apt in apts:
                            out[fname].append((apt, clean))
                    elif near and base(fname).startswith("NAV"):
                        try:
                            lat, lon = float(clean["LAT_DECIMAL"]), float(clean["LONG_DECIMAL"])
                        except (KeyError, ValueError):
                            continue
                        for apt, nm in near.near(lat, lon):
                            if apt in ids:
                                out[fname].append((apt, {**clean, "_NEAR_NM": f"{nm:.0f}"}))
            except csv.Error as e:
                print(f"  warning: skipped rest of {fname}: {e}")
    return out