"""
FAA class airspace shapefiles: floors, ceilings and boundaries of class B, C, D and E surface areas.

The NASR CSVs only say which class an airport has and its hours (CLS_ARSP). What the airspace
looks like (a class B shelf dropping from 3,000 to 2,500, a class D ceiling going up, a small
field ending up inside a new surface area) only exists in the shapefile, so it's read here.

Every change is described from an airport's point of view:
  - at the field: which layers sit over the airport's reference point, old vs new
    ("Orlando class B over the field: 3,000-10,000 ft MSL -> 2,500-10,000 ft MSL")
  - for the airport the airspace belongs to: shelves added or removed, and boundaries that moved
    even where they don't cover the field itself
Re-digitized boundaries (vertices moved, same shape) are noise and dropped.
Class E5 (700/1,200 ft floors) is skipped: it's everywhere and rarely changes how you fly.
"""
import io
import math
import struct
import zipfile
from collections import defaultdict

# LOCAL_TYPE values we read; everything else (CLASS_E5, ...) is skipped
TYPES = {"CLASS_B": "B", "CLASS_C": "C", "CLASS_D": "D",
         "CLASS_E2": "E surface", "CLASS_E3": "E extension", "CLASS_E4": "E extension"}
# a boundary counts as moved when the area changes this much or the centroid shifts this far
AREA_PCT = 0.02
SHIFT_NM = 0.2


# ---- reading shapefiles (standard library only) ----

def _find(zf, ext):
    """(name, bytes) of the class airspace .shp or .dbf in a zip, recursing into nested zips."""
    for name in zf.namelist():
        low = name.lower()
        if low.endswith(ext) and "class_airspace" in low.split("/")[-1]:
            return name, zf.read(name)
    for name in zf.namelist():
        if name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as inner:
                hit = _find(inner, ext)
                if hit:
                    return hit
    return None


def read_dbf(raw):
    """dBase III table -> [{field: str}, ...] (deleted records kept as None to stay aligned with .shp)."""
    n, hdr_len, rec_len = struct.unpack("<IHH", raw[4:12])
    fields, pos = [], 32
    while raw[pos] != 0x0D:
        name = raw[pos:pos + 11].split(b"\0")[0].decode("latin-1").strip().upper()
        fields.append((name, raw[pos + 16]))
        pos += 32
    out = []
    for i in range(n):
        rec = raw[hdr_len + i * rec_len: hdr_len + (i + 1) * rec_len]
        if not rec or rec[:1] == b"*":
            out.append(None)
            continue
        row, p = {}, 1
        for name, width in fields:
            row[name] = rec[p:p + width].decode("latin-1").strip()
            p += width
        out.append(row)
    return out


def read_shp(raw):
    """polygon shapefile -> [[ring, ...], ...], each ring a list of (lon, lat). non-polygons -> []."""
    out, pos = [], 100
    while pos + 8 <= len(raw):
        _, words = struct.unpack(">ii", raw[pos:pos + 8])
        body = raw[pos + 8: pos + 8 + words * 2]
        pos += 8 + words * 2
        stype = struct.unpack("<i", body[:4])[0] if len(body) >= 4 else 0
        if stype not in (5, 15, 25):          # polygon, polygonZ, polygonM
            out.append([])
            continue
        nparts, npts = struct.unpack("<ii", body[36:44])
        parts = list(struct.unpack(f"<{nparts}i", body[44:44 + 4 * nparts])) + [npts]
        base = 44 + 4 * nparts
        pts = [struct.unpack("<2d", body[base + 16 * i: base + 16 * i + 16]) for i in range(npts)]
        out.append([pts[parts[i]:parts[i + 1]] for i in range(nparts)])
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def altitude(val, code, uom=""):
    """'2500','MSL' -> '2,500 ft MSL'; 0/SFC -> 'SFC'; flight levels; negative = up to class A."""
    v, code, uom = _num(val), (code or "").upper(), (uom or "").upper()
    if code == "SFC" or (v == 0 and code in ("", "AGL", "SFC")):
        return "SFC"
    if v is None:
        return (val or "?").strip() or "?"
    if v < 0:
        return "class A"
    if uom == "FL" or code == "STD":
        return f"FL{int(v):03d}"
    return f"{int(v):,} ft {code or 'MSL'}".strip()


def layer(row):
    lo = altitude(row.get("LOWER_VAL"), row.get("LOWER_CODE"), row.get("LOWER_UOM"))
    hi = altitude(row.get("UPPER_VAL"), row.get("UPPER_CODE"), row.get("UPPER_UOM"))
    unit = lo.partition(" ")[2]
    if unit and hi.endswith(" " + unit):      # '3,000 ft MSL-10,000 ft MSL' -> '3,000-10,000 ft MSL'
        lo = lo.partition(" ")[0]
    return f"{lo}-{hi}"


