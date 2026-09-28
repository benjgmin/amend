"""
The verified glossary and the no-guess rule: a remark translation may expand a contraction only
to a meaning the FAA gives for it. the cases are real translations from remark_cache.json.
run:  python -m unittest tests.test_glossary -v
"""
import glob
import io
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from amend import cli, glossary, output, remarks

with open(glossary.SOURCES_FILE) as f:
    SOURCES = json.load(f)


def _index():
    """{TERM: [(list, usage, text)]} for every FAA row, read straight from faa_abbreviations.json
    rather than through glossary.senses(). a Chart Supplement cell like 'lgt, lgtd, lgts' names three terms."""
    out = {}
    for abbr, text in SOURCES["chart_supplement"]["rows"]:
        for k in re.split(r",\s*|\s+or\s+", glossary.norm(abbr)):
            out.setdefault(k.upper(), []).append(("CS", None, glossary.norm(text)))
    for abbr, text, usage in SOURCES["jo_7340_2"]["rows"]:
        out.setdefault(glossary.norm(abbr).upper(), []).append(("JO", usage, glossary.norm(text)))
    return out


FAA_ROWS = _index()


def faa_rows(term):
    return FAA_ROWS.get(term, [])


def says(meaning, text):
    return re.search(r"(?<![a-z])" + re.escape(meaning.lower()) + r"(?![a-z])", text.lower()) is not None


