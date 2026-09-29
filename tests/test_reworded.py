"""
A remark edit that only rewords the FAA text is fyi (amend/diff.py just_reworded). An edit that
changes what the remark means must keep its rank. These pin both sides.

MUST_KEEP_RANK: edits that change the meaning, each run through the real diff. Today the engine
reads several as a rewording and ranks them fyi: the numbers are compared as a set, not in
order; a taxiway letter or a day isn't compared at all; and opposite words (BEFORE/AFTER,
OVER/UNDER, a direction) aren't blockers. Those are marked KNOWN_MISS and run as expected
failures, so this file documents the gap without blocking a deploy (update.yml runs every test
before it publishes). When the engine is fixed, the case it fixes turns into an "unexpected
success" and fails: drop it from KNOWN_MISS in the same PR, like a gold known_failure.
The first three are real FAA rows from the 2026-09-03 -> 2026-10-01 cycle. The rest are made-up
edits of the shapes FAA remarks take, not FAA text.

MUST_STAY_REWORDED: real FAA rewordings (2026-08-06 -> 09-03 and 09-03 -> 10-01) that are fyi
today and must stay fyi, so a fix can't turn every SNOW -> SN, OVER -> OVR or LEFT -> L into an
act line.
run:  python -m unittest tests.test_reworded -v
"""
import unittest

from amend import diff as d

