"""
The verified glossary and the no-guess rule: a remark translation may expand a contraction only
to a meaning the FAA gives for it. the cases are real translations from remark_cache.json.
run:  python -m unittest tests.test_glossary -v
"""
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
            rows = faa_rows(cur.get("root", term))
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
        """a JO 7340.2-only meaning is accepted but not suggested until it's in CURATED: plenty are
        from other fields. the Chart Supplement's own list is what remarks are written with."""
        for term, e in glossary.load().items():
            if e["prompt"]:
                self.assertTrue(e["source"].startswith("CS") or term in glossary.CURATED, term)
        self.assertFalse(glossary.lookup("PRVD")["prompt"])        # provide: JO 7340.2 only
        self.assertTrue(glossary.lookup("OUBD")["prompt"])         # read against real remarks

    def test_meanings_from_other_fields_are_not_verified(self):
        for t in ("LL", "GOV", "LT", "PTS", "OB", "DP", "CC", "NC", "CTR", "RTG", "POC"):
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
     "closed federal holidays.", "TRANS has no verified meaning"),
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
    ("-3 FT DITCH 30 FT OUBD FM THLD.", "Ditch 3 feet deep, 30 feet outbound from the threshold."),
    ("R/W 1900 FT MSL, F/W 2700 FT MSL.", "Rotary wing 1900 feet MSL, fixed wing 2700 feet MSL."),
    ("TRANS ALERT: 1500Z-0700Z++ MON-SAT; 1600Z-0000Z++ SAT-SUN; CLSD FED HOL.",
     "TRANS ALERT: 1500Z-0700Z Monday through Saturday; 1600Z-0000Z Saturday through Sunday; closed FED holidays."),
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
     "Approach ratio 18:1 to displaced threshold over 85 foot tree, 1534 feet away, 0 feet B."),
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
                           ("TKOF NA.", "Takeoffs not authorized."), ("TKOF NA.", "Takeoff NA."),
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
        self.assertEqual(remarks.problems("COMM RQRD.", "Commercial required."), ["dropped COMM"])
        self.assertEqual(remarks.problems("APPROX 200 FT.", "Approach 200 feet."), ["dropped APPROX"])
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


class TestPrompt(unittest.TestCase):
    def test_the_model_is_told_faa_meanings_and_what_to_copy(self):
        p = remarks.prompt_for(["-3 FT DITCH 30 FT OUBD FM THLD.", "TO AND LDG NA SS-SR.",
                                "46 FT UNMKD POLE 240 FT L OF CNTRLN.", "PER FAR 91.", "ALT PHONE 555-0100.",
                                "TRANS ALERT AVBL."])
        for line in ("OUBD = outbound", "THLD = threshold", "FM = from", "SS-SR = sunset to sunrise",
                     "CNTRLN = centerline"):
            self.assertIn(f"\n{line}\n", p)
        copy = re.search(r"copy them exactly as written: (.*)\n", p).group(1).split(", ")
        self.assertEqual(sorted(copy), ["TRANS", "UNMKD"])
        # plain words, single letters and terms remarks use two ways get no meaning
        for t in ("TO", "L", "ALT", "PER", "NA"):
            self.assertNotIn(f"\n{t} = ", p)
        # nor do JO 7340.2-only meanings nobody has read against remarks, or ones that don't fit
        p = remarks.prompt_for(["100 LL AVBL.", "GOV ACFT ONLY.", "FUEL PRVD BY FBO."])
        for t in ("LL", "GOV", "PRVD"):
            self.assertNotIn(f"\n{t} = ", p)


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

    def test_cached_guesses_are_retired(self):
        with open(remarks.CACHE_FILE, "w") as f:
            json.dump({"-3 FT DITCH 30 FT OUBD FM THLD.": "Ditch 3 feet deep, 30 feet outside threshold.",
                       "RWY 18 NOT LGTD.": "Runway 18 is not lighted."}, f)
        out = remarks.translate_remarks(["-3 FT DITCH 30 FT OUBD FM THLD.", "RWY 18 NOT LGTD."], use_llm=False)
        self.assertEqual(out, {"RWY 18 NOT LGTD.": "Runway 18 is not lighted."})
        self.assertEqual(remarks.STATS["cache_retired"], 1)


class TestScrubHistory(unittest.TestCase):
    """past cycles get the same check as new ones; the FAA text replaces what fails, ids never move."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.hist = os.path.join(self.root, "history")
        os.mkdir(self.hist)
        self.raw, guess = GUESSES[2][:2]      # "TRANS ALERT: ..." read as "Transition alert ..."
        ok_raw, ok = RIGHT[2]                 # the same remark with TRANS kept as written
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
        self.assertEqual(remarks.scrub_history(self.hist), (1, 1))
        h = json.loads(self.read("XYZ.json"))
        self.assertEqual(h["entries"][0], {**self.entries[0], "summary": f"remark updated: {self.raw}"})
        self.assertEqual(h["entries"][1:], self.entries[1:])
        self.assertEqual(self.read("XYZ.json"), json.dumps(h, **output.MIN))   # as history.append writes it
        self.assertEqual({n: self.read(n) for n in before}, before)              # nothing else rewritten

    def test_a_second_run_changes_nothing(self):
        remarks.scrub_history(self.hist)
        once = self.read("XYZ.json")
        self.assertEqual(remarks.scrub_history(self.hist), (0, 0))
        self.assertEqual(self.read("XYZ.json"), once)

    def test_only_remarks_are_judged(self):
        self.write("XYZ.json", {"airport": "XYZ", "entries": [{**self.entries[0], "source": "APT_BASE"}]})
        self.assertEqual(remarks.scrub_history(self.hist), (0, 0))

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


if __name__ == "__main__":
    unittest.main()