class TestGlossary(unittest.TestCase):
    def test_committed_file_is_built_from_the_faa_lists(self):
        """glossary.json is generated. edit CURATED in glossary.py and run python -m amend.glossary."""
        with open(glossary.GLOSSARY_FILE) as f:
            committed = json.load(f)
        self.assertEqual(committed, json.loads(json.dumps(glossary.build())))

    def test_every_verified_meaning_is_faa_text(self):
        terms = glossary.load()
        verified = {t: e for t, e in terms.items() if e["verified"]}
        self.assertGreater(len(verified), 2500)
        for term, e in verified.items():
            if e.get("parts"):
                parts = [terms[p] for p in e["parts"]]
                self.assertTrue(all(p["verified"] for p in parts), term)
                self.assertEqual(e["expansion"], " to ".join(p["expansion"] for p in parts))
                continue
            cur = glossary.CURATED.get(term, {})
            rows = faa_rows(e.get("derived_from") or e.get("spelling_of") or cur.get("root", term))
            if term not in glossary.CURATED:     # weather-report meanings are used only when picked
                rows = [r for r in rows if r[0] == "CS" or r[1] in glossary.JO_USED]
            self.assertTrue(e["meanings"], term)
            for m in e["meanings"]:
                self.assertTrue(any(says(m, text) for _, _, text in rows), f"{term}: {m!r} is not FAA text")
            # and the source shown to readers is the list the first meaning came from
            src = ("CS", None) if e["source"].startswith("CS") else \
                ("JO", re.match(r"JO 2-1-1 \((\w+)\)", e["source"]).group(1))
            self.assertTrue(any((s, u if s == "JO" else None) == src and says(e["meanings"][0], text)
                                for s, u, text in rows), f"{term}: {e['source']}")

    def test_an_invented_meaning_is_refused(self):
        for cur in ({"THLD": {"expansion": "threshold lights"}},
                    {"ACC": {"expansion": "arriving"}},
                    {"ARNGMT": {"root": "ARNG", "expansion": "arrangement"}},   # the root says 'arrange'
                    {"FATO": {"accept": [r"\blanding area\b"]}},                  # in no FAA list
                    {"X-Y": {"parts": ["THLD", "ATD"]}}):                        # ATD has two meanings
            with mock.patch.dict(glossary.CURATED, cur), self.assertRaises((ValueError, KeyError), msg=cur):
                glossary.build()

    def test_run_together_meanings_are_the_faa_words(self):
        for term, (run, split) in glossary.CS_RUN_TOGETHER.items():
            self.assertEqual(" ".join(split), run)
            self.assertIn(run, [text for s, _, text in faa_rows(term) if s == "CS"], term)

    def test_unsettled_and_plain_word_terms_are_not_verified(self):
        g = glossary.load()
        for t in ("ATD", "TRANS", "TO", "CST", "B"):      # two meanings, or one that doesn't fit remarks
            self.assertFalse(g[t]["verified"], t)
            self.assertIsNone(g[t]["expansion"], t)
        for t in ("END", "PER", "HOLD", "IS"):
            self.assertTrue(g[t]["english"], t)
            self.assertFalse(g[t]["verified"], t)

    def test_the_model_is_told_only_reviewed_meanings(self):
        """a JO 7340.2-only meaning is accepted, but suggested only once it's been checked against
        real remarks (REVIEWED, CURATED): plenty are from other fields. the Chart Supplement's own
        list is what remarks are written with."""
        for term, e in glossary.load().items():
            if e["prompt"]:
                self.assertTrue(e["source"].startswith("CS") or term in glossary.CURATED
                                or term in glossary.REVIEWED, term)
        for t in ("THR", "MKD", "STWY", "OUBD"):                  # read against real remarks
            self.assertTrue(glossary.lookup(t)["prompt"], t)
        for t in ("DEPT", "OBS", "RLS", "NB", "MDT"):             # remarks use them two ways
            self.assertTrue(glossary.lookup(t)["verified"], t)
            self.assertFalse(glossary.lookup(t)["prompt"], t)

    def test_reviewed_terms_are_verified_jo_meanings(self):
        for t in glossary.REVIEWED:
            e = glossary.lookup(t)
            self.assertTrue(e and e["verified"] and e["source"].startswith("JO"), t)
            self.assertNotIn(t, glossary.CURATED)

    def test_meanings_from_other_fields_are_not_verified(self):
        for t in ("LL", "GOV", "LT", "PTS", "OB", "OG", "DP", "CC", "NC", "CTR", "RTG", "POC"):
            e = glossary.lookup(t)
            self.assertFalse(e["verified"], t)
            self.assertIn("doesn't fit", e["note"], t)
        for t in ("STRONG", "EVERY", "SPAN", "LONG"):             # words, not stereo routes or longitude
            self.assertTrue(glossary.lookup(t)["english"], t)

    def test_a_comma_inside_parentheses_is_one_meaning(self):
        self.assertEqual(glossary.lookup("DME")["expansion"],
                         "Distance Measuring Equipment (UHF standard, TACAN compatible)")
        self.assertTrue(glossary.lookup("HF")["verified"])
        self.assertIsNone(glossary.lookup("SEC").get("note"))     # picked in CURATED, so no "more than one" note

    def test_derived_forms(self):
        """JO 7340.2 1-2-3: HRS is HR + S. a derived form keeps its root's meaning."""
        hrs = glossary.lookup("HRS")
        self.assertEqual((hrs["derived_from"], hrs["expansion"], hrs["prompt"]), ("HR", "hour", False))
        self.assertEqual(glossary.lookup("MINS")["meanings"], ["minimum", "minute"])
        # English words the rule would misread: HOLD is not HOL + D (holiday)
        for t in ("HOLD", "WIND", "FIRST", "OWN"):
            self.assertTrue(glossary.lookup(t)["english"], t)
        self.assertIsNone(glossary.lookup("QZXW"))

    def test_only_reviewed_forms_are_derived(self):
        """the suffix rule also reads words, names and other codes as derived forms: DHS isn't
        decision heights (it's Homeland Security), SFAR isn't a single frequency approach. so only
        forms in DERIVED, each checked against real remarks, are derived; the rest are copied."""
        for t in ("DHS", "SFAR", "PRIST", "THRUST", "MINUS", "DSPLD", "SIMS", "USAR"):
            self.assertIsNone(glossary.lookup(t), t)
            self.assertEqual(remarks.problems(f"{t} RQRD.", f"{t} required."), [], t)
        self.assertTrue(remarks.problems("DHS RQRD.", "Decision heights required."))
        for t in sorted(glossary.DERIVED):
            e = glossary.lookup(t)
            self.assertTrue(e and e["verified"], t)
            self.assertTrue(e.get("derived_from") or t in glossary.load(), t)

    def test_a_remarks_own_spelling_takes_the_faa_forms_meaning(self):
        """APRCH and APPCH are how some remarks write the FAA's APCH, and EXTNDD its EXTDD (EXTD + D).
        TEMP isn't one: the FAA lists it as temperature, and remarks use it for that too"""
        for term, form, meaning in [("APRCH", "APCH", "approach"), ("APPCH", "APCH", "approach"),
                                    ("EXTNDD", "EXTDD", "extend")]:
            e = glossary.lookup(term)
            self.assertEqual((e["verified"], e["expansion"], e["spelling_of"], e["prompt"]),
                             (True, meaning, form, True), term)
            self.assertEqual(e["meanings"], glossary.lookup(form)["meanings"], term)
            self.assertTrue(e["source"].endswith(f"spelled {form}"), term)
            self.assertIn(f"the FAA writes {form}.", e["note"], term)
        self.assertFalse(glossary.lookup("TEMP")["verified"])
        self.assertIn("both ways", glossary.lookup("TEMP")["note"])
        for bad in ({"APCH": ("APRCH", "")},        # the FAA lists APCH itself
                    {"TEMPY": ("TEMP", "")},        # TEMP has no verified meaning to give
                    {"QZXWDD": ("QZXWD", "")}):     # not a reviewed derived form
            with mock.patch.dict(glossary.SPELLINGS, bad), self.assertRaises(ValueError, msg=bad):
                glossary.build()

    def test_sources_carry_provenance(self):
        cs, jo = SOURCES["chart_supplement"], SOURCES["jo_7340_2"]
        for s in (cs, jo):
            self.assertTrue(s["url"].startswith("https://"), s["url"])
            self.assertRegex(s["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(s["retrieved_at"], r"^\d{4}-\d\d-\d\dT")
        self.assertGreater(len(cs["rows"]), 700)
        self.assertGreater(len(jo["rows"]), 3000)
        self.assertTrue(jo["edition"].startswith("JO 7340.2"))

    def test_parse_jo(self):
        page = ("<table><tr><td>Contraction</td><td>Decode</td><td>Usage</td></tr>"
                "<tr><td>TKOF</td><td>take&#8211;off</td><td>ICAO</td></tr>"
                "<tr><td>AP­CH</td><td>approach</td><td>GEN</td></tr></table>")
        self.assertEqual(glossary.parse_jo(page), [["TKOF", "take-off", "ICAO"], ["APCH", "approach", "GEN"]])


# (remark, what the model wrote, why it's rejected), from remark_cache.json
GUESSES = [
    ("-3 FT DITCH 30 FT OUBD FM THLD.", "Ditch 3 feet deep, 30 feet outside threshold.", "OUBD is 'outbound'"),
    ("R/W 1900 FT MSL, F/W 2700 FT MSL.", "Runway elevation 1900 feet MSL, field elevation 2700 feet MSL.",
     "R/W is 'Rotary/Wing'"),
    ("TRANS ALERT: 1500Z-0700Z++ MON-SAT; 1600Z-0000Z++ SAT-SUN; CLSD FED HOL.",
     "Transition alert active 1500Z-0700Z Monday through Saturday; 1600Z-0000Z Saturday through Sunday; "
     "closed federal holidays.", "TRANS is 'transient'"),
    ("FATO LENGTH 70 FT, FATO WIDTH 70 FT, SAFETY AREA LENGTH 93 FT, SAFETY AREA WIDTH 93 FT.",
     "Landing area is 70 feet long by 70 feet wide with 93-foot-long by 93-foot-wide safety area.", "dropped FATO"),
    ("OT CALL (515) 291-5094 OR (515) 460-3892.", "Contact (515) 291-5094 or (515) 460-3892 for other information.",
     "OT is 'other times'"),
    ("30 FT TREES ABM RWY END 450 FT L OF CNTRLN.", "30 foot trees above runway end 450 feet left of centerline.",
     "ABM is 'abeam'"),
    ("APCH RWY 31 ALG E SIDE OF VALLEY; DEP RWY 13 ALG W SIDE OF VALLEY; WITH LNDG LGT ON; OPDT.",
     "Approach runway 31 along east side of valley; departure runway 13 along west side of valley; "
     "with landing lights on; operate day time only.", "OPDT is 'opposite direction traffic'"),
    ("NO INT DEP AUTH WO PPR FM AMGR.",
     "International departures are not authorized without prior permission from the airport manager.",
     "INT is 'intersection'"),
    ("CLSD 0500-1500Z. AVOID INT DEP.", "Closed 0500-1500Z, avoid instrument departures.", "INT is 'intersection'"),
    ("N GA APN MAX WINGSPAN 104 FT.", "Non-GA aircraft maximum wingspan 104 feet.", "APN is 'apron'"),
    ("ANG APN IS THE ONLY APN CPBL OF ACPTG C5 AT GWT.",
     "ANG airport is the only airport capable of accepting C5 at gross weight.", "APN is 'apron'"),
    ("GCO AVBL ON FREQ 121.725.", "Ground control outlet is available on frequency 121.725.",
     "GCO is 'Ground Communication Outlet'"),
    ("STD ACC RSRS APPLIED EXC 6000 FT BTN C130 ACFT.",
     "Standard aircraft arresting systems applied except 6000 feet between C130 aircraft.",
     "RSRS is 'Reduced Same Runway Separation'"),
    ("USE EXTREME CTN WHEN OPRG INTO AND OUT OF 5C1 FOR OTFC LDG SAN ANTONIO INTL (KSAT) AT 3000 FT MSL AND ABV.",
     "Use extreme caution when operating into and out of 5C1 for offshore landings at San Antonio International "
     "(KSAT) at 3000 feet mean sea level and above.", "OTFC is 'overflight traffic'"),
    ("RY 9 NR IS FADED.  RY 27 NR IS FADED.", "Runway 9 near end is faded and runway 27 near end is faded.",
     "NR is 'number'"),
    ("MILITARY: A-GEAR BAK-12B CABLE RAISED BY BAK-14M DEVICE O/R TO TWR.",
     "Military: arresting gear BAK-12B cable raised by BAK-14M device or tow to tower.", "O/R is 'On Request'"),
    ("HOSPITAL HELIPAD PCL FREQ 126.2.", "Hospital helipad common traffic advisory frequency is 126.2.",
     "PCL is 'pilot controlled lighting'"),
    ("NON-STD, PCL INSTALLED IN SOME TD AREAS.", "Non-standard, parachute canopy installed in some touchdown areas.",
     "PCL is 'pilot controlled lighting'"),
    ("24 HR HOP AT HOSPITAL 1.5 NM SSW OF ARPT; MNT CTAF.",
     "24-hour helicopter landing area at hospital 1.5 nautical miles south-southwest of airport; monitor CTAF.",
     "HOP is 'helicopter operations'"),
    ("PILOT SHELTER ACES: 1-2-0-0.", "Pilot shelter code is 1-2-0-0.", "ACES is 'access'"),
    ("PCR VALUE: 56/F/B/X/T.", "Runway surface condition report: 56 PCR value, friction measurement, poor condition, "
     "extremely slippery surface, tire.", "changed the pavement code F/B/X/T"),
    ("RSTD: TWY D LTD TO ACN 32 R/B/X/T.",
     "Taxiway D limited to aircraft classification number 32 rigid/bicycle/tandem/tandem.",
     "changed the pavement code R/B/X/T"),
    ("ST= 110.", "Seaplane base elevation is 110 feet.", "ST is 'saint'"),
    ("RED & WHITE L MKRS WITH REFLECTOR RAISED PANELS.", "Red and white lighted markings with reflector raised panels.",
     "L is 'Left'"),
    ("TFC PAT: ALL ARR AND DEP MAKE S TFC ONLY TO AVOID EXTRM RADIATION HAZ.",
     "All arrivals and departures make standard traffic pattern only to avoid extreme radiation hazard.",
     "S is 'South'"),
    ("FICONS NOT RGLRLY MNT.", "Runway edge lights not regularly monitored.", "FICONS is 'field condition'"),
    ("ALASKA RGNL HOSPITAL 2OK HELI ON ARPT; SEE SEPARATE LISTING FOR INFO.",
     "Alaska Regional Hospital has 2 OK-designated helicopter parking spots on the airport; see separate listing "
     "for more information.", "HELI is 'heliport'"),
    ("APCH RATIO 18:1 TO DTHR OVR +85 FT TREE, 1534 FT DIST, 0 FT B.",
     "Approach ratio 18 to 1 to displaced threshold over 85 foot tree, 1534 feet away, 0 feet both.",
     "B has no verified meaning"),
    # a right guess is still a guess: no FAA list defines NTSD
    ("RWY LGTS NTSD IN NR, TYPE, AND GLOBE COLOR; NO LGTS AT DSPLCD THLD.",
     "Runway lights are installed in number, type, and globe color not standard; there are no lights at the "
     "displaced threshold.", "NTSD is not in the verified glossary"),
    ("GRAIN ELEVATOR LEG", "Grain elevator landmark.", "dropped LEG"),
]

# the same remarks, said with the FAA's meanings or copied as written
RIGHT = [
    ("-3 FT DITCH 30 FT OUBD FM THLD.", "-3 foot ditch, 30 feet outbound from the threshold."),
    ("R/W 1900 FT MSL, F/W 2700 FT MSL.", "Rotary wing 1900 feet MSL, fixed wing 2700 feet MSL."),
    ("TRANS ALERT: 1500Z-0700Z++ MON-SAT; 1600Z-0000Z++ SAT-SUN; CLSD FED HOL.",
     "TRANS ALERT: 1500Z-0700Z++ Monday through Saturday; 1600Z-0000Z++ Saturday through Sunday; closed FED holidays."),
    ("FATO LENGTH 70 FT, FATO WIDTH 70 FT, SAFETY AREA LENGTH 93 FT, SAFETY AREA WIDTH 93 FT.",
     "FATO length 70 feet, FATO width 70 feet, safety area length 93 feet, safety area width 93 feet."),
    ("OT CALL (515) 291-5094 OR (515) 460-3892.", "Other times, call (515) 291-5094 or (515) 460-3892."),
    ("30 FT TREES ABM RWY END 450 FT L OF CNTRLN.", "30 foot trees abeam the runway end, 450 feet left of centerline."),
    ("APCH RWY 31 ALG E SIDE OF VALLEY; DEP RWY 13 ALG W SIDE OF VALLEY; WITH LNDG LGT ON; OPDT.",
     "Approach runway 31 along the east side of the valley; depart runway 13 along the west side of the valley; "
     "with landing lights on; opposite direction traffic."),
    ("NO INT DEP AUTH WO PPR FM AMGR.",
     "No intersection departures authorized without prior permission from the airport manager."),
    ("N GA APN MAX WINGSPAN 104 FT.", "North general aviation apron: maximum wingspan 104 feet."),
    ("ANG APN IS THE ONLY APN CPBL OF ACPTG C5 AT GWT.",
     "The ANG apron is the only apron capable of accepting C5 at gross weight."),
    ("GCO AVBL ON FREQ 121.725.", "Ground communication outlet available on frequency 121.725."),
    ("STD ACC RSRS APPLIED EXC 6000 FT BTN C130 ACFT.",
     "Standard Air Combat Command reduced same runway separation applied except 6000 feet between C130 aircraft."),
    ("RY 9 NR IS FADED.  RY 27 NR IS FADED.", "Runway 9 number is faded. Runway 27 number is faded."),
    ("MILITARY: A-GEAR BAK-12B CABLE RAISED BY BAK-14M DEVICE O/R TO TWR.",
     "Military: A-GEAR BAK-12B cable raised by BAK-14M device on request to the tower."),
    ("NON-STD, PCL INSTALLED IN SOME TD AREAS.",
     "Nonstandard pilot controlled lighting installed in some touchdown areas."),
    ("24 HR HOP AT HOSPITAL 1.5 NM SSW OF ARPT; MNT CTAF.",
     "24 hour helicopter operations at the hospital 1.5 nautical miles south-southwest of the airport; monitor CTAF."),
    ("PILOT SHELTER ACES: 1-2-0-0.", "Pilot shelter access: 1-2-0-0."),
    ("PCR VALUE: 56/F/B/X/T.", "PCR value: 56/F/B/X/T."),
    ("RSTD: TWY D LTD TO ACN 32 R/B/X/T.", "Restricted: taxiway D limited to ACN 32 R/B/X/T."),
    ("RED & WHITE L MKRS WITH REFLECTOR RAISED PANELS.", "Red and white L markers with reflector raised panels."),
    ("TFC PAT: ALL ARR AND DEP MAKE S TFC ONLY TO AVOID EXTRM RADIATION HAZ.",
     "Traffic pattern: all arrivals and departures make S traffic only to avoid extreme radiation hazard."),
    ("FICONS NOT RGLRLY MNT.", "Field conditions not regularly monitored."),
    ("APCH RATIO 18:1 TO DTHR OVR +85 FT TREE, 1534 FT DIST, 0 FT B.",
     "Approach ratio 18:1 to displaced threshold over +85 foot tree, 1534 feet away, 0 feet B."),
    ("RWY LGTS NTSD IN NR, TYPE, AND GLOBE COLOR; NO LGTS AT DSPLCD THLD.",
     "Runway lights NTSD in number, type, and globe color; no lights at the displaced threshold."),
    ("GRAIN ELEVATOR LEG", "Grain elevator leg."),
]


class TestNoGuess(unittest.TestCase):
    def test_real_guesses_are_rejected(self):
        self.assertGreaterEqual(len(GUESSES), 20)
        for raw, plain, why in GUESSES:
            found = remarks.problems(raw, plain)
            self.assertTrue(any(p.startswith(why) for p in found), f"{plain}\n  {found}")
            self.assertFalse(remarks.faithful(raw, plain), plain)

    def test_faa_meanings_and_copies_pass(self):
        for raw, plain in RIGHT:
            self.assertEqual(remarks.problems(raw, plain), [], plain)

    def test_meanings_the_faa_gives_more_than_one_of(self):
        self.assertEqual(remarks.problems("GA RAMP.", "General aviation ramp."), [])
        self.assertEqual(remarks.problems("PAPI GA 3.0.", "PAPI glide angle 3.0."), [])
        self.assertTrue(remarks.problems("GA RAMP.", "Gate ramp."))
        self.assertEqual(remarks.problems("15 MIN PRIOR.", "15 minutes prior."), [])
        self.assertEqual(remarks.problems("3,000 FT RMNG.", "3,000 feet remaining."), [])   # RMN + G
        self.assertTrue(remarks.problems("3,000 FT RMNG.", "3,000 feet remarks."))

    def test_an_unknown_term_is_copied_never_expanded(self):
        self.assertEqual(remarks.problems("46 FT UNMKD POLE.", "46 foot UNMKD pole."), [])
        self.assertEqual(remarks.problems("46 FT UNMKD POLE.", "46 foot unmarked pole."),
                         ["UNMKD is not in the verified glossary; it must stay as written"])

    def test_plain_words_are_kept(self):
        self.assertEqual(remarks.problems("PER FAR 91.", "Per FAR 91."), [])
        self.assertTrue(remarks.problems("PER FAR 91.", "Performance FAR 91."))
        self.assertEqual(remarks.problems("US CUSTOMS USER FEE ARPT.", "This is a U.S. Customs user fee airport."), [])
        self.assertTrue(remarks.problems("ACFT ONLY ABV 50 FT.", "Aircraft above 50 feet."))

    def test_negations_survive(self):
        dropped = ["dropped a negation: the FAA text has 1, the translation 0"]
        added = ["added a negation: the FAA text has 0, the translation 1"]
        for raw, plain in [("RWY 18 NOT LGTD.", "Runway 18 is not lighted."),
                           ("RWY 18 NOT LGTD.", "Runway 18 is unlighted."),
                           ("RWY NOT CLSD.", "Runway not closed."),
                           ("RWY 18 UNAVBL.", "Runway 18 is not available."),
                           ("NO FUEL AVBL.", "Fuel isn't available."),
                           ("NO TGL.", "Touch-and-go landings prohibited."),
                           ("PPR NLT 1700.", "PPR not later than 1700."), ("TKOF NA.", "Takeoff NA."),
                           ("CAUTION: RWY 30 PAPI U/S UFN.", "Caution: runway 30 PAPI out of service until further notice.")]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)
        self.assertEqual(remarks.problems("RWY 18 NOT LGTD.", "Runway 18 lighted."), dropped)
        self.assertEqual(remarks.problems("RWY NOT CLSD.", "Runway closed."), dropped)
        self.assertEqual(remarks.problems("NO FUEL AVBL.", "Fuel available."), dropped)
        self.assertIn(dropped[0], remarks.problems("RWY 18 UNAVBL.", "Runway 18 available."))
        self.assertEqual(remarks.problems("TWY A LGTD.", "Taxiway A is not lighted."), added)
        self.assertEqual(remarks.problems("RWY 18 PPR.", "Runway 18 no prior permission required."), added)
        # real ones: a clause with NOT left out, and an N (north) read as non-
        self.assertIn("dropped a negation: the FAA text has 3, the translation 2", remarks.problems(
            "MKD WITH 20 FT HIGH NRS; NO CNTRLN STRIPES. NRS NOT AT DSPLCD THR; NO DSPLCD THR MARKINGS.",
            "The runway is marked with 20 foot high numbered markers with no centerline stripes and no "
            "displaced threshold markings."))
        self.assertIn(added[0], remarks.problems("N GA APN MAX WINGSPAN 104 FT.",
                                                 "Non-GA aircraft maximum wingspan 104 feet."))
        # except NO before a case number
        self.assertEqual(remarks.problems("SEE AIRSPACE CASE NO. 2024-ASW-7785-NRA.",
                                          "See airspace case number 2024-ASW-7785-NRA."), [])

    def test_meanings_from_other_fields(self):
        self.assertTrue(remarks.problems("100 LL AVBL.", "100 landline available."))
        self.assertEqual(remarks.problems("100 LL AVBL.", "100LL available."), [])
        self.assertTrue(remarks.problems("GOV ACFT ONLY.", "Governor aircraft only."))
        self.assertEqual(remarks.problems("GOV ACFT ONLY.", "GOV aircraft only."), [])

    def test_a_contraction_is_not_a_plain_word(self):
        """a plain word may change its ending or be split, but a contraction isn't filled out."""
        self.assertEqual(remarks.problems("COMM RQRD.", "Commercial required."), ["dropped COMM", "added 'commercial'"])
        self.assertEqual(remarks.problems("APPROX 200 FT.", "Approach 200 feet."), ["dropped APPROX", "added 'approach'"])
        self.assertEqual(remarks.problems("APPROX 200 FT.", "APPROX 200 feet."), [])
        for raw, plain in [("20 FT DROPOFF 300 FT FM APCH END.", "There is a 20 foot drop-off 300 feet from the approach end."),
                           ("PHONE AVBL 24 HRS.", "Telephone available 24 hours."),
                           ("ALTITUDE CORRECTION REQUIRED.", "Altitude corrections are required."),
                           ("CONTROLLING OBSTN.", "Controlled obstruction.")]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)

    def test_compass_points(self):
        self.assertEqual(remarks.problems("115' LGTD/MKD RADIO TOWER 190' NNE.",
                                          "A 115-foot lighted and marked radio tower is 190 feet north-northeast."), [])
        self.assertTrue(remarks.problems("RADIO TOWER 190' NNE.", "Radio tower 190 feet northeast."))


