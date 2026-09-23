"""
Regression tests built from real cases found in FAA data.
run:  python -m unittest -v
"""
import io
import os
import tempfile
import unittest
import zipfile

from cyclewatch.pipeline import cycle_label, run


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in files.items():
            z.writestr(name, "\r".join(rows) + "\r")   # FAA files use old-mac line endings


class Case(unittest.TestCase):
    def diff(self, old, new, ids=None, dtpp=None):
        d = tempfile.mkdtemp()
        o, n = os.path.join(d, "2026-09-03_CSV.zip"), os.path.join(d, "2026-10-01_CSV.zip")
        make_zip(o, old)
        make_zip(n, new)
        return run(o, n, ids, dtpp, log=lambda *_: None)["airports"]

    def summaries(self, changes, priority=None):
        return [c["summary"] for c in changes if priority in (None, c["priority"])]


class TestRules(Case):
    def test_tower_hours_once_across_files(self):
        """VRB: tower hours live in ATC_BASE, FRQ and CLS_ARSP; report them once."""
        old = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "VRB,0700-2100"],
               "FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,TOWER_HRS", "VRB,VRB,126.3,0700-2100"]}
        new = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "VRB,0700-0100"],
               "FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,TOWER_HRS", "VRB,VRB,126.3,0700-0100"]}
        s = self.summaries(self.diff(old, new, {"VRB"})["VRB"], "action")
        self.assertEqual(s, ["tower hours changed: 0700-2100 -> 0700-0100 local"])

    def test_frequency_belongs_to_served_airport(self):
        """DAB approach serving NSB is NSB's frequency, not DAB's."""
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ", "DAB,NSB,125.30"]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ", "DAB,NSB,125.35"]}
        self.assertNotIn("DAB", self.diff(old, new, {"DAB"}))

    def test_navaid_type_change(self):
        """TRV (Treasure): VORTAC -> DME, even with a BOM on the header."""
        old = {"NAV_BASE.csv": ["\ufeffNAV_ID,NAV_TYPE,NAME,CITY", "TRV,VORTAC,TREASURE,VRB"]}
        new = {"NAV_BASE.csv": ["\ufeffNAV_ID,NAV_TYPE,NAME,CITY", "TRV,DME,TREASURE,VRB"]}
        s = self.summaries(self.diff(old, new, {"VRB"})["VRB"])
        self.assertIn("TRV (Treasure) navaid: now a DME (was a VORTAC)", s)

    def test_tpa_does_not_match_tampa(self):
        old = {"PFR_RMT_FMT.csv": ["Orig,Route String,Dest,Type", "DAB,DAB WORAK DADES1 TPA,TPA,L"]}
        new = {"PFR_RMT_FMT.csv": ["Orig,Route String,Dest,Type", "DAB,DAB WORAK DADES2 TPA,TPA,L"]}
        ch = self.diff(old, new, {"DAB"})["DAB"]
        self.assertEqual([c["priority"] for c in ch], ["ifr"])

    def test_star_frequency_label_is_fyi(self):
        """M02: new STAR names listed on an existing approach frequency aren't alerts."""
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "BNA,M02,118.4,APCH/P"]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "BNA,M02,118.4,APCH/P",
                           "BNA,M02,118.4,ALLLN STAR", "BNA,M02,122.9,CTAF"]}
        ch = self.diff(old, new, {"M02"})["M02"]
        self.assertEqual(self.summaries(ch, "action"), ["frequency 122.9 (CTAF) added"])

    def test_reworded_remark_is_fyi(self):
        old = {"APT_RMK.csv": ["ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK",
                               "SPS,A1,MIL ARPT CONDUCTS HI PER JET TRNG MON-FRI 1200-0200Z++."]}
        new = {"APT_RMK.csv": ["ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK",
                               "SPS,A1,MIL ARPT CONDUCTS HI PERFORMANCE JET TRNG MON-FRI 1200-0200Z++."]}
        self.assertEqual(self.diff(old, new, {"SPS"})["SPS"][0]["priority"], "fyi")

    def test_rco_removal_is_fyi(self):
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "BFD,BFD,122.2,BRADFORD RCO"]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE"]}
        c = self.diff(old, new, {"BFD"})["BFD"][0]
        self.assertEqual((c["priority"], c["summary"]),
                         ("fyi", "flight service (FSS) 122.2 via the Bradford outlet no longer available"))