def load(zip_path):
    """{(name, local_type): {"cls", "idents", "pieces": [(layer, rings, bbox)]}} from a shapefile zip,
    or None if the zip has no class airspace shapefile."""
    with zipfile.ZipFile(zip_path) as zf:
        shp, dbf = _find(zf, ".shp"), _find(zf, ".dbf")
    if not (shp and dbf):
        return None
    rows, shapes = read_dbf(dbf[1]), read_shp(shp[1])
    out = {}
    for row, rings in zip(rows, shapes):
        if not row or not rings:
            continue
        ltype = (row.get("LOCAL_TYPE") or "").upper().replace(" ", "_")
        if ltype not in TYPES:
            continue
        key = ((row.get("NAME") or "").upper(), ltype)
        a = out.setdefault(key, {"cls": TYPES[ltype], "idents": set(), "pieces": []})
        for k in ("IDENT", "ICAO_ID"):
            v = (row.get(k) or "").upper()
            if v:
                a["idents"].add(v)
                if len(v) == 4 and v.startswith("K"):
                    a["idents"].add(v[1:])
        pts = [p for r in rings for p in r]
        bbox = (min(p[1] for p in pts), min(p[0] for p in pts), max(p[1] for p in pts), max(p[0] for p in pts))
        a["pieces"].append((layer(row), rings, bbox))
    return out


# ---- geometry, in nautical miles on a local flat projection ----

def contains(rings, lat, lon):
    """even-odd point in polygon over every ring (so holes work)."""
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            (xi, yi), (xj, yj) = ring[i], ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def footprint(pieces):
    """(area sq NM, centroid lat, centroid lon) of a set of pieces."""
    area = cy = cx = 0.0
    for _, rings, _ in pieces:
        for ring in rings:
            if len(ring) < 3:
                continue
            k = math.cos(math.radians(ring[0][1])) * 60
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                c = (x1 * k) * (y2 * 60) - (x2 * k) * (y1 * 60)
                area += c
                cx += (x1 + x2) * c
                cy += (y1 + y2) * c
    if not area:
        return 0.0, 0.0, 0.0
    return abs(area) / 2, cy / (3 * area), cx / (3 * area)


def moved(old_pieces, new_pieces):
    a0, y0, x0 = footprint(old_pieces)
    a1, y1, x1 = footprint(new_pieces)
    shift = math.hypot((y1 - y0) * 60, (x1 - x0) * 60 * math.cos(math.radians(y0)))
    return abs(a1 - a0) > AREA_PCT * max(a0, a1) or shift > SHIFT_NM


def layers_at(a, lat, lon):
    """sorted layers of airspace a over a point, e.g. ['SFC-2,500 ft MSL']."""
    return sorted({lyr for lyr, rings, (s, w, n, e) in a["pieces"]
                   if s <= lat <= n and w <= lon <= e and contains(rings, lat, lon)})


# ---- the diff ----

def title(name, cls):
    """'ORLANDO CLASS B' -> 'Orlando class B'"""
    words = [w for w in name.title().split() if w.upper() not in ("CLASS", "AIRSPACE", "B", "C", "D", "E",
                                                                   "E2", "E3", "E4", "SURFACE", "AREA")]
    return f"{' '.join(words)} class {cls}".strip()


def diff(old, new, near, ids):
    """change records ({airport, priority, kind, source, summary}) for airports in ids.
    near: nasr.NearIndex of public airports (for 'what's under this airspace')."""
    out = []
    for key in sorted(set(old) | set(new)):
        a0, a1 = old.get(key), new.get(key)
        cls = (a1 or a0)["cls"]
        name = title(key[0], cls)
        owners = ((a0 or {}).get("idents", set()) | (a1 or {}).get("idents", set())) & ids
        said = set()

        # the airports under it: what's over the field now vs before
        boxes = [b for a in (a0, a1) if a for _, _, b in a["pieces"]]
        s, w = min(b[0] for b in boxes), min(b[1] for b in boxes)
        n, e = max(b[2] for b in boxes), max(b[3] for b in boxes)
        for apt, lat, lon in near.in_box(s, w, n, e):
            if apt not in ids:
                continue
            was = layers_at(a0, lat, lon) if a0 else []
            now = layers_at(a1, lat, lon) if a1 else []
            if was == now:
                continue
            who = f"class {cls}" if apt in owners else name
            if not was:
                text = f"now under {who}: {', '.join(now)}"
                kind = "added"
            elif not now:
                text = f"no longer under {who} (was {', '.join(was)})"
                kind = "removed"
            else:
                text = f"{who} over the field: {', '.join(was)} -> {', '.join(now)}"
                kind = "changed"
            out.append(_rec(apt, kind, text))
            said.add(apt)

        # the airport it belongs to: shelves and boundaries, even away from the field
        for apt in sorted(owners - said):
            if not a0:
                out.append(_rec(apt, "added", f"new class {cls} airspace"))
            elif not a1:
                out.append(_rec(apt, "removed", f"class {cls} airspace removed"))
            else:
                l0 = {lyr for lyr, _, _ in a0["pieces"]}
                l1 = {lyr for lyr, _, _ in a1["pieces"]}
                bits = []
                if l1 - l0:
                    bits.append("new " + ", ".join(sorted(l1 - l0)))
                if l0 - l1:
                    bits.append("removed " + ", ".join(sorted(l0 - l1)))
                redrawn = sorted(lyr for lyr in l0 & l1 if moved(
                    [p for p in a0["pieces"] if p[0] == lyr], [p for p in a1["pieces"] if p[0] == lyr]))
                if redrawn:
                    bits.append("boundary moved (" + ", ".join(redrawn) + ")")
                if bits:
                    out.append(_rec(apt, "changed", f"class {cls} airspace: " + "; ".join(bits)))
    return out


def _rec(apt, kind, summary):
    return {"airport": apt, "priority": "action", "kind": kind, "source": "CLS_ARSP_SHP",
            "summary": summary}
