"""
The engine version, the processing log (amend/runlog.py) and the input checks: every run leaves
a record built from what it actually read, and an FAA file that wasn't read completely stops
the run instead of publishing its missing rows as removals.
run:  python -m unittest tests.test_runlog -v
"""
import ast
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

from amend import ENGINE_VERSION, audit, cycles, history, nasr, runlog
from tests.test_pipeline_ops import REQ, FetchCase, zip_bytes

IDS = {"VRB", "DAB"}


def actions_env(test, **env):
    """run the test as if in the Actions run `env` describes: the GITHUB_* variables of the
    runner the tests themselves run on (run id, attempt, step summary) and the deploy's
    AMEND_COMMIT are taken out first."""
    keep = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_") and k != "AMEND_COMMIT"}
    p = mock.patch.dict(os.environ, {**keep, **env}, clear=True)
    p.start()
    test.addCleanup(p.stop)


def nasr_zip(path, files):
    """files: {name: text or bytes}; a name ending in .zip holds a nested {name: text} dict."""
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            if isinstance(body, dict):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as inner:
                    for n, b in body.items():
                        inner.writestr(n, b)
                body = buf.getvalue()
            z.writestr(name, body)
    return path


class TestLoadStopsOnBadInput(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def load(self, files, rows=None):
        return nasr.load(nasr_zip(os.path.join(self.dir, "x.zip"), files), IDS, rows=rows)

    def test_parse_error_fails_instead_of_dropping_the_rest_of_the_file(self):
        """a row the csv reader chokes on used to print a warning and skip the rest of the file,
        so every remark after it published as removed."""
        big = "x" * 200_000       # over the csv module's field limit: a real csv.Error
        text = "ARPT_ID,REMARK\rVRB,ONE\rVRB," + big + "\rDAB,THREE\r"
        with self.assertRaisesRegex(nasr.InputError, r"APT_RMK.csv .*after row 1"):
            self.load({"APT_RMK.csv": text})

    def test_two_different_files_with_one_name_fail(self):
        a = "ARPT_ID,TWR_HRS\rVRB,0700-2100\r"
        b = "ARPT_ID,TWR_HRS\rVRB,0700-0100\r"
        with self.assertRaisesRegex(nasr.InputError, "ATC_BASE.csv appears twice"):
            self.load({"ATC_BASE.csv": a, "more.zip": {"ATC_BASE.csv": b}})

    def test_the_same_file_packed_twice_is_fine(self):
        a = "ARPT_ID,TWR_HRS\rVRB,0700-2100\r"
        out = self.load({"ATC_BASE.csv": a, "more.zip": {"ATC_BASE.csv": a}})
        self.assertEqual(len(out["ATC_BASE.csv"]), 1)

    def test_rows_counts_every_row_not_just_ours(self):
        rows = {}
        self.load({"APT_BASE.csv": "ARPT_ID,NAME\rVRB,A\rXYZ,B\rABC,C\r",
                   "FIX_BASE.csv": "FIX_ID\rAAA\r",          # hidden file: not read, not counted
                   "APT_BASE_CHG_RPT.csv": "ARPT_ID\rVRB\r"}, rows)
        self.assertEqual(rows, {"APT_BASE.csv": 3})


class TestInputChecks(unittest.TestCase):
    def check(self, old, new, shapes=None):
        return audit.check_inputs({"old": old, "new": new}, shapes)

    def test_real_cycle_to_cycle_moves_pass(self):
        """the biggest real moves between Aug 2024 and Oct 2026 raise nothing."""
        e, w = self.check({"ATC_RMK.csv": 3186, "APT_RMK.csv": 90009, "PJA_CON.csv": 133,
                           "PFR_RMT_FMT.csv": 11878, "FSS_RMK.csv": 29},
                          {"ATC_RMK.csv": 3094, "APT_RMK.csv": 88928, "PJA_CON.csv": 142,
                           "PFR_RMT_FMT.csv": 12667, "FSS_RMK.csv": 29})
        self.assertEqual((e, w), ([], []))

    def test_truncated_file_stops_the_build(self):
        e, _ = self.check({"APT_RMK.csv": 90009}, {"APT_RMK.csv": 61000})
        self.assertEqual(len(e), 1)
        self.assertIn("APT_RMK.csv went from 90009 to 61000 rows (-32%)", e[0])

    def test_moderate_drop_is_flagged_not_blocked(self):
        e, w = self.check({"FRQ.csv": 40000}, {"FRQ.csv": 37600})     # -6%
        self.assertEqual(e, [])
        self.assertEqual(w, ["FRQ.csv went from 40000 to 37600 rows (-6%)"])

    def test_file_packed_twice_stops_the_build(self):
        e, _ = self.check({"NAV_BASE.csv": 1617}, {"NAV_BASE.csv": 3234})
        self.assertIn("packed twice", e[0])

    def test_missing_file_stops_the_build(self):
        e, _ = self.check({"ILS_BASE.csv": 1556, "APT_BASE.csv": 19427}, {"APT_BASE.csv": 19427})
        self.assertEqual(len(e), 1)
        self.assertIn("ILS_BASE.csv was in the old cycle (1556 rows) and is missing", e[0])

    def test_tiny_files_only_fail_when_emptied(self):
        self.assertEqual(self.check({"MAA_CON.csv": 3}, {"MAA_CON.csv": 1}), ([], []))
        e, _ = self.check({"ARB_BASE.csv": 38}, {"ARB_BASE.csv": 0})
        self.assertIn("the FAA file is empty", e[0])

    def test_new_file_is_flagged(self):
        e, w = self.check({"APT_BASE.csv": 10}, {"APT_BASE.csv": 10, "NEW.csv": 500})
        self.assertEqual(e, [])
        self.assertIn("NEW.csv is new this cycle (500 rows)", w[0])

    def test_file_empty_last_cycle_is_new_not_doubled(self):
        # a header-only file that gets rows is a new file, not "+100%, packed twice"
        e, w = self.check({"APT_BASE.csv": 10, "NEW.csv": 0}, {"APT_BASE.csv": 10, "NEW.csv": 120})
        self.assertEqual(e, [])
        self.assertIn("NEW.csv is new this cycle (120 rows)", w[0])
        self.assertEqual(self.check({"NEW.csv": 0}, {"NEW.csv": 0}), ([], []))

    def test_nothing_read_fails(self):
        self.assertEqual(self.check({"APT_BASE.csv": 10}, {})[0], ["no FAA files were read from the new cycle"])

    def test_airspace_shapes_are_checked_like_a_file(self):
        e, _ = self.check({"APT_BASE.csv": 10}, {"APT_BASE.csv": 10}, {"old": 1800, "new": 900})
        self.assertIn("class airspace shapefile went from 1800 to 900", e[0])

    def test_audit_runs_the_input_checks_and_flags_left_out_airspace(self):
        result = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "airports": {},
                  "csv_rows": {"old": {"APT_RMK.csv": 1000}, "new": {"APT_RMK.csv": 10}},
                  "airspace_error": "couldn't read the class airspace shapefile (ValueError: x)"}
        with tempfile.TemporaryDirectory() as h:
            report = audit.audit(result, h, today=__import__("datetime").date(2026, 9, 27))
        self.assertIn("APT_RMK.csv went from 1000 to 10", report["errors"][0])
        self.assertIn("airspace shape changes left out: couldn't read", " ".join(report["warnings"]))