# (name, file, old text, new text, rank the change should have)
MUST_KEEP_RANK = [
    # the VOR unusable sectors moved (009-059 -> 009-048 at 25 and 34 NM); the same cycle's DME
    # remark with the same edit ranks ifr, because its numbers changed as a set
    ("oth_vor_sectors", "NAV_RMK",
     "VOR UNUSBL 009-048 BYD 40 NM; 009-059 BYD 25 NM BLW 5000 FT: 009-059 BYD 34 NM BLW 7500; 049-059 BYD "
     "40 NM BLW 6000 FT; 049-059 BYD 46 NM BLW 7000 FT; 060-092 BYD 20 NM BLW 7500 FT; 060-150 BYD 40 NM.",
     "VOR UNUSBL  009-048 BYD 25 NM BLW 5000 FT; 009-048 BYD 34 NM BLW 7500 FT; 009-048 BYD 40 NM; 049-059 "
     "BYD 40 NM BLW 6000 FT; 049-059 BYD 46 NM BLW 7000 FT; 060-092 BYD 20 NM BLW 7500 FT; 060-150 BYD 40 NM.",
     "ifr"),
    # who you call for a clearance now depends on approach being closed, not the tower
    ("dbn_when_apch_clsd", "APT_RMK",
     "FOR CD CTC ATLANTA APCH AT 678-364-6132, WHEN ATCT CLSD CTC ATLANTA ARTCC AT 770-210-7692.",
     "FOR CD IF UNA TO CTC ON FSS FREQ, CTC ATLANTA APCH AT 678-364-6132, WHEN APCH CLSD CTC ATLANTA ARTCC "
     "AT 770-210-7692.",
     "action"),
    # reduced runway separation now applies to all AETC aircraft, not only fighters
    ("sps_all_aetc_acft", "APT_RMK",
     "MISC: AETC FTR ACFT EXP REDUCED RY SEPARATION: DAY/VFR, SIMILAR TYPE ACFT 3000 FT, DISSIMILAR TYPE ACFT "
     "6000 FT, NIGHT 6000 FT ALL AETC ACFT. TRAN AETC ACFT NOTIFY TWR ON INITIAL CTC IF REDUCED RY SEPARATION "
     "IS NOT DESIRED.",
     "MISC: AETC ACFT EXP REDUCED RWY SEPARATION. DAY/VFR, SIMILAR TYPE ACFT 3000 FT, DISSIMILAR TYPE ACFT "
     "6000 FT, NIGHT 6000 FT ALL AETC ACFT. TRAN AETC ACFT NOTIFY TWR ON INITIAL CTC IF REDUCED RWY SEPARATION "
     "IS NOT DESIRED.",
     "action"),
    # made-up edits from here on
    ("taxiway_letter", "APT_RMK", "TWY A CLSD.", "TWY B CLSD.", "action"),
    ("taxiway_side", "APT_RMK", "TWY A CLSD WEST OF TWY C.", "TWY A CLSD EAST OF TWY C.", "action"),
    ("weekdays_to_weekends", "APT_RMK", "RWY 18 CLSD MON-FRI.", "RWY 18 CLSD SAT-SUN.", "action"),
    ("night_to_day", "APT_RMK", "RWY 06 CLSD SS-SR.", "RWY 06 CLSD SR-SS.", "action"),
    ("winter_to_summer", "APT_RMK", "TWR CLSD DURING WINTER MONTHS.", "TWR CLSD DURING SUMMER MONTHS.", "action"),
    ("over_to_under", "APT_RMK", "RWY 27 CLSD TO ACFT OVER 12500 LBS.", "RWY 27 CLSD TO ACFT UNDER 12500 LBS.",
     "action"),
    ("before_to_after", "APT_RMK", "PPR 24 HRS BEFORE ARR.", "PPR 24 HRS AFTER ARR.", "action"),
    ("takeoff_to_landing", "APT_RMK", "RWY 36 CLSD TO TKOF.", "RWY 36 CLSD TO LNDG.", "action"),
    ("wet_to_dry", "APT_RMK", "RWY 18 CLSD WHEN WET.", "RWY 18 CLSD WHEN DRY.", "action"),
    ("north_to_south", "APT_RMK", "NOISE ABATEMENT: AVOID OVERFLIGHT OF SCHOOL N OF ARPT.",
     "NOISE ABATEMENT: AVOID OVERFLIGHT OF SCHOOL S OF ARPT.", "action"),
    ("left_to_right_traffic", "APT_RMK", "TPA 1000 FT AGL; LEFT TFC RWY 09.", "TPA 1000 FT AGL; RIGHT TFC RWY 09.",
     "action"),
    ("transient_to_based", "APT_RMK", "PPR FOR ALL TRANSIENT ACFT.", "PPR FOR ALL BASED ACFT.", "action"),
    ("helicopters_to_gliders", "APT_RMK", "PPR FOR TRANSIENT HELICOPTERS.", "PPR FOR TRANSIENT GLIDERS.", "action"),
    # ones the engine already gets right: a blocker word, a number, a facility
    ("gains_exc", "APT_RMK", "RWY 09 CLSD TO JET ACFT.", "RWY 09 CLSD EXC TO JET ACFT.", "action"),
    ("gains_not", "APT_RMK", "RWY 09 CLSD TO JET ACFT.", "RWY 09 NOT CLSD TO JET ACFT.", "action"),
    ("hour_to_day", "APT_RMK", "PPR 1 HR.", "PPR 1 DAY.", "action"),
    ("ctaf_to_unicom", "APT_RMK", "CTAF 122.8 WHEN TWR CLSD.", "UNICOM 122.8 WHEN TWR CLSD.", "action"),
    ("non_movement", "APT_RMK", "TRANSPONDER REQD IN MOVEMENT AREA.", "TRANSPONDER REQD IN NON-MOVEMENT AREA.",
     "action"),
]
KNOWN_MISS = {"oth_vor_sectors", "dbn_when_apch_clsd", "sps_all_aetc_acft", "taxiway_letter", "taxiway_side",
              "weekdays_to_weekends", "night_to_day", "winter_to_summer", "over_to_under", "before_to_after",
              "takeoff_to_landing", "wet_to_dry", "north_to_south", "left_to_right_traffic", "transient_to_based",
              "helicopters_to_gliders"}

