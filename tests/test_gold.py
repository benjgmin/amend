"""
The gold set: real FAA changes with the answer the engine should give, checked against the
FAA's own rows (tests/gold/cases.jsonl, how to add one: tests/gold/README.md).
run:  python -m unittest tests.test_gold -v      score it:  python -m amend.gold -v
"""
import collections
import unittest

from amend import gold


class TestGoldSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = gold.load_cases()
        cls.score = gold.score(cls.cases)

    def test_cases_are_well_formed(self):
        ids = collections.Counter(c.get("id") for c in self.cases)
        self.assertEqual([i for i, n in ids.items() if n > 1], [], "duplicate case ids")
        for c in self.cases:
            with self.subTest(case=c.get("id"), line=c["_line"]):
                self.assertEqual(gold.problems(c), [])

    def test_big_enough_and_varied(self):
        self.assertGreaterEqual(len(self.cases), 100)
        self.assertGreaterEqual(len({c["airport"] for c in self.cases}), 50)
        self.assertGreaterEqual(len({c["source"] for c in self.cases}), 15)
        for p in gold.PRIORITIES:
            self.assertTrue(any(c["expected"]["priority"] == p for c in self.cases), p)

    def test_every_case(self):
        """a case that fails is a regression, unless it's marked known_failure (a candidate
        engine bug nobody has fixed yet). a known failure that passes now needs its flag
        dropped, so the fix is on record."""
        for r in self.score["results"]:
            c = r["case"]
            with self.subTest(case=c["id"], airport=c["airport"], source=c["source"]):
                if c.get("known_failure"):
                    self.assertFalse(r["passed"], "passes now: remove known_failure from this case")
                else:
                    self.assertTrue(r["passed"], r["why"])


class TestScoring(unittest.TestCase):
    """the scorer itself, on made-up rows."""

    def case(self, old, new, expected, **kw):
        return {"id": "t", "source": "ATC_BASE.csv", "from_cycle": "2026-09-03", "cycle": "2026-10-01",
                "airport": "VRB", "field": "TWR_HRS", "old": old, "new": new, "kind": "changed",
                "rows": {"header": ["FACILITY_ID", "TWR_HRS"], "old": [["VRB", old]], "new": [["VRB", new]]},
                "expected": expected, "verified_by": "test", **kw}

    def test_counts(self):
        act = {"priority": "action", "category": "tower", "summary_contains": ["0700-0100"]}
        cases = [self.case("0700-2100", "0700-0100", act),                                  # right
                 self.case("0700-2100", "0700-0100", {"priority": "fyi", "category": "tower"}),   # false action
                 self.case("0700-2100", "0700-2100", act)]                                  # missed (hidden)
        s = gold.score(cases)
        self.assertEqual((s["total"], s["passed"], s["false_action"], s["missed_action"]), (3, 1, 1, 1))

    def test_hidden_and_bad_cases(self):
        s = gold.score([self.case("0700-2100", "0700-2100", {"priority": "hidden"}),
                        self.case("0700-2100", "0700-0100", {"priority": "urgent"})])
        self.assertEqual([r["passed"] for r in s["results"]], [True, False])
        self.assertIn("bad case", s["results"][1]["why"])

    def test_known_failure_that_passes_is_reported(self):
        s = gold.score([self.case("0700-2100", "0700-0100", {"priority": "action", "category": "tower"},
                                  known_failure=True)])
        self.assertEqual(s["fixed"], ["t"])

    def test_translations_never_leak_in(self):
        """the repo's remark_cache.json grows every cycle; it must not change what the gold set sees."""
        import json, os, tempfile
        from amend import remarks
        raw = "RWY 09 IS CLSD MON."
        cache = os.path.join(tempfile.mkdtemp(), "cache.json")
        with open(cache, "w") as f:
            json.dump({raw: "Runway 09 is closed Mondays."}, f)
        real, remarks.CACHE_FILE = remarks.CACHE_FILE, cache
        try:
            c = self.case("x", "y", {"priority": "fyi", "category": "remark"})
            c.update(source="APT_RMK.csv", field="REMARK", airport="X",
                     rows={"header": ["ARPT_ID", "LEGACY_ELEMENT_NUMBER", "REMARK"],
                           "old": [["X", "A1", "RWY 09 IS CLSD."]], "new": [["X", "A1", raw]]})
            self.assertIn(raw, gold.run_case(c)[0]["summary"])
            self.assertEqual(remarks.CACHE_FILE, cache)
        finally:
            remarks.CACHE_FILE = real

