"""The airport directory the app uses for names and search (site/airports.json)."""
import csv
import io
import zipfile

from .nasr import decode, iter_csvs

TYPES = {"A": "airport", "H": "heliport", "S": "seaplane base", "G": "gliderport",
         "U": "ultralight", "B": "balloonport", "C": "gliderport"}


def _num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def directory(zip_path):
    """[{id, icao, name, city, state, type, lat, lon}, ...] from APT_BASE, sorted by id."""
    out = []
    with zipfile.ZipFile(zip_path) as zf:
        for fname, raw in iter_csvs(zf):
            if fname.upper() != "APT_BASE.CSV":
                continue
            for row in csv.DictReader(io.StringIO(decode(raw), newline="")):
                g = lambda k: (row.get(k) or "").strip()
                if not g("ARPT_ID"):
                    continue
                a = {"id": g("ARPT_ID").upper(), "icao": g("ICAO_ID").upper(),
                     "name": g("ARPT_NAME").title(), "city": g("CITY").title(),
                     "state": g("STATE_CODE").upper(),
                     "type": TYPES.get(g("SITE_TYPE_CODE").upper(), "airport"),
                     "lat": _num(g("LAT_DECIMAL")), "lon": _num(g("LONG_DECIMAL"))}
                out.append({k: v for k, v in a.items() if v not in ("", None)})
            break
    return sorted(out, key=lambda a: a["id"])