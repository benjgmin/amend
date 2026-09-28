"""
Whole NASR rows added or removed, in plain English: no change may reach a pilot as a raw dump
of FAA column names ("removed (ils_mkr): rwy end id=34, ..."). Every case is a real row from
the 2026-07-09 .. 2026-10-01 cycles, trimmed to the columns that matter. Also: every number in
a summary must be in the FAA record it describes, and ids don't depend on the wording.
run:  python -m unittest tests.test_summaries -v
"""
import json
import os
import re
import tempfile
import unittest

from amend import backfill, english, fields, gold, remarks
from amend.diff import schedule_text
from amend.english import unsupported
from amend.pipeline import run
from tests.test_amend import Case, make_zip

HISTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
RAW_DUMP = r"^(added|removed|changed) \(|^[a-z_]+ (added|removed|changed): "


def setUpModule():
    global _real_cache
    _real_cache, remarks.CACHE_FILE = remarks.CACHE_FILE, os.path.join(tempfile.mkdtemp(), "cache.json")


def tearDownModule():
    remarks.CACHE_FILE = _real_cache


class Rows(Case):
    def one(self, files_old, files_new, apt):
        """the changes at apt, as [(priority, summary)]."""
        base = {"APT_BASE.csv": ["ARPT_ID", apt]}
        ch = self.diff({**base, **files_old}, {**base, **files_new}).get(apt, [])
        for c in ch:
            self.assertNotRegex(c["summary"], RAW_DUMP)
        return [(c["priority"], c["summary"]) for c in ch]


class TestIls(Rows):
    H_BASE = "ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,COMPONENT_STATUS,LOC_FREQ"
    H_GS = "ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,G_S_TYPE_CODE,G_S_ANGLE,G_S_FREQ"
    H_DME = "ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,CHANNEL"
    H_MKR = ("ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,ILS_COMP_TYPE_CODE,COMPONENT_STATUS,"
             "MKR_FAC_TYPE_CODE,MARKER_ID_BEACON,COMPASS_LOCATOR_NAME,FREQ,NAV_ID,NAV_TYPE")

    def test_new_ils_is_one_line(self):
        """NIP 2026-08-06: two new ILS/DME, each with its glideslope and DME: 2 lines, not 6."""
        new = {"ILS_BASE.csv": [self.H_BASE, "NIP,28,NIP,LD,OPERATIONAL IFR,109.15",
                                "NIP,10,NTW,LD,OPERATIONAL IFR,109.15"],
               "ILS_GS.csv": [self.H_GS, "NIP,28,NIP,LD,GS,3,331.25", "NIP,10,NTW,LD,GS,3,331.25"],
               "ILS_DME.csv": [self.H_DME, "NIP,28,NIP,LD,28Y", "NIP,10,NTW,LD,28Y"]}
        old = {k: [v[0]] for k, v in new.items()}
        self.assertEqual(sorted(self.one(old, new, "NIP")), [
            ("action", "new ILS/DME RWY 10 (NTW, 109.15) with glideslope 3°, DME channel 28Y"),
            ("action", "new ILS/DME RWY 28 (NIP, 109.15) with glideslope 3°, DME channel 28Y")])

    def test_removed_ils_takes_its_parts_and_remarks(self):
        """MCC 2026-08-06: ILS 34 gone with its glideslope, middle marker and remark."""
        old = {"ILS_BASE.csv": [self.H_BASE, "MCC,34,FKZ,LS,OPERATIONAL IFR,109.7"],
               "ILS_GS.csv": [self.H_GS, "MCC,34,FKZ,LS,GS,3,333.2"],
               "ILS_MKR.csv": [self.H_MKR, "MCC,34,FKZ,LS,MM,OPERATIONAL IFR,M,KZ,,,,"],
               "ILS_RMK.csv": ["ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,TAB_NAME,REMARK",
                               "MCC,34,FKZ,LS,ILS_BASE,GS UNUSBL BLO 400 FT."]}
        new = {k: [v[0]] for k, v in old.items()}
        self.assertEqual(self.one(old, new, "MCC"), [
            ("action", "ILS RWY 34 (FKZ, 109.7) with glideslope 3°, middle marker: removed")])

    def test_marker_alone(self):
        """SJT 2026-09-03 (gold g103): outer marker / compass locator decommissioned."""
        old = {"ILS_MKR.csv": [self.H_MKR, "SJT,03,SJT,LD,OM,OPERATIONAL IFR,MR,SJ,WOOLE,356,SJ,NDB"]}
        self.assertEqual(self.one(old, {"ILS_MKR.csv": [self.H_MKR]}, "SJT"), [
            ("action", "ILS/DME RWY 03 (SJT): outer marker (compass locator WOOLE 356) removed")])

    def test_type_names_are_the_faa_layouts(self):
        """ILS DATA LAYOUT.pdf 'System Type' column; unknown codes stay as the FAA wrote them."""
        self.assertEqual(english.ils_name({"SYSTEM_TYPE_CODE": "LC", "RWY_END_ID": "29", "ILS_LOC_ID": "MLT"}),
                         "LOC RWY 29 (MLT)")
        self.assertEqual(english.ils_name({"SYSTEM_TYPE_CODE": "DD", "RWY_END_ID": "08"}), "LDA/DME RWY 08")
        self.assertEqual(english.ils_name({"SYSTEM_TYPE_CODE": "ZZ"}), "ILS (ZZ)")