class TestDownloadRecord(FetchCase):
    def test_download_records_url_time_size_and_checksum(self):
        import hashlib
        body = zip_bytes()
        self.serve(body)
        self.assertTrue(cycles.download("https://faa/x.zip", self.path(), REQ))
        with open(cycles.meta_path(self.path())) as f:
            meta = json.load(f)
        self.assertEqual(meta["url"], "https://faa/x.zip")
        self.assertEqual(meta["bytes"], len(body))
        self.assertEqual(meta["sha256"], hashlib.sha256(body).hexdigest())
        self.assertTrue(meta["retrieved_at"].endswith("+00:00"))

    def test_run_log_reads_the_record_and_catches_a_swapped_file(self):
        self.serve(zip_bytes())
        cycles.download("https://faa/x.zip", self.path(), REQ)
        info, problems = runlog.file_info("nasr_new", "https://faa/x.zip", self.path())
        self.assertEqual(problems, [])
        self.assertIsNotNone(info["retrieved_at"])
        with open(self.path(), "wb") as f:           # the cache now holds some other file
            f.write(zip_bytes(extra={"MORE.csv": "A\r1\r"}))
        info, problems = runlog.file_info("nasr_new", "https://faa/x.zip", self.path())
        self.assertIsNone(info["retrieved_at"])
        self.assertIn("isn't the file that was downloaded", problems[0])

    def test_file_cached_before_records_existed_has_no_retrieval_time(self):
        with open(self.path(), "wb") as f:
            f.write(zip_bytes())
        info, problems = runlog.file_info("nasr_old", "https://faa/x.zip", self.path())
        self.assertEqual((info["retrieved_at"], problems), (None, []))
        self.assertEqual(len(info["sha256"]), 64)


