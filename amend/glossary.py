"""The verified glossary: which FAA contractions a remark translation may expand, and to what.

Every meaning here is copied from one of two FAA lists, extracted word for word into
faa_abbreviations.json:
  - "CS": Chart Supplement U.S., General Information, Abbreviations. The remarks are printed
    in the Chart Supplement, so where its list and JO 7340.2 disagree, its meaning wins.
  - "JO": FAA Order JO 7340.2 (Contractions), 2-1-1 Decode, the FAA-wide list.
A term neither list defines is unverified: remarks.problems() rejects any translation that
doesn't copy it exactly as written, and the FAA text is shown instead. The exception is a remark's
own spelling of an FAA contraction (SPELLINGS: APRCH for the FAA's APCH), which takes the FAA
form's meaning once every remark that uses it has been read.

glossary.json holds one entry per term:
  expansion  the meaning shown to the model and to readers. always FAA text, never reworded
  meanings   every FAA meaning a translation may use for the term (expansion is the first)
  verified   true when the meaning traces to CS or JO. false entries must be copied as written
  source     where expansion comes from, e.g. "CS" or "JO 2-1-1 (ICAO)"
  faa        every meaning the FAA lists for the term, for reviewers
  prompt     true when the model is told the meaning. single letters aren't: "TWY W" is a name
  note       why a meaning was picked, or why a term stays unverified
  accept     optional regexes a translation may match instead of a meaning's own words
  parts      for a pair like SS-SR: the terms it joins, which have to come out in that order
  english    an everyday English word in remarks (END, MUST), never expanded as a contraction
  spelling_of for a remark's own spelling (APRCH): the FAA contraction whose meaning it takes
  after      a meaning the term takes only right after certain words (AFTER: HI PER is performance)
  before     one it takes only right before certain words, from the FAA contraction it spells there
             (BEFORE: TRANS ALERT is transient alert, the FAA's TRAN)
  remarks_use for a term copied as written: the meanings remarks give it, for the reader's line

refresh the FAA lists and rebuild (needs faa.gov access and pypdf):
    python -m amend.glossary --refresh
rebuild glossary.json from faa_abbreviations.json and CURATED below:
    python -m amend.glossary
"""
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "faa_abbreviations.json")
GLOSSARY_FILE = os.path.join(HERE, "glossary.json")

JO_URL = "https://www.faa.gov/air_traffic/publications/atpubs/cnt_html/chap2_section_1.html"
JO_INDEX = "https://www.faa.gov/air_traffic/publications/atpubs/cnt_html/"
CS_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dafd/"

# JO 7340.2 usage codes. NWS, METAR and TAF meanings are weather-report codes that clash with
# how remarks read ("UP" = unknown precipitation, "CST" = coast, "UNSBL" = unseasonable), so they're
# listed, not used. the few plain weather words remarks do use (BTWN, MTN) are in CURATED
JO_USED = {"GEN", "ICAO", "ATC", "MIL"}

# JO 7340.2 1-2-3: "the contractions in this order may normally be used for any derivative of the
# root word ... variations may be shown by adding the following letters to the contraction of
# the root word". LGTS = LGT + S. a derived form must still render as its root's meaning
SUFFIXES = ("CLY", "BL", "LY", "RY", "NC", "DR", "NG", "RN", "ST", "NS", "TY", "MT", "US", "WD",
            "L", "D", "R", "V", "G", "S", "N")

# the Chart Supplement prints these as one line with two meanings run together. split on the
# FAA's own words, only while the printed text is exactly this
CS_RUN_TOGETHER = {
    "ACC": ("Air Combat Command Area Control Center", ["Air Combat Command", "Area Control Center"]),
    "ATD": ("Actual Time of Departure Along Track Distance", ["Actual Time of Departure", "Along Track Distance"]),
}

# words remarks use as plain English (or as names), never as contractions. a translation keeps
# the word; nothing is expanded, and the model isn't asked to copy them as codes
ENGLISH = {
    # the FAA lists these as contractions, but remarks mean the word: "RWY END", "BASE OPS",
    # "NEW CONCRETE", "PER FAR 91", "WA STATE", "SAN ANTONIO APCH" (END = stop-end of an RVR,
    # PER = performance, SAN = sanitary)
    "BASE", "CAN", "DO", "END", "FEW", "GRASS", "NEW", "PER", "SAN", "SELF", "SET", "SPOT", "STATE", "TOP",
    "UP", "VIA",
    # the same for function words: A is Amber, AS Air Station, IS island to the FAA. remarks.py
    # never reads these as contractions. IN (inch: '6 IN') and NO (number: 'CASE NO. 2024-...') stay
    "A", "AS", "BY", "IF", "IS",
    # not FAA terms, but the suffix rule would read them as one: HOLD = HOL + D (holiday),
    # WIND = WIN + D (winter), FIRST = FIR + ST (Flight Information Region)
    "ALAN", "APPLY", "BASED", "BURN", "CORN", "DOES", "ENDS", "FALL", "FIRST", "GAS", "HALL", "HARD",
    "HOLD", "LAND", "LOAD", "LOS", "PITS", "PLAN", "PRESS", "RAIN", "RAINS", "RAPID", "SAND", "SETS",
    "SIGN", "SIGNS", "SPOTS", "TODD", "TWIN", "TWINS", "WIND", "WING",
    # short words that look like codes: "DUE TO", "ALL RWYS", "OIL AVBL"
    "AIR", "ALL", "ANY", "BAY", "BIG", "BOX", "BUT", "CUT", "DAY", "DRY", "DUE", "E-MAIL", "FEE", "FLY",
    "GET", "GO", "HOT", "ICE", "JET", "KEY", "LEG", "LOT", "LOW", "MAY", "NOW", "OFF", "OIL", "OLD",
    "ONE", "ONLY", "OUR", "OUT", "OWN", "PAD", "PAY", "RED", "ROW", "RUN", "SEA", "SEE", "SIX", "SKI",
    "TEN", "TIE", "TOO", "TWO", "US", "USE", "WAY", "WET", "YOU",
    # read against every remark in NASR (2026-10-01), each one the word or a name, never a
    # contraction: "COURTESY CAR", "GRAIN BIN", "MIX OF WHITE & ORANGE", "BANNER TOW", "SMALL ARMS
    # RANGE", "US ARMY" (no vowel after the A, so they looked contracted), "DON TATE", "LEE COUNTY",
    # and halves of hyphenated words: "RUN-UPS", "PRE-COORD"
    "ARMS", "ARMY", "BIN", "CAR", "DON", "LEE", "MIX", "PRE", "TOW", "UPS",
    # words and names JO 7340.2 happens to list, or the suffix rule would build: "STRONG DOWNDRAFTS"
    # isn't stereo routes, "WING SPAN" isn't a stored program, "EVERY MON" isn't evening
    "AMAR", "ARC", "BALL", "CACTUS", "DISCS", "ELBA", "EVEN", "EVERY", "FILL", "HANG", "HEAD", "HEADS",
    "HELD", "LONG", "NESS", "PAUL", "PLANS", "RODD", "RUTS", "SPAN", "SPANS", "STRONG", "TAIL", "TIP",
    "VAN",
}

