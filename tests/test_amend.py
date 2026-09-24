"""
Regression tests built from real cases found in FAA data.
run:  python -m unittest -v
"""
import io
import os
import tempfile
import unittest
import zipfile

from amend.pipeline import cycle_label, run


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

    def test_contact_change_says_who(self):
        """BOS: 'name changed' meant the airport manager changed."""
        hdr = "ARPT_ID,TITLE,NAME,PHONE_NO"
        ch = self.diff({"APT_CON.csv": [hdr, "BOS,MANAGER,EDWARD FRENI,617-555-0100"]},
                       {"APT_CON.csv": [hdr, "BOS,MANAGER,SHARON WILLIAMS,617-555-0100"]}, {"BOS"})["BOS"]
        self.assertEqual((ch[0]["priority"], ch[0]["summary"]),
                         ("fyi", "airport manager changed: Edward Freni -> Sharon Williams"))

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

    def test_declared_distances(self):
        """VRB rwy 22: small ASDA/LDA wobble is fyi, in plain English."""
        hdr = "ARPT_ID,RWY_ID,RWY_END_ID,ACLT_STOP_DIST_AVBL,LNDG_DIST_AVBL"
        ch = self.diff({"APT_RWY_END.csv": [hdr, "VRB,04/22,22,4974,4974"]},
                       {"APT_RWY_END.csv": [hdr, "VRB,04/22,22,4945,4945"]}, {"VRB"})["VRB"]
        self.assertEqual((ch[0]["priority"], ch[0]["summary"]),
                         ("fyi", "runway 22: declared distances changed: accelerate-stop distance "
                                 "available (ASDA) 4,974 ft -> 4,945 ft; landing distance available "
                                 "(LDA) 4,974 ft -> 4,945 ft"))

    def test_declared_distance_big_cut_is_action(self):
        hdr = "ARPT_ID,RWY_ID,RWY_END_ID,LNDG_DIST_AVBL"
        ch = self.diff({"APT_RWY_END.csv": [hdr, "VRB,12R/30L,30L,7314"]},
                       {"APT_RWY_END.csv": [hdr, "VRB,12R/30L,30L,6200"]}, {"VRB"})["VRB"]
        self.assertEqual(ch[0]["priority"], "action")

    def test_new_airport_is_one_line(self):
        old = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME"]}
        new = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "02TT,LUNACITY RANCH AIRFIELD"],
               "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE", "02TT,18/36,2300,30,TURF"],
               "FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "02TT,02TT,122.9,CTAF"]}
        s = self.summaries(self.diff(old, new)["02TT"])
        self.assertEqual(s, ["new airport added to FAA database: Lunacity Ranch Airfield, "
                             "runway 18/36 2300x30 ft turf, CTAF 122.9"])


class TestProcedures(Case):
    def test_waypoint_detail(self):
        """TTHOR2 -> TTHOR3: which waypoints and transitions changed."""
        apt = ["ARPT_ID,STAR_COMPUTER_CODE"]
        rte = ["STAR_COMPUTER_CODE,ROUTE_PORTION_TYPE,ROUTE_NAME,POINT_SEQ,POINT"]
        old = {"APT_BASE.csv": ["ARPT_ID", "DAB"],
               "STAR_APT.csv": apt + ["DAB,LPERD.TTHOR2"],
               "STAR_RTE.csv": rte + ["LPERD.TTHOR2,BODY,LPERD-TTHOR,10,LPERD",
                                      "LPERD.TTHOR2,BODY,LPERD-TTHOR,20,LAANA",
                                      "COL.TTHOR2,TRANSITION,COL-LPERD,10,COL"]}
        new = {"APT_BASE.csv": ["ARPT_ID", "DAB"],
               "STAR_APT.csv": apt + ["DAB,LPERD.TTHOR3"],
               "STAR_RTE.csv": rte + ["LPERD.TTHOR3,BODY,LPERD-TTHOR,10,LPERD",
                                      "LPERD.TTHOR3,BODY,LPERD-TTHOR,20,WOXXO",
                                      "NECCK.TTHOR3,TRANSITION,NECCK-LPERD,10,NECCK"]}
        ch = self.diff(old, new)["DAB"][0]
        self.assertEqual(ch["summary"], "arrival/departure procedures new or updated: TTHOR3 (was TTHOR2)")
        self.assertEqual(ch["details"], ["TTHOR3 (was TTHOR2): waypoints added NECCK, WOXXO; waypoints removed COL, LAANA; "
                                         "transitions added NECCK; transitions removed COL"])

    def test_same_name_amended_in_all_airports_mode(self):
        """route points changed without a version bump: attributed via STAR_APT, compared by name."""
        apt = ["ARPT_ID,STAR_COMPUTER_CODE"]
        rte = ["STAR_COMPUTER_CODE,ROUTE_PORTION_TYPE,ROUTE_NAME,POINT_SEQ,POINT"]
        base_files = {"APT_BASE.csv": ["ARPT_ID", "ISM"], "STAR_APT.csv": apt + ["ISM,SNFLD.SNFLD3"]}
        old = {**base_files, "STAR_RTE.csv": rte + ["SNFLD.SNFLD3,BODY,SNFLD-SECOY,10,SNFLD",
                                                    "SNFLD.SNFLD3,BODY,SNFLD-SECOY,20,SECOY"]}
        new = {**base_files, "STAR_RTE.csv": rte + ["SNFLD.SNFLD3,BODY,SNFLD-SECOY,10,SNFLD",
                                                    "SNFLD.SNFLD3,BODY,SNFLD-SECOY,20,PDLLA"]}
        ch = self.diff(old, new)["ISM"][0]
        self.assertEqual(ch["details"], ["SNFLD3: waypoints added PDLLA; waypoints removed SECOY"])

    def test_transition_computer_code(self):
        """real NASR columns: the transition's name comes from TRANSITION_COMPUTER_CODE."""
        import tempfile, os
        from amend.procedures import load_routes
        p = os.path.join(tempfile.mkdtemp(), "r.zip")
        make_zip(p, {"STAR_RTE.csv": [
            "STAR_COMPUTER_CODE,ROUTE_PORTION_TYPE,ROUTE_NAME,TRANSITION_COMPUTER_CODE,POINT_SEQ,POINT",
            "SNFLD.SNFLD3,BODY,SNFLD-SECOY,,10,SNFLD",
            "SNFLD.SNFLD3,TRANSITION,CRG-SNFLD,CRG.SNFLD3,10,CRG"]})
        self.assertEqual(load_routes(p)["SNFLD3"]["transitions"], {"CRG"})

    def test_dp_code_order(self):
        from amend.procedures import split_code
        self.assertEqual(split_code("CONLE5.CONLE"), ("CONLE5", "CONLE"))
        self.assertEqual(split_code("SNFLD.SNFLD3"), ("SNFLD3", "SNFLD"))


