"""
Keep every raw FAA cycle, unchanged, as assets on one GitHub Release per cycle (tag faa-<cycle>).

The build deletes each cycle's files once they're diffed and the Actions cache only holds the
newest few, so without this nothing can be rebuilt or re-checked once the FAA stops serving a
cycle. The workflow in .github/workflows/archive.yml runs this; it never touches history/ or site/.

  python -m amend archive                      the cycle in effect and the next one
  python -m amend archive 2024-08-08 ...       specific cycles
  python -m amend archive --backfill           every cycle since Aug 2024
  python -m amend archive --list [--backfill]  what the FAA still serves, and how big (downloads nothing)

A release holds each file exactly as the FAA served it, plus manifest.json (source url, bytes,
sha256, retrieved_at per file, and which files the FAA no longer had). It's built as a draft
and published only after manifest.json is up, so a published faa-* release is always complete.
A published release is never changed: if its assets don't match its manifest the run fails,
and a draft left by a failed run is resumed, never overwritten with a different file.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from . import SCHEMA_VERSION
from .cycles import (CSV_REQUIRED, CYCLE, FIRST_ARCHIVED, FetchError, airspace_url, csv_url,
                     cycle_on_or_before, download, dtpp_id, dtpp_url, in_effect)

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
MANIFEST = "manifest.json"
TRIES = 3
WAIT = 10
# (kind, url for a cycle, files a zip must contain). every kind is kept when the FAA has it; only
# the NASR CSV zip is essential, the other two are often gone for old cycles
FILES = (
    ("nasr_csv", csv_url, CSV_REQUIRED),
    ("class_airspace", airspace_url, ()),
    ("dtpp_metafile", dtpp_url, ()),
)


class ArchiveError(Exception):
    """the archive and the FAA (or the archive and its own manifest) disagree. never papered
    over: a person has to look."""


def tag(d):
    return f"faa-{d.isoformat()}"


def _name(url):
    return urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- which cycles

def default_cycles(at=None):
    """the cycle in effect and the next one."""
    cur = in_effect(at)
    return [cur, cur + CYCLE]


def backfill_cycles(at=None):
    """every cycle from the oldest the FAA archive had (Aug 2024) through the next one."""
    out, d = [], FIRST_ARCHIVED
    last = in_effect(at) + CYCLE
    while d <= last:
        out.append(d)
        d += CYCLE
    return out


def parse_cycle(s):
    d = dt.date.fromisoformat(s)
    if cycle_on_or_before(d) != d:
        raise ValueError(f"{s} isn't a cycle date (nearest before it is {cycle_on_or_before(d)})")
    return d


# ---------------------------------------------------------------- GitHub releases

class GitHub:
    """the few Releases API calls the archive needs, with urllib (no dependencies)."""

    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def _call(self, method, url, body=None, headers=None, data=None, length=None):
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "amend-archive", **(headers or {})}
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if length is not None:
            h["Content-Length"] = str(length)
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=600) as r:
            raw = r.read()
        return json.loads(raw) if raw else None

    def call(self, method, path, body=None):
        """an API call, retried on 5xx / timeouts. 404 returns None."""
        last = None
        for attempt in range(1, TRIES + 1):
            try:
                return self._call(method, API + path, body)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code < 500:
                    raise ArchiveError(f"GitHub {method} {path}: HTTP {e.code} {e.read()[:300]!r}")
                last = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
            if attempt < TRIES:
                time.sleep(WAIT * 2 ** (attempt - 1))
        raise ArchiveError(f"GitHub {method} {path}: {last}")

    def find_release(self, t):
        """the release tagged t, drafts included (the tags endpoint doesn't return drafts)."""
        r = self.call("GET", f"/repos/{self.repo}/releases/tags/{t}")
        if r:
            return r
        page = 1
        while True:
            rs = self.call("GET", f"/repos/{self.repo}/releases?per_page=100&page={page}") or []
            for r in rs:
                if r["tag_name"] == t:
                    return r
            if len(rs) < 100:
                return None
            page += 1

    def create_draft(self, t, name, body):
        return self.call("POST", f"/repos/{self.repo}/releases",
                         {"tag_name": t, "name": name, "body": body, "draft": True,
                          "make_latest": "false"})

    def publish(self, release, body):
        return self.call("PATCH", f"/repos/{self.repo}/releases/{release['id']}",
                         {"draft": False, "make_latest": "false", "body": body})

    def assets(self, release):
        out, page = [], 1
        while True:
            a = self.call("GET", f"/repos/{self.repo}/releases/{release['id']}/assets"
                                 f"?per_page=100&page={page}") or []
            out += a
            if len(a) < 100:
                return out
            page += 1

    def delete_asset(self, asset):
        self.call("DELETE", f"/repos/{self.repo}/releases/assets/{asset['id']}")

    def upload(self, release, path, name, ctype):
        """upload one file. a failed try can leave a half-made asset behind, which blocks the
        name, so it's deleted before the next try."""
        url = (f"{UPLOADS}/repos/{self.repo}/releases/{release['id']}/assets?"
               + urllib.parse.urlencode({"name": name}))
        size, last = os.path.getsize(path), None
        for attempt in range(1, TRIES + 1):
            try:
                with open(path, "rb") as f:
                    return self._call("POST", url, headers={"Content-Type": ctype}, data=f,
                                      length=size)
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500 and e.code != 422:
                    raise ArchiveError(f"upload {name}: HTTP {e.code} {e.read()[:300]!r}")
                last = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = f"{type(e).__name__}: {e}"
            print(f"  upload {name} failed ({last})")
            for a in self.assets(release):
                if a["name"] == name and a.get("state") != "uploaded":
                    self.delete_asset(a)
            if attempt < TRIES:
                time.sleep(WAIT * 2 ** (attempt - 1))
        raise ArchiveError(f"upload {name}: {last}")

    def fetch_asset(self, asset, path):
        """download an asset. the API answers with a redirect to signed storage, which must be
        followed without our token."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        req = urllib.request.Request(
            f"{API}/repos/{self.repo}/releases/assets/{asset['id']}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/octet-stream",
                     "User-Agent": "amend-archive"})
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=600)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise ArchiveError(f"download asset {asset['name']}: HTTP {e.code}")
            r = urllib.request.urlopen(urllib.request.Request(
                e.headers["Location"], headers={"User-Agent": "amend-archive"}), timeout=600)
        with r, open(path, "wb") as f:
            shutil.copyfileobj(r, f)


# ---------------------------------------------------------------- archiving

def _uploaded(assets):
    return {a["name"]: a for a in assets if a.get("state", "uploaded") == "uploaded"}


def _digest(asset):
    """sha256 GitHub computed for an asset, when the API reports one."""
    d = asset.get("digest") or ""
    return d.split(":", 1)[1] if d.startswith("sha256:") else None


def check_release(gh, release, tmp):
    """a published release must still match its own manifest. returns the manifest."""
    assets = _uploaded(gh.assets(release))
    if MANIFEST not in assets:
        raise ArchiveError(f"{release['tag_name']} is published but has no {MANIFEST}")
    mpath = os.path.join(tmp, MANIFEST)
    gh.fetch_asset(assets[MANIFEST], mpath)
    with open(mpath, encoding="utf-8") as f:
        man = json.load(f)
    bad = []
    for fi in man["files"]:
        a = assets.get(fi["name"])
        if not a:
            bad.append(f"{fi['name']} missing")
        elif a["size"] != fi["bytes"]:
            bad.append(f"{fi['name']} is {a['size']} bytes, manifest says {fi['bytes']}")
        elif _digest(a) and _digest(a) != fi["sha256"]:
            bad.append(f"{fi['name']} sha256 {_digest(a)} != manifest {fi['sha256']}")
    if bad:
        raise ArchiveError(f"{release['tag_name']} doesn't match its manifest: " + "; ".join(bad))
    return man


def fetch_cycle(d, tmp):
    """download cycle d's files from the FAA into tmp, each through cycles.download (retries,
    HTML-page and truncation checks, zip CRCs, required CSVs). returns (files, missing)."""
    files, missing = [], []
    for kind, url_for, required in FILES:
        url = url_for(d)
        path = os.path.join(tmp, _name(url))
        if download(url, path, required):   # FetchError (can't tell) propagates: stop this cycle
            files.append({"name": _name(url), "kind": kind, "url": url,
                          "bytes": os.path.getsize(path), "sha256": sha256(path),
                          "retrieved_at": now(), "path": path})
        else:
            missing.append({"kind": kind, "url": url, "reason": "the FAA wasn't serving it"})
    return files, missing


def _body(d, files, missing):
    lines = [f"Raw FAA data for the cycle effective {d.isoformat()} (d-TPP cycle {dtpp_id(d)}), "
             "exactly as the FAA served it. Not for navigation.", "",
             f"`{MANIFEST}` lists each file's source URL, size, sha256 and when it was downloaded.",
             "", "| file | from | MB | sha256 |", "|---|---|---|---|"]
    for f in files:
        lines.append(f"| {f['name']} | {f['kind']} | {f['bytes'] / 1e6:.1f} | `{f['sha256'][:16]}…` |")
    for m in missing:
        lines.append(f"| (none) | {m['kind']} | | {m['reason']} when archived |")
    return "\n".join(lines)


def archive_cycle(gh, d, at=None, log=print):
    """archive one cycle. returns "done", "exists", "unavailable" or "not-yet"."""
    t = tag(d)
    rel = gh.find_release(t)
    with tempfile.TemporaryDirectory(prefix="amend-archive-") as tmp:
        if rel and not rel.get("draft"):
            man = check_release(gh, rel, tmp)
            log(f"{d}: already archived ({len(man['files'])} files, matches its manifest)")
            return "exists"

        files, missing = fetch_cycle(d, tmp)
        if not any(f["kind"] == "nasr_csv" for f in files):
            if rel:
                raise ArchiveError(f"{t}: a draft exists but the FAA no longer serves the CSV zip")
            log(f"{d}: the FAA doesn't serve this cycle's CSV zip, nothing to archive")
            return "unavailable"
        if missing and d > in_effect(at):
            # an upcoming cycle's files go up one by one; wait for all of them rather than
            # publishing a release that says one is gone for good
            log(f"{d}: upcoming and not fully posted yet ({', '.join(m['kind'] for m in missing)}), "
                "trying again next run")
            return "not-yet"

        if rel:
            log(f"{d}: resuming an unfinished release")
        else:
            rel = gh.create_draft(t, f"FAA data {d.isoformat()}", _body(d, files, missing))
        have = {a["name"]: a for a in gh.assets(rel)}
        if MANIFEST in have:
            gh.delete_asset(have.pop(MANIFEST))   # a draft's manifest was never published
        extra = sorted(n for n, a in have.items() if a.get("state") == "uploaded"
                       and n not in {f["name"] for f in files})
        if extra:
            raise ArchiveError(f"{t}: the draft has {', '.join(extra)}, which the FAA no longer "
                               "serves; not deleting it, look first")
        for f in files:
            a = have.get(f["name"])
            if a and a.get("state") == "uploaded":
                got = _digest(a)
                if got is None and a["size"] == f["bytes"]:
                    p = os.path.join(tmp, "existing")
                    gh.fetch_asset(a, p)
                    got = sha256(p)
                    os.remove(p)
                if a["size"] != f["bytes"] or got != f["sha256"]:
                    raise ArchiveError(f"{t}: the draft's {f['name']} differs from what the FAA "
                                       "serves now; not replacing it, look at both first")
                log(f"  {f['name']} already uploaded")
                continue
            if a:
                gh.delete_asset(a)   # half-made by a failed upload
            log(f"  uploading {f['name']} ({f['bytes'] / 1e6:.1f} MB)")
            gh.upload(rel, f["path"], f["name"], "application/zip" if f["name"].endswith(".zip")
                      else "application/xml")

        man = {"schema_version": SCHEMA_VERSION, "cycle": d.isoformat(), "dtpp_cycle": dtpp_id(d),
               "archived_at": now(), "commit": os.environ.get("GITHUB_SHA", ""),
               "files": [{k: v for k, v in f.items() if k != "path"} for f in files],
               "missing": missing}
        mpath = os.path.join(tmp, MANIFEST)
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=1)
        gh.upload(rel, mpath, MANIFEST, "application/json")
        gh.publish(rel, _body(d, files, missing))
        log(f"{d}: archived {len(files)} files as {t}" + (f", {len(missing)} gone" if missing else ""))
        return "done"


def run(gh, days, at=None, log=print):
    """archive each cycle; one cycle failing doesn't stop the rest. returns the failures."""
    failed = []
    for d in days:
        try:
            archive_cycle(gh, d, at, log)
        except (ArchiveError, FetchError) as e:
            log(f"{d}: FAILED: {e}")
            failed.append((d, str(e)))
    return failed