# (remark, what the model wrote, why it's rejected), from remark_cache.json: translations the
# FAA-meaning check passed that still said something the remark doesn't
SAID_MORE = [
    ("BEARING STRENGTH RWY 12/30: S81 T110 ST175 SBTT590 TT333 TDT800 DDT857 TRT510.",
     "Runway 12/30 bearing strength: single wheel 81, tandem 110, single tandem 175, single bicycle tandem 590, "
     "tandem tandem 333, tandem dual tandem 800, dual dual tandem 857, triple tandem 510.", "changed T110"),
    ("100LL 24 HR SELF SERVE WITH CREDIT CARD",
     "100 octane low-lead fuel is available 24 hours via self-serve with credit card.", "changed 100LL"),
    ("SELF SVC FUEL (100LL) AVBL 24 HRS. CTC FUEL C434-294-7558.",
     "Self-service 100LL fuel available 24 hours; contact fuel at 434-294-7558.", "changed C434"),
    ("TWR OPR MON-FRI 1230-0400Z++ EXC HOL",
     "Tower operates Monday through Friday 1230-0400Z and beyond except holidays.", "dropped ++"),
    ("(TWO) +4 FT NATURAL GAS RISERS LCTD ON RY 17/35 WEST EDGE.",
     "Two natural gas risers 4 feet above ground located on runway 17/35 west edge.", "dropped the sign of +4"),
    ("+22 FT FENCE 62 FT R & 515 FT FM RWY END; PENETRATES APCH SFC.",
     "A 62-foot-tall fence is 515 feet from the runway end on the right and penetrates the approach surface, "
     "plus a 22-foot fence.", "numbers moved"),
    ("RWY 35, 21 INCH CONCRETE LIGHT BASES, 28 FT FROM W. RWY EDGE, 1300 FM RWY END.",
     "Runway 35 and 21 have 21 inch concrete light bases 28 feet from the west runway edge and 1300 feet from "
     "the runway end.", "numbers moved"),
    ("OTS UFN.", "Runway threshold lights are out of service until further notice.", "added 'runway'"),
    ("TWY L SOUTH OF TWY L3 NOT VSB TO ATCT.",
     "Taxiway L south of taxiway L3 not visible to air traffic control tower.", "added 'air'"),
    ("UNUSBL BYD 8 DEG L OF CNTRLN.", "Runway is unusable beyond 8 degrees left of centerline.", "added 'runway'"),
    ("INDEX B AVBL WITH 4 HR PPR - 541-297-4777.",
     "Index B aircraft are available with 4 hours prior permission required by calling 541-297-4777.",
     "added 'aircraft'"),
    ("ACR OPS MORE THAN 30 PAX SEATS 24 HR PPR - AMGR.",
     "Air carrier operations with more than 30 passenger seats require 24 hour prior permission required - "
     "contact airport manager.", "repeated 'required'"),
    ("GLDR OPNS NE OF ARPT MAY-SEP.",
     "Glider operations northeast of the airport are permitted May through September.", "added 'permitted'"),
    ("RY 17 -3 FT DITCH 30 FT OUTBOUND FM THLD.",
     "Runway 17 has a minus 3 foot ditch 30 feet outbound from the threshold.", "dropped the sign of -3"),
]