class TestRunways(Rows):
    H = "ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE,COND,TREATMENT_CODE"
    H_END = "ARPT_ID,RWY_ID,RWY_END_ID"

    def test_new_runway(self):
        """40ND 2026-10-01: its two runway-end rows are the same news."""
        new = {"APT_RWY.csv": [self.H, "40ND,18/36,2546,60,TURF,,NONE"],
               "APT_RWY_END.csv": [self.H_END, "40ND,18/36,18", "40ND,18/36,36"]}
        old = {k: [v[0]] for k, v in new.items()}
        self.assertEqual(self.one(old, new, "40ND"), [("action", "new runway 18/36: 2546x60 ft turf")])

    def test_removed_runway(self):
        """NYL 2026-09-03."""
        old = {"APT_RWY.csv": [self.H, "NYL,17/35,5710,150,ASPH-CONC,GOOD,NONE"]}
        self.assertEqual(self.one(old, {"APT_RWY.csv": [self.H]}, "NYL"),
                         [("action", "runway 17/35 (5710x150 ft asph-conc): removed")])

    def test_helipad_is_fyi(self):
        """9OK1 2026-09-03: three hospital helipads removed; TA79: one added."""
        old = {"APT_RWY.csv": [self.H, "9OK1,H2,80,80,CONC,,NONE"]}
        self.assertEqual(self.one(old, {"APT_RWY.csv": [self.H]}, "9OK1"),
                         [("fyi", "helipad H2 (80x80 ft conc): removed")])
        self.assertEqual(self.one({"APT_RWY.csv": [self.H]}, {"APT_RWY.csv": [self.H, "TA79,H2,40,40,CONC,,NONE"]},
                                  "TA79"), [("fyi", "new helipad H2: 40x40 ft conc")])

    def test_runway_end_alone(self):
        """gold g026 NK72: a runway end row without its runway still names the runway."""
        new = {"APT_RWY_END.csv": [self.H_END, "NK72,16/34,16"]}
        self.assertEqual(self.one({"APT_RWY_END.csv": [self.H_END]}, new, "NK72"),
                         [("fyi", "new runway 16/34 end 16")])

    def test_arresting_system(self):
        """VPC 2026-09-03: EMAS at both ends of runway 01/19."""
        h = "ARPT_ID,RWY_ID,RWY_END_ID,ARREST_DEVICE_CODE"
        new = {"APT_ARS.csv": [h, "VPC,01/19,01,EMAS", "VPC,01/19,19,EMAS"]}
        self.assertEqual(sorted(self.one({"APT_ARS.csv": [h]}, new, "VPC")), [
            ("fyi", "runway 01: new arresting system (EMAS)"),
            ("fyi", "runway 19: new arresting system (EMAS)")])


class TestAttendance(Rows):
    H = "ARPT_ID,SKED_SEQ_NO,MONTH,DAY,HOUR"

    def test_whole_schedule_old_and_new(self):
        """IPJ 2026-10-01: both seasons dropped. OXI 2026-09-03: one row became three."""
        old = {"APT_ATT.csv": [self.H, "IPJ,1,APR-OCT,ALL,0800-1900", "IPJ,2,NOV-MAR,ALL,0800-1700"]}
        self.assertEqual(self.one(old, {"APT_ATT.csv": [self.H]}, "IPJ"), [
            ("action", "airport attendance: APR-OCT 0800-1900; NOV-MAR 0800-1700 -> none listed")])
        old = {"APT_ATT.csv": [self.H, "OXI,1,ALL,ALL,0800-1800"]}
        new = {"APT_ATT.csv": [self.H, "OXI,1,ALL,MON-THU,0730-1500", "OXI,2,ALL,FRI,0900-1700",
                               "OXI,3,ALL,SAT-SUN,0900-1600"]}
        self.assertEqual(self.one(old, new, "OXI"), [
            ("action", "airport attendance: 0800-1800 -> MON-THU 0730-1500; FRI 0900-1700; SAT-SUN 0900-1600")])

    def test_newly_listed_unattended_is_fyi(self):
        """MA87 2026-10-01: a private strip newly listed as UNATNDD; nothing you had went away."""
        new = {"APT_ATT.csv": [self.H, "MA87,1,UNATNDD,,"]}
        self.assertEqual(self.one({"APT_ATT.csv": [self.H]}, new, "MA87"),
                         [("fyi", "airport attendance listed: UNATNDD")])

    def test_renumbered_rows_are_nothing(self):
        old = {"APT_ATT.csv": [self.H, "DAB,1,ALL,MON-FRI,0800-1700", "DAB,2,ALL,SAT,0900-1200"]}
        new = {"APT_ATT.csv": [self.H, "DAB,1,ALL,MON-FRI,0800-1700", "DAB,3,ALL,SAT,0900-1200"]}
        self.assertEqual(self.one(old, new, "DAB"), [])

    def test_schedule_text(self):
        self.assertEqual(schedule_text([{"SKED_SEQ_NO": "1", "MONTH": "ON CALL", "DAY": "ON CALL",
                                         "HOUR": "ON CALL"}]), "ON CALL")    # 3U8
        self.assertEqual(schedule_text([{"SKED_SEQ_NO": "1", "MONTH": "ALL", "DAY": "ALL", "HOUR": "ALL"}]),
                         "ALL")                                              # 22PR