class TestNavaidsNearby(Case):
    def test_navaid_matched_to_nearby_airport(self):
        """all-airports mode: TRV (Treasure) is ~4 NM from VRB and has no airport column."""
        apt = ["ARPT_ID,ICAO_ID,FACILITY_USE_CODE,SITE_TYPE_CODE,LAT_DECIMAL,LONG_DECIMAL",
               "VRB,KVRB,PU,A,27.6556,-80.4179",
               "X99,,PR,A,27.66,-80.45",          # private: ignored
               "FAR,KFAR,PU,A,46.92,-96.81"]       # far away: ignored
        nav = "NAV_ID,NAV_TYPE,NAME,LAT_DECIMAL,LONG_DECIMAL"
        ch = self.diff({"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "TRV,VORTAC,TREASURE,27.6784,-80.4897"]},
                       {"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "TRV,DME,TREASURE,27.6784,-80.4897"]})
        self.assertEqual(list(ch), ["VRB"])
        self.assertEqual(ch["VRB"][0]["summary"],
                         "TRV (Treasure) navaid, 4 NM from the field: now a DME (was a VORTAC)")

    def test_tacan_coordinates_are_noise(self):
        apt = ["ARPT_ID,ICAO_ID,FACILITY_USE_CODE,SITE_TYPE_CODE,LAT_DECIMAL,LONG_DECIMAL",
               "DTO,KDTO,PU,A,33.2006,-97.1981"]
        nav = "NAV_ID,NAV_TYPE,NAME,LAT_DECIMAL,LONG_DECIMAL,TACAN_DME_STATUS,TACAN_DME_LAT_DECIMAL"
        ch = self.diff({"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "DQD,VORTAC,DENTON,33.2156,-97.1989,,"]},
                       {"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "DQD,VORTAC,DENTON,33.2156,-97.1989,"
                                                                  "OPERATIONAL IFR,33.21555555"]})
        self.assertEqual(ch["DTO"][0]["summary"], "DQD (Denton) navaid, 1 NM from the field: "
                                                  "TACAN/DME status: operational ifr (was none listed)")


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

    def test_str_is_an_arrival(self):
        """the real metafile codes STARs as STR."""
        xml = os.path.join(tempfile.mkdtemp(), "meta.xml")
        with open(xml, "w") as f:
            f.write('<digital_tpp cycle="2609"><airport_name apt_ident="BOS"><record>'
                    '<chart_code>STR</chart_code><chart_name>WOONS TWO</chart_name>'
                    '<useraction>C</useraction><pdf_name>X.PDF</pdf_name><amdtnum>2</amdtnum>'
                    '</record></airport_name></digital_tpp>')
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "BOS"]}, {"APT_BASE.csv": ["ARPT_ID", "BOS"]},
                       {"BOS"}, xml)["BOS"]
        self.assertEqual((ch[0]["priority"], ch[0]["summary"]), ("ifr", "arrival WOONS TWO amended (amdt 2)"))


class TestDirectory(unittest.TestCase):
    def test_airports_json(self):
        from amend.airports import directory
        p = os.path.join(tempfile.mkdtemp(), "a.zip")
        make_zip(p, {"APT_BASE.csv": ["ARPT_ID,ICAO_ID,ARPT_NAME,CITY,STATE_CODE,SITE_TYPE_CODE,LAT_DECIMAL,LONG_DECIMAL",
                                      "DAB,KDAB,DAYTONA BEACH INTL,DAYTONA BEACH,FL,A,29.17991667,-81.05805556",
                                      "7FL6,,SPRUCE CREEK,DAYTONA BEACH,FL,A,,"]})
        d = directory(p)
        self.assertEqual(d[1], {"id": "DAB", "icao": "KDAB", "name": "Daytona Beach Intl",
                                "city": "Daytona Beach", "state": "FL", "type": "airport",
                                "lat": 29.1799, "lon": -81.0581})
        self.assertNotIn("icao", d[0])


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