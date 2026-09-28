"""
The diff engine's own rules (amend/diff.py, collapse.py, rules.py), tested on real FAA text.
Each case here is a gold-set case (tests/gold/cases.jsonl) the engine used to get wrong, cut
down to the one rule it exercises, plus the hash-seed bug: the same FAA files must give the
same output on every run.
run:  python -m unittest tests.test_diff_engine -v
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

from amend import diff as d
from amend.pipeline import category, run
from tests.test_amend import Case, make_zip

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# rows where more than one pairing scores the same: before the fix, which old row got paired
# with which new row depended on Python's string hash seed (diff.py walked set differences)
TIES = {
    # two frequency uses on one frequency both replaced (CLT/IAD/EQY 124.0: KWEEN DP, BEAVY DP)
    "FRQ.csv": ["SERVICED_FACILITY,FREQ,FREQ_USE,SECTORIZATION",
                "DAB,124.0,KWEEN DP,NORTH", "DAB,124.0,BEAVY DP,SOUTH"],
    # BAM: two attendance schedules rewritten
    "APT_ATT.csv": ["ARPT_ID,SKED_SEQ_NO,MONTH,DAY,HOUR",
                    "DAB,1,ALL,MON-FRI,0800-1700", "DAB,2,ALL,SAT-SUN,0900-1500"],
    # an airport removed: its runways are listed in the one "airport removed" line (0E9, 93TS)
    "APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "DAB,DAYTONA BEACH INTL", "X50,MASSEY RANCH"],
    "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE",
                    "DAB,07L/25R,10500,150,ASPH", "X50,18/36,4000,75,ASPH", "X50,09/27,3000,60,TURF",
                    "X50,H1,40,40,CONC"],
}
TIES_NEW = {
    "FRQ.csv": ["SERVICED_FACILITY,FREQ,FREQ_USE,SECTORIZATION", "DAB,124.0,BATTA DP,EAST"],
    "APT_ATT.csv": ["ARPT_ID,SKED_SEQ_NO,MONTH,DAY,HOUR",
                    "DAB,1,ALL,MON-SUN,0800-1600", "DAB,2,ALL,MON-SUN,0900-1600"],
    "APT_BASE.csv": ["ARPT_ID,ARPT_NAME", "DAB,DAYTONA BEACH INTL"],
    "APT_RWY.csv": ["ARPT_ID,RWY_ID,RWY_LEN,RWY_WIDTH,SURFACE_TYPE_CODE", "DAB,07L/25R,10500,150,ASPH"],
}


def _run_with_seed(seed, old, new):
    code = ("import json, sys, tempfile, os; from amend import remarks; "
            "remarks.CACHE_FILE = os.path.join(tempfile.mkdtemp(), 'c.json'); "
            "from amend.pipeline import run; "
            "r = run(sys.argv[1], sys.argv[2], None, log=lambda *_: None); "
            "print(json.dumps([r['airports'], r['hidden']], sort_keys=True))")
    p = subprocess.run([sys.executable, "-c", code, old, new], cwd=HERE, capture_output=True,
                       text=True, env={**os.environ, "PYTHONHASHSEED": str(seed)})
    if p.returncode:
        raise RuntimeError(p.stderr[-2000:])
    return p.stdout.strip().splitlines()[-1]


class TestSameOutputEveryRun(unittest.TestCase):
    """the published ids hash the summary text, so a different pairing on a rebuild of the same
    FAA files changes ids and 'new since your last look' for nobody's reason."""

    def zips(self, old, new):
        dd = tempfile.mkdtemp()
        o, n = os.path.join(dd, "2026-08-06_CSV.zip"), os.path.join(dd, "2026-09-03_CSV.zip")
        make_zip(o, old)
        make_zip(n, new)
        return o, n

    def test_any_hash_seed(self):
        o, n = self.zips(TIES, TIES_NEW)
        outs = {_run_with_seed(seed, o, n) for seed in range(8)}
        self.assertEqual(len(outs), 1, "output depends on PYTHONHASHSEED")

    def test_any_row_order(self):
        """the FAA doesn't promise row order inside a file; shuffling rows changes nothing."""
        base_out = None
        rnd = random.Random(7)
        for _ in range(6):
            old = {f: [rows[0]] + rnd.sample(rows[1:], len(rows) - 1) for f, rows in TIES.items()}
            new = {f: [rows[0]] + rnd.sample(rows[1:], len(rows) - 1) for f, rows in TIES_NEW.items()}
            o, n = self.zips(old, new)
            got = json.dumps(run(o, n, None, log=lambda *_: None)["airports"], sort_keys=True)
            base_out = base_out or got
            self.assertEqual(got, base_out)

    def test_best_match_wins_over_first_come(self):
        """an old row pairs with the new row it matches best, even when another old row would
        have claimed that new row first."""
        o = [("A", {"K": "1", "X": "a", "Y": "b", "Z": "c"}),
             ("A", {"K": "1", "X": "a", "Y": "b", "Z": "q"})]
        n = [("A", {"K": "1", "X": "a", "Y": "b", "Z": "c2"}),
             ("A", {"K": "1", "X": "a", "Y": "b2", "Z": "q"})]
        recs = d.diff({"T.csv": o}, {"T.csv": n})
        pairs = sorted((f["old"], f["new"]) for r in recs for f in r["fields"])
        self.assertEqual(pairs, [("b", "b2"), ("c", "c2")])