class TestOtherFiles(Rows):
    H_ATC = ("FACILITY_TYPE,FACILITY_ID,FACILITY_NAME,REGION_CODE,PRIMARY_APCH_RADIO_CALL,APCH_P_PROVIDER,"
             "APCH_P_PROV_TYPE_CD,SECONDARY_APCH_RADIO_CALL,APCH_S_PROVIDER,APCH_S_PROV_TYPE_CD")

    def test_non_towered_field_gets_approach_control(self):
        """6V4 2026-08-06: who you call for IFR at a non-towered field is ifr, not act."""
        new = {"ATC_BASE.csv": [self.H_ATC, "NON-ATCT,6V4,WALL MUNI,AGL,ELLSWORTH,RCA,A,DENVER ARTCC,ZDV,C"]}
        self.assertEqual(self.one({"ATC_BASE.csv": [self.H_ATC]}, new, "6V4"), [
            ("ifr", "approach/departure control listed: ELLSWORTH (RCA), secondary DENVER ARTCC (ZDV)")])

    def test_empty_non_towered_entry(self):
        """P14 2026-09-03 (gold g100): an entry naming no service stays fyi, and says so."""
        old = {"ATC_BASE.csv": [self.H_ATC, "NON-ATCT,P14,HOLBROOK MUNI,AWP,,,,,,"]}
        self.assertEqual(self.one(old, {"ATC_BASE.csv": [self.H_ATC]}, "P14"), [
            ("fyi", "ATC facility entry removed, non-towered (it named no tower or approach control)")])

    def test_atis_and_services(self):
        """GYH 2026-01-22: new ATIS and LAWRS listed with a new tower's data."""
        h = "FACILITY_TYPE,FACILITY_ID,ATIS_NO,ATIS_HRS"
        self.assertEqual(self.one({"ATC_ATIS.csv": [h]}, {"ATC_ATIS.csv": [h, "ATCT,GYH,1,24"]}, "GYH"),
                         [("fyi", "new ATIS (hours 24)")])
        h = "FACILITY_TYPE,FACILITY_ID,CTL_SVC"
        self.assertEqual(self.one({"ATC_SVC.csv": [h, "ATCT-TRACON,FAR,LLWAS"]}, {"ATC_SVC.csv": [h]}, "FAR"),
                         [("fyi", "ATC service LLWAS: no longer listed")])

    def test_weather_station(self):
        """4MD added (gold g003), 4WN7 removed (gold g040)."""
        h = "ASOS_AWOS_ID,ASOS_AWOS_TYPE,NAVAID_FLAG,PHONE_NO"
        self.assertEqual(self.one({"AWOS.csv": [h]}, {"AWOS.csv": [h, "4MD,AWOS-3PT,N,"]}, "4MD"),
                         [("fyi", "new weather station: AWOS-3PT (4MD)")])
        self.assertEqual(self.one({"AWOS.csv": [h, "4WN7,AWOS-2,N,"]}, {"AWOS.csv": [h]}, "4WN7"),
                         [("action", "weather station AWOS-2 (4WN7): removed")])

    def test_class_airspace_radar_military(self):
        h = "ARPT_ID,CLASS_B_AIRSPACE,CLASS_C_AIRSPACE,CLASS_D_AIRSPACE,CLASS_E_AIRSPACE,AIRSPACE_HRS"
        new = {"CLS_ARSP.csv": [h, 'AUO,,,Y,,"CLASS D SVC 0700-2100 MON-FRI; 0800-1700 SAT & SUN; OTHER TIMES CLASS G"']}
        self.assertEqual(self.one({"CLS_ARSP.csv": [h]}, new, "AUO"), [
            ("action", "new class D airspace: CLASS D SVC 0700-2100 MON-FRI; 0800-1700 SAT & SUN; OTHER TIMES CLASS G")])
        h = "FACILITY_ID,FACILITY_TYPE,RADAR_TYPE,RADAR_NO,RADAR_HRS"
        self.assertEqual(self.one({"RDR.csv": [h, "ALO,AIRPORT,ASR,1,0600-2300"]}, {"RDR.csv": [h]}, "ALO"),
                         [("action", "radar airport surveillance radar (ASR): removed (was hours 0600-2300)")])
        h = "ARPT_ID,MIL_OPS_OPER_CODE,REMARK"
        new = {"MIL_OPS.csv": [h, 'TUL,R,"(MIL_OPS_OPER_CODE) ARNG - OPR 1230-2300Z++ TUE-FRI, EXC HOL."']}
        self.assertEqual(self.one({"MIL_OPS.csv": [h]}, new, "TUL"),
                         [("fyi", "new military operations: ARNG - OPR 1230-2300Z++ TUE-FRI, EXC HOL.")])

    def test_jump_area_contact(self):
        """BUF 2026-09-03."""
        h = "PJA_ID,FAC_ID,FAC_NAME,LOC_ID,COMMERCIAL_FREQ,COMMERCIAL_CHART_FLAG"
        new = {"PJA_CON.csv": [h, "PNY035,BUF,BUFFALO NIAGARA INTL,BUF,126.5,N"]}
        self.assertEqual(self.one({"PJA_CON.csv": [h]}, new, "BUF"), [
            ("fyi", "new parachute jump area PNY035 contact: Buffalo Niagara Intl (BUF) 126.5")])

    def test_file_without_english_keeps_its_rank(self):
        """a file nobody wrote English for yet shows the FAA's column names and values, and a
        change that ranks act stays act: a missing template never hides one."""
        h = "ARPT_ID,SOMETHING_CLSD"
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_NEW.csv": [h]},
                       {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_NEW.csv": [h, "DAB,RWY CLSD"]})["DAB"]
        self.assertEqual([(c["priority"], c["summary"]) for c in ch],
                         [("action", "added (apt_new): something clsd=RWY CLSD")])


class TestFrequencies(Rows):
    """ben, 2026-09-28: 'can we make it more descriptive what frequencies changed, i have no idea'."""
    H = "FACILITY,FACILITY_TYPE,ARTCC_OR_FSS_ID,SERVICED_FACILITY,PRIMARY_APPROACH_RADIO_CALL,FREQ,SECTORIZATION,FREQ_USE"

    def test_center_moves_to_another_rcag(self):
        """4AK 2026-10-01: Anchorage Center's two frequencies moved from the Bethel RCAG to the
        Murphy Dome RCAG. four raw rows, one change, and what an RCAG is (glossary, verified)."""
        old = {"FRQ.csv": [self.H, "BETHEL,RCAG,ZAN,4AK,,125.2,LOW,BETHEL RCAG",
                           "BETHEL,RCAG,ZAN,4AK,,372.0,LOW,BETHEL RCAG"]}
        new = {"FRQ.csv": [self.H, "MURPHY DOME,RCAG,ZAN,4AK,ANCHORAGE ARTCC,120.9,LOW/HIGH,MURPHY DOME RCAG",
                           "MURPHY DOME,RCAG,ZAN,4AK,ANCHORAGE ARTCC,319.2,LOW/HIGH,MURPHY DOME RCAG"]}
        self.assertEqual(self.one(old, new, "4AK"), [
            ("action", "center (ARTCC ZAN) frequencies: Bethel RCAG 125.2, 372.0 (low altitude) -> "
                       "Murphy Dome RCAG 120.9, 319.2 (low/high altitude); an RCAG is a remote center "
                       "air to ground facility")])

    def test_same_frequencies_through_another_rcag(self):
        """CN01 2026-10-01: 132.2 and 350.3 stayed, the site behind them changed."""
        old = {"FRQ.csv": [self.H, "RED BLUFF,RCAG,ZOA,CN01,,132.2,LOW,RED BLUFF RCAG",
                           "RED BLUFF,RCAG,ZOA,CN01,,350.3,LOW,RED BLUFF RCAG"]}
        new = {"FRQ.csv": [self.H, "UKIAH,RCAG,ZOA,CN01,,132.2,LOW,UKIAH RCAG",
                           "UKIAH,RCAG,ZOA,CN01,,350.3,LOW,UKIAH RCAG"]}
        ch = self.one(old, new, "CN01")
        self.assertEqual([s for _, s in ch], [
            "center frequencies 132.2, 350.3: now through the Ukiah RCAG instead of the Red Bluff RCAG; "
            "an RCAG is a remote center air to ground facility"])

    def test_approach_frequency_says_who_and_what(self):
        """CVO 2026-10-01: 'new frequency 119.6 (APCH/P DEP/P IC)' told a pilot nothing. IC isn't
        a word we have an FAA meaning for, so the FAA text stays next to ours."""
        new = {"FRQ.csv": [self.H, "EUG,ATCT-TRACON,,CVO,CASCADE,119.6,,APCH/P DEP/P IC"]}
        self.assertEqual(self.one({"FRQ.csv": [self.H]}, new, "CVO"), [
            ("action", "new Cascade approach/departure frequency 119.6 (primary; FAA: APCH/P DEP/P IC)")])

    def test_ctaf_moves(self):
        """GIF 2026-10-01: the CTAF went from 123.05 to 120.425, one change, not two."""
        old = {"FRQ.csv": [self.H, "GIF,NON-ATCT,,GIF,,123.05,,CTAF", "GIF,NON-ATCT,,GIF,,123.05,,UNICOM"]}
        new = {"FRQ.csv": [self.H, "GIF,NON-ATCT,,GIF,,120.425,,CTAF", "GIF,NON-ATCT,,GIF,,123.05,,UNICOM"]}
        self.assertEqual(self.one(old, new, "GIF"), [("action", "CTAF frequency: 123.05 -> 120.425")])

    def test_star_listings_are_one_line(self):
        """1M5 2026-10-01: eight 'also listed for X STAR' lines were one piece of news."""
        rows = [f"BNA,ATCT-TRACON,,1M5,NASHVILLE,{f},,{u}" for f, u in (
            ("118.4", "APCH/P"), ("360.7", "APCH/P"))]
        new = rows + [f"BNA,ATCT-TRACON,,1M5,NASHVILLE,{f},,{p} STAR" for f in ("118.4", "360.7")
                      for p in ("ALLLN", "JNING")]
        self.assertEqual(self.one({"FRQ.csv": [self.H] + rows}, {"FRQ.csv": [self.H] + new}, "1M5"), [
            ("fyi", "frequencies now also listed for arrivals (STARs): 118.4 for ALLLN and JNING; "
                    "360.7 for ALLLN and JNING")])


class TestRemarkSubject(Rows):
    """ben, 2026-09-28: 'removed remark "closed"?' NASR files each airport remark against a table,
    column and element: say what it's about."""
    H = "ARPT_ID,TAB_NAME,REF_COL_NAME,ELEMENT,REMARK"

    def test_closed_runway_remark_removed(self):
        """SPS 2026-10-01: the remark on runway 15C/33C that said only CLOSED. went away."""
        old = {"APT_RMK.csv": [self.H, "SPS,RUNWAY,RWY_ID,15C/33C,CLOSED."]}
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "SPS"], **old},
                       {"APT_BASE.csv": ["ARPT_ID", "SPS"], "APT_RMK.csv": [self.H]})["SPS"]
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0]["summary"],
                         "runway 15C/33C closure remark removed, so it may be open again: CLOSED.")

    def test_subjects(self):
        say = lambda tab, ref, el: english.remark_subject({"TAB_NAME": tab, "REF_COL_NAME": ref, "ELEMENT": el})
        self.assertEqual(say("RUNWAY", "RWY_ID", "15C/33C"), "runway 15C/33C")
        self.assertEqual(say("RUNWAY_SURFACE_TYPE", "SURFACE_TYPE_CODE", "15C/33C"), "runway 15C/33C surface")
        self.assertEqual(say("ARRESTING_DEVICE", "ARREST_DEVICE_CODE", "15C_MA-1A"),
                         "runway 15C arresting system MA-1A")
        self.assertEqual(say("RUNWAY", "RWY_LGT_CODE", "H1"), "helipad H1 edge light intensity")
        self.assertEqual(say("AIRPORT", "LGT_SKED", ""), "airport lighting schedule")
        self.assertEqual(say("AIRPORT", "BCN_LGT_SKED", ""), "airport beacon schedule")
        self.assertEqual(say("AIRPORT", "GENERAL_REMARK", ""), "")
        self.assertEqual(say("AIRPORT_SERVICE", "SERVICE_TYPE_CODE", "INSTR"),
                         "airport service pilot instruction (INSTR)")
        # a column the layouts don't name never shows up as a raw column name
        self.assertEqual(say("AIRPORT", "ARPT_PSN_SOURCE", ""), "")
        self.assertEqual(say("RUNWAY_END", "CLOSE_IN_OBSTN", "12"), "runway 12 end")