# an FAA meaning an ENGLISH word takes right after certain words, where every NASR remark with it
# there means that: {term: (the words before it, the FAA meaning, what was read)}. anywhere else
# it stays the word. build() refuses a meaning that isn't FAA text for the term
AFTER = {
    "PER": (("HI", "HIGH", "LOW"), "performance",
            "all 16 of NASR's HI PER, HIGH PER and LOW PER remarks on 2026-10-01 mean performance ('HI PER "
            "JET TRNG', 'HIGH PER TAKEOFF RQRD', 'LOW PER OR LOW PWRD ACFT'). most of its other 241 are the "
            "word per ('$15 PER NIGHT', 'PER AC 150/5390-2') or an id in a list; about 10 mean performance with "
            "nothing before them that shows it ('CHECK ACFT PER DATA CALCULATIONS'), and a translation can "
            "only keep those as the word"),
}

# a term that spells an FAA contraction right before certain words, where every NASR remark with it
# there means that (2026-10-01 cycle, all remark fields): {term: (the words after it, the FAA
# contraction, what was read)}. it takes that contraction's verified meaning there, and stays as
# written anywhere else. a translation may still copy it as written
BEFORE = {
    "TRANS": (("ALERT",), "TRAN",
              "all 26 of NASR's TRANS ALERT remarks on 2026-10-01 (23 texts) mean the military transient alert "
              "service ('TRANS ALERT SVC AVBL H24', 'PRIOR TO TRANS ALERT CLOSING'); 158 others write it the "
              "FAA's way, TRAN ALERT"),
}


