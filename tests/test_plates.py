"""plates: the courses printed on a changed chart, old edition against new (amend/plates.py)."""
import datetime as dt
import json
import os
import tempfile
import unittest

from amend import charthistory, dtpp, plates
from amend.freshness import decide

# what pypdf pulls off a real plate (05D RNAV (GPS) RWY 12, 2610), cut down: the courses come out
# as 125°, the glide path as 3.00° and the coordinates as 47°58'N, and a hold reads 215°215°
PLATE_TEXT = """APP CRS
305°
125°
TDZE 1924
RNAV (GPS) RWY 12
47°58'N-102°29'W
125°
SUSUE4500
125°
035°
215°215°
TCH 40
3.00°"""


class TestCourses(unittest.TestCase):
    def test_reads_courses_not_glide_paths_or_coordinates(self):
        self.assertEqual(plates.courses(PLATE_TEXT),
                         {"035": 1, "125": 3, "215": 2, "305": 1})

    def test_airport_diagram_headings_keep_their_tenths(self):
        self.assertEqual(plates.courses("RWY 12-30\n124.6°\n304.6°"), {"124.6": 1, "304.6": 1})

    def test_never_more_than_360(self):
        self.assertEqual(plates.courses("400° 361° 360°"), {"360": 1})


class TestCourseChanges(unittest.TestCase):
    def test_magnetic_variation_update(self):
        """every course on an ILS plate turned 2-3 degrees (2611, an Alaska ILS)."""
        old = {"074": 5, "254": 1, "210": 2, "030": 1, "120": 3}
        new = {"076": 5, "256": 1, "210": 1, "213": 2, "033": 1, "120": 3}
        self.assertEqual(plates.course_changes(old, new),
                         [("030", "033"), ("074", "076"), ("210", "213"), ("254", "256")])

    def test_a_course_printed_fewer_times_counts_as_gone(self):
        """one leg turned a degree while the same number stays printed on another leg."""
        old = {"174": 2, "175": 2, "355": 3}
        new = {"174": 1, "175": 3, "355": 3}
        self.assertEqual(plates.course_changes(old, new), [("174", "175")])

    def test_wraps_through_north(self):
        old = {"360": 4, "180": 6, "090": 3}
        new = {"005": 5, "185": 7, "095": 3}
        self.assertEqual(plates.course_changes(old, new), [("090", "095"), ("180", "185"), ("360", "005")])

    def test_more_than_five_degrees_is_not_a_pair(self):
        self.assertEqual(plates.course_changes({"072": 3, "252": 1}, {"080": 3, "252": 1}), [])

    def test_a_redesign_reports_nothing(self):
        """a STAR rebuilt with new legs: one old leg lands near an unrelated new one, and that's no
        reason to say it moved (2611: an ADERY leg 239° went and a SAV leg 241° came)."""
        old = {"085": 1, "059": 2, "030": 2, "042": 2, "077": 2, "086": 1, "239": 1, "038": 1}
        new = {"060": 1, "241": 1, "021": 1, "100": 1, "185": 1, "049": 2, "335": 1, "064": 2}
        self.assertEqual(plates.course_changes(old, new), [])

    def test_two_near_matches_are_not_a_pair(self):
        self.assertEqual(plates.course_changes({"072": 2, "300": 2}, {"070": 2, "074": 2, "300": 2}), [])

    def test_no_text_on_one_side_reports_nothing(self):
        """an old plate with no text layer has no courses; that isn't every course removed."""
        self.assertEqual(plates.course_changes({}, {"072": 4, "252": 2}), [])
        self.assertEqual(plates.course_changes({"072": 1}, {"070": 1}), [])

    def test_previous_edition(self):
        self.assertEqual(plates.previous(dt.date(2026, 9, 3)), "2608")
        self.assertEqual(plates.previous(dt.date(2026, 1, 22)), "2513")
        self.assertEqual(plates.previous(dt.date(2026, 2, 19)), "2601")


