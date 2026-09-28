"""the status page (amend/statuspage.py) shows what the run log says and nothing else."""
import copy
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from amend import runlog, statuspage

NOW = dt.datetime(2026, 9, 28, 13, 0, tzinfo=dt.timezone.utc)
META = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True, "changed_airports": 687}
REAL = sorted(glob.glob(os.path.join("audit", "runs", "*", "*-latest-*.json")))


def good():
    """a real published site-build record from the repo's run log"""
    with open(REAL[-1], encoding="utf-8") as f:
        return json.load(f)


def failed(started):
    """a run that crashed before choosing cycles: every result field is null"""
    return {"runlog_version": 1, "engine": "1.0.0", "engine_hash": "abc", "commit": None,
            "run": {"id": "9", "attempt": "1", "trigger": "schedule", "url": None}, "mode": "latest",
            "hash_seed": "0", "started_at": started, "finished_at": started, "seconds": 3.0,
            "from_cycle": None, "to_cycle": None, "upcoming": None, "sources": [], "csv_rows": None,
            "airspace_shapes": None, "changes": None, "remarks": None, "summary_checks": None, "checks": None,
            "outcome": "failed", "error": "URLError: <urlopen error timed out>", "verified": None, "published": False}


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@unittest.skipUnless(REAL, "no run log records in audit/runs")
class TestStatusPage(unittest.TestCase):
    def render(self, *recs):
        d = tempfile.mkdtemp()
        for i, r in enumerate(recs):
            folder = os.path.join(d, "2026-09-03")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f"{i:03d}.json"), "w", encoding="utf-8") as f:
                json.dump(r, f)
        site = tempfile.mkdtemp()
        statuspage.build(site, META, NOW, log_dir=d)
        with open(os.path.join(site, "status", "index.html"), encoding="utf-8") as f:
            return f.read()

    def test_published_run_is_current(self):
        r = good()
        html = self.render(r)
        t = text(html)
        self.assertIn("Amend is current, and the latest build passed every check", t)
        for s in r["sources"]:                         # every checksum, in full
            self.assertIn(s["sha256"], html)
        self.assertIn(f"{r['changes']['airports']:,} airports changed", t)
        self.assertIn("Pre-publish check", t)
        self.assertIn(r["run"]["url"], html)

    def test_zero_is_zero_not_blank(self):
        r = good()
        r["checks"] = {"errors": [], "warnings": [], "error_count": 0, "warning_count": 0}
        self.assertIn("0 errors, 0 warnings", text(self.render(r)))

    def test_nulls_say_not_recorded(self):
        r = good()
        r["sources"][0]["last_modified"] = None
        r["remarks"]["ai"]["est_cost_usd"] = None
        html = self.render(r)
        self.assertIn("not recorded", html)
        self.assertNotIn("None", text(html))
        self.assertNotIn("$None", html)

    def test_blocked_run_after_last_good_build(self):
        r = good()
        b = copy.deepcopy(r)
        b.update(mode="history", started_at="2026-09-28T23:00:00+00:00", outcome="blocked", published=False,
                 error="audit failed for 2026-09-03 -> 2026-10-01 <b>", verified=None,
                 checks={"errors": ["APT_RMK.csv went from 90009 to 100 rows (-100%)"], "warnings": [],
                         "error_count": 1, "warning_count": 0})
        html = self.render(r, b)
        t = text(html)
        self.assertIn("The latest run didn't publish", t)
        self.assertNotIn("Amend is current", t)
        self.assertIn("APT_RMK.csv went from 90009 to 100 rows", t)
        self.assertIn("&lt;b&gt;", html)             # FAA/run text is escaped, never markup
        self.assertNotIn("-> 2026-10-01 <b>", html)

    def test_crashed_run_shows_stages_as_not_run(self):
        html = self.render(failed("2026-09-28T12:00:00+00:00"))
        t = text(html)
        self.assertIn("The latest build didn't publish", t)
        self.assertIn("Not run", t)
        self.assertIn("timed out", t)
        self.assertNotIn("None", t)

    def test_waiting_on_verify(self):
        r = good()
        r.update(verified=None, published=None)
        t = text(self.render(r))
        self.assertIn("waiting on its pre-publish check", t)

    def test_unknown_fields_are_shown_not_dropped(self):
        r = good()
        r["runlog_version"] = runlog.RUNLOG_VERSION + 1
        r["first_seen"] = {"nasr_new": "2026-09-10T02:17:00+00:00"}
        r["summary_checks"]["leaks"] = {"APT_BASE.csv x": 2}
        t = text(self.render(r))
        self.assertIn("Other recorded fields", t)
        self.assertIn("first_seen", t)
        self.assertIn("leaks", t)
        self.assertIn(f"format {runlog.RUNLOG_VERSION + 1}", t)

    def test_empty_log(self):
        self.assertIn("No runs recorded yet", text(self.render()))

    def test_earlier_runs_listed_newest_first(self):
        a, b = good(), good()
        a["started_at"], b["started_at"] = "2026-09-27T10:00:00+00:00", "2026-09-27T20:00:00+00:00"
        c = good()
        c["started_at"] = "2026-09-28T10:00:00+00:00"
        html = self.render(a, b, c)
        self.assertLess(html.index("27 Sep 2026 2000Z"), html.index("27 Sep 2026 1000Z"))
        self.assertEqual(html.count('class="card cycle run"'), 2)


    def test_behind_check_only_on_a_published_headline(self):
        self.assertIn('data-hours="30"', self.render(good()))
        self.assertNotIn("data-last=", self.render(failed("2026-09-28T12:00:00+00:00")))