# ---------------------------------------------------------------- curated choices
# where the FAA lists more than one meaning, where its only meaning doesn't fit remarks, or where
# remarks say an FAA meaning in other words. read against real remarks in remark_cache.json.
#   expansion  one FAA meaning, or a list of them when remarks use more than one. build() refuses
#              anything that isn't FAA text for the term (or for its root, when "root" is given)
#   None       the term stays unverified and must be copied as written
#   accept     regexes for how translations correctly say the meaning in other words
#   remarks_use  for a term copied as written: the meanings remarks give it, read against every
#              NASR remark with it. a reader is told the term can mean any of them (remarks.untranslated)
CURATED = {
    # meanings picked from several
    "FM": {"expansion": "from",
           "note": "remarks use FM for 'from' (JO 7340.2, ICAO). the Chart Supplement's fan marker "
                   "and frequency modulation don't occur in remarks"},
    "FT": {"expansion": ["foot", "feet"]},
    "FOD": {"expansion": "foreign object debris",
            "note": "'FOD ON RWY EDGE', 'LOOSE AGGREGATE & FOD': remarks mean the loose material itself. JO "
                    "7340.2 and AC 150/5300-13B say foreign object debris; the Chart Supplement's Foreign "
                    "Object Damage is what it does to an engine (AC 150/5340-1M uses each that way)"},
    "CD": {"expansion": "clearance delivery", "accept": [r"\bclearances?\b"],
           "note": "'FOR CD CTC ... APCH'. candela and civil defense don't occur in remarks"},
    "CL": {"expansion": "centre line", "note": "'250 FT L OF CL'. remarks don't use CL for class"},
    "AC": {"expansion": "Advisory Circular", "note": "'FAA AC 150/5390-2'. not assistant chief"},
    "ACC": {"expansion": "Air Combat Command",
            "note": "'ACC COMD POST', 'ACC FAMILY DAYS' at Air Force bases. not area control center"},
    "ADS": {"expansion": "address", "note": "'EMAIL ADS:'. ADS-B is its own term"},
    "ASP": {"expansion": "airspace", "note": "'CLASS B ASP'. not airport system plan"},
    "AP": {"expansion": ["airport", "Area Planning"], "note": "both occur: 'AP OPS', 'FLIP AP/1'"},
    "CAP": {"expansion": ["capacity", "Civil Air Patrol"], "note": "both occur: 'GARBAGE CAP NA', 'CAP HANGAR'"},
    "CAT": {"expansion": "category", "note": "'CAT A ACFT', 'NFPA CAT'. not clear air turbulence"},
    "CRC": {"expansion": "circle", "note": "'44 FT DIAM CRC'. not cyclic redundancy check"},
    "DIST": {"expansion": "distance", "accept": [r"\baway\b"],
             "note": "'1534 FT DIST' reads as '1534 feet away'. not district"},
    "GA": {"expansion": ["general aviation", "glide angle"],
           "note": "both occur: 'GA RAMP', 'PAPI GA 3.0'. the model is told both"},
    "HOP": {"expansion": "helicopter operations", "note": "'HOP WI CTZL'. not handoff point"},
    "L": {"expansion": "Left", "prompt": False,
          "note": "'240 FT L' is left of the runway. JO 7340.2 (ICAO); in a PCR code it stays as written"},
    "LMT": {"expansion": "limit", "note": "'SPD LMT'. not Local Mean Time"},
    "LRG": {"expansion": "large", "note": "'LRG BIRDS'. not long range"},
    "LTR": {"expansion": ["later", "letter"], "note": "both occur: 'NO LTR THAN', 'LTR OF AGREEMENT'"},
    "MED": {"expansion": ["medium", "medical"],
            "note": "both occur: 'MED INTST', 'MED AMBULANCE'"},
    "MIN": {"expansion": ["minimum", "minute"], "note": "both occur: 'MIN 24 HR PN', '15 MIN PRIOR'"},
    "MOD": {"expansion": ["modify", "moderate"], "note": "both occur: 'WX MOD', 'MOD-SVR CROSSWIND'"},
    "MON": {"expansion": "Monday", "note": "'MON-FRI'. not Minimum Operational Network or above mountains"},
    "OBST": {"expansion": ["obstruction", "obstacle"]},
    "PTN": {"expansion": "portion", "note": "'CNTR PTN'. not procedure turn"},
    "PUB": {"expansion": ["public", "publication"], "note": "both occur: 'PUB USE', 'FLIGHT INFO PUB'"},
    "R": {"expansion": "right (runway identification)", "prompt": False,
          "note": "'172 FT R' is right of the runway. in a PCR code ('R/B/X/T') it stays as written"},
    "RES": {"expansion": ["reserve", "resident"], "note": "both occur: 'CALL TO RES', 'MGR RES ON ARPT'"},
    "SEC": {"expansion": ["second", "section"]},
    "SLP": {"expansion": "slope", "note": "'APCH SLP 20:1'. not speed limiting point"},
    "SPL": {"expansion": "special", "note": "'SPL EVENTS', 'SPL VFR'. not supplementary flight plan"},
    "SN": {"expansion": "snow", "note": "'SN REMOVAL'. not strategic or systems navigation"},
    "UNMON": {"expansion": "unmonitored", "note": "'FLD CONDS UNMON 2400-0400'"},
    "WTR": {"expansion": "Water", "note": "'WTR TWR', 'OVR WTR'. JO 7340.2 (NWS); well to right doesn't occur in remarks"},
    "W": {"expansion": ["West", "White"], "prompt": False,
          "note": "both occur: '30 FT W', 'W CONES'. the Chart Supplement also lists Warning Area and Watts"},
    # plain words JO 7340.2 lists only under NWS
    **{t: {"expansion": m, "note": "JO 7340.2 lists it only under NWS; the meaning is the plain word"}
       for t, m in [("BNDRY", "boundary"), ("BTWN", "between"), ("EXTRM", "extreme"),
                    ("MONTR", "monitor"), ("MRNG", "morning"), ("MTN", "mountain"),
                    ("NMBR", "number"), ("PRSNT", "present"), ("RNFL", "rainfall"),
                    ("SNW", "snow"), ("WINT", "winter"), ("WND", "wind")]},
    # derived forms whose root is left unverified or has more than one meaning
    "ARNGMT": {"root": "ARNG", "expansion": "arrange", "note": "ARNG + MT (JO 7340.2 1-2-3): arrangement"},
    "OPNS": {"root": "OPN", "expansion": "operation",
             "note": "OPN + S (JO 7340.2 1-2-3). OPN is open or operation; OPNS only reads as operations"},
    # the FAA meaning doesn't fit how remarks use the term: copied as written
    "EMS": {"expansion": None, "note": "not an FAA contraction: EM + S would read as 'emission', but "
                                       "remarks use EMS for emergency medical services"},
    "ARNG": {"expansion": None, "note": "the FAA lists 'arrange'; military remarks use ARNG for Army National Guard"},
    "TRANS": {"expansion": None,
              "note": "the FAA lists 'transmit', and remarks use TRANS for transmit ('TRANS INTENTIONS'), "
                      "transition ('TRANS SFC') and transient ('TRANS ACFT'). right before ALERT it's the "
                      "FAA's TRAN (BEFORE)"},
    "DECR": {"expansion": None, "note": "not an FAA contraction (JO 7340.2 has DCR); DEC + R would read as December"},
    "FRM": {"expansion": None, "note": "the FAA lists 'form'; remarks use FRM for from"},
    "MTUS": {"expansion": None, "note": "MTU + S would read as 'metric units'; remarks use MTUS for mountains"},
    "REQD": {"expansion": None, "note": "REQ + D would read as 'requested'; remarks use REQD for required"},
    "TEMP": {"expansion": None, "remarks_use": ["temporary", "temperature"],
             "note": "the FAA lists 'temperature' (its temporary is TMPRY), and remarks use TEMP both ways: "
                     "'HELIPAD TEMP CLSD' is temporary, 'WIND, TEMP, & ALTM INFO' and 'AWOS TEMP UNRELBL' "
                     "are temperature (10 and 8 of NASR's 18 on 2026-10-01). a check can't tell which one "
                     "a translation picked"},
    "N/A": {"expansion": None, "remarks_use": ["not authorized", "not available", "not applicable"],
            "note": "the FAA lists 'not applicable', and remarks use N/A three ways: not authorized "
                    "('AUTOPILOT COUPLED APCH N/A BLW 1570 FT', 'RSTD: SOLO STU N/A', 'TOUCH AND GO'S N/A'), "
                    "not available ('SNOW REMOVAL N/A', 'TWY P & S EDGE LGT N/A') and not applicable "
                    "('LNDG FEE (N/A FOR MIL AIRCRAFT)'): 11, 6 and 2 of NASR's 19 on 2026-10-01. a check "
                    "can't tell which one a translation picked"},
    "NA": {"expansion": None, "remarks_use": ["not authorized", "not available"],
           "note": "the FAA lists 'not authorized', and most remarks mean that ('TGL NA', 'AUTO CPD APCH NA "
                   "BLW 1200 FT MSL'), but dozens of NASR's 576 on 2026-10-01 mean not available ('SNOW "
                   "REMOVAL NA', 'AFT HR FUEL NA', 'ARFF NA', 'FONE NA'), and 'TGL, SVCS, CELL RECEPTION NA' "
                   "means both at once. a check can't tell which one a translation picked"},
    "TO": {"expansion": None, "note": "the FAA lists 'travel order'; remarks use TO for 'to', and for takeoff "
                                      "('TO AND LDG NA')"},
    "UNSBL": {"expansion": None, "note": "JO 7340.2 lists 'unseasonable' (NWS); remarks use it for unusable"},
    "WKND": {"expansion": None, "note": "the FAA lists 'weaken'; remarks use WKND for weekend (WKEND)"},
    "XS": {"expansion": None, "note": "JO 7340.2 lists XS only as atmospherics (ICAO); remarks use it "
                                      "for 'crosses', which no FAA list spells out"},
    # JO 7340.2 meanings from other fields, where remarks mean something else by the same letters
    **{t: {"expansion": None, "note": f"remarks use it for {use}; JO 7340.2's {faa!r} doesn't fit"}
       for t, (use, faa) in {
           "A/C": ("aircraft ('A/C MAINT')", "approach control"),
           "AFM": ("airfield manager ('CTC AFM')", "affirmative"),
           "AIRFLD": ("airfield", "air refueling"),
           "AR": ("Army Reserve ('ARNG, AR AND A')", "Atlantic Route"),
           "BSC": ("basic ('NSTD SMALL BSC MARKINGS')", "bird sweep completed"),
           "CA": ("California", "clear above (PIREP only)"),
           "CC": ("credit card ('100LL AVBL 24 HRS WITH CC')", "carbon copy"),
           "CONF": ("confirm and conference ('CONF RWY CONDS', 'CONF ROOM')", "confidential"),
           "CONSDR": ("consider", "continuous (CONS + DR)"),
           "CP": ("command post ('126TH CP')", "circular polarization"),
           "CTR": ("center ('MED CTR', 'RWY 29 CTR')", "control zone"),
           "DC": ("the DC-10", "direct current"),
           "DE": ("de- ('DE-ICE', 'DE-RIGGED')", "From (before a call sign)"),
           "DEF": ("defined ('DEF BY FAR PART 77')", "defense"),
           "DP": ("departure procedure, as on the d-TPP's DP charts", "dew point temperature"),
           "DPTS": ("departures ('PPR OR DPTS')", "depth (DPT + S)"),
           "DST": ("distance and daylight saving time", "distort"),
           "DZ": ("drop zone", "drizzle"),
           "EAS": ("Eareckson Air Station", "equivalent airspeed"),
           "ECA": ("explosive cargo area", "enter control area"),
           "ER": ("taxiway names ('TWYS EL AND ER')", "here"),
           "ET": ("Eastern Time ('M-F 8-4 ET')", "electronic technician"),
           "GOV": ("government ('MIL/GOV', 'NON DOD GOV')", "Governor"),
           "INS": ("inches ('CRACKS OVER 2 INS WIDE')", "inertial navigation system"),
           "KC": ("the KC-135 tanker", "kilocycles"),
           "LL": ("fuel ('100 LL & JET A AVBL')", "landline"),
           "LT": ("left ('440 FT LT OF CTLN')", "turn left after take-off"),
           "MAND": ("mandatory ('LDG PERMIT MAND')", "manual (MAN + D)"),
           "MOC": ("a maintenance office ('AIRFIELD MGMT, MOC & POL')", "minimum obstacle clearance"),
           "NC": ("North Carolina", "no change"),
           "OB": ("'+5 FT FENCE OB OF CNTRLN', not on board", "on board"),
           "OG": ("the operations group ('OG/CC APVL RQR')", "on ground"),
           "OWS": ("Operational Weather Squadron ('CTC 15 OWS')", "one way (OW + S)"),
           "PIT": ("hot pit refueling ('HOT PIT AVBL')", "pilot instructor training"),
           "POC": ("point of contact ('BASE OPS POC')", "proceed or proceeding on course"),
           "POCS": ("points of contact", "proceed or proceeding on course (POC + S)"),
           "PR": ("prior ('PR TO XNG RWY 10 THLD')", "photo reconnaissance"),
           "PRES": ("president", "pressure"),
           "PROVD": ("provide ('MUST PROVD 30 MIN PPR')", "provisional (PROV + D)"),
           "PTS": ("points ('BORROW PTS', 'GND CK PTS')", "polar track structure"),
           "RE": ("re- ('RE-ENTER')", "regard"),
           "RPA": ("remotely piloted aircraft", "request present altitude"),
           "RQ": ("required ('24-HR PPR RQ')", "Indication of a request"),
           "RTG": ("rotating ('ACTVT RTG BCN')", "radiotelegraph"),
           "SP": ("names and specs ('TXL SP', 'SP PRESAIR')", "standard holding pattern"),
           "SUB": ("substandard ('RWY MARKINGS ARE SUB')", "substitute"),
           "VA": ("Virginia and taxiway names ('TWY VA')", "victor airways"),
           "WV": ("West Virginia", "wind at altitude (PIREP only)"),
       }.items()},
    # JO 7340.2-only meanings read against real remarks: the model is told these
    "OUBD": {"note": "'DITCH 30 FT OUBD FM THLD', 'INBD & OUBD TO/FM KFFO'"},
    "OPDT": {"note": "'WITH LNDG LGT ON; OPDT'"},
    # the FAA meaning holds, but remarks also use the term another way: the model isn't told the
    # FAA meaning (so it won't force it on 'ALT PHONE'), and a translation still has to use it
    **{t: {"prompt": False, "note": n} for t, n in [
        ("ALT", "remarks also use ALT for alternate ('ALT PHONE'), which no FAA list gives"),
        ("HELI", "remarks also use HELI for helicopter ('HELI OPNS'), which no FAA list gives"),
        ("OBS", "remarks also use OBS for obstacle ('CTL OBS'), which no FAA list gives"),
    ]},
    # the FAA meaning, said the way remarks and pilots say it
    "ACRS": {"accept": [r"\bcross"], "note": "'RD ACRS APCH' reads as 'road crosses the approach'"},
    "ACTVT": {"accept": [r"\bturn(s|ed|ing)? on\b", r"\bclick"],
              "note": "pilot-controlled lighting: 'click the mic ... to turn on'"},
    "AFLD": {"accept": [r"\bairport\b", r"\bfield\b"]},
    "ALS": {"accept": [r"\bapproach light"]},
    "AMGR": {"accept": [r"\bmanager\b"]},
    "BASH": {"accept": [r"\bbird.{0,15}\bstrike"]},
    "APP": {"accept": [r"\bapproach\b"], "note": "'CTC APP' is 'contact approach'"},
    "ATCT": {"accept": [r"\btower\b"]},
    "DSTC": {"accept": [r"\baway\b"], "note": "'199 FT DSTC' reads as '199 feet away'"},
    "DTHR": {"accept": [r"\bdisplaced (runway )?threshold"]},
    "FLD": {"accept": [r"\bmid-?field\b"], "note": "'MID-FLD' reads as 'midfield'"},
    "FONE": {"accept": [r"\bphone", r"\bcall"]},
    "H24": {"accept": [r"\b24[- ]?(hours?|hrs?)\b", r"\baround the clock\b"]},
    "INVOF": {"accept": [r"\bnear\b"]},
    "LEN": {"accept": [r"\blong\b"], "note": "'LEN 800 FT' reads as '800 feet long'"},
    "MALSF": {"accept": [r"\bapproach light"]},
    "MID": {"expansion": "middle", "accept": [r"\bmid-?field\b"],
            "note": "'MID 8500 FT ASPH', 'MID-FLD'. mid-point is an RVR term"},
    "MALSR": {"accept": [r"\bapproach light"]},
    "OBSTN": {"accept": [r"\bobstacles?\b"], "note": "OBST, its root, also means obstacle (JO 7340.2, ICAO)"},
    "OTFC": {"accept": [r"\boverfl"]},
    "OTS": {"accept": [r"\bout\b"], "note": "'REIL OTS' reads as 'REIL out'"},
    "PAJA": {"accept": [r"\bparachut\w* jump"]},
    "PPR": {"accept": [r"\bprior permission\b"], "note": "'WO PPR' reads as 'without prior permission'"},
    "TGL": {"accept": [r"\btouch[- ]and[- ]go"]},
    "U/S": {"accept": [r"\bout of service\b"]},
    "UAS": {"accept": [r"\bun(manned|crewed) (aerial|aircraft)\b"]},
    "Z": {"accept": [r"\butc\b", r"\bcoordinated universal time\b", r"\bzulu\b"],
          "note": "'1300Z'. the Chart Supplement legend: hours 'are expressed in Coordinated Universal "
                  "Time (UTC) and shown as \"Z\" time'; the AIM (appendix 5) says 'Zulu (Z)'"},
    # SS-SR is one period, sunset to sunrise: the meanings have to come out in that order
    "SS-SR": {"parts": ["SS", "SR"], "accept": [r"\bsunset\b.{0,40}\bsunrise\b"]},
    "SR-SS": {"parts": ["SR", "SS"], "accept": [r"\bsunrise\b.{0,40}\bsunset\b"]},
}

