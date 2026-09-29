"""
A renumbered runway reads as one line, "runway 07/25 -> 08/26 (renumbered)", instead of a runway
removed and another added (amend/collapse.py _runway_changes). These pin what that step gets
right and document what it gets wrong today.

Real rows: MRI and WWR each renumbered two runways in the 2026-08-06 -> 09-03 cycle
(tests/fixtures/runway_renumber_mri_wwr.json, every APT_RWY and APT_RWY_END row at both). The
pairing is right, but the step drops the runway-end rows outright, and with them any other change
on that end: MRI's runway 25 -> 26 touchdown zone elevation went 137.3 -> 143.1 ft and nothing
says so.

Made-up rows: two runways the same size renumbered together get paired by size before number
(09/27 reads as renumbered to 01/19), and a runway the same size, 50 degrees off, is called
"renumbered".

Known misses run as expected failures, so this file blocks no deploy (update.yml runs every test
before it publishes). When collapse.py is fixed, the case it fixes turns into an "unexpected
success" and fails: remove its expectedFailure in the same PR.
run:  python -m unittest tests.test_runway_collapse -v
"""
import json
import os
import unittest

from amend.collapse import collapse
from amend.diff import diff

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "runway_renumber_mri_wwr.json")


def real(apt):
    """diff + collapse of one fixture airport's runway rows."""
    with open(FIXTURE, encoding="utf-8") as f:
        fx = json.load(f)
    side = lambda s: {fname: [(a, r) for a, r in rows if a == apt] for fname, rows in fx[s].items()}
    return collapse(diff(side("old"), side("new")))


def made_up(old, new):
    """collapse of APT_RWY rows [(RWY_ID, RWY_LEN, RWY_WIDTH), ...] removed and added."""
    rec = lambda kind, rid, ln, w: {"airport": "XYZ", "source": "APT_RWY.csv", "kind": kind, "priority": "action",
                                    "row": {"RWY_ID": rid, "RWY_LEN": ln, "RWY_WIDTH": w,
                                            "SURFACE_TYPE_CODE": "ASPH"}}
    return collapse([rec("removed", *r) for r in old] + [rec("added", *r) for r in new])


def said(recs):
    return sorted(r.get("summary_override", "") for r in recs if r.get("summary_override"))


class TestRealRenumberings(unittest.TestCase):
    def test_mri_pairs_by_number(self):
        s = said(real("MRI"))
        self.assertIn("runway 07/25 -> 08/26 (renumbered)", s)
        self.assertIn("runway 16/34 -> 17/35 (renumbered)", s)

    def test_wwr_pairs_by_number(self):
        s = said(real("WWR"))
        self.assertIn("runway 05/23 -> 06/24 (renumbered)", s)
        self.assertIn("runway 17/35 -> 18/36 (renumbered) (5502x100 -> 6002x100 ft)", s)

    def test_no_runway_reads_as_removed_or_added(self):
        for apt in ("MRI", "WWR"):
            recs = real(apt)
            self.assertEqual([r for r in recs if r["source"].startswith("APT_RWY")
                              and r["kind"] in ("added", "removed")], [], apt)

    @unittest.expectedFailure
    def test_mri_end_change_survives_the_renumbering(self):
        """runway end 25 -> 26: TDZ_ELEV 137.3 -> 143.1 has to be on some record after collapse."""
        fields = [f for r in real("MRI") for f in r.get("fields", [])]
        self.assertIn({"field": "TDZ_ELEV", "old": "137.3", "new": "143.1"}, fields)


class TestMadeUpRenumberings(unittest.TestCase):
    def test_one_runway_one_number(self):
        self.assertEqual(said(made_up([("09/27", "5000", "100")], [("10/28", "5000", "100")])),
                         ["runway 09/27 -> 10/28 (renumbered)"])

    @unittest.expectedFailure
    def test_same_size_pair_goes_by_number(self):
        s = said(made_up([("09/27", "5000", "100"), ("18/36", "5000", "100")],
                         [("01/19", "5000", "100"), ("10/28", "5000", "100")]))
        self.assertEqual(s, ["runway 09/27 -> 10/28 (renumbered)", "runway 18/36 -> 01/19 (renumbered)"])

    @unittest.expectedFailure
    def test_fifty_degrees_off_is_not_a_renumbering(self):
        s = said(made_up([("09/27", "5000", "100")], [("14/32", "5000", "100")]))
        self.assertEqual(len(s), 1)
        self.assertNotIn("(renumbered)", s[0])


if __name__ == "__main__":
    unittest.main()