def behind(now, last="2026-09-28T12:42:05+00:00", cyc="2026-10-01"):
    """run the headline's browser check in node at `now`; the new headline html, or "" if unchanged."""
    js = statuspage.BEHIND_JS.removeprefix("<script>").removesuffix("</script>")
    stub = (f"const a={{dataset:{{last:{json.dumps(last)},cyc:{json.dumps(cyc)},hours:'{statuspage.BEHIND_HOURS}',"
            f"log:'L'}},innerHTML:''}};const document={{getElementById:()=>a}};"
            f"Date.now=()=>Date.parse({json.dumps(now)});setTimeout=setInterval=()=>0;")
    out = subprocess.run(["node", "-e", stub + js + ";process.stdout.write(a.innerHTML)"],
                         capture_output=True, text=True, check=True)
    return out.stdout


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class TestBehindCheck(unittest.TestCase):
    def test_fresh_build_stays_green(self):
        self.assertEqual(behind("2026-09-28T14:00:00Z"), "")
        self.assertEqual(behind("2026-09-29T18:00:00Z"), "")     # 29h: a slow day of dropped crons

    def test_no_published_run_for_30h(self):
        h = behind("2026-09-29T19:00:00Z")
        self.assertIn("Amend is behind", h)
        self.assertIn("No run has published since 28 Sep 2026 1242Z", h)
        self.assertNotIn("isn't on Amend yet", h)

    def test_changeover_passed_without_new_cycle(self):
        h = behind("2026-10-29T09:30:00Z", last="2026-10-29T08:00:00+00:00")
        self.assertIn("The 29 Oct 2026 FAA cycle took effect 29 Oct 2026 0901Z and isn't on Amend yet", h)
        self.assertNotIn("No run has published", h)

    def test_upcoming_cycle_before_and_after_changeover(self):
        self.assertEqual(behind("2026-10-01T09:00:00Z", last="2026-10-01T08:00:00+00:00"), "")
        self.assertEqual(behind("2026-10-01T09:02:00Z", last="2026-10-01T08:00:00+00:00"), "")

    def test_several_cycles_behind(self):
        self.assertIn("The 24 Dec 2026 FAA cycle", behind("2026-12-25T00:00:00Z"))


class TestVerifyRefreshesThePage(unittest.TestCase):
    def test_verify_rewrites_status_after_passing(self):
        from unittest import mock
        from amend import cli, freshness
        from tests.test_pipeline_ops import TestVerify
        site, old = TestVerify().site(), os.getcwd()
        os.chdir(tempfile.mkdtemp())           # an empty run log, away from the repo's
        try:
            with mock.patch.object(freshness, "verify", lambda s: []), \
                    mock.patch.dict(os.environ, {"GITHUB_RUN_ID": ""}):
                cli.main(["verify", site])
        finally:
            os.chdir(old)
        with open(os.path.join(site, "status", "index.html"), encoding="utf-8") as f:
            self.assertIn("No runs recorded yet", f.read())


if __name__ == "__main__":
    unittest.main()
