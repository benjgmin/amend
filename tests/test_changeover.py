"""
The 0901Z changeover. The upcoming cycle is published weeks early, so the switch from "upcoming" to
"in effect" can't wait for a build that GitHub may start hours late: pages carry both versions and
app.js flips them at 0901Z by a clock checked against the server's. These tests pin it to the second.
run:  python -m unittest tests.test_changeover -v
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from amend import cycles, freshness, web

UTC = dt.timezone.utc
BEFORE = dt.datetime(2026, 10, 1, 9, 0, 59, tzinfo=UTC)
AT = dt.datetime(2026, 10, 1, 9, 1, 0, tzinfo=UTC)
META = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True, "changed_airports": 1}


class TestCycleMath(unittest.TestCase):
    def test_to_the_second(self):
        self.assertEqual(cycles.in_effect(BEFORE), dt.date(2026, 9, 3))
        self.assertEqual(cycles.in_effect(AT), dt.date(2026, 10, 1))
        self.assertEqual(web.status(META, BEFORE)[0], True)
        self.assertEqual(web.status(META, AT)[0], False)


class TestPages(unittest.TestCase):
    def build(self, now):
        site, hist = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, site)
        self.addCleanup(shutil.rmtree, hist)
        latest = {"VRB": [{"id": "a", "priority": "action", "category": "tower", "kind": "changed",
                           "summary": "tower hours: 0800-2200 -> 0600-2200 local", "source": "ATC_BASE"}]}
        directory = [{"id": "VRB", "icao": "KVRB", "name": "Vero Beach Rgnl", "city": "Vero Beach", "state": "FL"}]
        web.build(site, META, directory, latest, hist, now=now,
                  watchlists={"club": {"name": "Club", "airports": ["VRB"], "description": ""}})

        def read(*p):
            with open(os.path.join(site, *p), encoding="utf-8") as f:
                return f.read()
        return {"airport": read("VRB", "index.html"), "home": read("index.html"),
                "list": read("list", "index.html"), "named": read("list", "club", "index.html")}

    def test_built_a_second_before_carries_the_in_effect_version(self):
        for name, page in self.build(BEFORE).items():
            with self.subTest(page=name):
                self.assertIn('data-eff="2026-10-01T09:01:00Z"', page)
                self.assertIn('class="flip" data-after=', page)
        airport = self.build(BEFORE)["airport"]
        self.assertIn("Not in effect yet", airport)
        # the swap-in: in effect, and the countdown moves on to the next cycle
        self.assertIn("&lt;span class=&quot;ann ok&quot;&gt;In effect&lt;/span&gt;", airport)
        self.assertIn("data-until=&quot;2026-10-29T09:01:00Z&quot;", airport)

    def test_built_at_the_changeover_is_plain_in_effect(self):
        for name, page in self.build(AT).items():
            with self.subTest(page=name):
                self.assertNotIn("data-eff=", page)
                self.assertNotIn('class="flip"', page)
                self.assertNotIn("Not in effect yet", page)
                self.assertNotIn("(upcoming)", page)
        self.assertIn('<span class="ann ok">In effect</span>', self.build(AT)["airport"])


# app.js with just enough DOM to run AM.flip / AM.sync, and a clock the test sets
HARNESS = r"""
const vm = require("vm"), fs = require("fs");
const [appPath, eff, deviceNow, serverDate] = process.argv.slice(2);
let clock = Date.parse(deviceNow);
Date.now = () => clock;
const flips = [{innerHTML: "Not in effect yet", dataset: {after: "In effect"}, removeAttribute(a) { delete this.dataset.after }}];
const events = [];
globalThis.document = {
  body: {dataset: {eff, root: ""}},
  querySelectorAll: s => s === ".flip[data-after]" ? flips.filter(f => f.dataset.after) : [],
  getElementById: () => null, addEventListener() {}, dispatchEvent(e) { events.push(e.type) }};