# JO 7340.2-only meanings checked against the 4,458 translated remarks in remark_cache.json
# (2026-09-28): the model, told only 10 of them by the old prompt, read them the FAA's way, and
# where it didn't, the FAA meaning was the right one (STWY is stopway, not taxiway; EUO is
# emergency use only). the model is told these. any other JO 7340.2 meaning is still
# accepted in a translation but isn't suggested, since remarks may use the letters for
# something else: DEPT for department and departure, OBS for observation and obstacle, RLS
# for release and reduced level of service, NB and WB for taxiway names
REVIEWED = {
    "AATM", "ACDNT", "ACES", "ACTV", "AD", "ADNL", "ADQT", "ADVN", "ADVZY", "ADZY", "AFT",
    "AHD", "ALG", "ANG", "ANNC", "ARND", "ASPH", "ASSOC", "ASST", "ATMT", "ATND", "AUZ", "BDR",
    "BFR", "BGN", "BHND", "BLN", "BNTH", "BT", "BUR", "CAPT", "CDN", "CERT", "CFM", "CHNL",
    "CHTR", "CLB", "CLKWS", "CLR", "CMB", "CMPLX", "CMPSN", "CMSN", "CONFIG", "CONS", "CONTR",
    "CPBL", "CPTY", "CSDRBL", "CUST", "DBA", "DBL", "DER", "DFCLT", "DIAM", "DISC", "DLA",
    "DLVY", "DNWND", "DPT", "DRCTN", "DRG", "DSCNT", "DSGND", "DSNT", "DSPL", "DURG", "EFCT",
    "ELEC", "ENR", "ENRT", "ENTR", "EQUIP", "ERY", "EUO", "EXCP", "EXEC", "EXPC", "EXTSV",
    "FAM", "FICON", "FIRG", "FNA", "FQT", "FRQ", "FSDO", "FSL", "FST", "FTHR", "GEN", "GENOT",
    "GLD", "GNTR", "GRVL", "GTR", "HEL", "HLDG", "HNGR", "HYR", "ID", "IMT", "INDC", "INSP",
    "INTNS", "INTST", "INTXN", "IR", "IREG", "ITNRNT", "LCT", "LN", "LND", "LNDG", "LOA",
    "LONGL", "LST", "LVE", "LVL", "LWR", "MECH", "MEML", "MIDPT", "MISG", "MKD", "MNM", "MNTN",
    "MNVR", "MOV", "MPH", "MRKG", "MTR", "MTRL", "MULT", "NLT", "NMRS", "NNE", "NTFY", "OBND",
    "OBSC", "OCR", "OCS", "OFC", "OPER", "OTR", "OTRW", "OVHD", "OVNGT", "OVR", "OXY", "PCD",
    "PCT", "PERI", "PHYS", "PLINE", "PMSN", "PMT", "POSS", "PRI", "PRKG", "PROC", "PROCD",
    "PROG", "PROP", "PRVD", "PSBL", "PSGR", "PSN", "PSNL", "PUP", "RCMD", "REF", "RESP", "RFL",
    "RGLR", "RITE", "RLRD", "RMN", "ROT", "ROTG", "RPR", "RPRT", "RQMNTS", "RSCD", "RSTR",
    "RSVN", "RTNE", "RY", "SB", "SCTY", "SECT", "SENS", "SEPN", "SGFNT", "SHTDN", "SI", "SIMUL",
    "SLCT", "SML", "SMT", "SNGL", "SPCLY", "SPD", "SRY", "SSW", "STNR", "STS", "STWY", "SUF",
    "SUPT", "SUPVR", "SVR", "SWY", "TAX", "TBJT", "TEMPO", "THR", "THRUT", "TMT", "TRG",
    "TRNSP", "TRRN", "TRSN", "TSFR", "TSNT", "TURB", "TWD", "TXG", "TXL", "UNATNDD", "UNKN",
    "UNRELBL", "USBL", "VCY", "VFY", "VOL", "VR", "VRBL", "VSB", "VTOL", "WDI", "WI", "WID",
    "WKDAY", "WKEND", "XNG", "XPLOS"
}

