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
        self.assertIn("Amend is up to date", t)
        self.assertIn("The latest build passed every check", t)
        for part in ("FAA cycle", "Processing", "Checks", "Plain-English remarks", "Website and data files"):
            self.assertIn(f'<div class="sx-n">{part}</div>', html)      # spec §62.2: one line per part
        self.assertIn(f"{r['remarks']['plain_english']:,} of {r['remarks']['texts']:,} remarks", t)
        for s in r["sources"]:                         # every checksum, in full
            self.assertIn(s["sha256"], html)
        self.assertIn(f"changes detected at {r['changes']['airports']:,} airports", t)
        self.assertIn("Pre-publish check", t)
        self.assertIn(r["run"]["url"], html)
        self.assertIn("No blocked or crashed runs", t)

    def test_every_step_of_the_spec_outline_shows(self):
        """master spec §19: each step shows, with "Not recorded" where the run log has nothing for it"""
        t = text(self.render(good()))
        for step in ("Ingestion", "Parsing", "Normalization", "Diff", "Classification", "AI", "Validation",
                     "Publishing", "Processing", "Engine"):
            self.assertIn(f" {step} ", t)
        self.assertIn("Translator cost $", t)
        self.assertIn("contractions with no verified meaning", t)
        self.assertIn("Not counted: addresses, and the four-letter airport codes (KSPS) and center codes (ZOA)", t)

    def test_translator_failures_show_as_counts_not_api_text(self):
        r = good()
        r["remarks"]["ai"].update(llm_errors=3, llm_stopped=True, unanswered=40, rejects_skipped=5,
                                  llm_error="HTTP 400: Your credit balance is too low")
        t = text(self.render(r))
        self.assertIn("translator calls that failed (translation service unavailable) 3", t)
        self.assertIn("translator stopped after repeated failures yes", t)
        self.assertNotIn("credit balance", t)

    def test_cycle_rows_flip_at_0901z(self):
        """before the changeover the page carries the in-effect rows too, for app.js to swap in at 0901Z"""
        html = self.render(good())            # NOW is 28 Sep; 01 Oct is upcoming
        self.assertIn('class="flip" data-after="', html)
        m = [x for x in re.findall(r'data-after="([^"]*)"', html) if "In effect:" in x]
        self.assertEqual(len(m), 1)
        after = m[0].replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
        self.assertIn("In effect: 01 Oct 2026. The next one, 29 Oct 2026, shows up once the FAA posts it", after)
        self.assertIn("In effect: 03 Sep 2026. The next cycle, 01 Oct 2026, is already on Amend", text(html))

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
        self.assertNotIn("Amend is up to date", t)
        self.assertIn("APT_RMK.csv went from 90009 to 100 rows", t)        # in Problems, with the reason
        self.assertIn('class="bad" data-t=', html)                        # and a magenta bar in the strip
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

    def test_recent_runs_strip_oldest_first(self):
        a, b = good(), good()
        a["started_at"], b["started_at"] = "2026-09-27T10:00:00+00:00", "2026-09-27T20:00:00+00:00"
        c = good()
        c["started_at"] = "2026-09-28T10:00:00+00:00"
        html = self.render(a, b, c)
        strip = html[html.index('class="sx-bars"'):html.index('class="sx-legend"')]
        self.assertLess(strip.index("27 Sep 2026 10:00:00Z"), strip.index("27 Sep 2026 20:00:00Z"))
        self.assertLess(strip.index("27 Sep 2026 20:00:00Z"), strip.index("28 Sep 2026 10:00:00Z"))
        self.assertIn('data-t="2026-09-27T10:00:00Z"', strip)            # the tooltip's exact time
        self.assertEqual(strip.count('class="ok"'), 3)
        self.assertIn("3 builds: 3 published", text(html))
        self.assertEqual(html.count("<summary>Every step of the latest build</summary>"), 1)


    def test_behind_check_only_on_a_published_headline(self):
        self.assertIn('data-hours="30"', self.render(good()))
        r = good()
        r["upcoming"] = False
        self.assertIn('data-up="0"', self.render(r))
        self.assertNotIn("data-last=", self.render(failed("2026-09-28T12:00:00+00:00")))