class TestSweep(Rows):
    """findings from the 2026-09-28 engine sweep of the 10-01 build."""
    H_END = "ARPT_ID,RWY_ID,RWY_END_ID,OBSTN_TYPE,OBSTN_HGT,DIST_FROM_THR,CNTRLN_OFFSET,CNTRLN_DIR_CODE,OBSTN_CLNC_SLOPE"

    def test_obstacle_dropped_reads_whole(self):
        """FBL runway 30: the road obstacle went away; the line only said 'clearance slope'."""
        old = {"APT_RWY_END.csv": [self.H_END, "FBL,12/30,30,ROAD,14,580,280,R,27"]}
        new = {"APT_RWY_END.csv": [self.H_END, "FBL,12/30,30,,,,,,34"]}
        self.assertEqual([s for _, s in self.one(old, new, "FBL")], [
            "runway 30: controlling obstacle: ROAD 14 ft tall, 580 ft from threshold, 280 ft right of "
            "centerline -> none listed; obstacle clearance slope: 27:1 -> 34:1"])

    def test_obstacle_side_and_type_once(self):
        """02G runway 07: the obstacle moved to the other side of the centerline, and its type
        was a second 'controlling obstacle' phrase."""
        old = {"APT_RWY_END.csv": [self.H_END, "02G,07/25,07,TREE,8,321,58,R,15"]}
        new = {"APT_RWY_END.csv": [self.H_END, "02G,07/25,07,TREES,59,1340,181,L,19"]}
        self.assertEqual([s for _, s in self.one(old, new, "02G")], [
            "runway 07: controlling obstacle: TREE 8 ft tall, 321 ft from threshold, 58 ft right of "
            "centerline -> TREES 59 ft tall, 1340 ft from threshold, 181 ft left of centerline; "
            "obstacle clearance slope: 15:1 -> 19:1"])

    def test_airport_rename_said_once(self):
        """BVN: the new name showed on the airport, tower and frequency rows."""
        h_atc, h_frq = "FACILITY_TYPE,FACILITY_ID,FACILITY_NAME", "FACILITY,FACILITY_TYPE,SERVICED_FACILITY,SERVICED_FAC_NAME,FREQ,FREQ_USE"
        old = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "BVN,ALBION MUNI"],
               "ATC_BASE.csv": [h_atc, "NON-ATCT,BVN,ALBION MUNI"],
               "FRQ.csv": [h_frq, "BVN,NON-ATCT,BVN,ALBION MUNI,122.9,CTAF"]}
        new = {"APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "BVN,ALBION MUNI/RON LEVANDER FLD"],
               "ATC_BASE.csv": [h_atc, "NON-ATCT,BVN,ALBION MUNI/RON LEVANDER FLD"],
               "FRQ.csv": [h_frq, "BVN,NON-ATCT,BVN,ALBION MUNI/RON LEVANDER FLD,122.9,CTAF"]}
        ch = self.diff(old, new)["BVN"]
        self.assertEqual([c["summary"] for c in ch], ["airport name: Albion Muni -> Albion Muni/Ron Levander Fld"])