class TestRewordedOrNot(unittest.TestCase):
    """just_reworded() decides a remark only got reworded. real cases where it was wrong."""

    def test_monitoring_flip_is_not_a_rewording(self):   # g027 OKM
        self.assertFalse(d.just_reworded("ILS UNMONITORED.", "ILS MONITORED AT MOCC."))

    def test_added_restriction_is_not_a_rewording(self):   # g067 EVY
        self.assertFalse(d.just_reworded("RWY 11/29 CLSD FOR NIGHT OPS.",
                                         "RWY 11/29 CLSD FOR NIGHT OPS; DAYTIME VFR USE ONLY."))

    def test_real_rewordings_still_are(self):   # g019 HKY, g121 SPS, g101 RST
        self.assertTrue(d.just_reworded(
            "CLSD TO UNSKED ACR OPNS WITH MORE THAN 30 PSGR SEATS EXCP 24 HR PPR CALL AMGR 828-323-7408.",
            "CLSD TO UNSKED ACR OPS WITH MORE THAN 30 PAX SEATS EXC 24 HR PPR - 828-323-7408."))
        self.assertTrue(d.just_reworded("MIL ARPT CONDUCTS HI PER JET TRNG MON-FRI 1200-0200Z++.",
                                        "MIL ARPT CONDUCTS HI PERFORMANCE JET TRNG MON-FRI 1200-0200Z++."))


class TestHours(unittest.TestCase):
    """hours text rewritten with the same schedule (LUF, MTC) is not an hours change."""

    def test_same_schedule_new_format(self):
        self.assertTrue(d.same_hours(      # g083 LUF ATIS
            "OPR 1330Z-0530Z MON-THU, 1330Z-0130Z FRI, CLSD WEEKENDS, HOL, AND AETC FAMILY DAYS.",
            "1330-0530Z MON-THU; 1330-0130Z FRI; CLSD WKENDS, HOLS, & ACC FAMILY DAYS"))
        self.assertTrue(d.same_hours(      # g084 LUF class D
            "CLASS D SVC MON-THU 1330Z-0530Z, FRI 1330Z-0130Z, CLSD WEEKENDS, HOL, AND AETC FAMILY "
            "DAYS, OTHER TIMES CLASS G.",
            "CLASS D SVC 1330-0530Z MON-THU, 1330-0130Z FRI, CLSD WKENDS, HOLS, & ACC FAMILY DAYS; "
            "OTHER TIMES CLASS G"))
        self.assertTrue(d.same_hours(      # g091 MTC tower
            "1230-0400Z++, CLSD HOL.  OT UNCONTROLLED FOR DHS, ARNG, USCG OR EMERGENCY OPS.",
            "1230-0400Z++ EXC HOLS"))

    def test_real_hours_changes(self):
        for old, new in [
                ("0800-2200", "0700-2200"),                                     # g028 OUN tower
                ("OPEN 24 HRS.", "1500-0700Z++ MON-SUN EXC HOLS"),               # g111 BIF tower
                ("1800-0800Z MON-FRI; CLSD SAT, SUN AND HOL. MP 1630-2300Z WED.",  # g093 NGF radar
                 "0830-1700 MON; 0830-0100 TUE-FRI; 2100-0100 SAT; CLSD SUN & HOLS; MP 0630-1300 WED"),
                ("0700-2100 MON-FRI, 0800-2000 SAT-SUN", "0800-2000 MON-FRI, 0700-2100 SAT-SUN"),
                ("0700-2100 MON-FRI, CLSD HOL", "0700-2100 MON-FRI, OPR HOL"),
                ("0700-2100 MON-FRI, CLSD SAT", "0700-2100 MON-FRI, CLSD SUN"),
                ("0700-2100", "0700-2100Z"),                                    # local -> zulu
                ("1200-0200Z", "1200-0200Z++")]:                                # DST shift
            with self.subTest(old=old, new=new):
                self.assertFalse(d.same_hours(old, new))


