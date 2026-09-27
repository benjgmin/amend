"""
Regression tests built from real cases found in FAA data.
run:  python -m unittest -v
"""
import io
import json
import os
import tempfile
import unittest
import zipfile

from amend import remarks
from amend.pipeline import cycle_label, run


def setUpModule():
    # the repo's remark_cache.json grows every cycle; tests must not depend on what's in it
    global _real_cache
    _real_cache, remarks.CACHE_FILE = remarks.CACHE_FILE, os.path.join(tempfile.mkdtemp(), "cache.json")


def tearDownModule():
    remarks.CACHE_FILE = _real_cache


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
        self.assertEqual(s, ["tower hours: 0700-2100 -> 0700-0100 local"])

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
        self.assertIn("TRV (Treasure) navaid: VORTAC -> DME", s)

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
        self.assertEqual(self.summaries(ch, "action"), ["new frequency 122.9 (CTAF)"])

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
                         ("fyi", "airport manager: Edward Freni -> Sharon Williams"))

    def test_ils_remark_reads_like_a_remark(self):
        """BIF: a new ILS remark came out as 'added (ils_rmk): rwy end id=22, ...'."""
        hdr = "ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,TAB_NAME,REF_COL_NAME,REMARK"
        ch = self.diff({"ILS_RMK.csv": [hdr]},
                       {"ILS_RMK.csv": [hdr, "BIF,22,BIF,LD,ILS,GENERAL_REMARK,ILS UNMON DLY 0700-1500Z++."]},
                       {"BIF"})["BIF"][0]
        self.assertEqual(ch["summary"], "new ILS/DME RWY 22 remark: ILS UNMON DLY 0700-1500Z++.")
        self.assertEqual(ch["original"], "ILS UNMON DLY 0700-1500Z++.")

    def test_zulu_tower_hours_not_called_local(self):
        """BIF: 'OPEN 24 HRS. -> 1500-0700Z++ MON-SUN EXC HOLS local' is wrong; the Z already says it."""
        old = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "BIF,OPEN 24 HRS."]}
        new = {"ATC_BASE.csv": ["FACILITY_ID,TWR_HRS", "BIF,1500-0700Z++ MON-SUN EXC HOLS"]}
        s = self.summaries(self.diff(old, new, {"BIF"})["BIF"])
        self.assertEqual(s, ["tower hours: OPEN 24 HRS. -> 1500-0700Z++ MON-SUN EXC HOLS"])

    def test_sectorization_is_fyi(self):
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,SECTORIZATION", "BIF,BIF,134.1,BLISS RDO"]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,SECTORIZATION", "BIF,BIF,134.1,BIGGS AIC"]}
        self.assertEqual(self.diff(old, new, {"BIF"})["BIF"][0]["priority"], "fyi")

    def test_rco_removal_is_fyi(self):
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "BFD,BFD,122.2,BRADFORD RCO"]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE"]}
        c = self.diff(old, new, {"BFD"})["BFD"][0]
        self.assertEqual((c["priority"], c["summary"]),
                         ("fyi", "flight service (FSS) 122.2 via the Bradford outlet: discontinued"))

    def test_lighting_remark_in_frq_said_once_as_a_remark(self):
        """RPD 01 OCT 2026: the CTAF row in FRQ carries the same lighting remark as APT_RMK.
        it showed twice, once tagged frequency, and both as action for lights being added."""
        old_rmk = ("HIRL RY 01/19 PRESET ON LOW INTST SS-SR; TO INCR INTST & ACTVT REIL RY 19, "
                   "PAPI RYS 01 & 19 & MALSR RY 01 - CTAF.")
        new_rmk = ("HIRL RWY 01/19 PRESET ON LOW INTST SS-SR; TO INCR INTST & ACTVT MALSR RWY 01; "
                   "REIL RWY 19, 13, & 31; PAPI RWY 01, 19, 13, & 31; HIRL RWY 01/19; "
                   "MIRL RWY 13/31 - CTAF.")
        frq = "FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE,REMARK"
        rmk = "ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK"
        old = {"FRQ.csv": [frq, f'RPD,RPD,122.7,CTAF,"{old_rmk}"'],
               "APT_RMK.csv": [rmk, f'RPD,A81,"{old_rmk}"']}
        new = {"FRQ.csv": [frq, f'RPD,RPD,122.7,CTAF,"{new_rmk}"'],
               "APT_RMK.csv": [rmk, f'RPD,A81,"{new_rmk}"']}
        ch = self.diff(old, new, {"RPD"})["RPD"]
        self.assertEqual([(c["category"], c["priority"], c["source"]) for c in ch],
                         [("remark", "fyi", "APT_RMK")])
        self.assertEqual(ch[0]["summary"], "revised remark: " + new_rmk)

        # only in FRQ: still a remark, not a frequency
        ch = self.diff({"FRQ.csv": old["FRQ.csv"]}, {"FRQ.csv": new["FRQ.csv"]}, {"RPD"})["RPD"]
        self.assertEqual([(c["category"], c["priority"]) for c in ch], [("remark", "fyi")])
        self.assertEqual(ch[0]["summary"], "revised remark for CTAF 122.7: " + new_rmk)
        self.assertEqual(ch[0]["original"], new_rmk)

    def test_lighting_remark_losing_a_light_is_action(self):
        rmk = "ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK"
        old = {"APT_RMK.csv": [rmk, "RPD,A81,ACTVT MALSR RWY 01; REIL RWY 19; HIRL RWY 01/19 - CTAF."]}
        new = {"APT_RMK.csv": [rmk, "RPD,A81,ACTVT MALSR RWY 01; HIRL RWY 01/19 - CTAF."]}
        self.assertEqual(self.diff(old, new, {"RPD"})["RPD"][0]["priority"], "action")
        new = {"APT_RMK.csv": [rmk, "RPD,A81,ACTVT MALSR RWY 01; REIL RWY 19; HIRL RWY 01/19 - 122.8."]}
        self.assertEqual(self.diff(old, new, {"RPD"})["RPD"][0]["priority"], "action")

    def test_translation_that_loses_sunset_is_rejected(self):
        raw = "HIRL RWY 01/19 PRESET ON LOW INTST SS-SR - CTAF."
        self.assertFalse(remarks.faithful(raw, "preset on low intensity steady-state to steady-red"))
        self.assertTrue(remarks.faithful(raw, "preset on low intensity from sunset to sunrise"))