def metafile(records, cycle="2611", edate="10/29/26"):
    """a d-TPP metafile: records are (airport, code, name, action, pdf, amdt, amdt date)."""
    path = os.path.join(tempfile.mkdtemp(), "meta.xml")
    with open(path, "w") as f:
        f.write(f'<digital_tpp cycle="{cycle}" from_edate="0901Z  {edate}">')
        for apt, code, name, act, pdf, amdt, date in records:
            f.write(f'<airport_name apt_ident="{apt}"><record><chart_code>{code}</chart_code>'
                    f'<chart_name>{name}</chart_name><useraction>{act}</useraction>'
                    f'<pdf_name>{pdf}</pdf_name><amdtnum>{amdt}</amdtnum><amdtdate>{date}</amdtdate>'
                    f'</record></airport_name>')
        f.write("</digital_tpp>")
    return path


def plate(courses):
    return {"sha256": "x", "courses": courses}


class TestChartSummaries(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        plates.forget()

    def tearDown(self):
        plates.forget()

    def charts(self, records, **kw):
        return {apt: [r["summary_override"] for r in recs]
                for apt, recs in dtpp.load_dtpp(metafile(records, **kw), {"BJC", "FDK", "PAO"},
                                                self.root).items()}

    def test_amended_redrawn_or_changed(self):
        got = self.charts([
            ("BJC", "IAP", "ILS RWY 30R", "C", "B1.PDF", "4", "10/29/2026"),    # amended this edition
            ("FDK", "IAP", "RNAV (GPS) RWY 23", "C", "F1.PDF", "1C", "04/23/2020"),  # same amendment
            ("PAO", "IAP", "RNAV (GPS) RWY 31", "C", "P1.PDF", "2", ""),        # the FAA gives no date
            ("PAO", "IAP", "VOR RWY 13", "C", "P2.PDF", "ORIG", "06/11/2015")])
        self.assertEqual(got, {"BJC": ["approach ILS RWY 30R amended (amdt 4)"],
                               "FDK": ["approach RNAV (GPS) RWY 23 redrawn (still amdt 1C)"],
                               "PAO": ["approach RNAV (GPS) RWY 31 changed (amdt 2)",
                                       "approach VOR RWY 13 redrawn (still original)"]})

    def test_courses_that_moved_on_the_plate(self):
        plates.save("2610", {"F1.PDF": plate({"072": 4, "252": 1, "300": 2})}, self.root)
        plates.save("2611", {"F1.PDF": plate({"070": 4, "250": 1, "300": 2})}, self.root)
        recs = dtpp.load_dtpp(metafile([("FDK", "IAP", "ILS RWY 23", "C", "F1.PDF", "32A", "02/28/2019")]),
                              {"FDK"}, self.root)["FDK"]
        self.assertEqual(recs[0]["summary_override"],
                         "approach ILS RWY 23 redrawn (still amdt 32A): 072° now 070°, 252° now 250° on the chart")
        self.assertEqual(recs[0]["details"], ["printed on the chart: 072° -> 070°",
                                              "printed on the chart: 252° -> 250°"])
        self.assertEqual(recs[0]["chart"], {"code": "IAP", "name": "ILS RWY 23", "amdt": "32A",
                                            "pdf": "https://aeronav.faa.gov/d-tpp/2611/F1.PDF"})

    def test_more_than_three_courses_are_counted(self):
        plates.save("2610", {"F1.PDF": plate({"010": 1, "100": 1, "190": 1, "280": 1})}, self.root)
        plates.save("2611", {"F1.PDF": plate({"012": 1, "102": 1, "192": 1, "282": 1})}, self.root)
        got = self.charts([("FDK", "DP", "CATOC TWO", "C", "F1.PDF", "", "")])
        self.assertEqual(got["FDK"], ["departure CATOC TWO changed: 010° now 012°, 100° now 102°, "
                                      "190° now 192° and 1 more on the chart"])

    def test_a_page_shared_by_many_airports_says_no_number(self):
        """a state's TAKEOFF MINIMUMS page is one pdf filed under every airport on it: a heading
        that moved there belongs to one of them, not all."""
        plates.save("2610", {"NE1TO.PDF": plate({"172": 2, "300": 2, "010": 1})}, self.root)
        plates.save("2611", {"NE1TO.PDF": plate({"176": 2, "300": 2, "010": 1})}, self.root)
        got = self.charts([("FDK", "MIN", "TAKEOFF MINIMUMS", "C", "NE1TO.PDF", "", ""),
                           ("BJC", "MIN", "TAKEOFF MINIMUMS", "C", "NE1TO.PDF", "", "")])
        self.assertEqual(got, {"FDK": ["minimums page (TAKEOFF MINIMUMS) changed"],
                               "BJC": ["minimums page (TAKEOFF MINIMUMS) changed"]})

    def test_a_plate_not_read_says_no_number(self):
        plates.save("2611", {"F1.PDF": plate({"070": 4})}, self.root)      # old edition never read
        plates.save("2610", {"F1.PDF": None}, self.root)                   # or the FAA didn't serve it
        got = self.charts([("FDK", "IAP", "ILS RWY 23", "C", "F1.PDF", "32A", "02/28/2019")])
        self.assertEqual(got["FDK"], ["approach ILS RWY 23 redrawn (still amdt 32A)"])

    def test_changed_pdfs(self):
        path = metafile([("FDK", "IAP", "ILS RWY 23", "C", "F1.PDF", "1", ""),
                         ("FDK", "IAP", "ILS RWY 23, CONT.1", "C", "F1C1.PDF", "1", ""),
                         ("FDK", "IAP", "VOR RWY 5", "D", "DELETED_JOB.PDF", "", ""),
                         ("FDK", "IAP", "RNAV (GPS) RWY 5", "A", "F2.PDF", "", ""),
                         ("BJC", "APD", "AIRPORT DIAGRAM", "C", "B9AD.PDF", "", "")])
        self.assertEqual(dtpp.changed_pdfs(path), ("2611", dt.date(2026, 10, 29), ["B9AD.PDF", "F1.PDF"]))


class TestUpdate(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        plates.forget()
        self.log = []

    def test_reads_each_plate_once(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("needs pypdf")
        asked = []
        real = plates.read

        def get(url):
            asked.append(url)
            return None if "GONE" in url else b"%PDF-1.4 fake"
        plates.read = lambda b: {**plate({"072": 1}), "minimums": None}
        try:
            left = plates.update("2610", "2611", ["A.PDF", "GONE.PDF"], root=self.root, get=get,
                                 log=self.log.append)
            self.assertEqual(left, 0)
            self.assertEqual(plates.load("2610", self.root),
                             {"A.PDF": {**plate({"072": 1}), "minimums": None}, "GONE.PDF": None})
            n = len(asked)
            self.assertEqual(plates.update("2610", "2611", ["A.PDF", "GONE.PDF"], root=self.root, get=get), 0)
            self.assertEqual(len(asked), n)       # nothing asked twice, a 404 included
        finally:
            plates.read = real

    def test_a_broken_download_is_tried_again_then_given_up(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("needs pypdf")

        def get(url):
            raise TimeoutError
        for i in range(plates.GIVE_UP):
            left = plates.update("2610", "2611", ["A.PDF"], root=self.root, get=get, log=self.log.append)
            self.assertEqual(left, 2 if i < plates.GIVE_UP - 1 else 0)
        self.assertEqual(plates.load("2611", self.root), {"A.PDF": {"failed": plates.GIVE_UP}})

    def test_out_of_time_leaves_the_rest_for_the_next_build(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("needs pypdf")
        left = plates.update("2610", "2611", ["A.PDF", "B.PDF"], budget=-1, root=self.root,
                             get=lambda url: b"%PDF", log=self.log.append)
        self.assertEqual(left, 4)
        self.assertEqual(plates.load("2611", self.root), {})


    def test_a_plate_read_before_minimums_is_read_again_once(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("needs pypdf")
        plates.save("2610", {"A.PDF": plate({"072": 1}), "GONE.PDF": plate({"072": 1})}, self.root)
        plates.save("2611", {"A.PDF": plate({"070": 1}), "GONE.PDF": plate({"070": 1})}, self.root)
        real = plates.read
        plates.read = lambda b: {**plate({"070": 1}), "minimums": {"alts": ["700"], "rvr": {}, "vis": {}}}
        try:
            left = plates.update("2610", "2611", ["A.PDF", "GONE.PDF"], root=self.root,
                                 get=lambda url: None if "GONE" in url else b"%PDF", log=self.log.append)
        finally:
            plates.read = real
        self.assertEqual(left, 0)
        got = plates.load("2610", self.root)
        self.assertEqual(got["A.PDF"]["minimums"], {"alts": ["700"], "rvr": {}, "vis": {}})
        # the FAA no longer serves it: the courses read earlier stay, and it isn't asked again
        self.assertEqual(got["GONE.PDF"], {**plate({"072": 1}), "minimums": None})


# what pypdf pulls off a real approach plate's minimums (2611, cut down): "680/24 444 (500-½)" is
# a DA with its RVR, height above touchdown and that height rounded; the touchdown zone is 236
MINS_TEXT = """TDZE 236
680/24 444 (500-   )12
740-1
504 (600-1) 624 (700-1)
860-1
1496 (1500-1)6
503/50 290 (300-1)"""


class TestMinimums(unittest.TestCase):
    def test_reads_minimums_that_sit_above_the_touchdown_zone(self):
        """503 has its own height (290), so 213 is a base too; 1496 is glued to a 6 and isn't a
        minimum (14966 has no height that lands on 236 or 213)."""
        self.assertEqual(plates.minimums(MINS_TEXT),
                         {"alts": ["503", "680", "740", "860"], "rvr": {"503": ["50"], "680": ["24"]},
                          "vis": {"740": ["1"], "860": ["1"]}})

    def test_a_split_fraction_is_not_a_visibility(self):
        self.assertEqual(plates.minimums("680-1   467 (500-1)\n680-11 467")["vis"], {"680": ["1"]})

    def test_minimum_changes(self):
        old = {"alts": ["503", "680", "860"], "rvr": {"503": ["50"], "680": ["24"]}, "vis": {"860": ["1"]}}
        new = {"alts": ["503", "700", "860"], "rvr": {"503": ["45"], "700": ["24"]}, "vis": {"860": ["1½"]}}
        self.assertEqual(plates.minimum_changes(old, new),
                         [("minimum", "680", "700", None), ("rvr", "50", "45", "503"),
                          ("visibility", "1", "1½", "860")])

    def test_a_redesigned_approach_says_no_minimum(self):
        old = {"alts": ["600", "740", "760", "422"], "rvr": {}, "vis": {}}
        new = {"alts": ["720", "780", "513"], "rvr": {}, "vis": {}}
        self.assertEqual(plates.minimum_changes(old, new), [])

    def test_more_than_200_feet_is_not_a_pair(self):
        self.assertEqual(plates.minimum_changes({"alts": ["680"]}, {"alts": ["900"]}), [])

    def test_no_minimums_on_one_side_says_nothing(self):
        self.assertEqual(plates.minimum_changes({"alts": []}, {"alts": ["700"]}), [])
        self.assertEqual(plates.minimum_changes(None, {"alts": ["700"]}), [])

    def test_approach_summary(self):
        root = tempfile.mkdtemp()
        plates.forget()
        old = {"sha256": "x", "courses": {"072": 4, "252": 1, "300": 2},
               "minimums": {"alts": ["680", "1542"], "rvr": {"1542": ["40"]}, "vis": {}}}
        new = {"sha256": "y", "courses": {"072": 4, "252": 1, "300": 2},
               "minimums": {"alts": ["700", "1542"], "rvr": {"1542": ["26"]}, "vis": {}}}
        plates.save("2610", {"F1.PDF": old, "F2.PDF": old}, root)
        plates.save("2611", {"F1.PDF": new, "F2.PDF": new}, root)
        recs = dtpp.load_dtpp(metafile([("FDK", "IAP", "ILS RWY 23", "C", "F1.PDF", "32A", "10/29/2026"),
                                        ("FDK", "DP", "CATOC TWO", "C", "F2.PDF", "", "")]),
                              {"FDK"}, root)["FDK"]
        plates.forget()
        self.assertEqual(recs[0]["summary_override"], "approach ILS RWY 23 amended (amdt 32A): "
                                                      "minimum 680 now 700, RVR 4000 now 2600 at minimum 1542")
        self.assertEqual(recs[0]["details"], ["minimums on the plate: minimum 680 -> 700",
                                              "minimums on the plate: RVR 4000 -> 2600 at minimum 1542"])
        # only an approach has minimums; a departure's numbers aren't read as them
        self.assertEqual(recs[1]["summary_override"], "departure CATOC TWO changed")


class TestRebuildUntilRead(unittest.TestCase):
    def test_check_rebuilds_while_plates_are_unread(self):
        now = dt.datetime(2026, 10, 9, 12, tzinfo=dt.timezone.utc)
        meta = {"to_cycle": "2026-10-29", "upcoming": True, "includes_charts": True,
                "includes_airspace": True, "generated": now.isoformat()}
        build = {"inputs": "h"}
        posted = lambda url: True
        why = decide(now, {**meta, "includes_plates": False}, build, "h", ["2026-10-01"], posted)
        self.assertEqual(why, ["the changed plates for 2026-10-29 aren't all read yet"])
        self.assertEqual(decide(now, {**meta, "includes_plates": True}, build, "h", ["2026-10-01"], posted), [])
        # sites built before plates were read say nothing about them: no rebuild for that alone
        self.assertEqual(decide(now, meta, build, "h", ["2026-10-01"], posted), [])


class TestChartHistory(unittest.TestCase):
    def test_history_says_it_the_new_way_and_keeps_ids(self):
        root, hist = tempfile.mkdtemp(), tempfile.mkdtemp()
        plates.forget()
        plates.save("2610", {"F1.PDF": plate({"072": 4, "252": 1})}, root)
        plates.save("2611", {"F1.PDF": plate({"070": 4, "250": 1})}, root)
        entry = {"cycle": "2026-10-29", "from_cycle": "2026-10-01", "id": "keepme", "priority": "ifr",
                 "category": "chart", "kind": "changed", "source": "D-TPP",
                 "summary": "approach ILS RWY 23 amended (amdt 32A)",
                 "chart": {"code": "IAP", "name": "ILS RWY 23", "amdt": "32A"}}
        other = {**entry, "cycle": "2026-10-01", "id": "older"}
        with open(os.path.join(hist, "FDK.json"), "w") as f:
            json.dump({"airport": "FDK", "entries": [entry, other]}, f)
        meta = metafile([("FDK", "IAP", "ILS RWY 23", "C", "F1.PDF", "32A", "02/28/2019")])
        self.assertEqual(charthistory.redo(meta, hist, root), (1, 1, 1, 1))
        with open(os.path.join(hist, "FDK.json")) as f:
            got = json.load(f)["entries"]
        self.assertEqual(got[0]["id"], "keepme")
        self.assertEqual(got[0]["summary"],
                         "approach ILS RWY 23 redrawn (still amdt 32A): 072° now 070°, 252° now 250° on the chart")
        self.assertEqual(got[0]["details"], ["printed on the chart: 072° -> 070°", "printed on the chart: 252° -> 250°"])
        self.assertEqual(got[1], other)       # another cycle's entry is left alone
        self.assertEqual(charthistory.redo(meta, hist, root), (0, 1, 1, 0))    # safe to run again
        plates.forget()


if __name__ == "__main__":
    unittest.main()