# JO 7340.2 1-2-3 derived forms (LGTS = LGT + S) that remarks really use that way. the suffix rule
# also reads words, names and other codes as derivations: DHS isn't "decision heights" (it's
# Homeland Security), SFAR isn't a single frequency approach, PRIST is a fuel additive, THRUST
# and MINUS are words, DSPLD is "displaced" (not display). so only forms checked against every
# remark in remark_cache.json and history/ (2026-09-28: 437 derived forms, 51 of them wrong) are
# derived; any other one is copied as written until someone checks it and adds it here
DERIVED = {
    "ABNDD", "ACCUMG", "ACDNTS", "ACESS", "ACPTBL", "ACPTD", "ACPTG", "ACTVTD", "ACTVTY", "ADDNL",
    "ADDNLY", "ADVND", "ADZD", "ADZYS", "AFTR", "AGRMTS", "ALTS", "AMDD", "AMGRS", "APCHG", "APCHS",
    "APNS", "APNTMT", "APPRS", "APROPLY", "APRXLY", "APUS", "APVD", "ARNGMTS", "ARPTS", "ARRG",
    "ARRS", "ASGND", "ASSOCD", "ASSOCN", "ASSTNC", "ATCHD", "ATNDD", "ATNDNC", "AUTOLY", "AUZD",
    "AVBLTY", "AWTG", "AWYS", "BDRG", "BGNG", "BGNNG", "BGNS", "BLDGS", "BRGS", "CATS", "CERTD",
    "CFMD", "CFMG", "CFMN", "CFNS", "CHGS", "CHRGD", "CHRGS", "CLNCS", "CLRD", "CLRG", "CLRNC",
    "CLRNG", "CMPLTD", "CMSND", "CMSNG", "CNCTG", "CNLD", "CNTRD", "CNTRLNS", "CNTRR", "CNVGG",
    "COLLD", "COMS", "CONDS", "CONFIGNS", "CONSLY", "CONTD", "CONTN", "COORDD", "COORDG", "COORDN",
    "COORDR", "COVD", "CPBLTY", "CRCG", "CROSS", "CRTFYD", "CTCD", "CTCG", "CTCS", "CTLD", "CTLG",
    "CTLNG", "CTLS", "DCMSND", "DCMTS", "DCTD", "DEGS", "DEPG", "DEPNG", "DEPS", "DETS", "DISPLD",
    "DMGD", "DRCTD", "DRCTNL", "DSRD", "DSTCS", "DTHRS", "DTLS", "DTRMD", "DTRMN", "DVLPMT", "DVS",
    "ELECL", "ELEVD", "EMERGS", "ENGRNG", "ENGS", "EORS", "ESTABD", "ESTABL", "ESTABMT", "EXCLDG",
    "EXCLDN", "EXCLDNG", "EXCTG", "EXERS", "EXPD", "EXTDD", "EXTDG", "EXTDNG", "EXTDS", "EXTRMLY",
    "EXTSVLY", "FACS", "FBOS", "FCSTR", "FICONS", "FLDS", "FLTS", "FLWG", "FQTLY", "FREQS", "FSDOS",
    "FWDD", "GENLY", "GLDRS", "GLDS", "HAZUS", "HDGS", "HELS", "HGRS", "HGTS", "HNGRS", "HOLS",
    "HOPS", "HRS", "IMTLY", "INCLG", "INCLNG", "INCLS", "INCRD", "INCRS", "INDCR", "INDCS",
    "INDEFLY", "INSPD", "INSPN", "INSPNS", "INSTLD", "INSTLN", "INSTRD", "INSTRN", "INSTRNS",
    "INSTRS", "INTRPN", "INTSTY", "INTSV", "INTVLS", "KTS", "LCTG", "LCTNS", "LDGS", "LGTG",
    "LGTNG", "LMTD", "LMTNS", "LNDGS", "LNS", "LRGR", "LWRD", "MAINTD", "MDTLY", "MECHL", "MGRS",
    "MINS", "MIRLS", "MKRS", "MNMS", "MNTD", "MNTND", "MNTNS", "MNTS", "MNVRG", "MNVRNG", "MNVRS",
    "MOAS", "MOVMT", "MRKD", "MRKGS", "MRKS", "MSNS", "MTNS", "MTRLS", "MTS", "NAVAIDS", "NGTLY",
    "NGTS", "NMBRS", "NOTAMS", "NRS", "NRWS", "OBSCD", "OBSCS", "OBSL", "OBSTD", "OBSTG", "OBSTNG",
    "OBSTNS", "OBSTR", "OBSTS", "OCNLLY", "OCRS", "OGNG", "OPERD", "OPERG", "OPERN", "OPERNG",
    "OPERNS", "OPERS", "OPRD", "OPRG", "OPRN", "OPRNG", "OPRNS", "OPRS", "OPSS", "OVLAD", "OVRNS",
    "P-LINES", "PAPIS", "PARLS", "PATS", "PDS", "PENTG", "PERMLY", "PLAS", "PLINES", "PMTD", "PMTG",
    "PPRS", "PPSD", "PREVLY", "PRIMLY", "PRKD", "PROCS", "PRVDD", "PRVDG", "PRVDS", "PSGRS", "PSNS",
    "PTCPG", "PTNS", "PUBLD", "PVLG", "PVTLY", "PWRD", "PWRS", "QNS", "QUADS", "RCMDD", "RCVD",
    "RCVG", "RDCD", "RDCG", "REGS", "REILS", "REQS", "RESD", "RESL", "RESNC", "RESPBL", "RESV",
    "RFLG", "RFLNG", "RGLRLY", "RMKS", "RMNDR", "RMNG", "RPLCMT", "RPRS", "RPRTD", "RPRTG", "RPRTS",
    "RPTD", "RQRD", "RQRG", "RQRMT", "RQRS", "RSTRD", "RSTRN", "RSTRNS", "RSTRS", "RSVNS", "RTES",
    "RWYS", "RYS", "SEBD", "SECS", "SERS", "SERV", "SFCS", "SIDS", "SKEDD", "SKEDG", "SKEDS",
    "SLPD", "SLPS", "SMLR", "SMTD", "SPECS", "SQDNS", "SRNDD", "SRNDG", "SRNDNG", "SRNDS", "STDS",
    "STWYS", "SUPPLL", "SUPVRS", "SVCS", "SVRLY", "SVRTY", "TEMPOLY", "TGLS", "THLDS", "THRD",
    "THRS", "THUR", "TILL", "TKOFS", "TMPRYLY", "TMTN", "TRKG", "TRMTS", "TRNSPG", "TRNSPN",
    "TRSNL", "TUES", "TVLG", "TWRS", "TWYS", "TXLN", "TXLS", "UNABL", "UNAVBLTY", "UNCTLD",
    "UNMRKD", "UNSKEDD", "UNSVCBL", "VARNS", "VFYD", "VSBL", "VSLS", "WEDS", "WKDAYS", "WKENDS",
    "WKS", "WNDS", "WTS", "XNGS", "YDS", "YRS"
}