class TestRunLog(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        actions_env(self, GITHUB_RUN_ID="77", GITHUB_RUN_ATTEMPT="1", GITHUB_SHA="abc1234",
                    GITHUB_EVENT_NAME="schedule", GITHUB_REPOSITORY="o/r", PYTHONHASHSEED="0")

    def records(self):
        return runlog.runs(self.dir)

    RESULT = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "hidden": {"VRB": 4},
              "airports": {"VRB": [{"priority": "action", "category": "tower"},
                                   {"priority": "fyi", "category": "remark"}]},
              "csv_rows": {"old": {"APT_BASE.csv": 5}, "new": {"APT_BASE.csv": 6}},
              "remarks": {"texts": 3, "plain_english": 2},
              "checks": {"no_english": {"FRQ add": 2}, "summary_value_mismatches": 1}}

    def test_built_run(self):
        with runlog.Run("latest", self.dir) as r:
            r.cycles("2026-09-03", "2026-10-01", upcoming=True)
            r.result(self.RESULT)
            r.checks({"errors": [], "warnings": ["w"]})
            r.done()
        [rec] = self.records()
        self.assertEqual((rec["engine"], rec["commit"], rec["hash_seed"]), (ENGINE_VERSION, "abc1234", "0"))
        self.assertEqual((rec["mode"], rec["outcome"], rec["verified"], rec["published"]),
                         ("latest", "built", None, None))
        self.assertEqual(rec["run"], {"id": "77", "attempt": "1", "trigger": "schedule",
                                      "url": "https://github.com/o/r/actions/runs/77"})
        self.assertEqual(rec["summary_checks"], {"no_english": {"FRQ add": 2}, "summary_value_mismatches": 1})
        self.assertEqual(rec["changes"], {"airports": 1, "action": 1, "ifr": 0, "fyi": 1, "hidden": 4,
                                          "by_category": {"remark": 1, "tower": 1}})
        ai = rec["remarks"].pop("ai")
        self.assertEqual(rec["remarks"], {"texts": 3, "plain_english": 2, "raw_fallback": 1})
        self.assertIsInstance(ai, dict)          # remarks.STATS since #28: model usage for this process
        self.assertIn("llm_calls", ai)
        self.assertEqual(rec["checks"]["warning_count"], 1)
        self.assertEqual(rec["csv_rows"]["new"], {"APT_BASE.csv": 6})
        self.assertIsNotNone(rec["finished_at"])

        self.assertTrue(runlog.mark_verified(True, [], self.dir))
        [rec] = self.records()
        self.assertEqual((rec["verified"], rec["published"]), (True, True))

    def test_commit_is_the_one_built(self):
        """a run queued behind a deploy builds the branch as it is when it starts (AMEND_COMMIT),
        newer than the commit it was queued on (GITHUB_SHA) once that deploy's data commit lands"""
        os.environ["AMEND_COMMIT"] = "def5678"
        with runlog.Run("latest", self.dir) as r:
            r.done()
        self.assertEqual(self.records()[0]["commit"], "def5678")
        del os.environ["AMEND_COMMIT"], os.environ["GITHUB_SHA"]
        self.assertIsNone(runlog.built_commit())          # a local run

    def test_failed_verify_is_recorded(self):
        with runlog.Run("latest", self.dir) as r:
            r.done()
        runlog.mark_verified(False, ["index.html missing"], self.dir)
        [rec] = self.records()
        self.assertEqual((rec["verified"], rec["published"]), (False, False))
        self.assertIn("index.html missing", rec["error"])

    def test_crash_is_recorded_and_still_raised(self):
        with self.assertRaises(cycles.FetchError):
            with runlog.Run("latest", self.dir):
                raise cycles.FetchError("https://faa: HTTP 503")
        [rec] = self.records()
        self.assertEqual((rec["outcome"], rec["published"]), ("failed", False))
        self.assertEqual(rec["error"], "FetchError: https://faa: HTTP 503")

    def test_unreadable_faa_file_is_a_blocked_run(self):
        out = io.StringIO()     # the annotation it prints would land on this test job's own run
        with self.assertRaises(nasr.InputError), contextlib.redirect_stdout(out):
            with runlog.Run("history", self.dir):
                raise nasr.InputError("APT_RMK.csv: csv parse error")
        [rec] = self.records()
        self.assertEqual((rec["outcome"], rec["published"]), ("blocked", False))
        self.assertEqual(rec["checks"]["errors"], ["APT_RMK.csv: csv parse error"])
        self.assertIn("::error title=input check::APT_RMK.csv: csv parse error", out.getvalue())

    def test_gate_block_keeps_its_reason(self):
        with self.assertRaises(SystemExit):
            with runlog.Run("latest", self.dir) as r:
                r.checks({"errors": ["e"], "warnings": []})
                r.block("audit failed")
                raise SystemExit("audit failed")
        [rec] = self.records()
        self.assertEqual((rec["outcome"], rec["error"], rec["published"]), ("blocked", "audit failed", False))

    def test_nothing_logged_when_nothing_happened(self):
        with runlog.Run("history", self.dir):
            pass
        self.assertEqual(self.records(), [])

    def test_each_run_gets_its_own_file_in_the_folder_of_the_cycle_in_effect(self):
        for _ in range(3):
            with runlog.Run("latest", self.dir) as r:
                r.done()
        paths = runlog.files(self.dir)
        self.assertEqual(len(paths), 3)
        self.assertEqual({os.path.dirname(p) for p in paths},
                         {os.path.join(self.dir, cycles.in_effect().isoformat())})
        self.assertTrue(all(p.endswith("-latest-77-1.json") for p in paths))
        recs = self.records()
        self.assertEqual([r["runlog_version"] for r in recs], [1, 1, 1])
        self.assertEqual([r["started_at"] for r in recs], sorted(r["started_at"] for r in recs))

    def test_the_first_layout_is_split_into_one_file_per_record(self):
        """#25 shipped one file per cycle ({"runs": [...]}); the next record written moves those
        records into files of their own, named from the records, so every build that migrates
        writes the same files."""
        old = [{"runlog_version": 1, "mode": "latest", "run": {"id": "5", "attempt": "1"},
                "started_at": "2026-09-20T11:35:22+00:00", "outcome": "built"},
               {"runlog_version": 1, "mode": "history", "run": {"id": "6", "attempt": "1"},
                "started_at": "2026-09-21T14:20:01+00:00", "outcome": "appended"}]
        other = tempfile.mkdtemp()
        for d in (self.dir, other):
            with open(os.path.join(d, "2026-09-03.json"), "w") as f:
                json.dump({"runlog_version": 1, "cycle": "2026-09-03", "runs": old}, f)
        with runlog.Run("latest", self.dir) as r:
            r.done()
        runlog.migrate(other)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "2026-09-03.json")))
        recs = self.records()
        self.assertEqual(recs[:2], old)
        self.assertEqual(recs[2]["run"]["id"], "77")
        migrated = runlog.files(self.dir)[:2]
        self.assertEqual([os.path.relpath(p, self.dir) for p in migrated],
                         [os.path.relpath(p, other) for p in runlog.files(other)])
        self.assertEqual(os.path.basename(migrated[0]), "20260920T113522.000000Z-latest-5-1.json")

    def test_verify_marks_its_own_attempt_not_another_runs_build(self):
        with runlog.Run("latest", self.dir) as r:       # run 77, attempt 1
            r.done()
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
            with runlog.Run("latest", self.dir) as r:   # "re-run failed jobs": attempt 2
                r.done()
            with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "78", "GITHUB_RUN_ATTEMPT": "1"}):
                with runlog.Run("latest", self.dir) as r:
                    r.done()
            self.assertTrue(runlog.mark_verified(True, [], self.dir))
        marked = {(r["run"]["id"], r["run"]["attempt"]): r["verified"] for r in self.records()}
        self.assertEqual(marked, {("77", "1"): None, ("77", "2"): True, ("78", "1"): None})
        with mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "79"}):
            self.assertFalse(runlog.mark_verified(True, [], self.dir))

    def test_engine_change_without_a_version_bump_is_flagged(self):
        with runlog.Run("latest", self.dir) as r:
            r.done()
        r = runlog.Run("latest", self.dir)
        self.assertEqual(r.engine_warning(), [])
        r.rec["engine_hash"] = "0" * 16
        self.assertIn("ENGINE_VERSION is still", r.engine_warning()[0])

    def test_engine_files_cover_everything_the_diff_imports(self):
        """a new engine module left out of ENGINE_FILES would change output without the
        forgotten-bump warning ever firing."""
        here = os.path.dirname(runlog.__file__)
        todo, seen = ["pipeline"], set()
        while todo:
            m = todo.pop()
            if m in seen:
                continue
            seen.add(m)
            with open(os.path.join(here, f"{m}.py")) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    names = [node.module] if node.module else [a.name for a in node.names]
                    todo += [n for n in names if os.path.exists(os.path.join(here, f"{n}.py"))]
        self.assertEqual({f"{m}.py" for m in seen}, {f for f in runlog.ENGINE_FILES if f.endswith(".py")})
        self.assertIn("glossary.json", runlog.ENGINE_FILES)     # decides what a remark may say