class TestRunways(Case):
    def rwy(self, rows):
        return {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "CMY,X"],
                "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE", *rows]}

    def test_renumbered(self):
        ch = self.diff(self.rwy(["CMY,01/19,3032,95,ASPH"]), self.rwy(["CMY,02/20,3032,95,ASPH"]))
        self.assertEqual(self.summaries(ch["CMY"]), ["runway 01/19 -> 02/20 (renumbered)"])

    def test_renumbered_and_remeasured(self):
        ch = self.diff(self.rwy(["CMY,10/28,2800,100,TURF"]), self.rwy(["CMY,09/27,2803,60,TURF"]))
        self.assertEqual(self.summaries(ch["CMY"]),
                         ["runway 10/28 -> 09/27 (renumbered) (2800x100 -> 2803x60 ft)"])

    def test_wraparound(self):
        ch = self.diff(self.rwy(["CMY,36/18,3000,75,ASPH"]), self.rwy(["CMY,01/19,3000,75,ASPH"]))
        self.assertEqual(self.summaries(ch["CMY"]), ["runway 36/18 -> 01/19 (renumbered)"])

    def test_replaced(self):
        ch = self.diff(self.rwy(["CMY,18W/36W,5370,2300,WATER"]), self.rwy(["CMY,16W/34W,11936,2000,WATER"]))
        self.assertIn("-> 16W/34W (new runway)", ch["CMY"][0]["summary"])

    def test_declared_distances(self):
        """VRB rwy 22: small ASDA/LDA wobble is fyi, in plain English."""
        hdr = "ARPT_ID,RWY_ID,RWY_END_ID,ACLT_STOP_DIST_AVBL,LNDG_DIST_AVBL"
        ch = self.diff({"APT_RWY_END.csv": [hdr, "VRB,04/22,22,4974,4974"]},
                       {"APT_RWY_END.csv": [hdr, "VRB,04/22,22,4945,4945"]}, {"VRB"})["VRB"]
        self.assertEqual((ch[0]["priority"], ch[0]["summary"]),
                         ("fyi", "runway 22: declared distances: accelerate-stop distance "
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
        self.assertEqual(s, ["new airport in FAA database: Lunacity Ranch Airfield, "
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
        self.assertEqual(ch["summary"], "arrival/departure procedures new or updated: TTHOR2 -> TTHOR3")
        self.assertEqual(ch["details"], ["TTHOR2 -> TTHOR3: waypoints added NECCK, WOXXO; waypoints removed COL, LAANA; "
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
                         "TRV (Treasure) navaid, 4 NM from the field: VORTAC -> DME")

    def test_tacan_coordinates_are_noise(self):
        apt = ["ARPT_ID,ICAO_ID,FACILITY_USE_CODE,SITE_TYPE_CODE,LAT_DECIMAL,LONG_DECIMAL",
               "DTO,KDTO,PU,A,33.2006,-97.1981"]
        nav = "NAV_ID,NAV_TYPE,NAME,LAT_DECIMAL,LONG_DECIMAL,TACAN_DME_STATUS,TACAN_DME_LAT_DECIMAL"
        ch = self.diff({"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "DQD,VORTAC,DENTON,33.2156,-97.1989,,"]},
                       {"APT_BASE.csv": apt, "NAV_BASE.csv": [nav, "DQD,VORTAC,DENTON,33.2156,-97.1989,"
                                                                  "OPERATIONAL IFR,33.21555555"]})
        self.assertEqual(ch["DTO"][0]["summary"], "DQD (Denton) navaid, 1 NM from the field: "
                                                  "TACAN/DME status: none listed -> operational ifr")


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


class TestWeb(unittest.TestCase):
    def build(self):
        import datetime as dt
        from amend import web
        site = tempfile.mkdtemp()
        os.makedirs(os.path.join(site, "latest"))
        with open(os.path.join(site, "latest", "VRB.json"), "w") as f:
            f.write("{}")                                  # stands in for the app's JSON
        hist = tempfile.mkdtemp()
        with open(os.path.join(hist, "VRB.json"), "w") as f:
            json.dump({"airport": "VRB", "entries": [
                {"cycle": "2025-07-10", "priority": "action", "category": "tower", "kind": "changed",
                 "summary": "tower hours: 0700-2300 -> 0700-0100 local", "source": "ATC_BASE", "id": "x"}]}, f)
        latest = {"VRB": [{"id": "a", "priority": "action", "category": "tower", "kind": "changed",
                           "summary": "tower hours: 0800-2200 -> 0600-2200 local", "source": "ATC_BASE"},
                          {"id": "b", "priority": "ifr", "category": "chart", "kind": "changed",
                           "summary": "approach ILS OR LOC RWY 12R amended (amdt 3)", "source": "d-TPP",
                           "chart": {"code": "IAP", "name": "ILS", "amdt": "3", "pdf": "https://x/y.PDF"}}]}
        meta = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True, "changed_airports": 1}
        directory = [{"id": "VRB", "icao": "KVRB", "name": "Vero Beach Rgnl", "city": "Vero Beach", "state": "FL"},
                     {"id": "DAB", "icao": "KDAB", "name": "Daytona Beach Intl"}]
        n = web.build(site, meta, directory, latest, hist, now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc))
        return site, n

    def test_airport_page(self):
        site, n = self.build()
        self.assertEqual(n, 1)
        page = open(os.path.join(site, "VRB", "index.html")).read()
        self.assertIn('<meta property="og:title" content="VRB: ACT 1 · IFR 1 on 01 OCT · Vero Beach Rgnl">', page)
        self.assertIn('content="https://amend.watch/VRB/card.png"', page)
        self.assertTrue(os.path.exists(os.path.join(site, "VRB", "card.png")))
        self.assertIn('content="ACT 1 · IFR 1 · Tower hours: 0800-2200 → 0600-2200 local"', page)
        self.assertIn("Not in effect yet", page)
        self.assertIn("0800-2200 → 0600-2200", page)
        self.assertIn("View plate", page)
        self.assertIn("Effective 10 Jul 2025", page)          # history section
        self.assertIn('href="../guide/">What do these mean?', page)   # legend for the labels
        self.assertIn('<span class="ann act" title="Changes how you fly it', page)
        self.assertIn('<nav class="sb"', page)                      # desktop sidebar
        self.assertIn('data-f="ifr"', page)                         # filter tabs
        self.assertIn('id="c-2025-07-10"', page)                    # history cycles can be linked

    def test_guide_and_welcome(self):
        site, _ = self.build()
        guide = open(os.path.join(site, "guide", "index.html")).read()
        for text in ("Tower hours changed: 0700-2100 → 0700-0100 local", "Upcoming", "FAA text", 'href="../?welcome"'):
            self.assertIn(text, guide)
        index = open(os.path.join(site, "index.html")).read()
        self.assertIn('id="welcome" hidden', index)       # shown by script on a first visit only
        self.assertIn("How to read it", index)
        self.assertIn('href="guide/"', index)

    def test_json_paths_untouched(self):
        site, _ = self.build()
        self.assertEqual(open(os.path.join(site, "latest", "VRB.json")).read(), "{}")
        self.assertTrue(os.path.exists(os.path.join(site, "index.html")))
        self.assertTrue(os.path.exists(os.path.join(site, "assets", "style.css")))
        self.assertTrue(os.path.exists(os.path.join(site, "list", "index.html")))
        old = open(os.path.join(site, "watch", "index.html")).read()           # old ?w= links keep their query
        self.assertIn('location.replace("../list/"+location.search', old)
        self.assertIn("amend.watch", open(os.path.join(site, "index.html")).read())   # watchlist storage key


class TestWatchlists(unittest.TestCase):
    def test_validation(self):
        from amend.watchlists import validate
        self.assertEqual(validate("clubsvfr", {"name": "Club SVFR", "airports": ["DAB", "KOMN"]}), [])
        self.assertTrue(validate("Club SVFR!", {"name": "x", "airports": ["DAB"]}))     # bad link name
        self.assertTrue(validate("about", {"name": "x", "airports": ["DAB"]}))          # reserved
        self.assertTrue(validate("guide", {"name": "x", "airports": ["DAB"]}))
        self.assertTrue(validate("list", {"name": "x", "airports": ["DAB"]}))
        self.assertTrue(validate("clubsvfr", {"name": "", "airports": ["DAB"]}))        # no name
        self.assertTrue(validate("clubsvfr", {"name": "x", "airports": ["not an id"]}))

    def test_named_page(self):
        import datetime as dt
        from amend import web, watchlists
        d = tempfile.mkdtemp()
        watchlists.save("clubsvfr", "Club SVFR", ["DAB", "KVRB"], "Training area", directory=d)
        lists = watchlists.load_all(d)
        self.assertEqual(lists["clubsvfr"]["airports"], ["DAB", "VRB"])
        site = tempfile.mkdtemp()
        latest = {"VRB": [{"id": "a", "priority": "action", "category": "tower", "kind": "changed",
                           "summary": "tower hours: 0800-2200 -> 0600-2200 local", "source": "ATC_BASE"}]}
        meta = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True, "changed_airports": 1}
        web.build(site, meta, [{"id": "VRB", "name": "Vero Beach Rgnl"}], latest, None,
                  now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc), watchlists=lists)
        html_ = open(os.path.join(site, "list", "clubsvfr", "index.html")).read()
        self.assertIn('url=../../list/clubsvfr/', open(os.path.join(site, "watch", "clubsvfr", "index.html")).read())
        self.assertIn('url=../list/clubsvfr/', open(os.path.join(site, "clubsvfr", "index.html")).read())
        self.assertIn('content="https://amend.watch/list/clubsvfr/card.png"', html_)
        self.assertIn('href="../../assets/style.css"', html_)
        self.assertIn('href="../?w=', html_)                             # add to my list
        self.assertTrue(os.path.exists(os.path.join(site, "about", "index.html")))
        self.assertIn('content="Club SVFR: 1 of 2 airports change on 01 OCT · ACT 1"', html_)
        self.assertIn("0800-2200 → 0600-2200", html_)
        self.assertIn("No changes in this cycle.", html_)        # DAB


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


def make_shapefile_zip(path, features):
    """class airspace shapefile zip. features: [({field: value}, [ring of (lon, lat)])]"""
    import struct
    names = ["NAME", "LOCAL_TYPE", "IDENT", "LOWER_VAL", "LOWER_CODE", "UPPER_VAL", "UPPER_CODE"]
    recs = b""
    for i, (_, ring) in enumerate(features):
        pts = b"".join(struct.pack("<2d", x, y) for x, y in ring)
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        body = struct.pack("<i4d2ii", 5, min(xs), min(ys), max(xs), max(ys), 1, len(ring), 0) + pts
        recs += struct.pack(">ii", i + 1, len(body) // 2) + body
    shp = struct.pack(">i20xi", 9994, (100 + len(recs)) // 2) + struct.pack("<ii64x", 1000, 5) + recs
    width = 40
    dbf = struct.pack("<B3xIHH20x", 3, len(features), 32 + 32 * len(names) + 1, 1 + width * len(names))
    for n in names:
        dbf += n.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([width, 0]) + b"\0" * 14
    dbf += b"\r"
    for fields, _ in features:
        dbf += b" " + b"".join(str(fields.get(n, "")).encode().ljust(width) for n in names)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Shape_Files/Class_Airspace.shp", shp)
        z.writestr("Shape_Files/Class_Airspace.dbf", dbf + b"\x1a")


def box(lat, lon, r):
    """square ring around a point, r degrees each way (clockwise, closed, like the FAA's)"""
    return [(lon - r, lat - r), (lon - r, lat + r), (lon + r, lat + r), (lon + r, lat - r), (lon - r, lat - r)]


class TestAirspaceShapes(unittest.TestCase):
    APT = ["ARPT_ID,SITE_TYPE_CODE,FACILITY_USE_CODE,LAT_DECIMAL,LONG_DECIMAL",
           "VRB,A,PU,27.655,-80.418", "MCO,A,PU,28.429,-81.309", "ORL,A,PU,28.545,-81.333",
           "X21,A,PU,28.6,-80.0"]

    def run_shapes(self, old, new, ids=None):
        d = tempfile.mkdtemp()
        paths = [os.path.join(d, n) for n in ("2026-09-03_CSV.zip", "2026-10-01_CSV.zip", "o.zip", "n.zip")]
        for p in paths[:2]:
            make_zip(p, {"APT_BASE.csv": self.APT})
        make_shapefile_zip(paths[2], old)
        make_shapefile_zip(paths[3], new)
        return run(paths[0], paths[1], ids, log=lambda *_: None, airspace=paths[2:])["airports"]

    def d(self, ceiling, ring=None):
        return ({"NAME": "VERO BEACH CLASS D", "LOCAL_TYPE": "CLASS_D", "IDENT": "VRB", "LOWER_VAL": "0",
                 "LOWER_CODE": "SFC", "UPPER_VAL": ceiling, "UPPER_CODE": "MSL"}, ring or box(27.655, -80.418, 0.07))

    def b(self, lower, lat=28.429, lon=-81.309, r=0.05):
        return ({"NAME": "ORLANDO CLASS B", "LOCAL_TYPE": "CLASS_B", "IDENT": "MCO", "LOWER_VAL": lower,
                 "LOWER_CODE": "SFC" if lower == "0" else "MSL", "UPPER_VAL": "10000", "UPPER_CODE": "MSL"},
                box(lat, lon, r))

    def test_class_d_ceiling(self):
        """a class D ceiling going up changes the VFR altitudes you can fly over the field."""
        c = self.run_shapes([self.d("2500")], [self.d("3000")], {"VRB"})["VRB"]
        self.assertEqual([(x["priority"], x["category"], x["summary"]) for x in c],
                         [("action", "airspace", "class D over the field: SFC-2,500 ft MSL -> SFC-3,000 ft MSL")])

    def test_class_b_shelf_over_satellite_airport(self):
        """ORL sits under a 3,000 ft MCO class B shelf; the shelf drops to 2,500."""
        core = self.b("0")
        old = [core, self.b("3000", 28.545, -81.333, 0.04)]
        new = [core, self.b("2500", 28.545, -81.333, 0.04)]
        apts = self.run_shapes(old, new)
        self.assertEqual([c["summary"] for c in apts["ORL"]],
                         ["Orlando class B over the field: 3,000-10,000 ft MSL -> 2,500-10,000 ft MSL"])
        self.assertEqual([c["summary"] for c in apts["MCO"]],
                         ["class B airspace: new 2,500-10,000 ft MSL; removed 3,000-10,000 ft MSL"])
        self.assertNotIn("VRB", apts)

    def test_redigitized_boundary_is_noise(self):
        """same square with an extra vertex mid-edge and a hair of rounding: not a change."""
        ring = box(27.655, -80.418, 0.07)
        redrawn = [ring[0], (ring[0][0], 27.655), ring[1], ring[2], (ring[3][0] + 1e-5, ring[3][1]), ring[4]]
        self.assertEqual(self.run_shapes([self.d("2500")], [self.d("2500", redrawn)], {"VRB"}), {})

    def test_boundary_moved_away_from_field(self):
        """the class D got bigger but the field was inside both times: say the boundary moved."""
        c = self.run_shapes([self.d("2500")], [self.d("2500", box(27.655, -80.418, 0.09))], {"VRB"})["VRB"]
        self.assertEqual([x["summary"] for x in c], ["class D airspace: boundary moved (SFC-2,500 ft MSL)"])

    def test_new_surface_area_over_other_airport(self):
        e2 = ({"NAME": "MELBOURNE CLASS E2", "LOCAL_TYPE": "CLASS_E2", "IDENT": "MLB", "LOWER_VAL": "0",
               "LOWER_CODE": "SFC", "UPPER_VAL": "-9998", "UPPER_CODE": "MSL"}, box(28.6, -80.0, 0.05))
        c = self.run_shapes([self.d("2500")], [self.d("2500"), e2])["X21"]
        self.assertEqual([x["summary"] for x in c], ["now under Melbourne class E surface: SFC-class A"])

    def test_no_shapefile_is_skipped(self):
        d = tempfile.mkdtemp()
        o, n, e = (os.path.join(d, x) for x in ("2026-09-03_CSV.zip", "2026-10-01_CSV.zip", "empty.zip"))
        for p in (o, n, e):
            make_zip(p, {"APT_BASE.csv": self.APT})
        self.assertEqual(run(o, n, {"VRB"}, log=lambda *_: None, airspace=(e, e))["airports"], {})


if __name__ == "__main__":
    unittest.main()