# remarks that spell an FAA contraction their own way: APRCH where the FAA writes APCH. each takes
# the meaning of the FAA form it names, and only after every remark in NASR that uses it was read
# and meant that (2026-10-01 cycle, all remark fields). a translation may still copy it as written.
# not TEMP: the FAA lists it as temperature, and remarks use it for that too (see CURATED)
SPELLINGS = {
    "APPCH": ("APCH", "22 remarks in NASR (2026-10-01) write APPCH, all for approach: "
                      "'APPCH SLP 26:1 TO MKD DTHR', 'INDY APPCH - R, E 134.85'"),
    "APRCH": ("APCH", "20 remarks in NASR (2026-10-01) write APRCH, all for approach: "
                      "'RWY 33 APRCH 34:1 TO AER', 'APRCH END OF ALL RWYS'"),
    "EXTNDD": ("EXTDD", "35 remarks in NASR (2026-10-01) write EXTNDD, all for extended: "
                        "'10 FT TREES EXTNDD CNTRLN', 'ON EXTNDD RY CNTRLN'. EXTDD is EXTD + D (JO 1-2-3)"),
}


# ---------------------------------------------------------------- reading the glossary
_GLOSSARY = None


def load():
    """{TERM: entry}, read once."""
    global _GLOSSARY
    if _GLOSSARY is None:
        with open(GLOSSARY_FILE) as f:
            _GLOSSARY = json.load(f)["terms"]
    return _GLOSSARY


def lookup(term):
    """the glossary entry for a term, a reviewed derived one (LGTS from LGT + S), or None."""
    terms = load()
    if term in terms or term in ENGLISH:
        return terms.get(term)
    found = term in DERIVED and derivation(term, terms)
    if not found:
        return None
    root, suffix = found
    return {**terms[root], "derived_from": root, "prompt": False,
            "source": f"{terms[root]['source']} + JO 1-2-3 suffix {suffix}"}


def derivation(term, terms):
    """(root, suffix) of a derived form whose root has one verified meaning: HRS is ("HR", "S")."""
    for suffix in sorted(SUFFIXES, key=len):      # the longest root first: MINS is MIN + S
        root = term[:-len(suffix)]
        if not term.endswith(suffix) or len(root) < (2 if suffix == "S" else 3):
            continue
        base = terms.get(root)
        if base and base["verified"] and not base.get("parts"):
            return root, suffix
    return None


def contracted(term):
    """no vowels after the first letter: THLD, PRVDD, APCH. not HOLD or WIND."""
    return not re.search(r"[AEIOU]", term[1:])


def words(meaning):
    """the words of an FAA meaning, lowercase, parentheses dropped, US spelling: the FAA's ICAO
    meanings say 'centre line' where a translation says 'centerline'."""
    text = re.sub(r"\(.*?\)", " ", meaning.lower().replace("-", ""))
    text = text.replace("centre", "center").replace("metre", "meter")
    return re.findall(r"[a-z]+", text)


def senses_of(meaning):
    """the ways one FAA meaning can be said: 'light or lighting', 'observe, observed, or observation'."""
    return [s for s in re.split(r",\s*(?:or\s+)?|\s+or\s+", meaning) if s.strip()]