globalThis.Event = class { constructor(t) { this.type = t } };
globalThis.addEventListener = () => {};
globalThis.setInterval = () => 0;
const timers = [];
globalThis.setTimeout = (fn, ms) => { timers.push({fn, at: clock + ms}); return timers.length };
globalThis.clearTimeout = () => {};
globalThis.localStorage = {getItem: () => null, setItem() {}};
globalThis.fetch = () => Promise.resolve({headers: {get: h => h === "Date" ? serverDate || null : null}});
vm.runInThisContext(fs.readFileSync(appPath, "utf8"));
const out = {};
AM.sync();
out.textBeforeServer = flips[0].innerHTML;
setImmediate(() => {
  out.textAfterSync = flips[0].innerHTML;
  // run the timer sync() armed for the changeover (not its 1.5s fallback), at the moment it asked for
  const t = timers.filter(t => t.at !== Date.parse(deviceNow) + 1500).sort((a, b) => a.at - b.at)[0];
  out.timerAt = t ? new Date(t.at).toISOString() : null;
  if (t) { clock = t.at; t.fn() }
  out.textAfterTimer = flips[0].innerHTML;
  out.events = events;
  console.log(JSON.stringify(out));
});
"""


@unittest.skipUnless(shutil.which("node"), "needs node to run the page script")
class TestPageScript(unittest.TestCase):
    def run_js(self, device_now, server_date=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        app, harness = os.path.join(d, "app.js"), os.path.join(d, "h.js")
        with open(app, "w") as f:
            f.write(web.APP)
        with open(harness, "w") as f:
            f.write(HARNESS)
        out = subprocess.run(["node", harness, app, "2026-10-01T09:01:00Z", device_now, server_date or ""],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_opened_a_second_before_flips_at_0901z_exactly(self):
        r = self.run_js("2026-10-01T09:00:59.000Z")
        self.assertEqual(r["textAfterSync"], "Not in effect yet")
        self.assertEqual(r["timerAt"], "2026-10-01T09:01:00.025Z")   # 25ms slack so it never fires early
        self.assertEqual(r["textAfterTimer"], "In effect")
        self.assertEqual(r["events"], ["amend:flip"])

    def test_one_millisecond_before_is_still_upcoming(self):
        self.assertEqual(self.run_js("2026-10-01T09:00:59.999Z")["textAfterSync"], "Not in effect yet")

    def test_opened_after_the_changeover_flips_once_the_server_answers(self):
        r = self.run_js("2026-10-01T09:01:00.000Z")
        self.assertEqual(r["textBeforeServer"], "Not in effect yet")
        self.assertEqual(r["textAfterSync"], "In effect")

    def test_fast_device_clock_waits_for_the_server(self):
        """device 10 minutes fast: at its 09:05 the server says 08:55, so nothing flips yet."""
        r = self.run_js("2026-10-01T09:05:00.000Z", "Thu, 01 Oct 2026 08:55:00 GMT")
        self.assertEqual(r["textAfterSync"], "Not in effect yet")
        # the server's 0901Z on this device's clock: 09:10:59.5 (the header's second is read as its middle)
        self.assertEqual(r["timerAt"], "2026-10-01T09:10:59.525Z")
        self.assertEqual(r["textAfterTimer"], "In effect")

    def test_slow_device_clock_flips_on_server_time(self):
        """device 5 minutes slow: at its 08:57 the server says 09:02, so it flips as soon as the server answers."""
        r = self.run_js("2026-10-01T08:57:00.000Z", "Thu, 01 Oct 2026 09:02:00 GMT")
        self.assertEqual(r["textBeforeServer"], "Not in effect yet")
        self.assertEqual(r["textAfterSync"], "In effect")

    def test_small_differences_trust_the_device(self):
        """the Date header is whole seconds; under 2s off, the device's (NTP) clock is the better one."""
        r = self.run_js("2026-10-01T09:00:59.000Z", "Thu, 01 Oct 2026 09:01:00 GMT")
        self.assertEqual(r["textAfterSync"], "Not in effect yet")
        self.assertEqual(r["timerAt"], "2026-10-01T09:01:00.025Z")


class TestPickupLog(unittest.TestCase):
    def test_lag_line(self):
        now = dt.datetime(2026, 10, 8, 14, 13, tzinfo=UTC)
        lines = freshness.faa_log({
            "https://faa/29_Oct_2026_CSV.zip": (True, dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC)),
            "https://faa/d-tpp_Metafile.xml": (False, None),
            "https://faa/x.zip": (None, None)}, now)
        self.assertEqual(lines[0], "  faa: posted 2026-10-08 12:00Z (0d 2h 13m before this check)  "
                                   "https://faa/29_Oct_2026_CSV.zip")
        self.assertIn("not posted", lines[1])
        self.assertIn("couldn't tell", lines[2])

    def test_probe_reads_last_modified(self):
        from unittest import mock

        class R:
            headers = {"Last-Modified": "Thu, 08 Oct 2026 12:00:00 GMT"}

            def read(self, n):
                return b"PK\x03\x04"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with mock.patch("amend.cycles.urllib.request.urlopen", return_value=R()):
            self.assertEqual(cycles.probe_info("https://faa/x.zip"),
                             (True, dt.datetime(2026, 10, 8, 12, 0, tzinfo=UTC)))


class TestCheckAtTheChangeover(unittest.TestCase):
    def decide(self, now):
        meta = {**META, "includes_charts": True, "includes_airspace": True,
                "generated": (now - dt.timedelta(hours=1)).isoformat()}
        return freshness.decide(now, meta, {"inputs": "x"}, "x", ["2026-09-03"],
                                lambda url: "01_Oct_2026" in url or "2610" in url or "2026-10-01" in url
                                or "2026-09-03" in url)

    def test_nothing_to_do_a_second_before(self):
        self.assertEqual(self.decide(BEFORE), [])

    def test_rebuild_from_0901z_to_catch_history_up(self):
        why = self.decide(AT)
        self.assertIn("history doesn't have the 2026-10-01 cycle yet", why)


if __name__ == "__main__":
    unittest.main()
