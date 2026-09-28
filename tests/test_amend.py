"""
Regression tests built from real cases found in FAA data.
run:  python -m unittest -v
"""
import io
import json
import os
import re
import tempfile
import unittest
import zipfile

from amend import ENGINE_VERSION, remarks
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
        self.assertTrue(remarks.faithful(
            raw, "HIRL runway 01/19 preset on low intensity from sunset to sunrise; click the mic on CTAF."))

    def test_translation_audit_cases_are_rejected(self):
        """real translations from remark_cache.json that were wrong (audit, 2026-09-27)."""
        bad = [
            ("TO AND LDG NA SS-SR.", "Takeoff and landing not authorized sunrise to sunset."),
            ("30 FT PLINE CROSSES RWY CNTRLN 315 FT FM THR.",
             "30 foot pipeline crosses runway centerline 315 feet from threshold."),
            ("CTN: PAEW PARKED ON OR INVOF RWY.", "Caution: powered aircraft are parked on or near the runway."),
            ("FOR CD CTC CHICAGO APCH AT 847-289-0926.",
             "For crowd density information contact Chicago approach at 847-289-0926."),
            ("LGTD WIND CONES LCTD 1000 FT FM AER 17 & 35, LEFT SIDE.",
             "Lighted wind cones located 1000 feet from aerials 17 and 35, left side."),
            ("2400 FT MKD WITH CONES 300 FT AVBL FOR OVRN",
             "2400 feet marked with cones with 300 feet available for overnight parking."),
            ("TPA LGT ACFT 800 FT, HVY ACFT 1500 FT.", "Touchdown zone light aircraft 800 feet, heavy aircraft 1500 feet."),
            ("NRS & CNTRLN FADED.", "Runway markings and centerline are faded."),
            ("ACTVT REIL RWYS 14 & 32; MIRL RWY 14/32 - CTAF.",
             "Activate runway edge lights on runways 14 and 32 and medium intensity runway lights on runways 14/32."),
            ("ACTVT MIRL RWY 15/33 - CTAF.", "Activate medium intensity runway lights on runways 15/33 - contact CTAF."),
            # invented numbers: PCR has no runway in it, BT (back taxi) is not "90 degree"
            ("PCR VALUE: 1557/F/A/X/T",
             "Runway 15 pavement classification rating: 1557 feet, friction F, depth A, extent X, type T."),
            ("BT AND 180 DEG TURN ON RWY WILL BE RQR.", "90 degree and 180 degree turn on runway will be required."),
        ]
        for raw, plain in bad:
            self.assertFalse(remarks.faithful(raw, plain), plain)

    def test_faithful_translations_pass(self):
        good = [
            ("198 FT TWR 1,200 FT 'SW' OF ARPT.", "198 foot tower 1200 feet southwest of airport."),
            ("CAUTION: TREEO ARPT (4AL3), .25 NM SOUTH.", "Caution: TREEO airport (4AL3) is 0.25 nautical miles south."),
            ("30 FT PLINE CROSSES RWY 09.", "30 foot power line crosses runway 09."),
            ("ACTVT MIRL RWY 15/33 - CTAF.", "Click the mic on CTAF to turn on the medium intensity runway lights, runway 15/33."),
            # leaving a contraction alone is allowed; guessing is what's rejected
            ("RLLS.", "RLLS."),
            ("APCH RATIO 20:1 TO DTHR.", "Approach ratio 20:1 to the DTHR."),
            ("APCH RATIO 20:1 TO DTHR.", "Approach ratio 20:1 to the displaced threshold."),
        ]
        for raw, plain in good:
            self.assertEqual(remarks.problems(raw, plain), [], plain)

    def test_bad_cached_translation_falls_back_to_raw(self):
        """old cache entries get re-checked on load, so a tighter check retires them."""
        raw, ok = "30 FT PLINE CROSSES RWY 09.", "RWY 09 IS CLSD."
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump({raw: "30 foot pipeline crosses runway 09.", ok: "Runway 09 is closed."}, f)
        try:
            self.assertEqual(remarks.translate_remarks([raw, ok], use_llm=False),
                             {ok: "Runway 09 is closed."})
        finally:
            os.remove(remarks.CACHE_FILE)