class TestLighting(unittest.TestCase):
    """pilot-controlled lighting remarks: act only when a light stops coming on or the
    frequency you key changes."""

    def test_part_time_continuous_light_is_still_pilot_controlled(self):   # g015 DBN
        self.assertEqual(d.pcl_priority(
            "ACTVT MALSR  RWY 02; PAPI RWY 02 & 20 - CTAF. HIRL RWY 02/20 OPER CONT DUSK-2200; "
            "AFTER 2200 ACTVT - CTAF.",
            "ACTVT MALSR  RWY 02 - CTAF. HIRL RWY 02/20; PAPI RWY 02 AND 20 - OPER CONT DUSK-2200; "
            "AFTER 2200 ACTVT - CTAF."), "fyi")

    def test_renumbered_runways_keep_their_lights(self):   # g090 MRI
        self.assertEqual(d.pcl_priority(
            "ACTVT REIL RWY 07, 16, 25, 34; MIRL RWY 07/25 & 16/34 - CTAF. PAPI RWY 07, 25 & 34; "
            "VASI RWY 16 OPR CONSLY.; WHEN ATCT CLSD CTC MERRILL WX - CTAF OR 271-4355.",
            "ACTVT REIL RWY 08, 17, 26, 35; MIRL RWY 08/26 & 17/35 - CTAF. PAPI RWY 08, 26 & 35; "
            "VASI RWY 17 OPR CONSLY.; WHEN ATCT CLSD CTC MERRILL WX - CTAF OR 271-4355."), "fyi")

    def test_a_light_that_really_goes_away(self):
        self.assertEqual(d.pcl_priority("ACTVT MIRL RWY 07/25; REIL RWY 07 - CTAF.",
                                        "ACTVT MIRL RWY 07/25 - CTAF."), "action")
        # renumbered, but a REIL was dropped along the way
        self.assertEqual(d.pcl_priority("ACTVT MIRL RWY 07/25; REIL RWY 07 - CTAF.",
                                         "ACTVT MIRL RWY 08/26 - CTAF."), "action")
        # all day continuous, no pilot control left for the PAPI
        self.assertEqual(d.pcl_priority("ACTVT HIRL RWY 02/20; PAPI RWY 02 - CTAF.",
                                         "ACTVT HIRL RWY 02/20 - CTAF. PAPI RWY 02 OPER CONT."), "fyi")