# the same remarks and a few more, said the way the FAA text does
SAID_RIGHT = [
    ("BEARING STRENGTH RWY 12/30: S81 T110 ST175 SBTT590 TT333 TDT800 DDT857 TRT510.",
     "Bearing strength runway 12/30: S81 T110 ST175 SBTT590 TT333 TDT800 DDT857 TRT510."),
    ("100LL 24 HR SELF SERVE WITH CREDIT CARD", "100LL 24 hour self serve with credit card."),
    ("SELF SVC FUEL (100LL) AVBL 24 HRS. CTC FUEL C434-294-7558.",
     "Self-service fuel (100LL) available 24 hours. Contact fuel C434-294-7558."),
    ("TWR OPR MON-FRI 1230-0400Z++ EXC HOL", "Tower operates Monday through Friday 1230-0400Z++ except holidays."),
    ("(TWO) +4 FT NATURAL GAS RISERS LCTD ON RY 17/35 WEST EDGE.",
     "(Two) +4 foot natural gas risers located on runway 17/35 west edge."),
    ("+22 FT FENCE 62 FT R & 515 FT FM RWY END; PENETRATES APCH SFC.",
     "+22 foot fence 62 feet right and 515 feet from runway end; penetrates approach surface."),
    ("RWY 35, 21 INCH CONCRETE LIGHT BASES, 28 FT FROM W. RWY EDGE, 1300 FM RWY END.",
     "Runway 35, 21 inch concrete light bases, 28 feet from west runway edge, 1300 from runway end."),
    ("OTS UFN.", "Out of service until further notice."),
    ("TWY L SOUTH OF TWY L3 NOT VSB TO ATCT.",
     "Taxiway L south of taxiway L3 not visible to airport traffic control tower."),
    ("UNUSBL BYD 8 DEG L OF CNTRLN.", "Unusable beyond 8 degrees left of centerline."),
    ("INDEX B AVBL WITH 4 HR PPR - 541-297-4777.",
     "Index B available with 4 hour prior permission required - 541-297-4777."),
    ("ACR OPS MORE THAN 30 PAX SEATS 24 HR PPR - AMGR.",
     "Air carrier operations more than 30 passenger seats 24 hour prior permission required - airport manager."),
    ("GLDR OPNS NE OF ARPT MAY-SEP.", "Glider operations northeast of airport May through September."),
    ("RY 17 -3 FT DITCH 30 FT OUTBOUND FM THLD.", "Runway 17 -3 foot ditch 30 feet outbound from threshold."),
    # the FAA wrote RQR and PPR, so the translation may say require and required
    ("ALL ENGINE RUNUPS RQR PPR FM DUTY OPS OFFICER AT 937-6914/6800; RUNUPS 20 MIN MAX.",
     "All engine run-ups require prior permission required from duty operations officer at 937-6914/6800; "
     "run-ups 20 minutes maximum."),
    ("24 HR HOP AT HOSPITAL 1.5 NM SSW OF ARPT; MNT CTAF.",
     "24 hour helicopter operations at hospital 1.5 nautical miles south-south-west of airport; monitor CTAF."),
]