# ---------------------------------------------------------------- building glossary.json
def norm(text):
    """FAA text uses en dashes and odd hyphens; soft hyphens come from the HTML."""
    text = text.replace("­", "")
    return re.sub(r"[‐‑‒–—]", "-", text).strip()


def senses(sources):
    """{TERM: [(meaning, "CS" or "JO", usage)]} from both lists."""
    out = {}
    for abbr, meaning in sources["chart_supplement"]["rows"]:
        keys = [k.upper() for k in re.split(r",\s*|\s+or\s+", norm(abbr))]
        parts = [p.strip() for p in norm(meaning).split(",")]
        # "lgt, lgtd, lgts" = "light, lighted, lights": pair them up
        pairs = zip(keys, parts) if len(keys) > 1 and len(parts) == len(keys) else \
            ((k, norm(meaning)) for k in keys)
        for k, m in pairs:
            run, split = CS_RUN_TOGETHER.get(k, (None, None))
            out.setdefault(k, []).extend((p, "CS", None) for p in (split if m == run else [m]))
    for abbr, meaning, usage in sources["jo_7340_2"]["rows"]:
        out.setdefault(norm(abbr).upper(), []).append((norm(meaning), "JO", usage))
    return out


def _related(a, b):
    """do two FAA meanings share a word, give or take its ending? 'mark' and 'marker', 'move'
    and 'moving', 'observe' and 'observation'. not 'district' and 'distance', or 'minimum' and 'minute'."""
    wa = [w for w in words(a) if len(w) > 2 and w not in _FILLER]
    wb = [w for w in words(b) if len(w) > 2 and w not in _FILLER]
    return any(x.startswith(y) or y.startswith(x) or
               (min(len(x), len(y)) >= 4 and len(os.path.commonprefix([x, y])) >= min(5, len(x) - 1, len(y) - 1))
               for x in wa for y in wb)


_FILLER = {"and", "the", "for", "with", "from", "into", "not"}


def _one_sense(meanings):
    """true when every meaning is a form of the first: 'Civil, civil, civilian' or 'beacon' and
    'Rotating Light or Beacon', not 'Fan Marker, Frequency Modulation'."""
    parts = [p for m in meanings for p in re.split(r",(?![^()]*\))\s*", m) if p.strip()]
    return all(_related(parts[0], p) for p in parts[1:])


def _dedup(meanings):
    seen, out = set(), []
    for m in meanings:
        if m.lower() not in seen:
            seen.add(m.lower())
            out.append(m)
    return out


def default_entry(term, found):
    """entry for a term nobody curated: verified only when the FAA gives it one meaning."""
    faa = [f"{src}: {m}" + (f" ({u})" if u else "") for m, src, u in found]
    cs = _dedup(m for m, src, _ in found if src == "CS")
    jo = [(m, u) for m, src, u in found if src == "JO" and u in JO_USED]
    entry = {"expansion": None, "verified": False, "source": None, "faa": faa, "prompt": False}
    if cs:      # the remarks' own publication decides; JO meanings that agree are accepted too
        base, source = cs, "CS"
        also = [m for m, _ in jo if _related(m, cs[0])]
    elif jo:
        base, source, also = _dedup(m for m, _ in jo), f"JO 2-1-1 ({jo[0][1]})", []
    else:
        entry["note"] = "only a weather-report meaning in JO 7340.2"
        return entry
    if not _one_sense(base):
        entry["note"] = "the FAA lists more than one meaning; copied as written until one is picked"
        return entry
    # the model is told Chart Supplement meanings, and JO 7340.2 ones checked against real remarks
    # (REVIEWED, CURATED). others are accepted but not suggested: many are from other fields
    # (LL = landline, GOV = governor) and would push the model to a wrong reading
    entry.update(expansion=base[0], meanings=_dedup(base + also), verified=True, source=source,
                 prompt=len(term) > 1 and (source == "CS" or term in REVIEWED))
    return entry


def build(sources=None):
    """glossary.json from faa_abbreviations.json + CURATED + ENGLISH."""
    if sources is None:
        with open(SOURCES_FILE) as f:
            sources = json.load(f)
    found = senses(sources)
    terms = {t: default_entry(t, f) for t, f in found.items()}
    for term, cur in CURATED.items():
        entry = dict(terms.get(term) or {"expansion": None, "verified": False, "source": None,
                                         "faa": [], "prompt": False})
        if "parts" in cur:
            parts = [terms[p] for p in cur["parts"]]
            if not all(p["verified"] for p in parts):
                raise ValueError(f"{term}: every part must be verified")
            entry.update(expansion=" to ".join(p["expansion"] for p in parts), verified=True,
                         source=" + ".join(f"{t} ({p['source']})" for t, p in zip(cur["parts"], parts)),
                         meanings=[], parts=cur["parts"], prompt=cur.get("prompt", True))
        elif "expansion" in cur and cur["expansion"] is None:
            entry.update(expansion=None, verified=False, source=None, prompt=False)
            entry.pop("meanings", None)
        elif "expansion" in cur:
            picked = [cur["expansion"]] if isinstance(cur["expansion"], str) else cur["expansion"]
            root = cur.get("root", term)
            source = _source_of(root, picked[0], found)
            for m in picked[1:]:
                _source_of(root, m, found)
            if root != term:
                source = f"{source} {root} + JO 1-2-3 suffix {term[len(root):]}"
                entry["faa"] = [f"{root}: {f}" for f in terms[root]["faa"]]
            entry.update(expansion=" or ".join(picked), meanings=picked, verified=True, source=source,
                         prompt=cur.get("prompt", True))
            entry.pop("note", None)
        elif entry["verified"]:     # reviewed against real remarks: the model may be told the meaning
            entry["prompt"] = cur.get("prompt", len(term) > 1)
        if not entry["verified"] and ("accept" in cur or "parts" in cur):
            raise ValueError(f"{term}: accept patterns need a verified meaning")
        if "remarks_use" in cur and entry["verified"]:
            raise ValueError(f"{term}: remarks_use is for a term copied as written")
        for k in ("note", "accept", "remarks_use"):
            if k in cur:
                entry[k] = cur[k]
        terms[term] = entry
    for term, (form, seen) in SPELLINGS.items():
        if term in terms or term in ENGLISH:
            raise ValueError(f"{term} is an FAA term or an English word, not a spelling of {form}")
        root, suffix = (form, None) if form in terms else \
            (form in DERIVED and derivation(form, terms)) or (None, None)
        base = terms.get(root)
        if not (base and base["verified"]) or base.get("parts"):
            raise ValueError(f"{term}: {form} has no verified meaning")
        terms[term] = {**base, "source": base["source"] + (f" + JO 1-2-3 suffix {suffix}" if suffix else "")
                       + f", spelled {form}", "faa": [f"{root}: {f}" for f in base["faa"]], "prompt": True,
                       "spelling_of": form, "note": f"the FAA writes {form}. {seen}",
                       **({"derived_from": root} if suffix else {})}
    for term in ENGLISH:
        entry = terms.get(term)
        terms[term] = {"expansion": None, "verified": False, "source": None,
                       "faa": entry["faa"] if entry else [], "prompt": False, "english": True,
                       "note": "an everyday English word in remarks; kept as the word, never expanded"}
    for term, (before, meaning, seen) in AFTER.items():
        if term not in ENGLISH:
            raise ValueError(f"{term}: an AFTER rule is for a word remarks otherwise use as English")
        terms[term]["after"] = {"words": list(before), "meaning": meaning,
                                "source": _source_of(term, meaning, found), "note": seen}
    for term, (after, form, seen) in BEFORE.items():
        base, entry = terms.get(form), terms.get(term)
        if not (base and base["verified"]) or base.get("parts") or not entry or entry["verified"] \
                or entry.get("english"):
            raise ValueError(f"{term}: a BEFORE rule gives a term copied as written a verified contraction's meaning")
        entry["before"] = {"words": list(after), "meaning": base["expansion"], "spelling_of": form,
                           "source": f"{base['source']}, spelled {form}", "note": seen}
    return {"about": ("Contractions a remark translation may expand, each traced to an FAA list. "
                      "Built by amend/glossary.py from faa_abbreviations.json; edit CURATED there, "
                      "not this file."),
            "sources": {k: {x: v for x, v in s.items() if x != "rows"} for k, s in sources.items()},
            "terms": dict(sorted(terms.items()))}