class TestPriorityRules(Case):
    """whole-pipeline checks on the real rows, trimmed to the columns that matter."""

    def one(self, fname, header, old, new, apt):
        ch = self.diff({fname: [header] + old, "APT_BASE.csv": ["ARPT_ID", apt]},
                       {fname: [header] + new, "APT_BASE.csv": ["ARPT_ID", apt]}).get(apt, [])
        return ch

    def test_new_ramp_approval_requirement_is_act(self):   # g018 DFW
        h = "ARPT_ID,LEGACY_ELEMENT_NUMBER,REMARK"
        ch = self.one("APT_RMK.csv", h, [], ['DFW,A110-98,"ACFT USING SOUTH RAMP MUST OBTAIN APVL FM '
                                             'RAMP 129.825 PRIOR TO ENTERING RAMP AND PRIOR TO PUSHBACK."'], "DFW")
        self.assertEqual([c["priority"] for c in ch], ["action"])

    def test_one_foot_displaced_threshold_is_survey(self):   # g013 BNA
        h = "ARPT_ID,RWY_ID,RWY_END_ID,DISPLACED_THR_LEN"
        self.assertEqual(self.one("APT_RWY_END.csv", h, ["BNA,13/31,13,800"], ["BNA,13/31,13,801"], "BNA"), [])
        ch = self.one("APT_RWY_END.csv", h, ["BNA,13/31,13,800"], ["BNA,13/31,13,1200"], "BNA")
        self.assertEqual([c["priority"] for c in ch], ["action"])

    def test_vor_declination(self):   # g098 OTZ
        h = "NAV_ID,NAV_TYPE,MAG_VARN,MAG_VARN_HEMIS,MAG_VARN_YEAR"
        ch = self.one("NAV_BASE.csv", h, ["OTZ,VOR/DME,15,E,2010"], ["OTZ,VOR/DME,9,E,2025"], "OTZ")
        self.assertEqual([(c["priority"], c["category"]) for c in ch], [("action", "navaid")])
        # an NDB has no radials: its variation is the area's, bookkeeping
        self.assertEqual(self.one("NAV_BASE.csv", h, ["OTZ,NDB,15,E,2010"], ["OTZ,NDB,9,E,2025"], "OTZ"), [])
        # the year alone moving is bookkeeping too
        self.assertEqual(self.one("NAV_BASE.csv", h, ["OTZ,VOR/DME,15,E,2010"], ["OTZ,VOR/DME,15,E,2025"], "OTZ"), [])

    def test_empty_non_atct_row(self):   # g100 P14
        h = "FACILITY_TYPE,FACILITY_ID,FACILITY_NAME,REGION_CODE,TWR_HRS,TWR_CALL"
        ch = self.one("ATC_BASE.csv", h, ["NON-ATCT,P14,HOLBROOK MUNI,AWP,,"], [], "P14")
        self.assertEqual([(c["priority"], c["category"]) for c in ch], [("fyi", "tower")])
        ch = self.one("ATC_BASE.csv", h, ["ATCT,P14,HOLBROOK MUNI,AWP,0700-2100,HOLBROOK"], [], "P14")
        self.assertEqual([c["priority"] for c in ch], ["action"])

    def test_fss_outlet_note_in_a_tower_remark(self):   # g105 T03
        h = "FACILITY_ID,LEGACY_ELEMENT_NUMBER,REMARK_NO,REMARK"
        ch = self.one("ATC_RMK.csv", h, ['T03,1,1,"COMMUNICATIONS PRVDD BY PRESCOTT RADIO ON FREQS '
                                         '122.05R/113.5T (TUBA CITY RCO)."'], [], "T03")
        self.assertEqual([c["priority"] for c in ch], ["fyi"])
        # g050 AVL: an outlet note that says communications are unavailable is still act
        ch = self.one("ATC_RMK.csv", h, ['AVL,1,1,"COMM UNAVBL BLO 6000 FT EXCP BY RDU RADIO ON FREQ 122.3 '
                                         '(SUGARLOAF MOUNTAIN RCO) WHEN AVL APCH CTL CLSD."'], [], "AVL")
        self.assertEqual([c["priority"] for c in ch], ["action"])

    def test_new_awos_is_fyi_a_lost_one_is_act(self):   # g003 4MD, g040 4WN7
        h = "ASOS_AWOS_ID,ASOS_AWOS_TYPE"
        self.assertEqual([c["priority"] for c in self.one("AWOS.csv", h, [], ["4MD,AWOS-3PT"], "4MD")], ["fyi"])
        self.assertEqual([c["priority"] for c in self.one("AWOS.csv", h, ["4MD,AWOS-3PT"], [], "4MD")], ["action"])


class TestCategories(Case):
    def test_radar_hours_are_tower(self):   # g093 NGF
        self.assertEqual(category("RDR.csv"), "tower")

    def test_tower_hours_on_a_frequency_row_are_tower(self):   # g091 MTC
        h = "SERVICED_FACILITY,FREQ,FREQ_USE,TOWER_HRS"
        ch = self.diff({"FRQ.csv": [h, "MTC,119.6,APCH/P DEP/P,1230-0400Z++"], "APT_BASE.csv": ["ARPT_ID", "MTC"]},
                       {"FRQ.csv": [h, "MTC,119.6,APCH/P DEP/P,1230-0200Z++"], "APT_BASE.csv": ["ARPT_ID", "MTC"]})
        self.assertEqual([(c["priority"], c["category"]) for c in ch["MTC"]], [("action", "tower")])


if __name__ == "__main__":
    unittest.main()