class TestWhatTheRemarkSays(unittest.TestCase):
    """a translation says what the remark says and nothing more: codes copied, + - and ++ kept,
    numbers in the remark's order, and no word the remark or an FAA meaning doesn't account for."""

    def test_real_translations_that_said_more_are_rejected(self):
        for raw, plain, why in SAID_MORE:
            found = remarks.problems(raw, plain)
            self.assertTrue(any(p.startswith(why) for p in found), f"{plain}\n  {found}")

    def test_the_faa_text_said_plainly_passes(self):
        for raw, plain in SAID_RIGHT:
            self.assertEqual(remarks.problems(raw, plain), [], plain)

    def test_codes_stay_as_written(self):
        """PAM, from the hand-check: the D of DSN D523-4244 was dropped. C is the Chart Supplement's
        Commercial Circuit, so 'commercial' may stand for it; nothing gives D a meaning."""
        raw = ("RTNE CLASSIFIED/COMSEC STORAGE UNAVBL - AMGR D523-4244/4245; C850-283-4244/4245.")
        dropped = ("Routine classified/comsec storage unavailable - airport manager 523-4244/4245; "
                   "commercial 850-283-4244/4245.")
        self.assertIn("changed D523; a code of letters and digits stays as written", remarks.problems(raw, dropped))
        self.assertEqual(remarks.problems(raw, dropped.replace("manager 523", "manager D523")), [])
        self.assertEqual(remarks.problems("FUEL C850-283-4244.", "Fuel C850-283-4244."), [])
        self.assertTrue(remarks.problems("FUEL C850-283-4244.", "Fuel call 850-283-4244."))
        self.assertTrue(remarks.problems("FUEL C850-283-4244.", "Fuel 850-283-4244."))

    def test_codes_the_faa_gives_a_reading(self):
        """runway sides (JO 7340.2 L, R, C), Z after a time (the Chart Supplement legend: UTC, 'shown
        as Z time'; the AIM: Zulu), and a unit after a number"""
        for raw, plain in [("RWY 18R CLSD.", "Runway 18 right closed."),
                           ("RWY 18R CLSD.", "Runway 18R closed."),
                           ("ATCT 1200-0400Z.", "Airport traffic control tower 1200-0400 UTC."),
                           ("ATCT 1200-0400Z.", "Tower 1200-0400 Zulu."),
                           ("ATCT 1200-0400Z.", "Tower 1200-0400Z."),
                           ("99FT TREES 300 FT FM THR.", "99 feet trees 300 feet from threshold.")]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)
        self.assertTrue(remarks.problems("RWY 18R CLSD.", "Runway 18 left closed."))
        self.assertTrue(remarks.problems("ATCT 1200-0400Z.", "Tower 1200-0400 local."))

    def test_fod_is_debris(self):
        """the Chart Supplement's list says Foreign Object Damage; JO 7340.2 and AC 150/5300-13B say
        foreign object debris, and remarks mean the loose material ('FOD ON RWY EDGE'), so debris"""
        raw = "CAUTION: RWY 15C/33C AND RWY 15R/33L OVERRUNS HIGH POTENTIAL FOR FOD."
        for plain in ["Caution: runway 15C/33C and runway 15R/33L overruns high potential for foreign object debris.",
                      "Caution: runway 15C/33C and runway 15R/33L overruns high potential for FOD."]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)
        # what the site showed at SPS
        said = "Caution - runway 15C/33C and runway 15R/33L overruns have high potential for foreign object damage."
        self.assertIn("FOD is 'foreign object debris'", remarks.problems(raw, said)[0])
        self.assertIn("FOD = foreign object debris", remarks.prompt_for([raw]))
        self.assertEqual(remarks.problems("CRACKS THROUGHOUT RWY, FOD PRESENT.",
                                          "Cracks throughout runway, foreign object debris present."), [])

    SPS = ("CAUTION: MIL ARPT CONDUCTS HI PERFORMANCE JET TRNG IN A HI DENSITY ENVIRONMENT WITHIN 95 NM OF "
           "KSPS, 1200-0200Z++ MON-FRI TO FL390, AND WHEN TWR HR EXTN BY NOTAM, OCCASIONALLY SAT AND SUN.")

    def test_plus_plus_is_daylight_saving_time(self):
        """NASR writes the Chart Supplement's ‡ as ++, and the legend says that during daylight saving
        time "effective hours will be one hour earlier than shown". the model copies ++ and
        readable() says it; 'plus plus' is what the site showed at SPS before #41"""
        said = ("Caution: military airport conducts high performance jet training in a high density "
                "environment within 95 nautical miles of KSPS, 1200-0200Z plus plus Monday-Friday to FL390, "
                "and when tower hour extension by Notice to Airmen, occasionally Saturday and Sunday.")
        self.assertEqual(remarks.problems(self.SPS, said), ["dropped ++", "added 'plus'"])
        kept = said.replace("Z plus plus", "Z++")
        self.assertEqual(remarks.problems(self.SPS, kept), [])
        shown = remarks.readable(self.SPS, kept)
        self.assertIn("1200-0200Z (one hour earlier during daylight saving time) Monday-Friday", shown)
        self.assertEqual(remarks.problems(self.SPS, shown), [])
        # said anywhere else, or more times than the remark has ++, it's an added fact
        self.assertIn("added ++", remarks.problems("TWR 1200-0200Z MON-FRI.",
                                                   "Tower 1200-0200Z (one hour earlier during daylight saving time) Monday-Friday."))
        self.assertIn("added 'later'", remarks.problems(
            self.SPS, shown.replace("one hour earlier", "one hour later")))
        # only after a UTC time: a fuel grade and a time without Z keep their ++
        for raw, plain, want in [
                ("A++1300-0400Z++TUES-FRI WITH 24HR PN.", "A++1300-0400Z++TUES-FRI with 24 hour prior notice.",
                 "A++1300-0400Z (one hour earlier during daylight saving time) TUES-FRI with 24 hour prior notice."),
                ("ARFF NOT AVBL 0200-0700++.", "ARFF not available 0200-0700++.", "ARFF not available 0200-0700++."),
                ("ILS UNMON DLY 0700-1500Z++.", "ILS UNMON DLY 0700-1500Z++.", "ILS UNMON DLY 0700-1500Z++.")]:
            self.assertEqual(remarks.readable(raw, plain), want)
            self.assertEqual(remarks.problems(raw, want), [], want)

    def test_a_runway_side_is_written_the_faa_way(self):
        """translations wrote 33L/33C four ways ('33 Left', '33 left', '33 Center', '33C'). readable()
        writes the remark's own code after 'runway', and leaves a side the remark itself says in words"""
        for raw, plain, want in [
                ("DUE TO CLOSE PROXIMITY OF RWYS 33L & 33C USE VIGILANCE.",
                 "Due to close proximity of runways 33 Left and 33 Center use vigilance.",
                 "Due to close proximity of runways 33L and 33C use vigilance."),
                ("RSTD: RWY 15C/33C CLSD EXC XNG AT TWY G.",
                 "Restricted: runway 15 center/33 center closed except crossing at taxiway G.",
                 "Restricted: runway 15C/33C closed except crossing at taxiway G."),
                ("RWY 09R ROLLOUT RVR USED FOR RWY 09L MIDPOINT RVR.",            # PHL: the remark's 09R
                 "Runway 9 right rollout RVR is used for runway 9 left midpoint RVR.",
                 "Runway 09R rollout RVR is used for runway 09L midpoint RVR."),
                ("RWYS 13/31, 17R/35L UNLGTD 0300-1200Z.", "Runways 13/31 and 17 right/35 left are unlighted 0300-1200Z.",
                 "Runways 13/31 and 17R/35L are unlighted 0300-1200Z."),
                ("RWY 21L CALM WIND RWY.", "Runway 21l is the calm wind runway.", "Runway 21L is the calm wind runway."),
                # right traffic, and 20 feet left: sides in words, not runway ids
                ("RWY 6 RIGHT TFC & RWY 24 LEFT TFC.", "Runway 6 right traffic and runway 24 left traffic.",
                 "Runway 6 right traffic and runway 24 left traffic."),
                ("RWY 20L: POLE 20 L OF CNTRLN.", "Runway 20 left: pole 20 left of centerline.",
                 "Runway 20 left: pole 20 left of centerline."),
                ("RWY 18R RIGHT HAND TFC.", "Runway 18 right right-hand traffic.", "Runway 18R right-hand traffic.")]:
            self.assertEqual(remarks.readable(raw, plain), want)
            self.assertEqual(remarks.problems(raw, want), [], want)
        self.assertIn("'RWY 15C/33C' is 'runway 15C/33C', never '33 center'", remarks.PROMPT)

    def test_a_line_says_why_the_faa_words_show(self):
        """a remark in the FAA's words says why; so does a term a translation leaves as written when
        remarks use it more than one way. a plain translation, or FAA text with nothing to explain
        (a phone number), gets no line"""
        why = remarks.untranslated
        self.assertIsNone(why("RWY 18 CLSD.", "Runway 18 closed."))
        self.assertIsNone(why("615-347-4196", "615-347-4196"))
        self.assertIsNone(why(""))
        self.assertEqual(why("TIEDOWNS NA.", "Tiedowns NA."),
                         "NA is left as the FAA wrote it: it can mean not authorized or not available, and Amend "
                         "doesn't guess which.")
        self.assertEqual(why("RWY 18 CLSD."), "Kept in the FAA's words until it's translated.")
        wrong = remarks.problems("TIEDOWNS NA.", "Tiedowns not available.")
        self.assertEqual(why("TIEDOWNS NA.", None, wrong),
                         "Kept in the FAA's words: NA can mean not authorized or not available, and Amend doesn't "
                         "guess which.")
        self.assertEqual(why("14 FT HANGAR, 0 FT FROM RWY END, 66 FT RT.", "14 FT HANGAR, 0 FT FROM RWY END, 66 FT RT."),
                         "Kept in the FAA's words: Amend has no verified meaning for RT.")
        self.assertEqual(why("SOFT & RUTTED; IREG MRKD W CONES.", None,
                             remarks.problems("SOFT & RUTTED; IREG MRKD W CONES.", "Soft and rutted; irregular marked with cones.")[:3]),
                         "Kept in the FAA's words: the plain-English version didn't use the verified meaning for W "
                         "(west or white).")
        self.assertEqual(why("TIMBERED MOUTAIN SLOPE.", None, ["dropped MOUTAIN", "added 'mountain'"]),
                         "Kept in the FAA's words: the plain-English version didn't pass Amend's checks.")

    def test_a_meaning_may_change_form_to_read_as_english(self):
        """EXTN is 'extension': 'when tower hours are extended' says it, and the grammar words
        around it add nothing"""
        plain = ("Caution: military airport conducts high performance jet training in a high density "
                 "environment within 95 nautical miles of KSPS, 1200-0200Z++ Monday-Friday to FL390, and when "
                 "tower hours are extended by NOTAM, and occasionally on Saturday and Sunday.")
        self.assertEqual(remarks.problems(self.SPS, plain), [])
        self.assertEqual(remarks.problems(self.SPS, plain.replace("by NOTAM", "by a Notice to Airmen")), [])
        self.assertIn("WHEN TWR HR EXTN' is 'when tower hours are extended'", remarks.PROMPT)
        for noun, verb in [("extension", "extended"), ("extension", "extends"), ("permission", "permitted"),
                           ("division", "divided"), ("conversion", "converted"), ("revision", "revised")]:
            self.assertTrue(remarks._family(noun, verb) and remarks._family(verb, noun), (noun, verb))
        for noun, word in [("tension", "tend"), ("session", "set"), ("version", "vert"), ("extension", "extent")]:
            self.assertFalse(remarks._family(noun, word), (noun, word))

    def test_a_remarks_own_spelling_reads_as_the_faa_form(self):
        """what the site showed for this cycle's APRCH and EXTNDD remarks, and what it may show
        now. copied as written still passes; TEMP still has to stay as written"""
        for raw, was, now in [
                ("RWY 33 APRCH 34:1 TO AER", "Runway 33 APRCH 34:1 to approach end runway.",
                 "Runway 33 approach 34:1 to approach end of runway."),
                ("10 FT TREES EXTNDD CNTRLN.", "10 foot trees EXTNDD centerline.",
                 "10 foot trees on the extended centerline.")]:
            self.assertEqual(remarks.problems(raw, was), [], was)
            self.assertEqual(remarks.problems(raw, now), [], now)
            self.assertEqual(remarks.unverified(raw), [], raw)
        self.assertIn("EXTNDD is 'extend'", remarks.problems("10 FT TREES EXTNDD CNTRLN.",
                                                              "10 foot trees on external centerline.")[0])
        p = remarks.prompt_for(["RWY 33 APRCH 34:1 TO AER", "INDY APPCH - R, E 134.85", "HELIPAD TEMP CLSD."])
        for line in ("APRCH = approach", "APPCH = approach"):
            self.assertIn(f"\n{line}\n", p)
        self.assertIn("TEMP", re.search(r"copy them exactly as written: (.*)\n", p).group(1).split(", "))
        self.assertEqual(remarks.problems("HELIPAD TEMP CLSD.", "Helipad TEMP closed."), [])
        self.assertTrue(remarks.problems("HELIPAD TEMP CLSD.", "Helipad temporarily closed."))

    def test_na_and_n_a_stay_as_written(self):
        """the FAA lists NA as not authorized and N/A as not applicable, but remarks use both for not
        available too, and N/A for not authorized: live translations that read them the FAA's way
        said the wrong thing (2026-09-28). copied as written passes; any reading of them fails"""
        for term in ("NA", "N/A"):
            self.assertFalse(glossary.lookup(term)["verified"], term)
        for raw, wrong, kept in [
                ("RSTD: SOLO STU N/A.", "Restricted: Solo student not applicable.", "Restricted: solo students N/A."),
                ("TIEDOWNS NA.", "Tiedowns not authorized.", "Tiedowns NA."),
                ("WINTER MAINT NA.", "Winter maintenance is not authorized.", "Winter maintenance NA."),
                ("USE AT OWN RISK; TGL, SVCS, CELL RECEPTION NA.",
                 "Use at own risk; touch-and-go landings, services, cell reception not available.",
                 "Use at own risk; touch-and-go landings, services, cell reception NA.")]:
            self.assertTrue(remarks.problems(raw, wrong)[0].startswith(raw.split()[-1].strip(".") + " has no verified"),
                            wrong)
            self.assertEqual(remarks.problems(raw, kept), [], kept)
        p = remarks.prompt_for(["RSTD: SOLO STU N/A.", "TIEDOWNS NA."])
        self.assertEqual(sorted(re.search(r"copy them exactly as written: (.*)\n", p).group(1).split(", ")),
                         ["N/A", "NA"])
        # told only to copy them, the October build's model still wrote 'not available' for all 10
        self.assertIn("\nRemarks use N/A and NA more than one way, so copy them even where the meaning looks "
                      "plain: 'SNOW REMOVAL NA' is 'snow removal NA', never 'snow removal not available'.\n", p)
        self.assertIn("\nRemarks use NA more than one way, so copy it ", remarks.prompt_for(["TIEDOWNS NA."]))
        self.assertNotIn("more than one way", remarks.prompt_for(["TIEDOWNS AVBL."]))

    def test_per_after_hi_high_or_low_is_performance(self):
        """every HI PER, HIGH PER and LOW PER in NASR means performance, the FAA's PER (JO 7340.2); the
        translation of this one was rejected for saying so (2026-09-28). anywhere else PER is the word"""
        raw = ("CAUTION: MIL ARPT CONDUCTS HI PER JET TRNG IN A HI DENSITY ENVIRONMENT MON-FRI 1200-0200Z++ "
               "AND WHEN TWR HR EXTN BY NOTAM, OCNL SAT AND SUN.")
        plain = ("Caution: military airport conducts high performance jet training in a high density environment "
                 "Monday-Friday 1200-0200Z++ and when tower hours are extended by Notice to Airmen, occasionally "
                 "Saturday and Sunday.")
        self.assertEqual(remarks.problems(raw, plain), [])
        self.assertEqual(remarks.problems(raw, plain.replace("high performance", "high per")), [])
        self.assertEqual(glossary.lookup("PER")["after"]["source"], "JO 2-1-1 (ICAO)")
        for raw, plain in [("TPA LOW PER ACFT 1000 FT AGL, HIGH PER ACFT 1500 FT AGL",
                            "Traffic pattern altitude low performance aircraft 1000 feet AGL, high performance "
                            "aircraft 1500 feet AGL"),
                           ("LOW PER OR LOW PWRD ACFT MUST TKOF ON RWY 21.",
                            "Low performance or low powered aircraft must take off on runway 21.")]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)
        # no word before it that shows it: PER stays the word, even where it means performance
        for raw, plain in [("LDG FEE $15 PER NIGHT.", "Landing fee $15 performance night."),
                           ("CHECK ACFT PER DATA CALCULATIONS DUE TO RWY CONDS.",
                            "Check aircraft performance data calculations due to runway conditions.")]:
            self.assertEqual(remarks.problems(raw, plain), ["dropped PER", "added 'performance'"], plain)
        self.assertIn("\nPER right after HI, HIGH or LOW = performance\n", remarks.prompt_for(["CTN: HI PER MIL OPS R4809A."]))
        self.assertNotIn("PER right after", remarks.prompt_for(["LDG FEE $15 PER NIGHT."]))
        self.assertEqual(remarks.readable(raw, plain.replace("high performance", "high PER")), plain)
        bad = {"PER": (("HI",), "permission", "")}          # not an FAA meaning of PER
        with mock.patch.dict(glossary.AFTER, bad), self.assertRaises(ValueError):
            glossary.build()

    def test_trans_right_before_alert_is_transient(self):
        """all 26 TRANS ALERT remarks in NASR (2026-10-01) are the military transient alert service,
        the FAA's TRAN ALERT, and the site showed 'TRANS alert closing'. anywhere else TRANS is
        transmit, transition or transient, so it stays as written (okayed 2026-09-28)"""
        rule = glossary.lookup("TRANS")["before"]
        self.assertEqual((rule["words"], rule["meaning"], rule["spelling_of"], rule["source"]),
                         (["ALERT"], "transient", "TRAN", "CS, spelled TRAN"))
        self.assertFalse(glossary.lookup("TRANS")["verified"])
        raw = "RSTD: ALL TRAN ACFT MUST BE CHOCKED 30 MIN PRIOR TO TRANS ALERT CLOSING."
        plain = "Restricted: all transient aircraft must be chocked 30 minutes prior to transient alert closing."
        self.assertEqual(remarks.problems(raw, plain), [])
        copied = plain.replace("transient alert", "TRANS alert")
        self.assertEqual(remarks.problems(raw, copied), [])
        self.assertEqual(remarks.readable(raw, copied), plain)
        self.assertEqual(remarks.readable("TRANS ALERT: DE-ICING AVBL.", "TRANS alert: de-icing available."),
                         "Transient alert: de-icing available.")
        self.assertEqual(remarks.problems("TRANS ALERT SVC NOT AVBL.", "Transmit alert service not available."),
                         ["TRANS is 'transient' (CS, spelled TRAN, right before ALERT), not what the translation says"])
        # a remark that also uses TRANS elsewhere: only the TRANS right before ALERT reads transient
        raw = "ACFT SVC/TRANS ALERT WILL NOT SUPPORT LCL, ROUND ROBIN OR OUT AND BACK FOR TRANS ACFT."
        right = "Aircraft service/transient alert will not support local, round robin or out and back for TRANS aircraft."
        self.assertEqual(remarks.problems(raw, right), [])
        self.assertEqual(remarks.readable(raw, right.replace("transient alert", "TRANS alert")), right)
        self.assertTrue(remarks.problems(raw, right.replace("TRANS aircraft", "transient aircraft"))[0]
                        .startswith("TRANS has no verified meaning"))
        swapped = right.replace("transient alert", "TRANS alert").replace("TRANS aircraft", "transient aircraft")
        self.assertEqual(remarks.problems(raw, swapped),
                         ["TRANS is 'transient' (CS, spelled TRAN, right before ALERT), not what the translation says"])
        self.assertTrue(remarks.problems("TRANS ACFT RQR PPR.", "Transient aircraft require PPR.")[0]
                        .startswith("TRANS has no verified meaning"))
        # the model is told, and a remark that only has it there has nothing to copy
        self.assertEqual(remarks.unverified("TRANS ALERT SVC AVBL H24."), [])
        self.assertIn("TRANS", remarks.unverified(raw))
        p = remarks.prompt_for(["TRANS ALERT SVC AVBL H24.", raw])
        self.assertIn("\nTRANS right before ALERT = transient\n", p)
        self.assertIn("copy them exactly as written: TRANS (anywhere but right before ALERT)\n", p)
        self.assertNotIn("copy them exactly", remarks.prompt_for(["TRANS ALERT SVC AVBL H24."]))
        for bad in ({"TRANS": (("ALERT",), "TRNSX", "")},       # not an FAA contraction
                    {"TRAN": (("ALERT",), "TRAN", "")},         # a term that has its own meaning
                    {"PER": (("ALERT",), "PERF", "")}):          # an English word
            with self.subTest(bad=bad), mock.patch.dict(glossary.BEFORE, bad), self.assertRaises(ValueError):
                glossary.build()

    def test_signs_and_ranges(self):
        self.assertEqual(remarks.problems("10 FT TREES 125 -150 FT W OF RWY.",
                                          "10 foot trees 125 to 150 feet west of runway."), [])
        self.assertEqual(remarks.problems("10 FT TREES 125 -150 FT W OF RWY.",
                                          "10 foot trees 125-150 feet west of runway."), [])
        self.assertIn("dropped the sign of +10", remarks.problems("+10 FT BRUSH 30 FT DIST.",
                                                                  "Brush 10 feet high, 30 feet away."))

    def test_a_number_inside_a_contraction_may_be_said_in_words(self):
        """H24 is 'continuous operation' (CS). 3 remarks the October build asked were rejected for
        'lost number 24' when the model said that. the number may go only when the meaning is said
        in words: 'fuel 24 hours' can't be H24 and the 24 HR after it at once"""
        for plain in ["Self service fuel continuous operation.", "Self service fuel around the clock.",
                      "Self service fuel 24 hours.", "Self service fuel H24."]:
            self.assertEqual(remarks.problems("SELF SVC FUEL H24.", plain), [], plain)
        self.assertIn("lost number 24", remarks.problems("SELF SVC FUEL H24.", "Self service fuel."))
        raw = "FUEL H24; 24 HR PPR."
        self.assertEqual(remarks.problems(raw, "Fuel continuous operation; 24 hour prior permission required."), [])
        self.assertEqual(remarks.problems(raw, "Fuel 24 hours; prior permission required."),
                         ["numbers moved, dropped or repeated: 24"])
        self.assertEqual(remarks.problems("RWY 18 H24 EXC 2200-0600.",
                                          "Runway 18 continuous operation except 0600-2200."),
                         ["numbers moved, dropped or repeated: 18 600 2200"])
        self.assertIn("lost number 24", remarks.problems("CTC H24@X.COM.", "Contact @x.com."))

    def test_words_a_translation_may_write_differently(self):
        for raw, plain in [("TURN EAST AFT TKOF.", "Turn east after takeoff."),       # TKOF: take-off
                           ("TURN EAST AFT TKOF.", "Turn east after take-off."),
                           ("MAIL: P.O. BOX 240.", "Mail: P.O. Box 240."),
                           ("DITCH 75 FT FM CNTRLN RUNS LEN OF NORTHSIDE OF RWY.",
                            "Ditch 75 feet from centerline runs length of north side of runway."),
                           ("ADAMDCCC@YAHOO.COM EAGLEROCKTOM@GMAIL.COM", "ADAMDCCC@YAHOO.COM or EAGLEROCKTOM@GMAIL.COM"),
                           ("GATE ACES: 1-2-3-4.", "Gate access code: 1-2-3-4."),
                           ("NO TOUCH & GO'S.", "No touch and go's."),
                           ("RWY 18 NOT LGTD.", "Runway 18 isn't lighted.")]:
            self.assertEqual(remarks.problems(raw, plain), [], plain)