class TestWhyFaaWords(Case):
    """a remark shown in the FAA's words says why, in the public JSON and on the page"""

    def test_each_remark_change_says_why(self):
        rmk = "ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK"
        texts = ["TIEDOWNS NA.", "RWY 21L CALM WIND RWY.", "66 FT RT.", "SOFT & RUTTED; IREG MRKD W CONES.", "RWY 03 CLSD.",
                 "46 FT POLE 200 FT FM THLD.", "WMRICHARDSON@COPPER.NET"]
        cache = {"TIEDOWNS NA.": "Tiedowns NA.", "RWY 21L CALM WIND RWY.": "Runway 21 Left is the calm wind runway.",
                 "46 FT POLE 200 FT FM THLD.": "46 FT POLE 200 FT FM THLD.",       # sent back: asked again
                 "WMRICHARDSON@COPPER.NET": "WMRICHARDSON@COPPER.NET"}              # nothing to translate
        rejects = {"engine": ENGINE_VERSION, "remarks": {
            "SOFT & RUTTED; IREG MRKD W CONES.": ["W has no verified meaning (see glossary); it must stay as written"],
            "66 FT RT.": [remarks.SENT_BACK]}}
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump(cache, f)
        with open(remarks._rejects_file(), "w") as f:
            json.dump(rejects, f)
        try:
            ch = self.diff({"APT_RMK.csv": [rmk]},
                           {"APT_RMK.csv": [rmk] + [f'DAB,A{i},"{t}"' for i, t in enumerate(texts)]}, {"DAB"})["DAB"]
        finally:
            os.remove(remarks.CACHE_FILE)
            os.remove(remarks._rejects_file())
        got = {c["original"]: (c["summary"], c.get("untranslated")) for c in ch}
        self.assertEqual(got, {
            "TIEDOWNS NA.": ("new remark: Tiedowns NA.",
                             "NA is left as the FAA wrote it: it can mean not authorized or not available, and "
                             "Amend doesn't guess which."),
            "RWY 21L CALM WIND RWY.": ("new remark: Runway 21L is the calm wind runway.", None),
            "66 FT RT.": ("new remark: 66 FT RT.", "Kept in the FAA's words: Amend has no verified meaning for RT."),
            "SOFT & RUTTED; IREG MRKD W CONES.": (
                "new remark: SOFT & RUTTED; IREG MRKD W CONES.",
                "Kept in the FAA's words: W can mean west, white or with, and Amend doesn't guess which."),
            "RWY 03 CLSD.": ("new remark: RWY 03 CLSD.", "Kept in the FAA's words until it's translated."),
            "46 FT POLE 200 FT FM THLD.": ("new remark: 46 FT POLE 200 FT FM THLD.",
                                           "Kept in the FAA's words until it's translated."),
            "WMRICHARDSON@COPPER.NET": ("new remark: WMRICHARDSON@COPPER.NET", None)})

    def test_the_page_shows_it(self):
        from amend import web
        c = {"id": "r", "priority": "fyi", "category": "remark", "kind": "added", "source": "APT_RMK",
             "summary": "new remark: 66 FT RT.", "original": "66 FT RT.",
             "untranslated": "Kept in the FAA's words: Amend has no verified meaning for RT."}
        page = web.change_html(c, "2026-10-01")
        self.assertIn('<div class="why">Kept in the FAA&#x27;s words: Amend has no verified meaning for RT.</div>'
                      '<details class="more"><summary>FAA text</summary>', page)
        self.assertNotIn('class="why"', web.change_html({**c, "untranslated": None}, "2026-10-01"))
        from amend import feeds       # and news readers get it too
        self.assertIn("<br><small>Kept in the FAA&#x27;s words: Amend has no verified meaning for RT.</small>"
                      "<br><small>FAA text: 66 FT RT.</small>", feeds.change_li(c))
        # the lists page draws changes in the browser, from the same JSON
        with open(web.__file__, encoding="utf-8") as f:
            self.assertIn("if(c.untranslated)more='<div class=\"why\">'+esc(c.untranslated)+'</div>'+more;", f.read())