class TestRunways(Case):
    def rwy(self, rows):
        return {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "CMY,X"],
                "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE", *rows]}

    def test_renumbered(self):
        ch = self.diff(self.rwy(["CMY,01/19,3032,95,ASPH"]), self.rwy(["CMY,02/20,3032,95,ASPH"]))
        self.assertEqual(self.summaries(ch["CMY"]), ["runway 01/19 renumbered to 02/20"])

    def test_renumbered_and_remeasured(self):
        ch = self.diff(self.rwy(["CMY,10/28,2800,100,TURF"]), self.rwy(["CMY,09/27,2803,60,TURF"]))
        self.assertEqual(self.summaries(ch["CMY"]),
                         ["runway 10/28 renumbered to 09/27 (now 2803x60 ft, was 2800x100)"])

    def test_wraparound(self):
        ch = self.diff(self.rwy(["CMY,36/18,3000,75,ASPH"]), self.rwy(["CMY,01/19,3000,75,ASPH"]))
        self.assertEqual(self.summaries(ch["CMY"]), ["runway 36/18 renumbered to 01/19"])

    def test_replaced(self):
        ch = self.diff(self.rwy(["CMY,18W/36W,5370,2300,WATER"]), self.rwy(["CMY,16W/34W,11936,2000,WATER"]))
        self.assertIn("replaced by runway 16W/34W", ch["CMY"][0]["summary"])

    def test_new_airport_is_one_line(self):
        old = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME"]}
        new = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "02TT,LUNACITY RANCH AIRFIELD"],
               "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE", "02TT,18/36,2300,30,TURF"],
               "FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "02TT,02TT,122.9,CTAF"]}
        s = self.summaries(self.diff(old, new)["02TT"])
        self.assertEqual(s, ["new airport added to FAA database: Lunacity Ranch Airfield, "
                             "runway 18/36 2300x30 ft turf, CTAF 122.9"])


class TestCharts(Case):
    def test_dtpp(self):
        xml = os.path.join(tempfile.mkdtemp(), "meta.xml")
        with open(xml, "w") as f:
            f.write('<digital_tpp cycle="2610"><airport_name apt_ident="DAB">'
                    '<record><chart_code>IAP</chart_code><chart_name>ILS OR LOC RWY 07L</chart_name>'
                    '<useraction>C</useraction><pdf_name>00237IL7L.PDF</pdf_name><amdtnum>9</amdtnum></record>'
                    '<record><chart_code>IAP</chart_code><chart_name>VOR RWY 16</chart_name>'
                    '<useraction>D</useraction><pdf_name>DELETED.PDF</pdf_name></record>'
                    '</airport_name></digital_tpp>')
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "DAB"]}, {"APT_BASE.csv": ["ARPT_ID", "DAB"]},
                       {"DAB"}, xml)["DAB"]
        self.assertEqual(self.summaries(ch, "ifr"), ["approach ILS OR LOC RWY 07L amended (amdt 9)",
                                                     "approach VOR RWY 16 removed"])
        self.assertEqual(ch[0]["chart"]["pdf"], "https://aeronav.faa.gov/d-tpp/2610/00237IL7L.PDF")
        self.assertNotIn("pdf", ch[1]["chart"])


class TestSchema(Case):
    def test_shape(self):
        old = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "VRB,0700-2100"]}
        new = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "VRB,0700-0100"]}
        c = self.diff(old, new, {"VRB"})["VRB"][0]
        for k in ("id", "priority", "category", "kind", "summary", "source"):
            self.assertIn(k, c)
        self.assertEqual(c["category"], "tower")
        self.assertEqual(len(c["id"]), 12)

    def test_cycle_labels(self):
        self.assertEqual(cycle_label("03_Sep_2026_CSV.zip"), "2026-09-03")
        self.assertEqual(cycle_label("data/2026-10-01_CSV.zip"), "2026-10-01")


if __name__ == "__main__":
    unittest.main()
