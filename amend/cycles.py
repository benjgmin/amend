"""FAA 28-day cycle math, download URLs, and downloading."""
import datetime as dt
import os
import shutil
import urllib.error
import urllib.request
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


def zip_path(d):
    return os.path.join(DATA, f"{d.isoformat()}_CSV.zip")


def dtpp_path(d):
    return os.path.join(DATA, f"dtpp_{dtpp_id(d)}.xml")


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


def download(url, path):
    """download url to path unless it's already there. True if we have the file."""
    if looks_valid(path):
        return True
    if os.path.exists(path):
        print(f"  {path} is corrupt, downloading again")
        os.remove(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(f"downloading {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "amend"})
        with urllib.request.urlopen(req, timeout=300) as r, open(path + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        if not looks_valid(path + ".part", path):
            raise ValueError("not a valid zip/xml (error page?)")
        os.replace(path + ".part", path)
        return True
    except urllib.error.HTTPError as e:
        print(f"  not available ({e.code})")
    except Exception as e:
        print(f"  failed: {e}")
    if os.path.exists(path + ".part"):
        os.remove(path + ".part")
    return False


def get_cycle(d):
    return download(csv_url(d), zip_path(d))


def get_dtpp(d):
    """path to the d-TPP metafile for cycle d, or None (the FAA doesn't keep old ones)."""
    p = dtpp_path(d)
    return p if download(dtpp_url(d), p) else None
