"""
Fetching, scheduling and publishing: what a run does when the FAA is slow, flaky, late or
serves something broken. The rule every test here guards: when in doubt, don't publish.
run:  python -m unittest tests.test_pipeline_ops -v
"""
import datetime as dt
import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

from amend import cycles, freshness

UTC = dt.timezone.utc
REQ = cycles.CSV_REQUIRED


def zip_bytes(names=REQ, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, "ARPT_ID\rVRB\r")
        for n, b in (extra or {}).items():
            z.writestr(n, b)
    return buf.getvalue()


class Resp:
    """enough of an HTTP response for shutil.copyfileobj and cycles.download."""

    def __init__(self, body, length=None):
        self.f, self.headers = io.BytesIO(body), {}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def read(self, n=-1):
        return self.f.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("https://faa", code, "x", {}, None)


class FetchCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.calls = 0
        p = mock.patch("amend.cycles.time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def serve(self, *answers):
        """each call to the FAA gets the next answer: bytes, (bytes, content-length) or an exception."""
        answers = list(answers)

        def fake(url, timeout):
            self.calls += 1
            a = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(a, Exception):
                raise a
            body, length = a if isinstance(a, tuple) else (a, len(a))
            return Resp(body, length)
        p = mock.patch("amend.cycles._open", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)

    def path(self, name="2026-10-01_CSV.zip"):
        return os.path.join(self.dir, name)


class TestDownload(FetchCase):
    def test_good_zip(self):
        self.serve(zip_bytes())
        self.assertTrue(cycles.download("u", self.path(), REQ))
        self.assertTrue(zipfile.is_zipfile(self.path()))

    def test_404_means_not_posted_and_is_not_retried(self):
        self.serve(http_error(404))
        self.assertFalse(cycles.download("u", self.path(), REQ))
        self.assertEqual(self.calls, 1)

    def test_error_page_with_a_200_means_not_posted(self):
        self.serve(b"<!DOCTYPE html><html><body>File not found</body></html>")
        self.assertFalse(cycles.download("u", self.path(), REQ))
        self.assertFalse(os.path.exists(self.path()))

    def test_timeout_then_success_is_retried(self):
        self.serve(socket.timeout("timed out"), urllib.error.URLError("reset"), zip_bytes())
        self.assertTrue(cycles.download("u", self.path(), REQ))
        self.assertEqual(self.calls, 3)

    def test_server_errors_raise_instead_of_looking_unposted(self):
        """a 503 is not "the FAA hasn't posted it": saying False here would flip the site
        from the upcoming preview back to the current cycle, or skip a cycle in history."""
        self.serve(http_error(503))
        with self.assertRaises(cycles.FetchError):
            cycles.download("u", self.path(), REQ)
        self.assertEqual(self.calls, cycles.TRIES)
        self.assertEqual(os.listdir(self.dir), [])

    def test_truncated_download_never_lands(self):
        good = zip_bytes()
        self.serve((good[: len(good) // 2], len(good)))
        with self.assertRaises(cycles.FetchError):
            cycles.download("u", self.path(), REQ)
        self.assertEqual(os.listdir(self.dir), [])   # no .part, nothing for the cache to keep

    def test_corrupt_member_is_caught(self):
        """the zip index is fine but a file inside is garbled: only a CRC check sees it."""
        buf = io.BytesIO(zip_bytes())
        with zipfile.ZipFile(buf, "a", zipfile.ZIP_STORED) as z:
            z.writestr("BIG.csv", "A,B\r" + "x" * 5000)
        good = bytearray(buf.getvalue())
        i = good.index(b"BIG.csv") + len(b"BIG.csv") + 50   # inside the stored file's bytes
        good[i:i + 20] = b"\0" * 20
        self.serve(bytes(good))
        with self.assertRaises(cycles.FetchError):
            cycles.download("u", self.path(), REQ)

    def test_zip_missing_a_core_file_is_refused(self):
        """a NASR zip without FRQ.csv would diff as every frequency in the country removed."""
        self.serve(zip_bytes([n for n in REQ if n != "FRQ.csv"]))
        with self.assertRaisesRegex(cycles.FetchError, "missing FRQ.csv"):
            cycles.download("u", self.path(), REQ)

    def test_core_files_inside_nested_zips_count(self):
        inner = zip_bytes()
        self.serve(zip_bytes([], extra={"CSV_Data/APT_CSV.zip": inner}))
        self.assertTrue(cycles.download("u", self.path(), REQ))

    def test_truncated_xml_is_refused(self):
        self.serve(b'<?xml version="1.0"?><digital_tpp cycle="2610"><state_code><city_name>')
        with self.assertRaises(cycles.FetchError):
            cycles.download("u", self.path("dtpp_2610.xml"))

    def test_good_xml(self):
        self.serve(b'<?xml version="1.0"?><digital_tpp cycle="2610"><record/></digital_tpp>')
        self.assertTrue(cycles.download("u", self.path("dtpp_2610.xml")))

    def test_cached_file_skips_the_network(self):
        with open(self.path(), "wb") as f:
            f.write(zip_bytes())
        self.serve(http_error(500))
        self.assertTrue(cycles.download("u", self.path(), REQ))
        self.assertEqual(self.calls, 0)


class TestProbe(unittest.TestCase):
    def probe(self, answer, url="https://faa/x.zip"):
        def fake(req, timeout):
            if isinstance(answer, Exception):
                raise answer
            return Resp(answer)
        with mock.patch("amend.cycles.urllib.request.urlopen", side_effect=fake):
            return cycles.probe(url)

    def test_answers(self):
        self.assertTrue(self.probe(b"PK\x03\x04rest"))
        self.assertFalse(self.probe(http_error(404)))
        self.assertFalse(self.probe(b"<!DOCTYPE html>"))
        self.assertIsNone(self.probe(http_error(500)))
        self.assertIsNone(self.probe(socket.timeout()))
        self.assertTrue(self.probe(b'<?xml version="1.0"?>', "https://faa/d-tpp_Metafile.xml"))


class TestCycleMath(unittest.TestCase):
    def test_changeover_is_0901z_not_midnight(self):
        self.assertEqual(cycles.in_effect(dt.datetime(2026, 10, 1, 9, 0, tzinfo=UTC)), dt.date(2026, 9, 3))
        self.assertEqual(cycles.in_effect(dt.datetime(2026, 10, 1, 9, 1, tzinfo=UTC)), dt.date(2026, 10, 1))
        self.assertEqual(cycles.in_effect(dt.datetime(2026, 10, 28, 23, 0, tzinfo=UTC)), dt.date(2026, 10, 1))


NOW = dt.datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
HIST = ["2026-08-06", "2026-09-03"]


def live(to="2026-10-01", upcoming=True, charts=True, airspace=True, hours_ago=3):
    frm = (dt.date.fromisoformat(to) - cycles.CYCLE).isoformat()
    return {"from_cycle": frm, "to_cycle": to, "upcoming": upcoming, "includes_charts": charts,
            "includes_airspace": airspace,
            "generated": (NOW - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")}


def faa(posted=("2026-10-01",), unknown=()):
    """posted(url) for the FAA having these cycles' files up."""
    def f(url):
        if any(c in url or cycles.dtpp_id(dt.date.fromisoformat(c)) in url for c in unknown):
            return None
        return any(k in url for c in posted for k in (
            c, dt.date.fromisoformat(c).strftime("%d_%b_%Y"), cycles.dtpp_id(dt.date.fromisoformat(c))))
    return f


class TestCheck(unittest.TestCase):
    def decide(self, meta=None, build=None, posted=None, now=NOW, hist=HIST):
        return freshness.decide(now, live() if meta is None else meta,
                                {"inputs": "abc"} if build is None else build,
                                "abc", hist, posted or faa())

    def test_nothing_new(self):
        self.assertEqual(self.decide(), [])

    def test_next_cycle_just_posted(self):
        why = self.decide(meta=live("2026-09-03", upcoming=False))
        self.assertTrue(any("FAA has 2026-10-01 (upcoming)" in w for w in why), why)

    def test_cant_reach_faa_builds(self):
        self.assertTrue(self.decide(posted=faa((), unknown=("2026-10-01",))))

    def test_merge_not_live_yet(self):
        self.assertEqual(self.decide(build={"inputs": "old"}), ["the repo changed since the last deploy"])

    def test_no_build_record_builds(self):
        self.assertTrue(self.decide(build={}))

    def test_daily_refresh(self):
        self.assertEqual(self.decide(meta=live(hours_ago=21)), ["last build was 21h ago"])

    def test_unreadable_live_site_builds(self):
        self.assertTrue(freshness.decide(NOW, None, None, "abc", HIST, faa()))

    def test_charts_posted_after_the_csv(self):
        posted = faa()
        self.assertTrue(self.decide(meta=live(charts=False), posted=posted))
        self.assertEqual(self.decide(meta=live(charts=False),
                                     posted=lambda u: False if "d-tpp" in u else posted(u)), [])

    def test_airspace_needs_both_cycles(self):
        """the build diffs old vs new shapes; if the FAA dropped the old file, rebuilding every
        3 hours can't add airspace, so don't."""
        posted = faa(("2026-09-03", "2026-10-01"))
        self.assertTrue(self.decide(meta=live(airspace=False), posted=posted))
        only_new = lambda u: False if "2026-09-03/class_airspace" in u else posted(u)
        self.assertEqual(self.decide(meta=live(airspace=False), posted=only_new), [])

    def test_changeover_day_before_0901z(self):
        """10-01 at 05:00Z: 10-01 is still upcoming, even though the date says it's the day."""
        now = dt.datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
        meta = live()
        meta["generated"] = (now - dt.timedelta(hours=2)).isoformat()
        self.assertEqual(self.decide(meta=meta, now=now), [])
        after = now + dt.timedelta(hours=5)   # 10:00Z: in effect, and history needs it
        why = self.decide(meta=meta, now=after)
        self.assertIn("history doesn't have the 2026-10-01 cycle yet", why)
        self.assertTrue(any("FAA has 2026-10-01" in w and "upcoming" not in w for w in why), why)

    def test_check_writes_github_output_and_fails_open(self):
        out = os.path.join(tempfile.mkdtemp(), "out")
        with mock.patch("amend.freshness._get_json", side_effect=OSError("down")), \
                mock.patch("amend.freshness.probe", return_value=None):
            self.assertTrue(freshness.check(out, NOW))
        with open(out) as f:
            self.assertEqual(f.read(), "build=true\n")

    def test_fingerprint_changes_with_inputs(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "amend"))
        with open(os.path.join(d, "amend", "x.py"), "w") as f:
            f.write("a = 1\n")
        a = freshness.fingerprint(d)
        with open(os.path.join(d, "amend", "x.py"), "w") as f:
            f.write("a = 2\n")
        self.assertNotEqual(a, freshness.fingerprint(d))


class TestVerify(unittest.TestCase):
    def site(self, n_changed=2, airports=10):
        d = tempfile.mkdtemp()

        def w(rel, obj):
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w") as f:
                json.dump(obj, f)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write("<html>" + "x" * 2000)
        os.makedirs(os.path.join(d, "assets"))
        with open(os.path.join(d, "assets", "app.js"), "w") as f:
            f.write("var AM;" + "x" * 2000)
        head = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01"}
        apts = {a: {"action": 1} for a in ["VRB", "DAB", "MCO"][:n_changed]}
        w("latest/meta.json", {**head, "changed_airports": n_changed})
        w("latest/index.json", {**head, "airports": apts})
        for a in apts:
            w(f"latest/{a}.json", {})
            w(f"{a}/index.html", "")
        w("airports.json", {"airports": [{"id": str(i)} for i in range(airports)]})
        w("history/index.json", {"cycles": ["2026-09-03"]})
        w("build.json", {"inputs": "abc"})
        return d

    def test_good_site(self):
        self.assertEqual(freshness.verify(self.site(), min_airports=5), [])

    def test_empty_diff_is_refused(self):
        self.assertIn("latest/index.json lists no changed airports", freshness.verify(self.site(0), 5))

    def test_tiny_directory_is_refused(self):
        self.assertTrue(freshness.verify(self.site(airports=3), min_airports=5))

    def test_missing_airport_file(self):
        d = self.site()
        os.remove(os.path.join(d, "latest", "VRB.json"))
        self.assertTrue(any("have no file" in p for p in freshness.verify(d, 5)))

    def test_half_built_site(self):
        d = self.site()
        os.remove(os.path.join(d, "latest", "meta.json"))
        os.remove(os.path.join(d, "index.html"))
        os.remove(os.path.join(d, "assets", "app.js"))
        bad = freshness.verify(d, 5)
        self.assertIn("index.html missing", bad)
        self.assertIn("assets/app.js missing", bad)
        self.assertTrue(any(p.startswith("latest/meta.json") for p in bad))


class TestRunsStopInsteadOfGuessing(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        self.addCleanup(os.chdir, self.old)

    def test_history_does_not_skip_a_cycle_on_a_flaky_download(self):
        from amend import history
        os.makedirs("history")
        cur = cycles.in_effect()
        done, c = [], cycles.FIRST_ARCHIVED + cycles.CYCLE
        while c < cur:       # everything up to date except the cycle now in effect
            done.append(c.isoformat())
            c += cycles.CYCLE
        with open("history/cycles.json", "w") as f:
            json.dump({"cycles": done, "skipped": []}, f)

        def get(d):
            if d == cur:
                raise cycles.FetchError("503")
            return True
        with mock.patch("amend.history.get_cycle", side_effect=get), \
                mock.patch("amend.history.run", side_effect=AssertionError("diffed across a gap")):
            with self.assertRaisesRegex(cycles.FetchError, "503"):
                history.update()
        with open("history/cycles.json") as f:
            self.assertEqual(json.load(f)["skipped"], [])

    def test_latest_does_not_drop_the_preview_on_a_flaky_download(self):
        from amend import latest
        with mock.patch("amend.latest.get_cycle", side_effect=cycles.FetchError("timeout")):
            with self.assertRaises(cycles.FetchError):
                latest.build(llm=False)
        self.assertFalse(os.path.exists("site"))


if __name__ == "__main__":
    unittest.main()