@unittest.skipUnless(shutil.which("git"), "needs git")
class TestTwoBuildsPushCleanly(unittest.TestCase):
    """the workflow pushes run records with git pull --rebase. a build that queued behind another
    starts from a checkout without the other's data commit; when every build appended to one
    shared file per cycle, the rebase conflicted and that merge never deployed."""

    def git(self, cwd, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                               *args], cwd=cwd, check=True, capture_output=True, text=True)

    def test_records_from_two_builds_on_one_checkout_both_push(self):
        root = tempfile.mkdtemp()
        seed = os.path.join(root, "seed")
        self.git(root, "init", "-q", "-b", "master", seed)
        os.makedirs(os.path.join(seed, "audit", "runs"))
        with open(os.path.join(seed, "audit", "runs", "2026-09-03.json"), "w") as f:   # the first layout
            json.dump({"runlog_version": 1, "cycle": "2026-09-03", "runs": [
                {"runlog_version": 1, "mode": "latest", "run": {"id": "100", "attempt": "1"},
                 "started_at": "2026-09-28T11:35:22+00:00", "outcome": "built"}]}, f)
        self.git(seed, "add", "audit")
        self.git(seed, "commit", "-q", "-m", "start")
        self.git(root, "clone", "-q", "--bare", seed, "origin.git")
        clones = []
        for run_id in ("101", "102"):             # both check out the same commit
            clone = os.path.join(root, run_id)
            self.git(root, "clone", "-q", "origin.git", clone)
            actions_env(self, GITHUB_RUN_ID=run_id, GITHUB_RUN_ATTEMPT="1")
            with runlog.Run("latest", os.path.join(clone, "audit", "runs")) as r:
                r.done()
            self.git(clone, "add", "audit")
            self.git(clone, "commit", "-q", "-m", "data: run log")
            clones.append(clone)
        self.git(clones[0], "push", "-q", "origin", "HEAD:master")
        self.git(clones[1], "pull", "-q", "--rebase", "origin", "master")    # used to conflict here
        self.git(clones[1], "push", "-q", "origin", "HEAD:master")
        check = os.path.join(root, "check")
        self.git(root, "clone", "-q", "origin.git", check)
        self.assertEqual(sorted(r["run"]["id"] for r in runlog.runs(os.path.join(check, "audit", "runs"))),
                         ["100", "101", "102"])
        self.assertFalse(os.path.exists(os.path.join(check, "audit", "runs", "2026-09-03.json")))