def behind(now, last="2026-09-28T12:42:05+00:00", cyc="2026-10-01", up="1"):
    """run the headline's browser check in node at `now`; the new headline html, or "" if unchanged."""
    js = statuspage.BEHIND_JS.removeprefix("<script>").removesuffix("</script>")
    stub = (f"const a={{dataset:{{last:{json.dumps(last)},cyc:{json.dumps(cyc)},hours:'{statuspage.BEHIND_HOURS}',"
            f"log:'L',up:'{up}'}},innerHTML:''}};const document={{getElementById:id=>id==='stans'?a:{{}}}};"
            f"Date.now=()=>Date.parse({json.dumps(now)});setTimeout=setInterval=()=>0;")
    out = subprocess.run(["node", "-e", stub + js + ";process.stdout.write(a.innerHTML)"],
                         capture_output=True, text=True, check=True)
    return out.stdout


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class TestAlwaysDoneSteps(unittest.TestCase):
    """normalizing and the tests always happen on a real build, so they never read "not recorded"
    (to a pilot that reads like the step was skipped)"""

    def test_normalize_is_done_once_the_comparison_ran(self):
        self.assertIn("k-ok", statuspage.s_norm({"changes": {}}))
        self.assertNotIn("Not recorded", statuspage.s_norm({"changes": {}}))
        self.assertIn("Not run", statuspage.s_norm({}))

    def test_tests_passed_on_a_github_build(self):
        html = statuspage.s_tests({"run": {"trigger": "schedule"}})
        self.assertIn("k-ok", html)
        self.assertIn(">Passed<", html)

    def test_local_build_says_the_tests_did_not_run(self):
        for r in ({"run": {"trigger": "local"}}, {}):
            html = statuspage.s_tests(r)
            self.assertIn(">Not run<", html)
            self.assertNotIn("Not recorded", html)


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

    def test_faa_late_is_not_an_amend_outage(self):
        """§62.2: the last build (fresh) found the next cycle not posted yet, so the FAA is late"""
        h = behind("2026-10-29T12:00:00Z", last="2026-10-29T08:00:00+00:00", up="0")
        self.assertIn("Waiting on the FAA", h)
        self.assertIn("hadn't posted it when Amend last built the site (29 Oct 2026 0800Z)", h)
        self.assertIn("not an Amend outage", h)
        self.assertNotIn("Amend is behind", h)

    def test_faa_late_but_no_recent_build_is_still_behind(self):
        h = behind("2026-10-30T20:00:00Z", last="2026-10-29T08:00:00+00:00", up="0")
        self.assertIn("Amend is behind", h)
        self.assertIn("either the FAA's server is down or an Amend run failed", h)

    def test_several_cycles_behind(self):
        self.assertIn("The 24 Dec 2026 FAA cycle", behind("2026-12-25T00:00:00Z"))