class TestColumns(Rows):
    """a changed column reads as the FAA layout's English, never its column name, and a code
    reads with the meaning the layout gives it. real rows, trimmed."""

    def test_approach_control_listed(self):
        """4AK 2026-10-01: the homepage card said 'apch p prov type cd: (none) -> C'."""
        h = ("FACILITY_ID,FACILITY_TYPE,PRIMARY_APCH_RADIO_CALL,APCH_P_PROVIDER,APCH_P_PROV_TYPE_CD,"
             "PRIMARY_DEP_RADIO_CALL,DEP_P_PROVIDER,DEP_P_PROV_TYPE_CD")
        self.assertEqual(self.one({"ATC_BASE.csv": [h, "4AK,NON-ATCT,,,,,,"]},
                                  {"ATC_BASE.csv": [h, "4AK,NON-ATCT,ANCHORAGE ARTCC,ZAN,C,ANCHORAGE ARTCC,ZAN,C"]},
                                  "4AK"),
                         [("action", "approach/departure control: none -> ANCHORAGE ARTCC (ZAN)")])

    def test_provider_type_is_decoded(self):
        h = "FACILITY_ID,FACILITY_TYPE,APCH_P_PROVIDER,APCH_P_PROV_TYPE_CD"
        (_, s), = self.one({"ATC_BASE.csv": [h, "X01,NON-ATCT,ZSE,C"]},
                           {"ATC_BASE.csv": [h, "X01,NON-ATCT,S46,T"]}, "X01")
        self.assertEqual(s, "approach control: ZSE (ARTCC) -> S46 (TRACON)")

    def test_codes_read_with_their_meaning(self):
        h = "ARPT_ID,RWY_ID,RWY_END_ID,VGSI_CODE,RWY_END_LGTS_FLAG,FAR_PART_77_CODE"
        (_, s), = self.one({"APT_RWY_END.csv": [h, "DAB,07/25,07,P2L,N,PIR"]},
                           {"APT_RWY_END.csv": [h, "DAB,07/25,07,P4L,Y,PIR"]}, "DAB")
        self.assertEqual(s, "runway 07: runway end identifier lights (REIL): no -> yes; visual glide slope "
                            "indicator: 2-light PAPI on left side of runway (P2L) -> 4-light PAPI on left "
                            "side of runway (P4L)")

    def test_a_code_the_layout_doesnt_define_stays_as_written(self):
        """ILS_GS G_S_TYPE_CODE is 'GS'/'GD' in the data, but the layout only lists 'GLIDE SLOPE'
        and 'GLIDE SLOPE/DME': no guessing which is which."""
        self.assertEqual(fields.say("G_S_TYPE_CODE", "ILS_GS", "GD"), "GD")
        self.assertEqual(fields.say("OBSTN_MRKD_CODE", "APT_RWY_END", "LM"), "LM")
        self.assertEqual(fields.say("SURFACE_TYPE_CODE", "APT_RWY", "GRVL"), "GRVL")
        self.assertEqual(fields.say("SURFACE_TYPE_CODE", "APT_RWY", "ASPH-TURF"),
                         "asphalt or bituminous concrete / grass; sod (ASPH-TURF)")

    def test_lists_say_what_came_and_went(self):
        h = "ARPT_ID,FUEL_TYPES,OTHER_SERVICES"
        (_, s), = self.one({"APT_BASE.csv": [h, "DAB,100LL,INSTR"]},
                           {"APT_BASE.csv": [h, "DAB,\"100LL,A\",\"INSTR,RNTL\""]}, "DAB")
        self.assertEqual(s, "fuel: added Jet A, kerosene, without FS-II (A); "
                            "services: added aircraft rental (RNTL)")

    def test_whose_column_it_is(self):
        h = "ARPT_ID,TITLE,NAME,ADDRESS1"
        (_, s), = self.one({"APT_CON.csv": [h, "DAB,MANAGER,JO SMITH,1 MAIN ST"]},
                           {"APT_CON.csv": [h, "DAB,MANAGER,JO SMITH,2 MAIN ST"]}, "DAB")
        self.assertEqual(s, "airport manager address: 1 MAIN ST -> 2 MAIN ST")

    def run_diff(self, old, new):
        d = tempfile.mkdtemp()
        o, n = os.path.join(d, "2026-09-03_CSV.zip"), os.path.join(d, "2026-10-01_CSV.zip")
        make_zip(o, old)
        make_zip(n, new)
        return run(o, n, None, log=lambda *_: None)

    def test_unnamed_column_keeps_act_and_is_counted(self):
        """a column the FAA layouts we read don't name: shown as the FAA wrote it, still act if
        it ranks act (never quietly demoted), and counted in the run's checks (TestRealCycle
        fails on any real one)."""
        h = "ARPT_ID,RWY_ID,RWY_LEN,NEW_LGT_COL"
        r = self.run_diff({"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h, "DAB,07/25,4000,N"]},
                          {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h, "DAB,07/25,4000,Y"]})
        self.assertEqual([(c["priority"], c["summary"]) for c in r["airports"]["DAB"]],
                         [("action", "runway 07/25: NEW_LGT_COL: N -> Y")])
        self.assertEqual(r["checks"]["no_english"], {"APT_RWY changed": 1})

    def test_every_column_in_the_layouts_has_a_name(self):
        """every column of every file the engine reads, from the real zip's headers."""
        import csv, io, zipfile
        from amend.rules import HIDDEN_FILES, base as fbase, is_noise_col
        zips = [z for z in ZIPS if os.path.exists(z)]
        if not zips:
            self.skipTest("needs the FAA NASR zips in data/")
        missing = set()
        with zipfile.ZipFile(zips[-1]) as z:
            for n in z.namelist():
                b = fbase(n.split("/")[-1])
                if (not n.endswith(".csv") or b.startswith(HIDDEN_FILES) or "DATA_STRUCTURE" in b
                        or b.startswith(("STAR", "DP", "PFR", "AWY", "ARB", "MAA", "WXL", "FSS"))):
                    continue
                with z.open(n) as f:
                    header = next(csv.reader(io.TextIOWrapper(f, encoding="latin-1")))
                missing |= {f"{b}.{c}" for c in header if not fields.known(c, b)
                            and c not in ("EFF_DATE", "LAST_INFO_RESPONSE") and not is_noise_col(c)}
        self.assertEqual(sorted(missing), [])