def _source_of(term, expansion, found):
    """which FAA list gave this meaning. raises if neither did: the glossary never invents one."""
    for m, src, usage in found.get(term, []):
        options = [m] + senses_of(m) + [p.strip() for p in m.split(",")]
        if any(expansion.lower() == o.lower() for o in options):
            return "CS" if src == "CS" else f"JO 2-1-1 ({usage})"
    raise ValueError(f"{term}: {expansion!r} is not an FAA meaning of {term}")


def write(glossary, path=GLOSSARY_FILE):
    """one term per line, so a review diff shows exactly which terms changed."""
    lines = ["{",
             f' "about": {json.dumps(glossary["about"])},',
             f' "sources": {json.dumps(glossary["sources"], sort_keys=True)},',
             ' "terms": {']
    items = list(glossary["terms"].items())
    for i, (term, entry) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"  {json.dumps(term)}: {json.dumps(entry, ensure_ascii=False)}{comma}")
    lines += [" }", "}"]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- refreshing the FAA lists
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "amend glossary (github.com/benjgmin/amend)"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def _stamp(url, body):
    return {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def parse_jo(page):
    """rows of the 2-1-1 Decode tables: [contraction, definition, usage]."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        cells = [norm(re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", td))))
                 for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)]
        if len(cells) == 3 and cells[0] != "Contraction":
            rows.append(cells)
    return rows


def parse_cs(pdf_bytes):
    """rows of the Chart Supplement's Abbreviations pages: [abbreviation, description]."""
    import pypdf   # only needed to refresh the list, not to run amend
    pages = [p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages]
    rows = []
    for text in pages:
        if not re.search(r"Abbreviation\s*\.+\s*Description", text):
            continue
        for line in text.splitlines():
            s = line.rstrip()
            if (not s.strip() or re.match(r"^\s*(\d+\s+)?GENERAL INFORMATION(\s+\d+)?\s*$", s)
                    or re.match(r"^Abbreviation\s*\.+\s*Description", s.strip())
                    or re.match(r"^[A-Z]{2,3}, \d+ [A-Z]{3} \d{4} to", s.strip())
                    or s.strip() in ("Abbreviations", "ABBREVIATIONS")):
                continue
            m = re.match(r"^(.+?)\s*\.{2,}\s*(.+)$", s)
            if m:
                rows.append([m.group(1).strip(), m.group(2).strip()])
            elif rows and not s.startswith(("The following", "the Legend", "form.", "For additional")):
                rows[-1][1] += " " + s.strip()
    return rows


def refresh():
    """download both FAA lists and rewrite faa_abbreviations.json. faa.gov must be reachable."""
    index = _get(JO_INDEX).decode("utf-8", "replace")
    m = re.search(r"Effective:\s*([\d/]+)\s*Change:\s*([^<\n]+?)\s*FAA", re.sub(r"<[^>]+>", " ", index))
    edition = re.search(r"FAA Order (JO 7340\.2\w*)", index)
    page = _get(JO_URL)
    jo = {**_stamp(JO_URL, page), "title": "FAA Order JO 7340.2, Contractions, 2-1-1 Decode",
          "edition": edition.group(1) if edition else None,
          "effective": m.group(1) if m else None, "change": m.group(2).strip() if m else None,
          "rows": parse_jo(page.decode("utf-8", "replace"))}
    links = re.findall(r'href="([^"]*DCS_(\d{8})\.zip)"', _get(CS_PAGE).decode("utf-8", "replace"))
    today = time.strftime("%Y%m%d")
    url = max((l for l in links if l[1] <= today), key=lambda l: l[1])[0]
    body = _get(url)
    z = zipfile.ZipFile(io.BytesIO(body))
    front = sorted(n for n in z.namelist() if re.search(r"(^|/)EC_front_.*\.pdf$", n))[0]
    pdf = z.read(front)
    cs = {**_stamp(url, body), "title": "Chart Supplement U.S., General Information, Abbreviations",
          "file": os.path.basename(front), "file_sha256": hashlib.sha256(pdf).hexdigest(),
          "rows": parse_cs(pdf)}
    if len(jo["rows"]) < 3000 or len(cs["rows"]) < 700:
        raise RuntimeError(f"FAA lists look incomplete: JO {len(jo['rows'])} rows, CS {len(cs['rows'])} rows")
    sources = {"chart_supplement": cs, "jo_7340_2": jo}
    write_sources(sources)
    return sources


def write_sources(sources, path=SOURCES_FILE):
    """provenance first, then one FAA row per line."""
    out = ["{"]
    for i, (name, src) in enumerate(sources.items()):
        meta = {k: v for k, v in src.items() if k != "rows"}
        out.append(f" {json.dumps(name)}: {{")
        out += [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in meta.items()]
        out.append('  "rows": [')
        rows = src["rows"]
        out += [f"   {json.dumps(r, ensure_ascii=False)}{',' if j < len(rows) - 1 else ''}"
                for j, r in enumerate(rows)]
        out.append("  ]")
        out.append(" }" + ("," if i < len(sources) - 1 else ""))
    out.append("}")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    src = refresh() if "--refresh" in sys.argv else None
    g = build(src)
    write(g)
    n = sum(1 for e in g["terms"].values() if e["verified"])
    print(f"wrote {GLOSSARY_FILE}: {len(g['terms'])} terms, {n} verified")