class TestPrompt(unittest.TestCase):
    def test_the_model_is_told_faa_meanings_and_what_to_copy(self):
        p = remarks.prompt_for(["-3 FT DITCH 30 FT OUBD FM THLD.", "TO AND LDG NA SS-SR.",
                                "46 FT UNMKD POLE 240 FT L OF CNTRLN.", "PER FAR 91.", "ALT PHONE 555-0100.",
                                "TRANS ALERT AVBL."])
        for line in ("OUBD = outbound", "THLD = threshold", "FM = from", "SS-SR = sunset to sunrise",
                     "CNTRLN = centerline"):
            self.assertIn(f"\n{line}\n", p)
        copy = re.search(r"copy them exactly as written: (.*)\n", p).group(1).split(", ")
        self.assertEqual(sorted(copy), ["NA", "UNMKD"])
        self.assertIn("\nTRANS right before ALERT = transient\n", p)
        # plain words, single letters and terms remarks use two ways get no meaning
        for t in ("TO", "L", "ALT", "PER", "NA"):
            self.assertNotIn(f"\n{t} = ", p)
        # nor do JO 7340.2-only meanings that don't fit remarks, or that remarks use two ways
        p = remarks.prompt_for(["100 LL AVBL.", "GOV ACFT ONLY.", "CALL FIRE DEPT.", "RWY 18 THR DSPLCD."])
        for t in ("LL", "GOV", "DEPT"):
            self.assertNotIn(f"\n{t} = ", p)
        self.assertIn("\nTHR = threshold\n", p)


