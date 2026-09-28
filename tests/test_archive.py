"""
The raw FAA archive (amend/archive.py): each cycle's files kept unchanged on a GitHub Release.
The rules guarded here: a published release is complete and never changed, a mismatch stops the
run instead of overwriting, and a cycle that's still being posted waits.
run:  python -m unittest tests.test_archive -v
"""
import datetime as dt
import hashlib
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from amend import archive, cycles

UTC = dt.timezone.utc
AT = dt.datetime(2026, 9, 28, 12, tzinfo=UTC)      # 2026-09-03 in effect, 2026-10-01 next
PAST, CUR, NEXT = dt.date(2025, 1, 23), dt.date(2026, 9, 3), dt.date(2026, 10, 1)


class FakeGitHub:
    """in-memory stand-in for archive.GitHub."""

    def __init__(self):
        self.releases, self.blobs, self.calls, self.next_id = [], {}, [], 1
        self.fail_upload = set()   # names whose next upload fails, leaving a half-made asset

    def _id(self):
        self.next_id += 1
        return self.next_id

    def find_release(self, t):
        return next((r for r in self.releases if r["tag_name"] == t), None)

    def create_draft(self, t, name, body):
        r = {"id": self._id(), "tag_name": t, "name": name, "body": body, "draft": True, "assets": []}
        self.releases.append(r)
        self.calls.append(("create", t))
        return r

    def publish(self, release, body):
        release["draft"], release["body"] = False, body
        self.calls.append(("publish", release["tag_name"]))

    def assets(self, release):
        return [dict(a) for a in release["assets"]]

    def delete_asset(self, asset):
        for r in self.releases:
            r["assets"] = [a for a in r["assets"] if a["id"] != asset["id"]]
        self.calls.append(("delete", asset["name"]))

    def add(self, release, name, data, state="uploaded", digest=True):
        a = {"id": self._id(), "name": name, "size": len(data), "state": state}
        if digest:
            a["digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
        self.blobs[a["id"]] = data
        release["assets"].append(a)
        return a

    def upload(self, release, path, name, ctype):
        with open(path, "rb") as f:
            data = f.read()
        if name in self.fail_upload:
            self.fail_upload.discard(name)
            self.add(release, name, data[:3], state="starter")
            raise archive.ArchiveError(f"upload {name}: HTTP 502")
        self.calls.append(("upload", name))
        return self.add(release, name, data)

    def fetch_asset(self, asset, path):
        with open(path, "wb") as f:
            f.write(self.blobs[asset["id"]])

    def manifest(self, t):
        r = self.find_release(t)
        a = next(a for a in r["assets"] if a["name"] == archive.MANIFEST)
        return json.loads(self.blobs[a["id"]])


def content(url):
    """the bytes the fake FAA serves for url."""
    if url.endswith(".zip"):
        from tests.test_pipeline_ops import zip_bytes
        return zip_bytes(extra={"tag.txt": url})
    return f"<?xml version='1.0'?><digital_tpp url='{url}'/>".encode()


class FakeFAA:
    def __init__(self, gone=(), broken=()):
        self.gone, self.broken, self.fetched = set(gone), set(broken), []

    def __call__(self, url, path, required=()):
        self.fetched.append(url)
        if any(g in url for g in self.broken):
            raise cycles.FetchError(f"{url}: HTTP 503")
        if any(g in url for g in self.gone):
            return False
        with open(path, "wb") as f:
            f.write(content(url))
        return True


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.gh, self.log = FakeGitHub(), []

    def run_cycle(self, d, faa=None):
        self.faa = faa or FakeFAA()
        with mock.patch("amend.archive.download", self.faa):
            return archive.archive_cycle(self.gh, d, AT, self.log.append)

    def test_new_cycle_uploads_files_then_manifest_then_publishes(self):
        self.assertEqual(self.run_cycle(CUR), "done")
        r = self.gh.find_release("faa-2026-09-03")
        self.assertFalse(r["draft"])
        ups = [c[1] for c in self.gh.calls if c[0] == "upload"]
        self.assertEqual(ups, ["03_Sep_2026_CSV.zip", "class_airspace_shape_files.zip",
                               "d-tpp_Metafile.xml", "manifest.json"])
        self.assertEqual(self.gh.calls[-1], ("publish", "faa-2026-09-03"))
        man = self.gh.manifest("faa-2026-09-03")
        self.assertEqual((man["cycle"], man["dtpp_cycle"], man["missing"]), ("2026-09-03", "2609", []))
        for f in man["files"]:
            data = content(f["url"])
            self.assertEqual(f["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(f["bytes"], len(data))
            self.assertTrue(f["retrieved_at"].endswith("Z"))
            self.assertNotIn("path", f)

    def test_published_release_is_a_no_op_without_downloading(self):
        self.run_cycle(CUR)
        n = len(self.gh.calls)
        self.assertEqual(self.run_cycle(CUR), "exists")
        self.assertEqual(self.faa.fetched, [])
        self.assertEqual(len(self.gh.calls), n)

    def test_published_release_that_drifted_from_its_manifest_fails(self):
        self.run_cycle(CUR)
        r = self.gh.find_release("faa-2026-09-03")
        a = next(a for a in r["assets"] if a["name"].endswith("CSV.zip"))
        a["digest"] = "sha256:" + "0" * 64
        n = len(self.gh.calls)
        with self.assertRaisesRegex(archive.ArchiveError, "doesn't match its manifest"):
            self.run_cycle(CUR)
        self.assertEqual(len(self.gh.calls), n)   # nothing deleted or re-uploaded

    def test_published_release_missing_an_asset_fails(self):
        self.run_cycle(CUR)
        r = self.gh.find_release("faa-2026-09-03")
        r["assets"] = [a for a in r["assets"] if not a["name"].endswith(".xml")]
        with self.assertRaisesRegex(archive.ArchiveError, "d-tpp_Metafile.xml missing"):
            self.run_cycle(CUR)

    def test_old_cycle_keeps_what_the_faa_still_has(self):
        self.assertEqual(self.run_cycle(PAST, FakeFAA(gone=["d-tpp"])), "done")
        man = self.gh.manifest("faa-2025-01-23")
        self.assertEqual([f["kind"] for f in man["files"]], ["nasr_csv", "class_airspace"])
        self.assertEqual([m["kind"] for m in man["missing"]], ["dtpp_metafile"])
        self.assertIn("dtpp_metafile", self.gh.find_release("faa-2025-01-23")["body"])

    def test_cycle_without_csv_zip_makes_no_release(self):
        self.assertEqual(self.run_cycle(PAST, FakeFAA(gone=["CSV.zip"])), "unavailable")
        self.assertEqual(self.gh.releases, [])

    def test_upcoming_cycle_waits_for_every_file(self):
        self.assertEqual(self.run_cycle(NEXT, FakeFAA(gone=["d-tpp"])), "not-yet")
        self.assertEqual(self.gh.releases, [])
        self.assertEqual(self.run_cycle(NEXT), "done")

    def test_failed_upload_leaves_a_draft_that_the_next_run_finishes(self):
        self.gh.fail_upload.add("class_airspace_shape_files.zip")
        with self.assertRaises(archive.ArchiveError):
            self.run_cycle(CUR)
        r = self.gh.find_release("faa-2026-09-03")
        self.assertTrue(r["draft"])                        # never published half done
        self.assertEqual(self.run_cycle(CUR), "done")
        names = sorted(a["name"] for a in r["assets"])
        self.assertEqual(names, sorted(["03_Sep_2026_CSV.zip", "class_airspace_shape_files.zip",
                                        "d-tpp_Metafile.xml", "manifest.json"]))
        self.assertTrue(all(a["state"] == "uploaded" for a in r["assets"]))
        ups = [c[1] for c in self.gh.calls if c[0] == "upload"]
        self.assertEqual(ups.count("03_Sep_2026_CSV.zip"), 1)   # the good one was kept

    def test_draft_without_digest_is_checked_by_downloading_it(self):
        r = self.gh.create_draft("faa-2026-09-03", "x", "")
        self.gh.add(r, "03_Sep_2026_CSV.zip", content(cycles.csv_url(CUR)), digest=False)
        self.assertEqual(self.run_cycle(CUR), "done")
        ups = [c[1] for c in self.gh.calls if c[0] == "upload"]
        self.assertNotIn("03_Sep_2026_CSV.zip", ups)

    def test_draft_with_a_different_file_is_never_overwritten(self):
        r = self.gh.create_draft("faa-2026-09-03", "x", "")
        self.gh.add(r, "03_Sep_2026_CSV.zip", b"PK an older version")
        with self.assertRaisesRegex(archive.ArchiveError, "differs from what the FAA serves now"):
            self.run_cycle(CUR)
        self.assertNotIn("delete", [c[0] for c in self.gh.calls])
        self.assertTrue(r["draft"])

    def test_draft_holding_a_file_the_faa_dropped_stops(self):
        r = self.gh.create_draft("faa-2025-01-23", "x", "")
        self.gh.add(r, "d-tpp_Metafile.xml", content(cycles.dtpp_url(PAST)))
        with self.assertRaisesRegex(archive.ArchiveError, "no longer serves"):
            self.run_cycle(PAST, FakeFAA(gone=["d-tpp"]))
        self.assertNotIn("delete", [c[0] for c in self.gh.calls])

    def test_one_bad_cycle_doesnt_stop_the_rest(self):
        faa = FakeFAA(broken=["23_Jan_2025"])
        with mock.patch("amend.archive.download", faa):
            failed = archive.run(self.gh, [PAST, CUR], AT, self.log.append)
        self.assertEqual([d for d, _ in failed], [PAST])
        self.assertIsNone(self.gh.find_release("faa-2025-01-23"))
        self.assertFalse(self.gh.find_release("faa-2026-09-03")["draft"])


class CyclesTest(unittest.TestCase):
    def test_default_is_in_effect_and_next(self):
        self.assertEqual(archive.default_cycles(AT), [CUR, NEXT])

    def test_backfill_runs_aug_2024_through_next(self):
        days = archive.backfill_cycles(AT)
        self.assertEqual((days[0], days[-1], len(days)), (dt.date(2024, 8, 8), NEXT, 29))
        self.assertTrue(all(b - a == cycles.CYCLE for a, b in zip(days, days[1:])))

    def test_off_grid_date_is_rejected(self):
        self.assertEqual(archive.parse_cycle("2024-08-08"), dt.date(2024, 8, 8))
        with self.assertRaisesRegex(ValueError, "isn't a cycle date"):
            archive.parse_cycle("2024-08-09")

    def test_tag(self):
        self.assertEqual(archive.tag(CUR), "faa-2026-09-03")


class Resp(io.BytesIO):
    def __init__(self, body=b"", headers=None, status=200):
        super().__init__(body)
        self.headers, self.status = headers or {}, status


class RemoteSizeTest(unittest.TestCase):
    def size(self, handler):
        with mock.patch("amend.archive.urllib.request.urlopen", side_effect=handler):
            return archive.remote_size("https://nfdc.faa.gov/x/03_Sep_2026_CSV.zip")

    def test_head_503_falls_back_to_a_range_read(self):
        # what nfdc.faa.gov's Akamai storage really does (probe run 2026-09-28)
        def fake(req, timeout=None):
            if req.get_method() == "HEAD":
                raise urllib.error.HTTPError(req.full_url, 503, "x", {}, io.BytesIO())
            return Resp(b"PK\x03\x04" + b"\0" * 12, {"Content-Range": "bytes 0-15/23097812"}, 206)
        self.assertEqual(self.size(fake), (True, 23097812))

    def test_gone_and_unknown(self):
        def gone(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO())

        def down(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 503, "x", {}, io.BytesIO())

        def page(req, timeout=None):
            if req.get_method() == "HEAD":
                return Resp(b"", {"Content-Type": "text/html", "Content-Length": "900"})
            return Resp(b"<!doctype html><p>", {"Content-Length": "900"})
        self.assertEqual(self.size(gone), (False, 0))
        self.assertEqual(self.size(down), (None, 0))
        self.assertEqual(self.size(page), (False, 0))


class GitHubClientTest(unittest.TestCase):
    def setUp(self):
        self.gh = archive.GitHub("benjgmin/amend", "tok")
        p = mock.patch("amend.archive.time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_find_release_falls_back_to_drafts(self):
        def fake(req, timeout=None):
            if "/tags/" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO())
            return Resp(json.dumps([{"tag_name": "faa-2026-09-03", "draft": True}]).encode())
        with mock.patch("amend.archive.urllib.request.urlopen", side_effect=fake):
            self.assertTrue(self.gh.find_release("faa-2026-09-03")["draft"])
            self.assertIsNone(self.gh.find_release("faa-2026-10-01"))

    def test_upload_sends_the_file_with_its_length_and_token(self):
        seen = {}

        def fake(req, timeout=None):
            seen["url"], seen["h"] = req.full_url, dict(req.header_items())
            seen["body"] = req.data.read()
            return Resp(b'{"id": 9}')
        path = os.path.join(self.tmp(), "f.zip")
        with open(path, "wb") as f:
            f.write(b"PK1234")
        with mock.patch("amend.archive.urllib.request.urlopen", side_effect=fake):
            self.gh.upload({"id": 5}, path, "03_Sep_2026_CSV.zip", "application/zip")
        self.assertEqual(seen["url"], "https://uploads.github.com/repos/benjgmin/amend/releases/5/"
                                      "assets?name=03_Sep_2026_CSV.zip")
        self.assertEqual(seen["body"], b"PK1234")
        self.assertEqual(seen["h"]["Content-length"], "6")
        self.assertEqual(seen["h"]["Authorization"], "Bearer tok")

    def test_client_errors_are_not_retried(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 422, "bad", {}, io.BytesIO(b"nope"))
        with mock.patch("amend.archive.urllib.request.urlopen", side_effect=fake):
            with self.assertRaisesRegex(archive.ArchiveError, "HTTP 422"):
                self.gh.call("POST", "/repos/x/releases", {})
        self.assertEqual(len(calls), 1)

    def test_server_errors_are_retried(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO())
            return Resp(b'{"ok": true}')
        with mock.patch("amend.archive.urllib.request.urlopen", side_effect=fake):
            self.assertEqual(self.gh.call("GET", "/x"), {"ok": True})

    def test_asset_download_follows_the_redirect_without_the_token(self):
        seen = []

        class Opener:
            def open(self, req, timeout=None):
                seen.append(dict(req.header_items()))
                raise urllib.error.HTTPError(req.full_url, 302, "found",
                                             {"Location": "https://objects.example/x?sig=1"}, None)

        def fake(req, timeout=None):
            seen.append(dict(req.header_items()))
            return Resp(b"{}")
        path = os.path.join(self.tmp(), "m.json")
        with mock.patch("amend.archive.urllib.request.build_opener", return_value=Opener()), \
                mock.patch("amend.archive.urllib.request.urlopen", side_effect=fake):
            self.gh.fetch_asset({"id": 3, "name": "manifest.json"}, path)
        self.assertEqual(seen[0]["Authorization"], "Bearer tok")
        self.assertNotIn("Authorization", seen[1])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"{}")

    def tmp(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        return d


if __name__ == "__main__":
    unittest.main()