# ---------------------------------------------------------------- what the FAA still serves

def remote_size(url):
    """(served?, bytes) without downloading: HEAD, then a 16-byte Range read (nfdc.faa.gov's
    Akamai storage answers every HEAD with 503). served is None when we couldn't tell."""
    for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-15"})):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "amend", **extra})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                size = r.headers.get("Content-Length")
                rng = r.headers.get("Content-Range") or ""
                if "/" in rng:
                    size = rng.rsplit("/", 1)[1]
                if method == "HEAD":
                    if "html" in (r.headers.get("Content-Type") or "") or not (size or "").isdigit():
                        continue
                    return True, int(size)
                head = r.read(16).lstrip(b"\xef\xbb\xbf \t\r\n")
                ok = head.startswith(b"PK") if url.endswith(".zip") else (
                    head.startswith(b"<") and not head.lower().startswith((b"<!doctype", b"<html")))
                return ok, int(size) if ok and (size or "").isdigit() else 0
        except urllib.error.HTTPError as e:
            if method == "HEAD":
                continue
            return (False, 0) if e.code in (403, 404, 410) else (None, 0)
        except Exception:
            if method == "HEAD":
                continue
            return None, 0
    return None, 0


def availability(days, log=print):
    """print what the FAA serves for each cycle, and the total size. returns the rows."""
    rows, total = [], 0
    log("| cycle | " + " | ".join(k for k, _, _ in FILES) + " | MB |")
    log("|---|" + "---|" * len(FILES) + "---|")
    for d in days:
        cells, mb = [], 0
        for kind, url_for, _ in FILES:
            ok, size = remote_size(url_for(d))
            cells.append({True: f"{size / 1e6:.1f} MB", False: "gone", None: "?"}[ok])
            mb += size if ok else 0
        total += mb
        rows.append((d, cells, mb))
        log(f"| {d} | " + " | ".join(cells) + f" | {mb / 1e6:.1f} |")
    log(f"\n{sum(1 for _, c, _ in rows if c[0] not in ('gone', '?'))} of {len(rows)} cycles still "
        f"have their CSV zip; {total / 1e9:.2f} GB to archive everything that's served")
    return rows


def main(a):
    days = ([parse_cycle(c) for c in a.cycles] if a.cycles
            else backfill_cycles() if a.backfill else default_cycles())
    if a.list:
        availability(days)
        return
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        sys.exit("archive needs GITHUB_REPOSITORY (owner/name) and GITHUB_TOKEN with contents: write")
    failed = run(GitHub(repo, token), days)
    if failed:
        sys.exit(f"{len(failed)} cycle(s) not archived: " + ", ".join(str(d) for d, _ in failed))