class TestTranslateStats(unittest.TestCase):
    """translate_remarks records what the model cost and what the check threw out."""

    def setUp(self):
        self._cache = remarks.CACHE_FILE
        remarks.CACHE_FILE = os.path.join(tempfile.mkdtemp(), "cache.json")
        self.prompts = []

    def tearDown(self):
        remarks.CACHE_FILE = self._cache

    def run_with(self, texts, answer):
        def urlopen(req, timeout=None):
            prompt = json.loads(req.data)["messages"][0]["content"]
            self.prompts.append(prompt)
            batch = json.loads(prompt.split("\nRemarks:\n", 1)[1])
            body = {"content": [{"type": "text", "text": json.dumps(answer(batch))}],
                    "usage": {"input_tokens": 1000, "output_tokens": 200}}
            return io.BytesIO(json.dumps(body).encode())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
                mock.patch.object(remarks.urllib.request, "urlopen", side_effect=urlopen):
            return remarks.translate_remarks(texts, use_llm=True)

    def test_usage_cost_and_rejections(self):
        answers = {
            "RWY 18 NOT LGTD.": "Runway 18 is not lighted.",
            "-3 FT DITCH 30 FT OUBD FM THLD.": "Ditch 3 feet deep, 30 feet outside threshold.",
            "46 FT UNMKD POLE.": "46 foot UNMKD pole.",
            "PCR VALUE: 56/F/B/X/T.": {"value": 56},          # not a string
        }
        out = self.run_with(list(answers), lambda batch: [answers[r] for r in batch])
        self.assertEqual(out, {"RWY 18 NOT LGTD.": "Runway 18 is not lighted.",
                               "46 FT UNMKD POLE.": "46 foot UNMKD pole."})
        s = remarks.STATS
        self.assertEqual((s["llm_calls"], s["input_tokens"], s["output_tokens"]), (1, 1000, 200))
        self.assertAlmostEqual(s["est_cost_usd"], (1000 * 1.00 + 200 * 5.00) / 1e6)
        self.assertEqual((s["sent"], s["translated"], s["rejected"], s["bad_batches"]), (4, 2, 2, 0))
        self.assertEqual(s["unknown_terms"], {"UNMKD": 1})
        self.assertIn("\nOUBD = outbound\n", self.prompts[0])

    def test_wrong_shape_is_skipped(self):
        out = self.run_with(["RWY 18 NOT LGTD.", "46 FT UNMKD POLE."], lambda batch: ["Runway 18 is not lighted."])
        self.assertEqual(out, {})
        self.assertEqual((remarks.STATS["bad_batches"], remarks.STATS["sent"], remarks.STATS["llm_calls"]), (1, 0, 1))

    def fail_with(self, texts, error):
        calls = []
        def urlopen(req, timeout=None):
            calls.append(req)
            raise error()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key"}), \
                mock.patch.object(remarks.urllib.request, "urlopen", side_effect=urlopen), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            cache = remarks.translate_remarks(texts, use_llm=True)
        return cache, calls, out.getvalue()

    def test_no_credit_falls_back_to_faa_text_and_says_so(self):
        """a failed call never stops the build: the FAA text shows, the run log has the count and
        the API's own message, and the Actions run shows a warning"""
        body = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                           "message": "Your credit balance is too low to access the Anthropic API."}}).encode()
        error = lambda: remarks.urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 400,
                                                        "Bad Request", {}, io.BytesIO(body))
        cache, calls, out = self.fail_with(["RWY 18 NOT LGTD.", "46 FT UNMKD POLE."], error)
        self.assertEqual(cache, {})
        s = remarks.STATS
        self.assertEqual((s["llm_errors"], s["llm_calls"], s["unanswered"], s["llm_stopped"]), (1, 0, 2, False))
        self.assertEqual(s["llm_error"], "HTTP 400: Your credit balance is too low to access the Anthropic API.")
        self.assertIn("::warning title=remark translation::1 of 1 calls failed", out)
        self.assertNotIn("sk-ant-test-key", out + json.dumps(s))

    def test_three_failures_in_a_row_stop_asking(self):
        """an outage can't hold a build past its time limit: after 3 failed calls the rest stay FAA text"""
        texts = [f"RWY {n} NOT LGTD." for n in range(10, 30)]
        with mock.patch.object(remarks, "BATCH", 2):
            cache, calls, out = self.fail_with(texts, lambda: TimeoutError("timed out"))
        s = remarks.STATS
        self.assertEqual((len(calls), s["llm_errors"], s["llm_stopped"], s["unanswered"]), (3, 3, True, 20))
        self.assertEqual(s["llm_error"], "TimeoutError: timed out")

    def test_an_unreadable_answer_is_a_bad_batch(self):
        def urlopen(req, timeout=None):
            body = {"content": [{"type": "text", "text": '["Runway 18 is not li'}], "usage": {}}
            return io.BytesIO(json.dumps(body).encode())
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
                mock.patch.object(remarks.urllib.request, "urlopen", side_effect=urlopen):
            self.assertEqual(remarks.translate_remarks(["RWY 18 NOT LGTD."], use_llm=True), {})
        s = remarks.STATS
        self.assertEqual((s["bad_batches"], s["llm_errors"], s["unanswered"]), (1, 0, 1))

    def test_a_rejected_answer_is_asked_again_only_after_an_engine_change(self):
        answers = {"RWY 18 NOT LGTD.": "Runway 18 is not lighted.",
                   "OTS UFN.": "Runway threshold lights are out of service until further notice."}
        self.run_with(list(answers), lambda batch: [answers[r] for r in batch])
        with open(os.path.join(os.path.dirname(remarks.CACHE_FILE), remarks.REJECTS_FILE)) as f:
            self.assertEqual(json.load(f), {"engine": remarks.ENGINE_VERSION,
                                            "remarks": {"OTS UFN.": ["added 'runway'", "added 'threshold'",
                                                                     "added 'lights'"]}})
        self.prompts.clear()
        self.run_with(list(answers), lambda batch: [answers[r] for r in batch])
        self.assertEqual((self.prompts, remarks.STATS["rejects_skipped"]), ([], 1))
        with mock.patch.object(remarks, "ENGINE_VERSION", "9.9.9"):
            self.run_with(list(answers), lambda batch: ["Out of service until further notice." for r in batch])
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.run_with([], None), {"RWY 18 NOT LGTD.": "Runway 18 is not lighted.",
                                                   "OTS UFN.": "Out of service until further notice."})

    def test_cached_guesses_are_retired(self):
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump({"-3 FT DITCH 30 FT OUBD FM THLD.": "Ditch 3 feet deep, 30 feet outside threshold.",
                       "RWY 18 NOT LGTD.": "Runway 18 is not lighted."}, f)
        out = remarks.translate_remarks(["-3 FT DITCH 30 FT OUBD FM THLD.", "RWY 18 NOT LGTD."], use_llm=False)
        self.assertEqual(out, {"RWY 18 NOT LGTD.": "Runway 18 is not lighted."})
        self.assertEqual(remarks.STATS["cache_retired"], 1)

    def test_the_faa_text_sent_back_is_not_kept(self):
        """an answer that is the FAA text itself passes the checks, since it guesses at nothing, but for a
        remark with contractions to expand nothing was translated: 93 cached answers were that on
        2026-09-28 ('15 FT TREES 57 FT FM THR, 248 FT R.'). a PCR VALUE line or an email stays as written"""
        trees, pcr, email = "15 FT TREES 57 FT FM THR, 248 FT R.", "PCR VALUE: 690/F/B/X/T", "WMRICHARDSON@COPPER.NET"
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump({t: t for t in (trees, pcr, email)}, f)
        texts = [trees, pcr, email, "RWY 18 NOT LGTD."]
        out = self.run_with(texts, lambda batch: list(batch))           # every answer is the FAA text
        self.assertEqual(out, {pcr: pcr, email: email})
        s = remarks.STATS
        self.assertEqual((s["cache_retired"], s["sent"], s["sent_back"], s["rejected"], s["translated"]),
                         (1, 2, 2, 0, 0))
        self.assertEqual(remarks.rejected(), {trees: [remarks.SENT_BACK], "RWY 18 NOT LGTD.": [remarks.SENT_BACK]})
        self.assertEqual(remarks.untranslated(trees, None, [remarks.SENT_BACK]),
                         "Kept in the FAA's words until it's translated.")
        self.assertEqual(remarks.untranslated("14 FT HANGAR, 0 FT FROM RWY END, 66 FT RT.", None, [remarks.SENT_BACK]),
                         "Kept in the FAA's words: Amend has no verified meaning for RT.")
        self.prompts.clear()                                            # asked again only after an engine change
        self.run_with(texts, lambda batch: list(batch))
        self.assertEqual((self.prompts, remarks.STATS["rejects_skipped"]), ([], 2))
        with mock.patch.object(remarks, "ENGINE_VERSION", "9.9.9"):
            out = self.run_with(texts, lambda batch: ["15 feet trees 57 feet from threshold, 248 feet R." if t == trees
                                                      else "Runway 18 not lighted." for t in batch])
        self.assertEqual(out[trees], "15 feet trees 57 feet from threshold, 248 feet R.")

    def test_plus_plus_is_said_in_every_translation(self):
        """cached and new translations alike, and the cache keeps passing its own check"""
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump({"ILS UNMON DLY 0700-1500Z++.": "ILS is unmonitored daily from 0700-1500Z++."}, f)
        answers = {"TWR 1200-0200Z++ MON-FRI.": "Tower 1200-0200Z++ Monday-Friday."}
        out = self.run_with(list(answers) + ["ILS UNMON DLY 0700-1500Z++."], lambda batch: [answers[r] for r in batch])
        self.assertEqual(out, {
            "ILS UNMON DLY 0700-1500Z++.": "ILS is unmonitored daily from 0700-1500Z (one hour earlier during daylight saving time).",
            "TWR 1200-0200Z++ MON-FRI.": "Tower 1200-0200Z (one hour earlier during daylight saving time) Monday-Friday."})
        self.assertEqual(self.run_with([], None), out)
        self.assertEqual(remarks.STATS["cache_retired"], 0)

    def test_the_review_queue_leaves_out_names(self):
        remarks.translate_remarks(["46 FT UNMKD POLE.", "APCH/DEP SVC PRVDD BY OAKLAND ARTCC (ZOA) ON 132.2/350.3.",
                                   "ARPT PHYS ADS: 2382 AIRPORT RD, JEFFERSON, OH 44047-9491."],
                                  use_llm=False, ids={"ZOA"}, states={"OH"})
        self.assertEqual(remarks.STATS["unknown_terms"], {"UNMKD": 1})


