"""temporary: why does nfdc.faa.gov answer 503? try variations on a few cycles."""
import sys
import urllib.error
import urllib.request
sys.path.insert(0, ".")
import datetime as dt
from amend import cycles

UAS = {"amend": "amend", "browser": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def try_(url, method, ua, rng):
    h = {"User-Agent": UAS[ua]}
    if rng:
        h["Range"] = "bytes=0-15"
    req = urllib.request.Request(url, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read(16) if method == "GET" else b""
            return f"{r.status} len={r.headers.get('Content-Length')} range={r.headers.get('Content-Range')} lm={r.headers.get('Last-Modified')} head={b[:4]!r}"
    except urllib.error.HTTPError as e:
        body = e.read(300)
        return f"{e.code} server={e.headers.get('Server')} retry={e.headers.get('Retry-After')} body={body[:200]!r}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


for d in (dt.date(2026, 9, 3), dt.date(2024, 8, 8)):
    for url in (cycles.csv_url(d), cycles.airspace_url(d)):
        for method, ua, rng in (("HEAD", "amend", False), ("GET", "amend", True), ("GET", "amend", False),
                                ("GET", "browser", False), ("HEAD", "browser", False)):
            print(d, url.rsplit('/', 2)[-2:], method, ua, "range" if rng else "", "->", try_(url, method, ua, rng), flush=True)
for url in ("https://nfdc.faa.gov/", "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"):
    print(url, try_(url, "GET", "browser", False))
