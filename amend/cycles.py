"""FAA 28-day cycle math, download URLs, and downloading."""
import datetime as dt
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ANCHOR = dt.date(2026, 9, 3)       # a known NASR / d-TPP effective date
CYCLE = dt.timedelta(days=28)
FIRST_ARCHIVED = dt.date(2024, 8, 8)  # oldest cycle in the FAA NASR archive
DATA = "data"


def cycle_on_or_before(day):
    return ANCHOR + ((day - ANCHOR).days // 28) * CYCLE


def csv_url(d):
    return f"https://nfdc.faa.gov/webContent/28DaySub/extra/{d.day:02d}_{d.strftime('%b')}_{d.year}_CSV.zip"


def dtpp_id(d):
    """d-TPP cycle id, e.g. 2610 = 10th 28-day cycle of 2026."""
    n, x = 1, d
    while (x - CYCLE).year == d.year:
        x -= CYCLE
        n += 1
    return f"{d.year % 100:02d}{n:02d}"


def dtpp_url(d):
    return f"https://aeronav.faa.gov/d-tpp/{dtpp_id(d)}/xml_data/d-tpp_Metafile.xml"


def airspace_url(d):
    """class airspace shapefiles, published with each NASR cycle (not in the CSV zip)."""
    return f"https://nfdc.faa.gov/webContent/28DaySub/{d.isoformat()}/class_airspace_shape_files.zip"


def zip_path(d):
    return os.path.join(DATA, f"{d.isoformat()}_CSV.zip")


def dtpp_path(d):
    return os.path.join(DATA, f"dtpp_{dtpp_id(d)}.xml")


def airspace_path(d):
    return os.path.join(DATA, f"{d.isoformat()}_airspace.zip")


EFFECTIVE = dt.timedelta(hours=9, minutes=1)   # cycles change over at 0901Z
MISSING = (403, 404, 410)   # the FAA hasn't posted it (or no longer keeps it)
TRIES = 3                   # attempts per file before a run gives up
TIMEOUT = 60                # seconds of silence before a download counts as stalled
WAIT = 10                   # seconds before the first retry; doubles each time
# a CSV zip without these can't be diffed: every row in the missing file would read as removed
CSV_REQUIRED = ("APT_BASE.csv", "APT_RWY.csv", "APT_RWY_END.csv", "APT_RMK.csv", "FRQ.csv",
                "NAV_BASE.csv", "ATC_BASE.csv")


class FetchError(Exception):
    """a download that failed for a reason other than the FAA not having the file (timeouts,
    5xx, truncated or corrupt files). the run must stop: guessing "not posted" here would
    publish the wrong cycle or a diff with holes in it."""


def in_effect(now=None):
    """the cycle pilots are flying on right now (UTC, 0901Z changeover)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return cycle_on_or_before((now - EFFECTIVE).date())


def looks_valid(path, name=None):
    """a real zip / XML, not an error page served with a 200. a bad file would otherwise
    sit in the Actions cache and break every run after it."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    if (name or path).lower().endswith(".zip"):
        return zipfile.is_zipfile(path)
    with open(path, "rb") as f:
        head = f.read(512).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") and not head.startswith((b"<!doctype html", b"<html"))


def _is_html(path):
    with open(path, "rb") as f:
        head = f.read(512).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<!doctype html", b"<html"))


def _zip_names(zf):
    """every file name in a zip, recursing into nested zips, after checking every CRC.
    raises on a corrupt member."""
    bad = zf.testzip()
    if bad:
        raise ValueError(f"corrupt member {bad}")
    names = []
    for n in zf.namelist():
        names.append(n.split("/")[-1])
        if n.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(n))) as inner:
                names += _zip_names(inner)
    return names