class TestSubdomains(unittest.TestCase):
    """status.amend.watch and docs.amend.watch (amend/subsite.py, cloudflare/_worker.js)"""
    def pages(self):
        from amend import docspage
        site = tempfile.mkdtemp()
        statuspage.build(site, META, NOW, log_dir=tempfile.mkdtemp())
        with open(os.path.join(site, "status", "index.html"), encoding="utf-8") as f:
            return f.read(), "".join(docspage.one_page(n, META, NOW) for n in range(len(docspage.PAGES)))

    def test_off_keeps_everything_on_amend_watch(self):
        """with the names off (as before they worked), nothing forwards and every link stays on amend.watch"""
        from unittest import mock
        from amend import web
        with mock.patch.object(web, "SUBDOMAINS", False):
            status, docs = self.pages()
        for html in (status, docs):
            self.assertNotIn('location.hostname===', html.split("</head>")[0])
            self.assertIn('href="https://amend.watch/docs/"', html)
            self.assertIn('href="https://amend.watch/status/"', html)
            # shared files from the page's own origin: the proxy passes /assets/ through to amend.watch
            self.assertIn('href="/assets/style.css?v=', html)
            self.assertIn('src="/assets/app.js?v=', html)
        for anchor in ("how", "sources", "limits", "open", "status"):   # linked from the site and the app
            self.assertIn(f'<section id="{anchor}">', docs)
        for path in ("using/", "how-it-works/", "api/"):
            self.assertIn(f'href="https://amend.watch/docs/{path}"', docs)

    def test_on_forwards_the_old_pages_and_links(self):
        from amend import web
        self.assertTrue(web.SUBDOMAINS)        # on since both names opened in a browser, 2026-09-28
        status, docs = self.pages()
        about = web.about_page(META, {}, [], NOW)
        self.assertIn('href="/assets/style.css?v=', status)   # shared files still from the page's own origin
        self.assertIn('if(location.hostname==="amend.watch")location.replace("https://status.amend.watch/"'
                      '+location.search+location.hash)', status)
        self.assertIn('location.replace("https://docs.amend.watch/"', docs)
        self.assertIn('<link rel="canonical" href="https://status.amend.watch/">', status)
        self.assertIn('href="https://docs.amend.watch/how-it-works/#status"', status)
        self.assertIn('"how": "https://docs.amend.watch/how-it-works/#how"', about)
        for path in ("using/", "how-it-works/", "api/"):   # each docs page forwards to its own address
            self.assertIn(f'location.replace("https://docs.amend.watch/{path}"', docs)
        self.assertIn('href="https://status.amend.watch/">Status</a>', about)
        self.assertNotIn('href="../docs/"', about)


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class TestProxy(unittest.TestCase):
    def test_worker_serves_each_page_and_only_fetches_amend_watch(self):
        d = tempfile.mkdtemp()
        shutil.copy(os.path.join("cloudflare", "_worker.js"), os.path.join(d, "w.mjs"))
        js = """import w from "./w.mjs";const calls=[];
globalThis.fetch=async(u,o)=>{calls.push(o.method+" "+u);return new Response("x",{status:200})};const out=[];
for(const [u,m] of [["https://status.amend.watch/","GET"],["https://docs.amend.watch/","GET"],
  ["https://docs.amend.watch/assets/style.css?v=1","GET"],["https://status.amend.watch/latest/meta.json","HEAD"],
  ["https://status.amend.watch/VRB/","GET"],["https://x.pages.dev/","GET"],["https://docs.amend.watch/","POST"]]){
  const r=await w.fetch(new Request(u,{method:m}));out.push(r.status+" "+(r.headers.get("location")||""))}
process.stdout.write(JSON.stringify({out,calls}))"""
        with open(os.path.join(d, "t.mjs"), "w") as f:
            f.write(js)
        res = json.loads(subprocess.run(["node", "t.mjs"], cwd=d, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(res["out"], ["200 ", "200 ", "200 ", "200 ", "301 https://amend.watch/VRB/",
                                      "302 https://amend.watch/", "405 "])
        self.assertEqual(res["calls"], ["GET https://amend.watch/status/", "GET https://amend.watch/docs/",
                                        "GET https://amend.watch/assets/style.css?v=1",
                                        "HEAD https://amend.watch/latest/meta.json"])

    def run_js(self, js):
        d = tempfile.mkdtemp()
        shutil.copy(os.path.join("cloudflare", "_worker.js"), os.path.join(d, "w.mjs"))
        with open(os.path.join(d, "t.mjs"), "w") as f:
            f.write(js)
        return json.loads(subprocess.run(["node", "t.mjs"], cwd=d, capture_output=True, text=True, check=True).stdout)

    def test_docs_pages(self):
        res = self.run_js("""import w from "./w.mjs";const calls=[];
globalThis.fetch=async(u,o)=>{calls.push(o.method+" "+u);return new Response("x",{status:200})};const out=[];
for(const u of ["https://docs.amend.watch/api/","https://docs.amend.watch/how-it-works/?x=1","https://docs.amend.watch/using",
  "https://docs.amend.watch/api/index.html","https://docs.amend.watch/apix/","https://status.amend.watch/api/"]){
  const r=await w.fetch(new Request(u));out.push(r.status+" "+(r.headers.get("location")||""))}
process.stdout.write(JSON.stringify({out,calls}))""")
        self.assertEqual(res["out"], ["200 ", "200 ", "301 https://docs.amend.watch/using/", "200 ",
                                      "301 https://amend.watch/apix/", "301 https://amend.watch/api/"])
        self.assertEqual(res["calls"], ["GET https://amend.watch/docs/api/", "GET https://amend.watch/docs/how-it-works/",
                                        "GET https://amend.watch/docs/api/"])

    def test_checks_json(self):
        """status.amend.watch/checks.json: GitHub's run list, trimmed; a GitHub error still answers, with no runs"""
        res = self.run_js("""import w from "./w.mjs";const calls=[];let ok=true;
globalThis.fetch=async(u,o)=>{calls.push(u);return ok?new Response(JSON.stringify({workflow_runs:[{id:1,event:"workflow_dispatch",
  status:"completed",conclusion:"success",run_started_at:"2026-09-28T21:43:05Z",updated_at:"2026-09-28T21:43:30Z",
  html_url:"https://github.com/benjgmin/amend/actions/runs/1",actor:{login:"x"},head_commit:{message:"m"}}]}),{status:200})
  :new Response("rate limited",{status:403})};
const a=await (await w.fetch(new Request("https://status.amend.watch/checks.json"))).json();ok=false;
const r=await w.fetch(new Request("https://status.amend.watch/checks.json"));const b=await r.json();
const d=await w.fetch(new Request("https://docs.amend.watch/checks.json"));
process.stdout.write(JSON.stringify({a,b,st:r.status,type:r.headers.get("content-type"),docs:d.status+" "+d.headers.get("location"),calls}))""")
        self.assertEqual(res["a"], {"runs": [{"event": "workflow_dispatch", "status": "completed", "conclusion": "success",
                                              "started": "2026-09-28T21:43:05Z", "updated": "2026-09-28T21:43:30Z",
                                              "url": "https://github.com/benjgmin/amend/actions/runs/1"}]})
        self.assertEqual(res["b"]["runs"], [])
        self.assertEqual((res["st"], res["type"]), (200, "application/json; charset=utf-8"))
        self.assertEqual(res["docs"], "301 https://amend.watch/checks.json")
        self.assertTrue(all(u.startswith("https://api.github.com/repos/benjgmin/amend/actions/workflows/update.yml/runs")
                            for u in res["calls"]))


class TestChecksCard(unittest.TestCase):
    def test_card_links_github_and_loads_checks_only_off_amend_watch(self):
        html = statuspage.checks_card()
        self.assertIn('href="https://github.com/benjgmin/amend/actions/workflows/update.yml"', html)
        self.assertIn('fetch("/checks.json")', html)
        self.assertIn('location.hostname==="amend.watch")return', html)
        self.assertNotIn("innerHTML", statuspage.CHECKS_JS + statuspage.TIP_JS)   # GitHub's text never goes in as HTML


class TestDocsPages(unittest.TestCase):
    def test_api_page_carries_every_schema_field(self):
        """the API page is built from SCHEMA.md, so every field in its tables is on the page"""
        from amend import docspage
        api = docspage.one_page(len(docspage.PAGES) - 1, META, NOW)
        with open("SCHEMA.md", encoding="utf-8") as f:
            fields = re.findall(r"^\| `([a-z_]+)`", f.read(), flags=re.M)
        self.assertGreater(len(fields), 20)
        for fld in fields:
            self.assertIn(f"<code>{fld}</code>", api)
        self.assertIn("<pre><code>{&quot;schema_version&quot;: 1", api)
        self.assertIn('<section id="change">', api)

    def test_old_single_page_anchors_move_to_their_page(self):
        from amend import docspage
        home = docspage.one_page(0, META, NOW)
        head = home.split("</head>")[0]
        m = json.loads(re.search(r"const m=(\{.*?\})\[", head).group(1))
        self.assertEqual({k: m[k] for k in ("how", "limits", "sources", "status", "labels", "remarks", "api")},
                         {"how": "how-it-works/", "limits": "how-it-works/", "sources": "how-it-works/",
                          "status": "how-it-works/", "labels": "using/", "remarks": "using/", "api": "api/"})
        self.assertLess(head.index("const m="), head.index('location.hostname==="amend.watch"'))   # before the forward
        self.assertNotIn("open", m)   # still on the first page

    def test_a_renamed_schema_heading_fails_loudly(self):
        from unittest import mock
        from amend import docspage
        with mock.patch.object(docspage, "schema", lambda: {"": ""}):
            with self.assertRaises(ValueError):
                docspage.api_sections()


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