# (name, file, old, new): real FAA edits, same meaning, fyi today
MUST_STAY_REWORDED = [
    ("maf_taxiways", "APT_RMK", "TWYS  B & F NORTH RWY 10/28 CLSD TO ACFT OVER 60000 LBS.",
     "TWYS  B AND F N RWY 10/28 CLSD TO ACFT OVR 60000 LBS."),
    ("blm_over", "APT_RMK", "RWY 03/21 CLSD TO ACFT OVER 12500 LBS.", "RWY 03/21 CLSD TO ACFT OVR 12500 LBS."),
    ("1s2_snow", "APT_RMK", "CLSD WHEN SNOW ON RY.", "CLSD WHEN SN ON RWY."),
    ("56c_season", "APT_RMK", "ARPT CLSD NOV-APR & WHEN SNOW COVD.", "ARPT CLSD NOV-APR AND WHEN SN COVD."),
    ("s43_closed", "APT_RMK", "CLOSED NOV 1 - MAY 31.", "CLSD NOV 1 - MAY 31."),
    ("gwr_ry", "APT_RMK", "RY 06/24 CLSD WINTER MONTHS.", "RWY 06/24 CLSD WINTER MONTHS."),
    ("24a_left", "APT_RMK", "UNUSBL BYD 8 DEG LEFT OF CNTRLN.", "UNUSBL BYD 8 DEG L OF CNTRLN."),
    ("24a_after", "APT_RMK", "AFTER SS ACTVT REIL RWY 33; PAPI RWY 15 & 33; MIRL RWY 15/33 - CTAF.",
     "AFT SS ACTVT REIL RWY 33; PAPI RWY 15 & 33; MIRL RWY 15/33 - CTAF."),
    ("sps_rys", "APT_RMK", "DUE TO CLOSE PROXIMITY OF RYS 33L & 33C USE VIGILANCE WITH MONITOR GND TRACK FOR "
     "THE HI-TACAN  RY 33C APCH.", "DUE TO CLOSE PROXIMITY OF RWYS 33L & 33C USE VIGILANCE WITH MONITOR GND "
     "TRACK FOR THE HI-TACAN  RWY 33C APCH."),
]

# the columns that make the old and new row one remark, so the diff pairs them
ROW = {"APT_RMK": {"ARPT_ID": "XYZ", "LEGACY_ELEMENT_NUMBER": "A110-1"},
       "NAV_RMK": {"NAV_ID": "XYZ", "NAV_TYPE": "VOR/DME"}}


def rank(fname, old, new):
    """the rank the diff gives one remark edited from old to new."""
    recs = d.diff({f"{fname}.csv": [("XYZ", {**ROW[fname], "REMARK": old})]},
                  {f"{fname}.csv": [("XYZ", {**ROW[fname], "REMARK": new})]})
    assert len(recs) == 1 and recs[0]["kind"] == "changed", recs
    return recs[0]["priority"]


class TestMeaningChangesKeepTheirRank(unittest.TestCase):
    pass


class TestRewordingsStayFyi(unittest.TestCase):
    pass


def _keeps(fname, old, new, want):
    def test(self):
        self.assertEqual(rank(fname, old, new), want, f"{old!r} -> {new!r} ranked as a rewording")
    return test


def _stays(fname, old, new):
    def test(self):
        self.assertTrue(d.just_reworded(old, new), f"{old!r} -> {new!r} no longer reads as a rewording")
        self.assertEqual(rank(fname, old, new), "fyi")
    return test


for _name, _f, _old, _new, _want in MUST_KEEP_RANK:
    _t = _keeps(_f, _old, _new, _want)
    setattr(TestMeaningChangesKeepTheirRank, f"test_{_name}",
            unittest.expectedFailure(_t) if _name in KNOWN_MISS else _t)
for _name, _f, _old, _new in MUST_STAY_REWORDED:
    setattr(TestRewordingsStayFyi, f"test_{_name}", _stays(_f, _old, _new))


class TestTheListsAreConsistent(unittest.TestCase):
    def test_every_known_miss_is_a_case(self):
        self.assertEqual(KNOWN_MISS - {c[0] for c in MUST_KEEP_RANK}, set())

    def test_names_are_unique(self):
        names = [c[0] for c in MUST_KEEP_RANK] + [c[0] for c in MUST_STAY_REWORDED]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
