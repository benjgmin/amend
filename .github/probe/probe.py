"""temporary: which FAA cycles are still served, and how big. HEAD / tiny Range reads only."""
import datetime as dt
import urllib.error
import urllib.request

from amend import cycles


def info(url):
    for method, hdrs in (("HEAD", {}), ("GET", {"Range": "bytes=0-15"})):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "amend", **hdrs})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                head = r.read(16) if method == "GET" else b""
                size = r.headers.get("Content-Length")
                cr = r.headers.get("Content-Range")
                if cr and "/" in cr:
                    size = cr.split("/")[-1]
                lm = r.headers.get("Last-Modified", "")
                ctype = r.headers.get("Content-Type", "")
                if method == "HEAD" and (not size or "html" in ctype):
                    continue
                if method == "GET" and not head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith((b"PK", b"<?xml", b"<d", b"<D")):
                    return f"{r.status} not-file {ctype} {head[:12]!r}", 0, lm
                return str(r.status), int(size or 0), lm
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405):
                continue
            return str(e.code), 0, ""
        except Exception as e:
            return f"ERR {type(e).__name__}: {e}", 0, ""
    return "?", 0, ""


d = dt.date(2022, 1, 27)
last = cycles.in_effect() + 2 * cycles.CYCLE
tot = {"csv": 0, "airspace": 0, "dtpp": 0}
print("| cycle | csv | csv MB | airspace | airspace MB | d-TPP | d-TPP MB | csv last-modified |")
print("|---|---|---|---|---|---|---|---|")
while d <= last:
    row = [d.isoformat()]
    lms = ""
    for k, u in (("csv", cycles.csv_url(d)), ("airspace", cycles.airspace_url(d)), ("dtpp", cycles.dtpp_url(d))):
        st, size, lm = info(u)
        if k == "csv":
            lms = lm
        if st in ("200", "206") and d >= cycles.FIRST_ARCHIVED:
            tot[k] += size
        row += [st, f"{size / 1e6:.1f}" if size else ""]
    row.append(lms)
    print("| " + " | ".join(row) + " |", flush=True)
    d += cycles.CYCLE
print()
print("totals since 2024-08-08 (MB):", {k: round(v / 1e6, 1) for k, v in tot.items()},
      "sum", round(sum(tot.values()) / 1e6, 1))
print("sample urls:", cycles.csv_url(dt.date(2024, 8, 8)), cycles.airspace_url(dt.date(2024, 8, 8)),
      cycles.dtpp_url(dt.date(2024, 8, 8)))
