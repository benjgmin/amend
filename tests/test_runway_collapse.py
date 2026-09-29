"""
A renumbered runway reads as one line, "runway 07/25 -> 08/26 (renumbered)", instead of a runway
removed and another added (amend/collapse.py _runway_changes).

Real rows: MRI and WWR each renumbered two runways in the 2026-08-06 -> 09-03 cycle
(tests/fixtures/runway_renumber_mri_wwr.json, every APT_RWY and APT_RWY_END row at both). Before
engine 1.3.8 the step dropped the runway-end rows outright, and with them any other change on
that end: MRI's runway 25 -> 26 touchdown zone elevation went 137.3 -> 143.1 ft and nothing said
so. Now each end is compared old against new under its new number.

Made-up rows, each after a real case: two runways the same size renumbered together paired by
size before number (09/27 read as renumbered to 01/19; TUS 2023-11-30 paired its new 12/30 with
the wrong parallel). What decides "renumbered" was checked against the FAA's own end positions in
every cycle since 2022.
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
    """collapse of APT_RWY rows removed and added: [(RWY_ID, RWY_LEN, RWY_WIDTH), ...], or with a
    fourth item {end id: {column: value}} for that runway's APT_RWY_END rows."""
    recs = []
    for kind, rwys in (("removed", old), ("added", new)):
        for rid, ln, w, *ends in rwys:
            recs.append({"airport": "XYZ", "source": "APT_RWY.csv", "kind": kind, "priority": "action",
                         "row": {"RWY_ID": rid, "RWY_LEN": ln, "RWY_WIDTH": w, "SURFACE_TYPE_CODE": "ASPH"}})
            for end, cols in (ends[0] if ends else {}).items():
                recs.append({"airport": "XYZ", "source": "APT_RWY_END.csv", "kind": kind, "priority": "action",
                             "row": {"RWY_ID": rid, "RWY_END_ID": end, **cols}})
    return collapse(recs)


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

    def test_mri_end_change_survives_the_renumbering(self):
        """runway end 25 -> 26: TDZ_ELEV 137.3 -> 143.1 has to be on some record after collapse."""
        fields = [f for r in real("MRI") for f in r.get("fields", [])]
        self.assertIn({"field": "TDZ_ELEV", "old": "137.3", "new": "143.1"}, fields)


class TestMadeUpRenumberings(unittest.TestCase):
    def test_one_runway_one_number(self):
        self.assertEqual(said(made_up([("09/27", "5000", "100")], [("10/28", "5000", "100")])),
                         ["runway 09/27 -> 10/28 (renumbered)"])

    def test_same_size_pair_goes_by_number(self):
        s = said(made_up([("09/27", "5000", "100"), ("18/36", "5000", "100")],
                         [("01/19", "5000", "100"), ("10/28", "5000", "100")]))
        self.assertEqual(s, ["runway 09/27 -> 10/28 (renumbered)", "runway 18/36 -> 01/19 (renumbered)"])

    def test_parallels_pair_by_size(self):
        """TUS 2023-11-30: 11L/29R became 12/30 (same ends, same size) and 11R/29L closed.
        both parallels are one number from 12 and point the same way; the size tells them apart."""
        side = lambda: {"TRUE_ALIGNMENT": "135"}
        recs = made_up([("11L/29R", "10996", "150", {"11L": side()}), ("11R/29L", "8408", "75", {"11R": side()})],
                       [("12/30", "10996", "150", {"12": side()})])
        self.assertEqual(said(recs), ["runway 11L/29R -> 12/30 (renumbered)"])
        self.assertEqual([r["row"]["RWY_ID"] for r in recs if r["kind"] == "removed"
                          and r["source"] == "APT_RWY.csv"], ["11R/29L"])

    def test_same_size_far_apart_is_still_renumbered(self):
        """the same length and width is the same strip whatever the new number: E70 16/34 ->
        18/36 (2023-09-07), A34 05/23 -> 07/25 and 1NY3 18/36 -> 16/34 kept their ends where
        they were. 9 of these since 2022, none a new runway."""
        self.assertEqual(said(made_up([("16/34", "3000", "60")], [("18/36", "3000", "60")])),
                         ["runway 16/34 -> 18/36 (renumbered)"])

    def test_ends_the_other_way_round_at_another_heading_is_a_new_runway(self):
        """I34 2024-07-11: 18/36 at 180 degrees true became a longer 01/19 at 186, somewhere
        else on the field. 36 -> 01 alone doesn't make it the same strip."""
        s = said(made_up([("18/36", "3433", "40", {"18": {"TRUE_ALIGNMENT": "180"}, "36": {"TRUE_ALIGNMENT": "360"}})],
                         [("01/19", "5405", "100", {"01": {"TRUE_ALIGNMENT": "6"}, "19": {"TRUE_ALIGNMENT": "186"}})]))
        self.assertEqual(s, ["runway 18/36 -> 01/19 (new runway) (3433x40 -> 5405x100 ft)"])

    def test_ends_listed_the_other_way_round(self):
        """FSO 2026-03-19: 01/19 -> 18/36, lengthened at one end. 19 is now 18 and 01 is now 36,
        so a new displaced threshold on the old 19 end reads as runway 18."""
        recs = made_up([("01/19", "3001", "60", {"01": {"TRUE_ALIGNMENT": "349"},
                                                 "19": {"TRUE_ALIGNMENT": "169"}})],
                       [("18/36", "4001", "75", {"18": {"TRUE_ALIGNMENT": "169", "DISPLACED_THR_LEN": "300"},
                                                 "36": {"TRUE_ALIGNMENT": "349"}})])
        self.assertEqual(said(recs), ["runway 01/19 -> 18/36 (renumbered) (3001x60 -> 4001x75 ft)"])
        ends = [(r["context"]["RWY_END_ID"], r["fields"]) for r in recs if r["source"] == "APT_RWY_END.csv"]
        self.assertEqual(ends, [("18", [{"field": "DISPLACED_THR_LEN", "old": "", "new": "300"}])])

    def test_a_new_runway_keeps_its_ends_to_itself(self):
        """a replaced runway's ends are other ends: no end-by-end comparison, the one line says it."""
        recs = made_up([("18W/36W", "5370", "2300", {"18W": {"TRUE_ALIGNMENT": "175"}})],
                       [("16W/34W", "11936", "2000", {"16W": {"TRUE_ALIGNMENT": "155"}})])
        self.assertEqual(said(recs), ["runway 18W/36W -> 16W/34W (new runway) (5370x2300 -> 11936x2000 ft)"])
        self.assertEqual([r for r in recs if r["source"] == "APT_RWY_END.csv"], [])

if __name__ == "__main__":
    unittest.main()