class TestReviewQueue(unittest.TestCase):
    """the status page's list of contractions with no verified meaning is the glossary's to-do list,
    so it holds only real gaps: not ids NASR lists, addresses, names or plain words. the cases are
    cut from real NASR remarks (2026-10-01)."""
    IDS, STATES = {"ZOA", "KSPS"}, {"AK", "CO", "IL", "OH", "TX"}

    def gone(self, raw):
        return set(remarks.unverified(raw)) - set(remarks.review_terms(raw, self.IDS, self.STATES))

    def test_ids_and_addresses_leave_the_list(self):
        for raw, gone in [
            ("APCH/DEP SVC PRVDD BY OAKLAND ARTCC (ZOA) ON FREQS 127.8/353.5 (UKIAH RCAG).", {"ZOA"}),
            ("WITHIN 95 NM OF KSPS, 1200-0200Z++ MON-FRI TO FL390", {"KSPS"}),
            ("ARPT PHYS ADS: 38550 JET CENTER DR, WILLOUGHBY, OH 44094-8174.", {"DR", "OH"}),
            ("CONTACT: MARK NEGELY 5409 N KNOXVILLE AVE PEORIA, IL 61614309-672-5622", {"AVE", "IL"}),
            ("1508 INDUS BLVD.", {"BLVD"}),
            ("PHYS ARPT LOCATION: N1405 LINDSEY RD, LODI, WI 53555", {"RD"}),
            ("AIRPORT LOCATION: 19100 FM 1155 E, WASHINGTON, TX", {"TX"}),
            ("AMGR P.O. BOX 1500 ANTON LARSON ROAD KODIAK AK 99615.", {"AK"}),
            ("STUDENT TRNG ACT INVOF COLORADO SPRINGS & PUEBLO, CO.", {"CO"}),
        ]:
            self.assertEqual(self.gone(raw), gone, raw)

    def test_the_same_letters_as_contractions_stay(self):
        for raw in ["PUB RD 209 FT FM RWY END, 14 FT ABV RWY & 14 FT FM LT OF CTLN.",     # road
                    "+15 FT COUNTY RD & +15 ARPT ACCESS RD.",
                    "17:1 OBSTN CLNC SLOPE OVR 18 F RD, 310 FT DSTC.",
                    "CHAIRMAN OF THOMAS CO ARPT AUTH CELL 308-645-7303.",             # county
                    # three-letter ids stay: BAK is also an arresting gear ("BAK 15 (175 FT OVRN)")
                    "COLUMBUS MUNI, BAK, CLASS D AIRSPACE 3 NM SE EFF 1130-0300Z++, 118.6 OT."]:
            self.assertEqual(self.gone(raw), set(), raw)
        # an id the glossary knows as a contraction stays on the list
        self.assertEqual(remarks.review_terms("HELIPAD TEMP CLSD.", {"TEMP"}), ["TEMP"])

    def test_a_translation_still_copies_them(self):
        raw = "ARPT PHYS ADS: 38550 JET CENTER DR, WILLOUGHBY, OH 44094-8174."
        self.assertEqual(remarks.problems(raw, "Airport physical address: 38550 Jet Center DR, Willoughby, OH "
                                               "44094-8174."), [])
        found = remarks.problems(raw, "Airport physical address: 38550 Jet Center Drive, Willoughby, Ohio 44094-8174.")
        self.assertTrue(any(p.startswith("DR ") for p in found) and any(p.startswith("OH ") for p in found), found)

    def test_plain_words_and_names_arent_contractions(self):
        cases = [("COURTESY CAR AVBL.", "CAR", "Courtesy car available.", "Courtesy vehicle available."),
                 ("GRAIN BIN", "BIN", "Grain bin", "Grain silo"),
                 ("MIX OF WHITE & ORANGE 5-GALLON BUCKETS.", "MIX", "Mix of white and orange 5-gallon buckets.",
                  "Blend of white and orange 5-gallon buckets."),
                 ("GLIDER TOW AVBL.", "TOW", "Glider tow available.", "Glider launch available."),
                 ("CTN: SMALL ARMS RANGE.", "ARMS", "Caution: small arms range.", "Caution: small weapons range."),
                 ("PPR FOR ARMY RAMP.", "ARMY", "Prior permission required for Army ramp.",
                  "Prior permission required for military ramp."),
                 ("CO-OWNERS: DON TATE, LEE COWIE AND LELAND COWIE.", "DON",
                  "Co-owners: Don Tate, Lee Cowie and Leland Cowie.", "Co-owners: Tate, Lee Cowie and Leland Cowie."),
                 ("FOR CD CTC SAN ANTONIO APCH AT 210-805-5516.", "SAN",
                  "For clearance delivery contact San Antonio approach at 210-805-5516.",
                  "For clearance delivery contact sanitary Antonio approach at 210-805-5516."),
                 ("USE MID-FLD RUN-UP PAD FOR ALL RUN-UPS.", "UPS", "Use the midfield run-up pad for all run-ups.",
                  "Use the midfield run-up pad for all engine checks."),
                 ("HEL INSTRUCTION BY PRE-ARRANGEMENT ONLY.", "PRE", "Helicopter instruction by pre-arrangement only.",
                  "Helicopter instruction by arrangement only.")]
        for raw, word, right, wrong in cases:
            self.assertTrue(glossary.lookup(word)["english"], word)
            self.assertNotIn(word, remarks.unverified(raw))
            self.assertEqual(remarks.problems(raw, right), [], right)
            self.assertIn(f"dropped {word}", remarks.problems(raw, wrong), wrong)
        # the model isn't told a meaning for them, or to copy them as codes
        p = remarks.prompt_for([c[0] for c in cases])
        copy = re.search(r"copy them exactly as written: (.*)\n", p)
        for word in (c[1] for c in cases):
            self.assertNotIn(f"\n{word} = ", p)
            self.assertNotIn(word, copy.group(1).split(", ") if copy else [])


class TestScrubHistory(unittest.TestCase):
    """past cycles get the same check as new ones; the FAA text replaces what fails, ids never move."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.hist = os.path.join(self.root, "history")
        os.mkdir(self.hist)
        self.raw, guess = GUESSES[2][:2]      # "TRANS ALERT: ..." read as "Transition alert ..."
        ok_raw, ok = RIGHT[2]                 # the same remark with TRANS kept as written
        ok = remarks.readable(ok_raw, ok)     # ... said the way translations are said now: transient alert
        self.entries = [
            {"cycle": "2026-09-03", "id": "aaa", "source": "APT_RMK", "summary": f"remark updated: {guess}",
             "original": self.raw},
            {"cycle": "2026-09-03", "id": "bbb", "source": "APT_RMK", "summary": f"new remark: {ok}",
             "original": ok_raw},
            {"cycle": "2026-08-06", "id": "ccc", "source": "ATC_RMK", "summary": f"remark removed: {self.raw}",
             "original": self.raw},
            {"cycle": "2026-08-06", "id": "ddd", "source": "APT_RWY", "summary": "runway 5/23 length: 5000 -> 5200 ft"},
        ]
        self.write("XYZ.json", {"airport": "XYZ", "entries": self.entries})
        self.write("ABC.json", {"airport": "ABC", "entries": self.entries[1:]})
        with open(os.path.join(self.hist, "cycles.json"), "w") as f:
            json.dump({"cycles": ["2026-09-03"], "skipped": []}, f, indent=1)

    def write(self, name, h):
        output.dump(h, os.path.join(self.hist, name))

    def read(self, name):
        with open(os.path.join(self.hist, name), encoding="utf-8") as f:
            return f.read()

    def test_rejected_translations_go_back_to_faa_text(self):
        before = {n: self.read(n) for n in ("ABC.json", "cycles.json")}
        self.assertEqual(remarks.scrub_history(self.hist), (1, 0, 1))
        h = json.loads(self.read("XYZ.json"))
        self.assertEqual(h["entries"][0], {**self.entries[0], "summary": f"remark updated: {self.raw}",
                                           "untranslated": "Kept in the FAA's words: Amend has no verified "
                                                           "meaning for FED; the plain-English version didn't "
                                                           "use the verified meaning for TRANS (transient)."})
        self.assertEqual(h["entries"][1:], self.entries[1:])
        self.assertEqual(self.read("XYZ.json"), json.dumps(h, **output.MIN))   # as history.append writes it
        self.assertEqual({n: self.read(n) for n in before}, before)              # nothing else rewritten

    def test_a_second_run_changes_nothing(self):
        remarks.scrub_history(self.hist)
        once = self.read("XYZ.json")
        self.assertEqual(remarks.scrub_history(self.hist), (0, 0, 0))
        self.assertEqual(self.read("XYZ.json"), once)

    def test_only_remarks_are_judged(self):
        self.write("XYZ.json", {"airport": "XYZ", "entries": [{**self.entries[0], "source": "APT_BASE"}]})
        self.assertEqual(remarks.scrub_history(self.hist), (0, 0, 0))

    def test_translations_that_pass_are_said_as_now(self):
        """a runway side and ++ read the same in history as in the latest cycle, and a term left as
        written gets its line"""
        entries = [
            {"cycle": "2024-10-03", "id": "p1", "source": "APT_RMK", "original": "RWY 21L CALM WIND RWY.",
             "summary": "new remark: Runway 21 Left is the calm wind runway."},
            {"cycle": "2024-10-03", "id": "p2", "source": "APT_RMK", "original": "CUSTOMS 1400-0130Z++ MON-FRI.",
             "summary": "new remark: Customs 1400-0130Z++ Monday-Friday."},
            {"cycle": "2024-10-03", "id": "p3", "source": "APT_RMK", "original": "HELIPAD TEMP CLSD.",
             "summary": "new remark: Helipad TEMP closed."}]
        self.write("XYZ.json", {"airport": "XYZ", "entries": entries})
        self.assertEqual(remarks.scrub_history(self.hist), (0, 2, 1))
        h = json.loads(self.read("XYZ.json"))["entries"]
        self.assertEqual([e["summary"] for e in h], [
            "new remark: Runway 21L is the calm wind runway.",
            "new remark: Customs 1400-0130Z (one hour earlier during daylight saving time) Monday-Friday.",
            "new remark: Helipad TEMP closed."])
        self.assertEqual([e.get("untranslated") for e in h], [
            None, None, "TEMP is left as the FAA wrote it: it can mean temporary or temperature, and Amend "
                        "doesn't guess which."])
        self.assertEqual([e["id"] for e in h], ["p1", "p2", "p3"])
        self.assertEqual(remarks.scrub_history(self.hist), (0, 0, 0))

    def test_the_command(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with mock.patch("sys.stdout", new=io.StringIO()) as out:
                cli.main(["scrub-history"])
        finally:
            os.chdir(cwd)
        self.assertIn("1 translations in history/ fail the checks", out.getvalue())
        self.assertEqual(json.loads(self.read("XYZ.json"))["entries"][0]["summary"], f"remark updated: {self.raw}")

    def test_history_holds_no_rejected_translation(self):
        """the check and history/ change together: after making the checks stricter or changing
        readable(), run python -m amend scrub-history and commit history/ with the change."""
        bad = []
        for path in glob.glob(os.path.join(os.path.dirname(__file__), "..", "history", "*.json")):
            with open(path, encoding="utf-8") as f:
                h = json.load(f)
            for e in h.get("entries", []):
                raw, (head, sep, plain) = e.get("original"), e["summary"].partition(": ")
                if raw and sep and e.get("source") in remarks.REMARK_FILES + ("FRQ",) \
                        and not (remarks.faithful(raw, plain) and remarks.readable(raw, plain) == plain):
                    bad.append(f"{h.get('airport')} {e['cycle']}: {e['summary']}")
        self.assertEqual(bad[:5], [], f"{len(bad)} in all; run python -m amend scrub-history")


if __name__ == "__main__":
    unittest.main()