def check_file(path, name=None, required=()):
    """full check of a fresh download, before it's allowed into data/ (and the Actions cache).
    raises ValueError saying what's wrong."""
    name = (name or path).lower()
    if name.endswith(".zip"):
        if not zipfile.is_zipfile(path):
            raise ValueError("not a zip (truncated?)")
        with zipfile.ZipFile(path) as zf:
            names = {n.upper() for n in _zip_names(zf)}
        missing = [r for r in required if r.upper() not in names]
        if missing:
            raise ValueError(f"missing {', '.join(missing)}")
    else:
        root = None
        for event, el in ET.iterparse(path, events=("start", "end")):   # ParseError if truncated
            if root is None:
                root = el.tag
            if event == "end":
                el.clear()
        if root is None:
            raise ValueError("empty XML")


def _open(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "amend"})
    return urllib.request.urlopen(req, timeout=timeout)


def meta_path(path):
    """where download() records how a file was fetched: url, time, size, sha256, FAA headers.
    the run log reads it; a file kept in the Actions cache keeps its first retrieval time."""
    return path + ".json"


def download(url, path, required=()):
    """download url to path unless it's already there.
    True: we have it. False: the FAA hasn't posted it (404/403/410, or an HTML page instead
    of the file). raises FetchError when it can't tell, after TRIES attempts."""
    if looks_valid(path):
        return True
    if os.path.exists(path):
        print(f"  {path} is corrupt, downloading again")
        os.remove(path)
    if os.path.exists(meta_path(path)):
        os.remove(meta_path(path))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    part, last = path + ".part", None
    for attempt in range(1, TRIES + 1):
        print(f"downloading {url}" + (f" (try {attempt}/{TRIES})" if attempt > 1 else ""))
        try:
            sha = hashlib.sha256()
            with _open(url, TIMEOUT) as r, open(part, "wb") as f:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    sha.update(chunk)
                    f.write(chunk)
                want = r.headers.get("Content-Length")
                headers = {k: r.headers.get(h) for k, h in (("last_modified", "Last-Modified"),
                                                            ("etag", "ETag"))}
            got = os.path.getsize(part)
            if want and want.isdigit() and int(want) != got:
                raise ValueError(f"got {got} of {want} bytes")
            if _is_html(part):
                print("  not available (got a web page instead of the file)")
                os.remove(part)
                return False
            check_file(part, path, required)
            os.replace(part, path)
            with open(meta_path(path), "w") as f:
                json.dump({"url": url, "bytes": got, "sha256": sha.hexdigest(),
                           "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                           **headers}, f, indent=1)
            return True
        except urllib.error.HTTPError as e:
            if e.code in MISSING:
                print(f"  not available ({e.code})")
                if os.path.exists(part):
                    os.remove(part)
                return False
            last = f"HTTP {e.code}"
        except Exception as e:   # timeouts, resets, truncated or corrupt files
            last = f"{type(e).__name__}: {e}"
        print(f"  failed: {last}")
        if os.path.exists(part):
            os.remove(part)
        if attempt < TRIES:
            time.sleep(WAIT * 2 ** (attempt - 1))
    raise FetchError(f"{url}: {last}")


def probe(url):
    """is url posted? True / False, or None if we couldn't tell. reads a few bytes, not the file."""
    req = urllib.request.Request(url, headers={"User-Agent": "amend", "Range": "bytes=0-15"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(16).lstrip(b"\xef\xbb\xbf \t\r\n")
    except urllib.error.HTTPError as e:
        return False if e.code in MISSING else None
    except Exception:
        return None
    if url.lower().endswith(".zip"):
        return head.startswith(b"PK")
    return head.startswith(b"<") and not head.lower().startswith((b"<!doctype", b"<html"))


def get_cycle(d):
    return download(csv_url(d), zip_path(d), CSV_REQUIRED)


def get_dtpp(d):
    """path to the d-TPP metafile for cycle d, or None (the FAA doesn't keep old ones)."""
    p = dtpp_path(d)
    return p if download(dtpp_url(d), p) else None


def get_airspace(d):
    """path to cycle d's class airspace shapefile zip, or None."""
    p = airspace_path(d)
    return p if download(airspace_url(d), p) else None


def get_airspace_pair(old, new):
    """(old, new) shapefile zips for pipeline.run(airspace=...), or None if either is missing."""
    pair = (get_airspace(old), get_airspace(new))
    return pair if all(pair) else None