if __name__ == "__main__":
    unittest.main()


class TestRecordReviews(unittest.TestCase):
    """python -m amend.gold --record: an instructor's answers go into the cases file, and only
    answered cases count."""

    def setUp(self):
        import shutil, tempfile, os
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "cases.jsonl")
        shutil.copy(gold.CASES, self.path)
        self.before = open(self.path, encoding="utf-8").read()

    def responses(self, answers, **kw):
        return {"id": "r1", "packet": "instructor-review-v1", "date": "2026-09-30",
                "reviewer": {"credit": "J.S.", "certificates": "CFII", "contact": "js@example.com"},
                "answers": answers, **kw}

    def test_only_answered_cases_are_recorded(self):
        res = gold.record(self.responses({
            "g002": {"verdict": "right"},
            "g005": {"verdict": "wrong", "why": ["too_low", "bogus"], "note": "night closure matters"},
            "g016": {"verdict": "unsure"},
            "g034": {"verdict": ""}, "g046": {}, "g999": {"verdict": "right"}}), self.path)
        self.assertEqual(res["added"], [("g002", "right"), ("g005", "wrong"), ("g016", "unsure")])
        self.assertEqual(res["skipped"], ["g034", "g046"])
        self.assertEqual(res["unknown"], ["g999"])
        cases = {c["id"]: c for c in gold.load_cases(self.path)}
        for c in cases.values():
            self.assertEqual(gold.problems(c), [], c["id"])
        self.assertTrue(gold.checked_by_person(cases["g002"]))
        self.assertFalse(gold.checked_by_person(cases["g005"]))
        self.assertFalse(gold.checked_by_person(cases["g016"]), "not sure is not a check")
        self.assertFalse(gold.checked_by_person(cases["g034"]), "blank is not a check")
        self.assertTrue(gold.disputed(cases["g005"]))
        self.assertEqual(cases["g005"]["reviews"][0]["why"], ["too_low"])
        self.assertEqual(cases["g005"]["expected"]["priority"], "action", "a wrong verdict never edits the answer")
        self.assertEqual(cases["g002"]["reviews"][0]["by"], "J.S., flight instructor (CFII)")
        self.assertNotIn("js@example.com", open(self.path, encoding="utf-8").read())

    def test_untouched_lines_stay_byte_for_byte(self):
        gold.record(self.responses({"g002": {"verdict": "right"}}), self.path)
        old, new = self.before.split("\n"), open(self.path, encoding="utf-8").read().split("\n")
        self.assertEqual(len(old), len(new))
        self.assertEqual(sum(a != b for a, b in zip(old, new)), 1)

    def test_same_packet_twice_adds_nothing(self):
        gold.record(self.responses({"g002": {"verdict": "right"}}), self.path)
        res = gold.record(self.responses({"g002": {"verdict": "right"}}), self.path)
        self.assertEqual(res["added"], [])
        other = gold.record(self.responses({"g002": {"verdict": "right"}}, id="r2",
                                           reviewer={"credit": "", "certificates": "CFI"}), self.path)
        self.assertEqual(other["added"], [("g002", "right")])
        c = {c["id"]: c for c in gold.load_cases(self.path)}["g002"]
        self.assertEqual([r["by"] for r in c["reviews"]],
                         ["J.S., flight instructor (CFII)", "flight instructor (CFI), not named"])

    def test_dry_run_writes_nothing(self):
        gold.record(self.responses({"g002": {"verdict": "right"}}), self.path, write=False)
        self.assertEqual(open(self.path, encoding="utf-8").read(), self.before)

    def test_bad_review_is_caught(self):
        case = {"reviews": [{"by": "", "verdict": "yes", "date": ""}]}
        self.assertEqual(len(gold.review_problems(case["reviews"][0])), 3)