class TestAccuracyAudit(Case):
    """01 OCT 2026 audit: real cases where amend ranked bookkeeping as act, said a thing twice,
    or labeled it wrong."""

    def one(self, old, new, apt):
        return self.diff(old, new, {apt}).get(apt, [])

    def test_survey_rounding_is_not_a_change(self):
        """YNG: glide slope 'site elevation: 1108.5 -> 1108.6' was act. F87: 'rwy len source:
        OWNER -> 3RD PARTY SURVEY' was act. FRM: 5503 -> 5505 ft runway was act."""
        gs = "ARPT_ID,RWY_END_ID,ILS_LOC_ID,SYSTEM_TYPE_CODE,SITE_ELEVATION"
        self.assertEqual(self.one({"ILS_GS.csv": [gs, "YNG,14,YNG,LS,1108.5"]},
                                  {"ILS_GS.csv": [gs, "YNG,14,YNG,LS,1108.6"]}, "YNG"), [])
        rwy = "ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,RWY_LEN_SOURCE"
        self.assertEqual(self.one({"APT_RWY.csv": [rwy, "F87,16/34,3000,60,OWNER"]},
                                  {"APT_RWY.csv": [rwy, "F87,16/34,3000,60,3RD PARTY SURVEY"]}, "F87"), [])
        self.assertEqual(self.one({"APT_RWY.csv": [rwy, "FRM,13/31,5503,100,"]},
                                  {"APT_RWY.csv": [rwy, "FRM,13/31,5505,100,"]}, "FRM"), [])

    def test_runway_length(self):
        """F41 3999 -> 4012 ft is a remeasure (fyi); 4998 -> 4370 ft is act."""
        rwy = "ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH"
        c = self.one({"APT_RWY.csv": [rwy, "F41,17/35,3999,75"]}, {"APT_RWY.csv": [rwy, "F41,17/35,4012,75"]}, "F41")
        self.assertEqual([x["priority"] for x in c], ["fyi"])
        c = self.one({"APT_RWY.csv": [rwy, "F41,17/35,4998,75"]}, {"APT_RWY.csv": [rwy, "F41,17/35,4370,75"]}, "F41")
        self.assertEqual([x["priority"] for x in c], ["action"])

    def test_awos_phone_and_type_are_fyi(self):
        """OFK: 'AWOS/ASOS phone number' and AUM 'AWOS-3 -> AWOS-3PT' were act."""
        aw = "ASOS_AWOS_ID,ASOS_AWOS_TYPE,PHONE_NO"
        c = self.one({"AWOS.csv": [aw, "OFK,ASOS,402-644-4480"]}, {"AWOS.csv": [aw, "OFK,ASOS,402-302-2024"]}, "OFK")
        self.assertEqual([x["priority"] for x in c], ["fyi"])
        frq = "FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE,SERVICED_SITE_TYPE"
        c = self.one({"FRQ.csv": [frq, "AUM,AUM,118.375,AUM AWOS-3,AWOS-3"]},
                     {"FRQ.csv": [frq, "AUM,AUM,118.375,AUM AWOS-3PT,AWOS-3PT"]}, "AUM")
        self.assertEqual([x["priority"] for x in c], ["fyi"])

    def test_holding_patterns_are_not_airport_changes(self):
        """MTH: the Marathon NDB hold showed up at Marathon airport as act, only because the
        navaid id matches the airport id. same for military training route points."""
        hp = "HP_NAME,HP_NO,NAV_ID,NAV_TYPE,HOLD_DIRECTION"
        self.assertEqual(self.one({"HPF_BASE.csv": [hp, "MARATHON NDB*FL,1,MTH,NDB,W"]},
                                  {"HPF_BASE.csv": [hp]}, "MTH"), [])

    def test_new_row_is_not_act_because_of_a_column_name(self):
        """ACV: a removed VOR checkpoint was act because the file has a NAV_ID column."""
        ck = "NAV_ID,NAV_TYPE,BRG,AIR_GND_CODE,CHK_DESC"
        c = self.one({"NAV_CKPT.csv": [ck, "ACV,VOR/DME,148,G,.8 NM AT APCH END RWY 32 RUNUP AREA."]},
                     {"NAV_CKPT.csv": [ck]}, "ACV")
        self.assertEqual([(x["priority"], x["summary"]) for x in c],
                         [("fyi", "ACV VOR checkpoint 148°: .8 nm at apch end rwy 32 runup area: removed")])
        # a runway disappearing is still act, even though nothing in the row says so
        rwy = "ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH"
        c = self.one({"APT_RWY.csv": [rwy, "ACV,14/32,4499,150", "ACV,02/20,6000,150"]},
                     {"APT_RWY.csv": [rwy, "ACV,02/20,6000,150"]}, "ACV")
        self.assertEqual([x["priority"] for x in c], ["action"])

    def test_new_runway_ends_not_repeated(self):
        rwy, end = "ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH", "ARPT_ID,RWY_ID,RWY_END_ID,RWY_MARKING_TYPE_CODE"
        old = {"APT_RWY.csv": [rwy, "34IN,18/36,2500,60"], "APT_RWY_END.csv": [end, "34IN,18/36,18,NONE"]}
        new = {"APT_RWY.csv": [rwy, "34IN,18/36,2500,60", "34IN,03/21,2000,60"],
               "APT_RWY_END.csv": [end, "34IN,18/36,18,NONE", "34IN,03/21,03,NONE", "34IN,03/21,21,NONE"]}
        c = self.one(old, new, "34IN")
        self.assertEqual([x["source"] for x in c], ["APT_RWY"])

    def test_always_on_lights_are_not_pilot_controlled(self):
        """JWY: dropping 'PAPI RWY 18 & 36 OPR CONSLY.' from a CTAF lighting remark was act,
        as if the PAPI stopped coming on. OKH: '07 & 25' -> '07/25' was act too."""
        rmk = "ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK"
        pri = lambda o, n: [x["priority"] for x in self.one(
            {"APT_RMK.csv": [rmk, f'X,A1,"{o}"']}, {"APT_RMK.csv": [rmk, f'X,A1,"{n}"']}, "X")]
        self.assertEqual(pri("ACTVT REIL RWY 18; MIRL RWY 18/36 - CTAF. PAPI RWY 18 & 36 OPR CONSLY.",
                             "ACTVT REIL RWY 18; MIRL RWY 18/36 - CTAF."), ["fyi"])
        self.assertEqual(pri("ACTVT NSTD LIRL RWY 07 & 25 - CTAF.", "ACTVT NSTD LIRL RWY 07/25 - CTAF."),
                         ["fyi"])
        # MAZ: 'REILS RWY 09' dropped out; the plural hid it
        self.assertEqual(pri("RWY 09/27 MIRLS SS-SR. ACTVT PAPI RWYS 09 & 27; REILS RWY 09 - CTAF.",
                             "ACTVT RWY 09/27 MIRLS & PAPI RWY 27 - CTAF.  PAPI RWY 9 OPER CONTIUNOUS."),
                         ["action"])

    def test_same_remark_on_two_frequencies_said_once(self):
        """E01: the same 'APCH/DEP SVC PRVDD BY' remark on two FRQ rows showed twice."""
        frq = "FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE,REMARK"
        o, n = "APCH/DEP SVC PRVDD BY ZFW ON FREQS 133.1/298.95", "APCH/DEP SVC PRVDD BY FORT WORTH ARTCC ON FREQS 133.1/298.95"
        c = self.one({"FRQ.csv": [frq, f"ZFW,E01,133.1,APCH/P,{o}", f"ZFW,E01,298.95,APCH/P,{o}"]},
                     {"FRQ.csv": [frq, f"ZFW,E01,133.1,APCH/P,{n}", f"ZFW,E01,298.95,APCH/P,{n}"]}, "E01")
        self.assertEqual(len(c), 1)

    def test_navaid_unusable_sectors_are_ifr_remarks(self):
        """DIK: VOR unusable sectors changing was fyi, and ILS/navaid remarks were labeled navaid."""
        hdr = "NAV_ID,NAV_TYPE,REMARK"
        c = self.one({"NAV_RMK.csv": [hdr, "DIK,VOR/DME,VOR UNUSBL 005-015 BYD 40 NM."]},
                     {"NAV_RMK.csv": [hdr, "DIK,VOR/DME,VOR UNUSBL 010-020 BYD 52 NM."]}, "DIK")
        self.assertEqual([(x["priority"], x["category"]) for x in c], [("ifr", "remark")])

    def test_declared_distances_no_longer_listed_is_fyi(self):
        """RVS: ASDA/LDA 2641 ft -> blank read as a runway cut to zero."""
        end = "ARPT_ID,RWY_ID,RWY_END_ID,ACLT_STOP_DIST_AVBL,LNDG_DIST_AVBL,RWY_END_ELEV"
        c = self.one({"APT_RWY_END.csv": [end, "RVS,01L/19R,01L,2641,2641,614.6"]},
                     {"APT_RWY_END.csv": [end, "RVS,01L/19R,01L,,,614.8"]}, "RVS")
        self.assertEqual([x["priority"] for x in c], ["fyi"])


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

    def test_name_lists(self):
        """the ids and states the remark review queue doesn't count, from NASR's own files"""
        from amend.nasr import name_lists
        d = tempfile.mkdtemp()
        old, new = os.path.join(d, "old.zip"), os.path.join(d, "new.zip")
        make_zip(old, {"APT_BASE.csv": ["ARPT_ID,ICAO_ID,STATE_CODE", "SPS,KSPS,TX", "1T7,,TX"]})
        make_zip(new, {"APT_BASE.csv": ["ARPT_ID,ICAO_ID,STATE_CODE", "ADK,PADK,AK"],
                       "ARB_BASE.csv": ["LOCATION_ID,LOCATION_NAME", "ZOA,OAKLAND", "ZAN,ANCHORAGE"]})
        self.assertEqual(name_lists(old, new), ({"KSPS", "PADK", "ZOA", "ZAN"}, {"TX", "AK"}))


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
        self.assertRegex(page, r'assets/style\.css\?v=[0-9a-f]{10}"')  # cache-busted stylesheet
        self.assertIn('data-f="ifr"', page)                         # filter tabs
        self.assertIn('id="c-2025-07-10"', page)                    # history cycles can be linked
        self.assertIn('data-look="VRB"', page)                      # "New" labels since the last visit
        self.assertIn('<div class="it p-action" data-id="a">', page)
        self.assertIn('data-id="x" data-c="2025-07-10"', page)       # history items carry their cycle
        self.assertIn('data-until="2026-10-01T09:01:00Z"', page)     # countdown to the changeover
        self.assertIn('id="wbtn" data-apt="VRB"', page)             # add to a list from the airport page
        self.assertIn('id="wmenu"', page)                           # ...or pick which lists, with more than one
        self.assertIn('NASR_Subscription/2026-10-01" target="_blank"', page)   # every change links its FAA source
        self.assertIn('title="Official FAA plate (d-TPP)">View plate', page)
        self.assertIn('NASR_Subscription/2025-07-10"', page)          # history links its own cycle
        self.assertIn('FAA cycle 01 Oct 2026<span class="flip" data-after=""> (upcoming)</span> · updated '
                      '<time datetime="2026-09-24T00:00:00Z" data-ago="2026-09-24T00:00:00Z">24 Sep 0000Z</time>', page)
        self.assertIn('data-built="2026-09-24T00:00:00Z"', page)      # the page says when it's stale
        self.assertIn('id="stale" hidden', page)

    def test_countdown_and_calendar(self):
        import datetime as dt
        from amend import web
        meta = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True}
        before, after = (dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc), dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc))
        self.assertEqual(web.next_changeover(meta, before), (dt.datetime(2026, 10, 1, 9, 1, tzinfo=dt.timezone.utc), True))
        self.assertEqual(web.next_changeover(meta, after), (dt.datetime(2026, 10, 29, 9, 1, tzinfo=dt.timezone.utc), False))
        site, _ = self.build()
        ics = open(os.path.join(site, "cycles.ics"), newline="").read()
        self.assertIn("DTSTART:20261001T090100Z\r\n", ics)
        self.assertIn("DTSTART:20260903T090100Z", ics)               # the one in effect, too
        self.assertEqual(ics.count("BEGIN:VEVENT"), 15)
        index = open(os.path.join(site, "index.html")).read()
        self.assertIn('id="next"', index)                           # coming up at your airports
        self.assertIn('"eff": "2026-10-01T09:01:00Z", "after": "2026-10-29T09:01:00Z"', index)

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
        app = open(os.path.join(site, "assets", "app.js")).read()
        self.assertIn('K="amend.lists"', app)                       # lists storage key
        self.assertIn('OLD="amend.watch"', app)                     # the old single watchlist still migrates

    def test_history_skips_the_cycle_shown(self):
        import datetime as dt
        from amend import web
        site, hist = tempfile.mkdtemp(), tempfile.mkdtemp()
        row = {"priority": "fyi", "category": "remark", "kind": "changed", "summary": "remark updated", "source": "APT_RMK"}
        with open(os.path.join(hist, "VRB.json"), "w") as f:     # the daily job adds the cycle in effect to history
            json.dump({"airport": "VRB", "entries": [{**row, "cycle": "2026-09-03", "id": "n"},
                                                     {**row, "cycle": "2025-07-10", "id": "o"}]}, f)
        meta = {"from_cycle": "2026-08-06", "to_cycle": "2026-09-03", "upcoming": False, "changed_airports": 1}
        web.build(site, meta, [{"id": "VRB", "name": "Vero Beach Rgnl"}], {"VRB": [{**row, "id": "n"}]}, hist,
                  now=dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc))
        page = open(os.path.join(site, "VRB", "index.html")).read()
        self.assertIn('id="c-2025-07-10"', page)
        self.assertNotIn('id="c-2026-09-03"', page)              # already at the top of the page, not again below
        self.assertEqual(page.count('data-id="n"'), 1)

    def test_lists_pages(self):
        site, _ = self.build()
        index = open(os.path.join(site, "index.html")).read()
        self.assertRegex(index, r'<script src="assets/app\.js\?v=[0-9a-f]{10}"></script>')
        vrb = open(os.path.join(site, "VRB", "index.html")).read()
        self.assertIn('<input type="hidden" name="go" value="1">', vrb)     # sidebar search: an exact ID opens it
        self.assertIn('id="sq"', index)                                     # same sidebar on the home page
        self.assertIn('id="sbw"', index)
        app = open(os.path.join(site, "assets", "app.js")).read()
        self.assertIn('function which(ls,el)', app)                         # the sidebar opens the list the page shows
        self.assertIn('href="list/">Lists</a>', index)                      # phone top bar reaches the lists
        lists = open(os.path.join(site, "list", "index.html")).read()
        for part in ('id="ltabs"', 'id="actions"', 'id="manage"', 'id="lnote"', '"DAB":["KDAB","Daytona Beach Intl"]'):
            self.assertIn(part, lists)
        nf = open(os.path.join(site, "404.html")).read()
        self.assertIn('<meta name="robots" content="noindex">', nf)
        self.assertIn('href="/assets/style.css?v=', nf)          # served at any depth, so links start at /
        self.assertIn('replace(/^K(?=[A-Z]{3}$)/,"")', nf)       # /kvrb -> /VRB/

    @unittest.skipUnless(__import__("shutil").which("node"), "needs node")
    def test_lists_script(self):
        import subprocess
        site, _ = self.build()
        r = subprocess.run(["node", "-e", LISTS_TEST, os.path.join(site, "assets", "app.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_brand_and_trust(self):
        from amend import brand, web
        site, _ = self.build()
        for f in ("favicon.ico", "site.webmanifest", "404.html", "assets/icon.svg", "assets/apple-touch-icon.png",
                  "assets/icon-512.png", "assets/icon-maskable-512.png", "assets/fonts/plex-sans-latin.woff2",
                  "assets/fonts/OFL.txt"):
            self.assertTrue(os.path.exists(os.path.join(site, f)), f)
        page = open(os.path.join(site, "VRB", "index.html")).read()
        self.assertNotIn("fonts.googleapis.com", page)                  # fonts come from amend.watch
        self.assertIn('href="../assets/fonts/plex-sans-latin.woff2" as="font"', page)
        self.assertIn('<link rel="icon" href="../favicon.ico"', page)
        self.assertIn('<link rel="canonical" href="https://amend.watch/VRB/">', page)
        self.assertIn('static.cloudflareinsights.com/beacon.min.js', page)   # the about page's privacy note says so
        self.assertIn('class="mk"', page)                               # the logo, tile coloured by the theme
        self.assertIn("not affiliated with the FAA", page)
        self.assertIn("issues/new?title=VRB%3A%20", page)               # report a wrong change
        self.assertIn('url(fonts/plex-sans-latin.woff2)', open(os.path.join(site, "assets", "style.css")).read())
        about = open(os.path.join(site, "about", "index.html")).read()
        self.assertIn('id="report"', about)
        self.assertIn('"privacy": "../privacy/"', about)                 # old /about/#privacy links still land
        self.assertIn('"how": "https://docs.amend.watch/how-it-works/#how"', about)   # old /about/#how goes to the docs name
        read = lambda p: open(os.path.join(site, p, "index.html")).read()
        docs, privacy, terms, log = read("docs"), read("privacy"), read("terms"), read("changelog")
        how, api, using = read("docs/how-it-works"), read("docs/api"), read("docs/using")
        for text in ('id="how"', 'id="limits"', "NOTAMs.</b>"):
            self.assertIn(text, how)
        self.assertIn('id="meta"', api)
        self.assertIn('id="lists"', using)
        self.assertIn('id="start"', docs)
        for text in ("Cloudflare Web Analytics", "GitHub Pages", "served by amend.watch itself", "No accounts"):
            self.assertIn(text, privacy)
        self.assertIn("Not for navigation", terms)
        self.assertIn(web.UPDATES[0][1][0][:40], log)
        for p in (about, docs, privacy, terms, log):
            self.assertNotIn("coming soon", p.lower())
        for p in (about, privacy, terms, log):
            self.assertIn('href="../privacy/">Privacy</a>', p)
        self.assertIn(f'href="{web.SITE_URL}privacy/">Privacy</a>', docs)   # docs has its own name (subsite.py)
        missing = open(os.path.join(site, "404.html")).read()
        self.assertIn('href="/assets/style.css?v=', missing)              # served at any depth
        self.assertIn('replace(/^K(?=[A-Z]{3}$)/,"")', missing)          # /kvrb goes on to /VRB/
        self.assertNotIn('rel="canonical"', missing)
        manifest = json.load(open(os.path.join(site, "site.webmanifest")))
        self.assertEqual(manifest["name"], "Amend")
        # the red pen: both a's inside the tile, the strike across the old a and clear of the new one, on whole
        # pixels at 16 px
        xs, ys = [], []
        for cmd, args in re.findall(r"([MLHVQZ])([^MLHVQZ]*)", brand.A_PATH):
            v = [float(n) for n in args.split()]
            if cmd == "H":
                xs += v
            elif cmd == "V":
                ys += v
            else:
                xs, ys = xs + v[0::2], ys + v[1::2]
        ink = lambda x, base, s: (x + min(xs) * s, x + max(xs) * s, base - max(ys) * s, base - min(ys) * s)
        old, new = ink(*brand.OLD), ink(*brand.NEW)
        for left, right, top, bottom in (old, new):
            self.assertTrue(2 < left < right < 62 and 2 < top < bottom < 62)
        x0, y0, x1, y1 = brand.STRIKE
        self.assertTrue(x0 < old[0] and old[1] < x1 < new[0])
        self.assertTrue(old[2] < y0 < y1 < old[3] and y0 % 4 == 0 and y1 % 4 == 0)
        icon = open(os.path.join(site, "assets", "icon.svg")).read()
        self.assertIn(brand.LIGHT["strike"], icon)
        self.assertIn(brand.DARK["strike"], icon)                      # the favicon follows dark mode

    def test_logo_matches_font(self):
        from amend import brand
        try:
            import fontTools  # noqa: F401  (a dev tool: CI only has Pillow)
        except ImportError:
            self.skipTest("needs fontTools")
        self.assertEqual(brand._a_path(), brand.A_PATH)


# runs assets/app.js with a fake localStorage: the lists saved in the browser, and the old single watchlist
LISTS_TEST = r"""
const vm = require("vm"), fs = require("fs"), assert = require("assert").strict;
const src = fs.readFileSync(process.argv[1], "utf8");
function load(store, broken) {
  const st = {getItem: k => { if (broken) throw new Error("denied"); return k in store ? store[k] : null },
              setItem: (k, v) => { if (broken) throw new Error("denied"); store[k] = String(v) }};
  const ctx = {localStorage: st, sessionStorage: st, navigator: {}, URL, setInterval() {}, addEventListener() {},
               location: {href: "https://amend.watch/VRB/"},
               document: {body: {dataset: {root: "../"}}, querySelectorAll: () => [], getElementById: () => null, addEventListener() {}}};
  vm.createContext(ctx);
  vm.runInContext(src + ";this.LS=LS", ctx);
  return ctx.LS;
}
const plain = x => JSON.parse(JSON.stringify(x));
// the old watchlist and its name become the first list, and amend.watch keeps every saved airport
let store = {"amend.watch": '["DAB","VRB","dab"]', "amend.watch.name": "Club SVFR"};
let LS = load(store);
const first = plain(LS.all());
assert.equal(first.length, 1);
assert.match(first[0].id, /^w[0-9a-z]+$/);
assert.deepEqual([first[0].name, first[0].ids], ["Club SVFR", ["DAB", "VRB"]]);
assert.deepEqual(plain(LS.all()), first);                    // same id on every read
assert.deepEqual(plain(load({"amend.watch": '["DAB","VRB"]'}).all())[0].name, "My airports");
assert.notEqual(plain(load({"amend.watch": '["SFB"]'}).all())[0].id, first[0].id);   // not one id for everyone
// more lists: the new one is in use, names don't repeat, amend.watch is every airport on any list
const trip = LS.create("Keys trip", ["EYW", "MTH"]);
assert.equal(LS.active().id, trip.id);
assert.equal(LS.create("keys TRIP", []).name, "keys TRIP 2");
assert.deepEqual(JSON.parse(store["amend.watch"]), ["DAB", "VRB", "EYW", "MTH"]);
LS.set(trip.id, ["FLL", "EYW"], true);
assert.deepEqual(plain(LS.all().find(l => l.id === trip.id).ids), ["EYW", "MTH", "FLL"]);
LS.set(trip.id, ["MTH"], false);
assert.equal(LS.rename(trip.id, "  Club svfr ").name, "Club svfr 2");
assert.equal(LS.same(["VRB", "DAB"], "whatever").id, first[0].id);
assert.equal(LS.same(["DAB"], ""), null);
assert.equal(LS.link(LS.all()[0]), "https://amend.watch/list/?w=DAB,VRB&n=Club%20SVFR");
LS.use(first[0].id); LS.remove(first[0].id);
assert.equal(LS.active().id, trip.id);                        // deleting the list in use moves to another
assert.deepEqual(plain(LS.union()), ["EYW", "FLL"]);
// junk in storage: bad ids dropped, long names cut, unreadable lists fall back to amend.watch
store = {"amend.lists": JSON.stringify([{id: "a", name: "x".repeat(99), ids: ["DAB", "no way", 7, "VRB"]}, {name: "no id"}])};
const [a] = plain(load(store).all());
assert.deepEqual([a.name.length, a.ids], [60, ["DAB", "VRB"]]);
assert.deepEqual(plain(load({"amend.lists": "{nope", "amend.watch": '["SFB"]'}).all())[0].ids, ["SFB"]);
// storage blocked (some private modes): no lists, no crash
LS = load({}, true);
assert.deepEqual(plain(LS.all()), []);
assert.equal(LS.active(), null);
LS.create("x", ["DAB"]);
"""


class TestFeeds(unittest.TestCase):
    def test_airport_feed(self):
        import xml.etree.ElementTree as ET
        site, _ = TestWeb().build()
        xml = open(os.path.join(site, "VRB", "feed.xml"), encoding="utf-8").read()
        ch = ET.fromstring(xml).find("channel")                       # well-formed RSS
        self.assertEqual(ch.findtext("link"), "https://amend.watch/VRB/")
        items = ch.findall("item")
        self.assertEqual([i.findtext("guid") for i in items], ["amend.watch/VRB/2026-10-01", "amend.watch/VRB/2025-07-10"])
        self.assertEqual(items[0].findtext("title"), "VRB: 2 changes (1 action item) on 01 Oct 2026")
        self.assertEqual(items[0].findtext("pubDate"), "Thu, 03 Sep 2026 09:01:00 +0000")   # stable, never ahead
        body = items[0].findtext("description")
        self.assertLess(body.index("Action (1)"), body.index("IFR procedures (1)"))     # action items first
        self.assertIn("0800-2200 → 0600-2200", body)
        self.assertIn("NASR_Subscription/2026-10-01", body)
        self.assertEqual(items[1].findtext("link"), "https://amend.watch/VRB/#c-2025-07-10")
        page = open(os.path.join(site, "VRB", "index.html")).read()
        self.assertIn('<link rel="alternate" type="application/rss+xml" title="VRB changes each FAA cycle" '
                      'href="https://amend.watch/VRB/feed.xml">', page)
        self.assertIn('id="alerts"', page)
        self.assertIn('<details class="addw pop" id="alerts"><summary class="btn ghost dd">Get alerts</summary>', page)
        self.assertEqual(page.count('id="alerts"'), 1)                    # opens under the button, not a rail card
        self.assertIn('<script type="speculationrules">', page)          # hover prefetch between pages
        self.assertIn('<div id="sbw" data-on="VRB"></div><script>SB.side()</script>', page)   # lists on first paint
        quiet = ET.parse(os.path.join(site, "DAB", "feed.xml")).getroot().find("channel")   # no page, still a feed
        self.assertEqual(quiet.findall("item"), [])
        self.assertEqual(quiet.findtext("link"), "https://amend.watch/")
        self.assertFalse(os.path.exists(os.path.join(site, "DAB", "index.html")))
        self.assertIn('id="opml"', open(os.path.join(site, "list", "index.html")).read())
        self.assertIn("Copy alert link", page)                               # pilot words first, RSS under More options
        self.assertIn("<summary>More options</summary>", page)

    def test_list_feed_and_email(self):
        import datetime as dt
        import xml.etree.ElementTree as ET
        from amend import web
        site = tempfile.mkdtemp()
        hist = tempfile.mkdtemp()
        with open(os.path.join(hist, "DAB.json"), "w") as f:
            json.dump({"airport": "DAB", "entries": [
                {"cycle": "2026-09-03", "priority": "fyi", "category": "remark", "kind": "changed",
                 "summary": "remark reworded", "original": "RWY 7L CLSD", "source": "APT_RMK", "id": "r"}]}, f)
        latest = {"VRB": [{"id": "a", "priority": "action", "category": "tower", "kind": "changed",
                           "summary": "tower hours: 0800-2200 -> 0600-2200 local", "source": "ATC_BASE"}]}
        meta = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01", "upcoming": True, "changed_airports": 1}
        lists = {"club": {"name": "Club & Co", "description": "", "airports": ["DAB", "VRB"]}}
        now = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
        web.build(site, meta, [{"id": "VRB", "name": "Vero Beach Rgnl"}], latest, hist, now=now, watchlists=lists)
        items = ET.parse(os.path.join(site, "list", "club", "feed.xml")).getroot().find("channel").findall("item")
        self.assertEqual([i.findtext("title") for i in items],
                         ["Club & Co: 1 change at 1 airport on 01 Oct 2026 (1 action item)",
                          "Club & Co: 1 change at 1 airport on 03 Sep 2026 (no action items)"])
        self.assertIn("FAA text: RWY 7L CLSD", items[1].findtext("description"))
        page = open(os.path.join(site, "list", "club", "index.html")).read()
        self.assertIn('href="https://amend.watch/list/club/feed.xml"', page)
        self.assertNotIn('name="email"', page)                       # no email form until EMAIL_FORM is set
        old, web.EMAIL_FORM = web.EMAIL_FORM, "https://buttondown.com/api/emails/embed-subscribe/x"
        try:
            web.build(site, meta, [], latest, hist, now=now, watchlists=lists)
        finally:
            web.EMAIL_FORM = old
        page = open(os.path.join(site, "list", "club", "index.html")).read()
        self.assertIn('action="https://buttondown.com/api/emails/embed-subscribe/x"', page)
        self.assertIn('name="tag" value="list:club"', page)
        self.assertNotIn('name="email"', open(os.path.join(site, "VRB", "index.html")).read())   # lists only

class TestWatchlists(unittest.TestCase):
    def test_validation(self):
        from amend.watchlists import validate
        self.assertEqual(validate("clubsvfr", {"name": "Club SVFR", "airports": ["DAB", "KOMN"]}), [])
        self.assertTrue(validate("Club SVFR!", {"name": "x", "airports": ["DAB"]}))     # bad link name
        self.assertTrue(validate("about", {"name": "x", "airports": ["DAB"]}))          # reserved
        self.assertTrue(validate("guide", {"name": "x", "airports": ["DAB"]}))
        self.assertTrue(validate("privacy", {"name": "x", "airports": ["DAB"]}))
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
        self.assertIn('href="../../assets/style.css?v=', html_)
        self.assertIn('href="../?w=', html_)                             # save to my lists, even without script
        self.assertIn('id="savenamed" href="../?w=DAB,VRB&amp;n=Club%20SVFR" data-ids="DAB,VRB"', html_)
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

    def test_e3_and_e4_extensions_changed_together_listed_once(self):
        """two class E extensions of one airport, moved together, read the same: one line, one id."""
        def ext(kind, ring):
            return ({"NAME": f"VERO BEACH CLASS {kind}", "LOCAL_TYPE": f"CLASS_{kind}", "IDENT": "VRB",
                     "LOWER_VAL": "700", "LOWER_CODE": "SFC", "UPPER_VAL": "2500", "UPPER_CODE": "MSL"}, ring)
        a, b = box(27.72, -80.418, 0.03), box(27.76, -80.418, 0.03)
        c = self.run_shapes([self.d("2500"), ext("E3", a), ext("E4", a)],
                            [self.d("2500"), ext("E3", b), ext("E4", b)], {"VRB"})["VRB"]
        self.assertEqual(len({x["summary"] for x in c}), len(c))
        self.assertEqual(len({x["id"] for x in c}), len(c))

    def test_no_shapefile_is_skipped(self):
        d = tempfile.mkdtemp()
        o, n, e = (os.path.join(d, x) for x in ("2026-09-03_CSV.zip", "2026-10-01_CSV.zip", "empty.zip"))
        for p in (o, n, e):
            make_zip(p, {"APT_BASE.csv": self.APT})
        self.assertEqual(run(o, n, {"VRB"}, log=lambda *_: None, airspace=(e, e))["airports"], {})


class TestReleaseAudit(Case):
    """amend/audit.py: checks that stop a bad cycle from reaching pilots."""
    TODAY = __import__("datetime").date(2026, 9, 27)

    def ch(self, summary, apt="VRB", priority="action", **kw):
        from amend.pipeline import change_id
        return {"id": change_id(apt, "2026-10-01", summary), "priority": priority, "category": "remark",
                "kind": "changed", "summary": summary, "source": kw.pop("source", "APT_RMK"), **kw}

    def check(self, airports):
        from amend.audit import check_changes
        return check_changes(airports, "2026-10-01")

    def test_real_cycle_output_passes(self):
        old = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "VRB,VRB,126.3,LCL/P"],
               "APT_RMK.csv": ["ARPT_ID,REMARK", "VRB,ACTVT MIRL RWY 04/22 - CTAF."]}
        new = {"FRQ.csv": ["FACILITY,SERVICED_FACILITY,FREQ,FREQ_USE", "VRB,VRB,126.3,LCL/P",
                           "VRB,VRB,122.9,CTAF"],
               "APT_RMK.csv": ["ARPT_ID,REMARK", "VRB,ACTVT MIRL RWY 04/22 - 126.3."]}
        self.assertEqual(self.check(self.diff(old, new, {"VRB"})), ([], []))

    def test_cycle_dates(self):
        from amend.audit import check_cycles
        self.assertEqual(check_cycles("2026-09-03", "2026-10-01", self.TODAY), [])
        self.assertIn("not an FAA cycle date", check_cycles("2026-09-03", "2026-10-02", self.TODAY)[0])
        self.assertTrue(check_cycles("2026-08-06", "2026-10-01", self.TODAY))       # skipped a cycle
        self.assertEqual(check_cycles("2026-08-06", "2026-10-01", self.TODAY, gap_ok=True), [])
        self.assertIn("more than one cycle ahead", check_cycles("2026-10-01", "2026-10-29", self.TODAY)[0])

    def test_duplicates(self):
        c = self.ch("remark removed: RWY 04 CLSD.")
        errs, _ = self.check({"VRB": [c, dict(c)]})
        self.assertEqual(len(errs), 2)      # same id and same text

    def test_code_bug_in_summary(self):
        errs, _ = self.check({"VRB": [self.ch("frequency None (CTAF) added", source="FRQ")]})
        self.assertIn("code bug", errs[0])

    def test_faa_none_value_is_not_a_code_bug(self):
        """a name column the FAA sets to NONE prints as 'None' through .title(); that's data."""
        c = self.ch("airport manager: Smith -> None", priority="fyi", source="APT_CON",
                    fields=[{"field": "NAME", "old": "SMITH", "new": "NONE"}])
        self.assertEqual(self.check({"VRB": [c]}), ([], []))

    def test_mistranslation_in_output(self):
        """3T3, Oct 2024: SS-SR dropped and 'contact CTAF' on pilot-controlled lighting."""
        raw = "MIRL RWY 08/26 PRESET TO LOW SS-SR; TO INCR INTST AND ACTVT REIL RWY 26; MIRL RWY 08/26  - CTAF."
        bad = self.ch("revised remark: Runway 08/26 medium intensity runway lights preset to low; contact "
                      "CTAF to increase intensity and activate REIL on runway 26.", original=raw)
        errs, _ = self.check({"3T3": [bad]})
        self.assertTrue(any("SS-SR" in e for e in errs) and any("click the mic" in e for e in errs))
        self.assertEqual(self.check({"3T3": [self.ch("revised remark: " + raw, original=raw)]}), ([], []))

    def test_changed_number_in_translation(self):
        raw = "RWY 04 CLSD 2200-0600."
        errs, _ = self.check({"VRB": [self.ch("new remark: Runway 04 closed 10pm to 8am.", original=raw)]})
        self.assertTrue(any("lost number 2200" in e for e in errs))

    def test_chart_from_wrong_cycle(self):
        c = self.ch("approach ILS RWY 11R amended (amdt 2)", priority="ifr", source="D-TPP",
                    chart={"pdf": "https://aeronav.faa.gov/d-tpp/2609/00110IL11R.PDF"})
        self.assertIn("wrong cycle", self.check({"DAB": [c]})[0][0])
        c["chart"]["pdf"] = "https://aeronav.faa.gov/d-tpp/2610/00110IL11R.PDF"
        self.assertEqual(self.check({"DAB": [c]}), ([], []))

    def test_impossible_values_warn(self):
        def fields(name, new):
            return self.ch(f"{name}: x -> {new}", source="APT_RWY", fields=[{"field": name, "old": "x", "new": new}])
        _, warn = self.check({"VRB": [fields("RWY_ID", "16/37"), fields("RWY_ID", "12/14"),
                                      fields("RWY_LEN", "0"), fields("G_S_ANGLE", "30"),
                                      self.ch("new frequency 95.5 (CTAF)", source="FRQ")]})
        self.assertEqual(len(warn), 5)
        _, warn = self.check({"VRB": [fields("RWY_ID", "08W/26W"), fields("RWY_ID", "NE/SW"),
                                      fields("RWY_ID", "H1"), fields("RWY_ID", "16/35"),
                                      fields("G_S_ANGLE", "3.5"),
                                      self.ch("frequency 34.5 (ARMY OPS) added", source="FRQ"),
                                      self.ch("frequency 142.6 (ATIS) added", source="FRQ"),
                                      self.ch("frequency 243.0 (EMERG) added", source="FRQ")]})
        self.assertEqual(warn, [])

    def test_fyi_values_are_not_checked(self):
        c = self.ch("x", priority="fyi", source="APT_RWY", fields=[{"field": "RWY_LEN", "old": "1", "new": "0"}])
        self.assertEqual(self.check({"VRB": [c]}), ([], []))

    def test_action_count_against_past_cycles(self):
        from amend.audit import check_counts
        apts = {f"A{i}": [self.ch("x", apt=f"A{i}")] for i in range(400)}
        self.assertEqual(check_counts(apts, [400, 450, 380]), ([], []))
        self.assertEqual(len(check_counts(apts, [130, 140, 150])[1]), 1)      # ~3x: warn
        self.assertEqual(len(check_counts(apts, [60, 70, 75])[0]), 1)         # ~6x: stop
        self.assertIn("only 5 airports", check_counts(dict(list(apts.items())[:5]), [])[0][0])

    def test_packet_has_watched_and_busiest_action_and_ifr_only(self):
        from amend.audit import packet
        result = {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01",
                  "airports": {"X21": [self.ch("a", apt="X21")], "ZZZ": [self.ch("b", apt="ZZZ")],
                               "ATL": [self.ch("c", apt="ATL", priority="fyi")]}}
        p = packet(result, {"errors": [], "warnings": ["w"]}, {"t": {"airports": ["X21"]}})
        self.assertEqual(list(p["airports"]), ["X21"])
        self.assertEqual(p["warnings"], ["w"])
        self.assertEqual(p, packet(result, {"errors": [], "warnings": ["w"]}, {"t": {"airports": ["X21"]}}))

    def test_history_has_no_mistranslations(self):
        """history is shown forever; a translation the checks reject must not be in it."""
        import glob
        from amend.audit import translation_problems
        bad = []
        for path in glob.glob(os.path.join(os.path.dirname(__file__), "..", "history", "*.json")):
            with open(path, encoding="utf-8") as f:
                h = json.load(f)
            bad += [f"{h.get('airport')} {e['cycle']}: {e['summary']}" for e in h.get("entries", [])
                    if translation_problems(e)]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