class TestHistoryIsStamped(unittest.TestCase):
    def test_new_entries_carry_the_engine_version(self):
        old = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        self.addCleanup(os.chdir, old)
        os.makedirs("history")
        history.append({"from_cycle": "2026-09-03", "to_cycle": "2026-10-01",
                        "airports": {"VRB": [{"id": "x", "priority": "fyi", "summary": "s"}]}})
        with open("history/VRB.json") as f:
            [e] = json.load(f)["entries"]
        self.assertEqual((e["engine"], e["cycle"], e["id"]), (ENGINE_VERSION, "2026-10-01", "x"))


class TestAirspaceLeftOutIsSaid(unittest.TestCase):
    def test_unreadable_shapefile_means_includes_airspace_false(self):
        """meta.json used to say airspace was included when the shapefile failed to parse,
        so the scheduled check never retried it."""
        from amend.pipeline import run
        d = tempfile.mkdtemp()
        o, n, bad = (os.path.join(d, x) for x in ("2026-09-03_CSV.zip", "2026-10-01_CSV.zip", "bad.zip"))
        for p in (o, n):
            nasr_zip(p, {"APT_BASE.csv": "ARPT_ID,SITE_TYPE_CODE\rVRB,A\r"})
        nasr_zip(bad, {"Shape_Files/Class_Airspace.shp": b"garbage", "Shape_Files/Class_Airspace.dbf": b"x"})
        result = run(o, n, {"VRB"}, log=lambda *_: None, airspace=(bad, bad))
        self.assertFalse(result["includes_airspace"])
        self.assertIn("couldn't read the class airspace shapefile", result["airspace_error"])
        self.assertIsNone(result["airspace_shapes"])

        result = run(o, n, {"VRB"}, log=lambda *_: None)
        self.assertEqual((result["includes_airspace"], result["airspace_error"]), (False, None))

    def test_the_retry_downloads_the_airspace_zips_again(self):
        """includes_airspace false makes the next scheduled check rebuild. the unreadable zips
        must leave the cache, or that build reads the same files and fails the same way."""
        from amend import latest
        old_cwd = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        self.addCleanup(os.chdir, old_cwd)
        actions_env(self)
        cur = cycles.in_effect()
        nxt = cur + cycles.CYCLE
        os.makedirs(cycles.DATA)
        for p in (cycles.zip_path(cur), cycles.zip_path(nxt), cycles.airspace_path(cur), cycles.airspace_path(nxt)):
            with open(p, "wb") as f:
                f.write(b"PK")
            with open(cycles.meta_path(p), "w") as f:
                json.dump({"url": "u", "sha256": "s"}, f)
        result = {"from_cycle": cur.isoformat(), "to_cycle": nxt.isoformat(), "airports": {}, "hidden": {},
                  "csv_rows": {"old": {"APT_BASE.csv": 100}, "new": {"APT_BASE.csv": 100}},
                  "includes_airspace": False, "airspace_shapes": None,
                  "airspace_error": "couldn't read the class airspace shapefile (ValueError: x)"}
        pair = (cycles.airspace_path(cur), cycles.airspace_path(nxt))
        with mock.patch("amend.latest.get_cycle", return_value=True), \
                mock.patch("amend.latest.get_dtpp", return_value=None), \
                mock.patch("amend.latest.get_airspace_pair", return_value=pair), \
                mock.patch("amend.latest.run", return_value=result), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            latest.build(llm=False)                   # an empty diff: the audit stops it
        for d in (cur, nxt):
            self.assertFalse(os.path.exists(cycles.airspace_path(d)))
            self.assertFalse(os.path.exists(cycles.meta_path(cycles.airspace_path(d))))
            self.assertTrue(os.path.exists(cycles.zip_path(d)))          # NASR zips stay cached
        [rec] = runlog.runs()
        self.assertEqual([s["role"] for s in rec["sources"]],           # logged before they went
                         ["nasr_old", "nasr_new", "airspace_old", "airspace_new"])


if __name__ == "__main__":
    unittest.main()