class TestValues(Case):
    """spec: output is checked against the structured old/new values before it's published."""

    def test_unsupported(self):
        vals = ["18/36", "2546", "60", "TURF"]
        self.assertEqual(unsupported("new runway 18/36: 2546x60 ft turf", vals), [])
        self.assertEqual(unsupported("runway 18: new arresting system", vals), [])
        self.assertEqual(unsupported("new runway 18/36: 2564x60 ft turf", vals), ["2564"])
        self.assertEqual(unsupported("declared distances: 1,234 ft", ["1234"]), [])

    def test_bad_template_shows_faa_values(self):
        """a template that prints a number the FAA row doesn't have never reaches a pilot."""
        real = english.ROW_SUMMARIES["APT_RWY"]
        english.ROW_SUMMARIES["APT_RWY"] = lambda kind, row: f"new runway {row['RWY_ID']}: 9999 ft"
        try:
            h = "ARPT_ID,RWY_ID,RWY_LEN"
            ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h]},
                           {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h, "DAB,18/36,2546"]})["DAB"]
        finally:
            english.ROW_SUMMARIES["APT_RWY"] = real
        self.assertEqual([c["summary"] for c in ch], ["apt_rwy added: runway 18/36, length 2546"])

    def test_rows_publish_their_fields(self):
        h = "ARPT_ID,RWY_ID,RWY_LEN"
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h, "DAB,18/36,2546"]},
                       {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": [h]})["DAB"]
        self.assertEqual(ch[0]["fields"], [{"field": "RWY_ID", "old": "18/36", "new": ""},
                                           {"field": "RWY_LEN", "old": "2546", "new": ""}])


class TestIds(Case):
    """ids hash the FAA change, not its wording: better English keeps 'new since you looked'."""
    OLD = {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN"]}
    NEW = {"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN", "DAB,18/36,2546"]}

    def test_rewording_keeps_the_id(self):
        before = self.diff(self.OLD, self.NEW)["DAB"][0]
        real = english.ROW_SUMMARIES["APT_RWY"]
        english.ROW_SUMMARIES["APT_RWY"] = lambda kind, row: f"runway {row['RWY_ID']} is new"
        try:
            after = self.diff(self.OLD, self.NEW)["DAB"][0]
        finally:
            english.ROW_SUMMARIES["APT_RWY"] = real
        self.assertNotEqual(before["summary"], after["summary"])
        self.assertEqual(before["id"], after["id"])

    def test_ids_unique_per_airport(self):
        """two rows that differ only in dropped survey columns are still two changes."""
        h = "ARPT_ID,RWY_ID,RWY_END_ID,ARREST_DEVICE_CODE,LAT_DECIMAL"
        new = {"APT_BASE.csv": ["ARPT_ID", "DAB"],
               "APT_ARS.csv": [h, "DAB,07/25,07,BAK-12,29.1", "DAB,07/25,07,BAK-12,29.2"]}
        ch = self.diff({"APT_BASE.csv": ["ARPT_ID", "DAB"], "APT_ARS.csv": [h]}, new)["DAB"]
        self.assertEqual(len({c["id"] for c in ch}), len(ch))


class TestBackfill(unittest.TestCase):
    """history/ entries older code wrote as raw dumps (real ones from history/, 2024-2026)."""

    def e(self, summary, source, kind, i):
        return {"cycle": "2026-08-06", "from_cycle": "2026-07-09", "id": i, "priority": "action",
                "category": "navaid", "kind": kind, "source": source, "summary": summary}

    def test_parse(self):
        self.assertEqual(backfill.parse("removed (apt_att): sked seq no=1, month=ALL, day=MON-WED, FRI, "
                                        "hour=0930-1530"),
                         ("removed", "APT_ATT", {"SKED_SEQ_NO": "1", "MONTH": "ALL", "DAY": "MON-WED, FRI",
                                                 "HOUR": "0930-1530"}))
        self.assertIsNone(backfill.parse("new ILS/DME RWY 28 (NIP, 109.15)"))

    def test_ils_folds_and_ids_stay(self):
        """NIP 2026-08-06, as the old code wrote it: 3 dumps -> 1 line with the ILS entry's id."""
        es = [self.e("added (ils_base): rwy end id=28, ils loc id=NIP, system type code=LD, "
                     "state name=FLORIDA, region code=ASO, rwy len=9003", "ILS_BASE", "added", "a1"),
              self.e("added (ils_gs): rwy end id=28, ils loc id=NIP, system type code=LD, component "
                     "status=OPERATIONAL IFR, component status date=2026/06/30, g s type code=GS",
                     "ILS_GS", "added", "a2"),
              self.e("added (ils_dme): rwy end id=28, ils loc id=NIP, system type code=LD, component "
                     "status=OPERATIONAL IFR, component status date=2026/06/30, site elevation=15",
                     "ILS_DME", "added", "a3")]
        out = backfill._cycle(es)
        self.assertEqual([(x["id"], x["summary"]) for x in out],
                         [("a1", "new ILS/DME RWY 28 (NIP) with glideslope, DME")])
        self.assertEqual(backfill._cycle(out), out)     # a second run changes nothing

    def test_hidden_files_and_runway_ends_go(self):
        es = [self.e("removed (hpf_base): hp name=MTH NDB, ...", "HPF_BASE", "removed", "h1"),
              self.e("removed (apt_rwy): rwy id=07/25, rwy len=4000, rwy width=40, surface type code=DIRT",
                     "APT_RWY", "removed", "r1"),
              self.e("removed (apt_rwy_end): rwy id=07/25, rwy end id=07", "APT_RWY_END", "removed", "r2")]
        self.assertEqual([(x["id"], x["summary"]) for x in backfill._cycle(es)],
                         [("r1", "runway 07/25 (4000x40 ft dirt): removed")])

    def test_attendance_says_what_the_dump_kept(self):
        es = [self.e("removed (apt_att): sked seq no=2, month=ALL, day=SAT- SUN, hour=0700-1900",
                     "APT_ATT", "removed", "t1")]
        self.assertEqual([x["summary"] for x in backfill._cycle(es)],
                         ["airport attendance schedule: dropped SAT- SUN 0700-1900"])


class TestHistory(unittest.TestCase):
    def test_no_column_names_in_history(self):
        """after python -m amend.backfill: no changed entry shows an FAA column name."""
        left = []
        for name in sorted(os.listdir(HISTORY)):
            if name.endswith(".json") and name not in ("index.json", "cycles.json"):
                with open(os.path.join(HISTORY, name), encoding="utf-8") as f:
                    left += [(name, e["summary"]) for e in json.load(f)["entries"] if backfill.leaks(e)]
        self.assertEqual(left[:5], [], f"{len(left)} history entries show FAA column names: "
                                       f"run python -m amend.backfill")

    def test_no_raw_dumps_in_history(self):
        """after python -m amend.backfill. a merge that brings old history back: run it again."""
        dumps = []
        for name in sorted(os.listdir(HISTORY)):
            if name.endswith(".json") and name not in ("index.json", "cycles.json"):
                with open(os.path.join(HISTORY, name), encoding="utf-8") as f:
                    dumps += [(name, e["summary"]) for e in json.load(f)["entries"]
                              if backfill.RAW.match(e["summary"])]
        self.assertEqual(dumps[:5], [], f"{len(dumps)} raw dumps in history/: run python -m amend.backfill")


META = gold.snapshot_meta()
ZIPS = [os.path.join(gold.DATA, META["zips"][k]["file"]) for k in ("from", "to")]


@unittest.skipIf(not all(map(os.path.exists, ZIPS)), "needs the snapshot's FAA NASR zips in data/ "
                                                      "(download lines in tests/gold/README.md)")
class TestRealCycle(unittest.TestCase):
    def test_no_raw_dumps_in_a_whole_cycle(self):
        """every airport, one real cycle pair: no raw dump, no summary with a value the FAA
        record doesn't have, no file without English."""
        r = run(ZIPS[0], ZIPS[1], None, log=lambda *_: None)
        dumps = [(apt, c["summary"]) for apt, ch in r["airports"].items() for c in ch
                 if re.search(RAW_DUMP, c["summary"])]
        self.assertEqual(dumps, [])
        self.assertEqual(r["checks"], {"no_english": {}, "summary_value_mismatches": 0})
        leaked = [(apt, c["summary"]) for apt, ch in r["airports"].items() for c in ch
                  if backfill.leaks({**c, "fields": c.get("fields") or []})]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
