"""
Every rule that decides what counts as a change, what's noise, and how important it is.
Tuning the output almost always means editing this file.
"""
import re

# columns that change every cycle and are never real changes
IGNORE_COLS = {"EFF_DATE", "LAST_INFO_RESPONSE", "LAST_INFO_RESPONSE_DATE"}

# identity columns: hidden in summaries
ID_COLS = {"SITE_NO", "SITE_TYPE_CODE", "STATE_CODE", "CITY", "COUNTRY_CODE", "ARPT_ID"}

# columns that decide which airport a row belongs to, in order of preference.
# FRQ rows use SERVICED_FACILITY so "SJC approach serving PAO" goes to PAO, not SJC.
ATTRIB_COLS = ("ARPT_ID", "SERVICED_FACILITY", "FACILITY_ID", "NAV_ID", "LOC_ID",
               "ASOS_AWOS_ID", "Orig", "Dest", "ORIGIN_ID", "DSTN_ID")

# files where a row can mention an airport while being ABOUT another one
STRICT_FILES = ("FRQ", "PFR")

# when pairing an old row with a new row, these must match (if the file has them)
PAIR_KEYS = {
    "PFR_RMT_FMT": ("Orig", "Dest", "Type"),
    "APT_RMK": ("LEGACY_ELEMENT_NUMBER",),
    "ATC_RMK": ("LEGACY_ELEMENT_NUMBER", "REMARK_NO"),
    "APT_RWY_END": ("RWY_ID", "RWY_END_ID"),
    "APT_RWY": ("RWY_ID",),
    "FRQ": ("SERVICED_FACILITY", "FREQ"),
    "NAV_BASE": ("NAV_ID",),
    "ATC_BASE": ("FACILITY_ID",),
    "CLS_ARSP": ("ARPT_ID",),
    "AWOS": ("ASOS_AWOS_ID",),
    "APT_ATT": ("ARPT_ID",),
    "APT_BASE": ("ARPT_ID",),
    "APT_CON": ("TITLE",),
}

# whole files that are noise or duplicate other files. skipped at load time.
#   PFR_SEG/PFR_BASE: routes already readable in PFR_RMT_FMT   LID: duplicate id list
#   FIX: fix definitions, not airport changes   CDR: airline coded departure routes
#   COM: duplicates the RCO/outlet info already in FRQ
#   HPF: holding patterns, MTR: military training route points. neither is about an airport:
#   they only matched one because a navaid id equals an airport id (the MTH NDB hold -> MTH,
#   IR-320 point S -> INW) and every new/removed point showed up as act.
HIDDEN_FILES = ("PFR_SEG", "PFR_BASE", "LID", "FIX", "CDR", "COM", "HPF", "MTR")

# changes that only touch these columns are hidden (stats, survey bookkeeping, pavement data)
HIDDEN_ONLY_COLS = {"AIR_TAXI_OPS", "ANNUAL_OPS_DATE", "BASED_GLIDERS", "BASED_HEL",
                    "BASED_JET_ENG", "BASED_MIL_ACFT", "BASED_MULTI_ENG", "BASED_SINGLE_ENG",
                    "BASED_ULTRALGT_ACFT", "COMMERCIAL_OPS", "COMMUTER_OPS", "ITNRNT_OPS",
                    "LOCAL_OPS", "MIL_ACFT_OPS", "LAST_INSPECTION", "LENGTH_SOURCE_DATE",
                    "PAVEMENT_CLASSIFICATION", "PCN_PCR_NUMBER", "PCN", "PAVEMENT_TYPE_CODE",
                    "SUBGRADE_STRENGTH_CODE", "TIRE_PRES_CODE", "DTRM_METHOD_CODE",
                    "GROSS_WT_SW", "GROSS_WT_DW", "GROSS_WT_DTW", "GROSS_WT_DDTW"}
NAME_COLS = {"FACILITY_NAME", "FAC_NAME", "SERVICED_FAC_NAME", "NAME", "ARPT_NAME"}
FYI_ONLY_COLS = {"SECTORIZATION", "OBSTN_HGT", "OBSTN_CLNC_SLOPE", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE",
                 "DIST_FROM_THR", "FREQ_USE", "RWY_MARKING_COND", "COND",
                 # FRQ echoes of a navaid/AWOS change already reported by its own file
                 "SERVICED_SITE_TYPE", "SERVICED_CITY", "SERVICED_STATE",
                 # AWOS-3 -> AWOS-3PT, ATIS -> D-ATIS, beacon schedule: nice to know, not how you fly
                 "ASOS_AWOS_TYPE", "DESCRIPTION", "BCN_LGT_SKED", "BCN_LENS_COLOR"}

ACTION_PREFIXES = ("ATC", "CLS_ARSP", "FRQ", "ILS", "APT_ATT", "AWOS")
ACTION_COL_WORDS = {"NAV", "PROVIDER", "HRS", "HOURS", "FREQ", "CLASS", "AIRSPACE", "CLOSED",
                    "STATUS", "LGT", "LIGHT", "LIGHTS", "LEN", "WIDTH", "TPA", "ATTEND"}
ACTION_TEXT_WORDS = ("CLSD", "CLOSED", "TWR", "PPR", "NOT AVBL", "UNAVBL", "UNUSBL", "CTAF", "TPA",
                     "PROHIBITED", "RSTD", "NOISE", "TRANSPONDER",
                     # DFW: "MUST OBTAIN APVL FM RAMP 129.825 PRIOR TO ENTERING RAMP". not APVL
                     # alone: "WAIVED BY FAA (10/06/2009 ALP APVL LTR)" is history
                     "OBTAIN APVL", "PRIOR APVL")

# a remark that only got reworded is fyi (diff.just_reworded). these words change what it
# means, so a remark that gains or loses one was not just reworded: OKM "ILS UNMONITORED" ->
# "ILS MONITORED AT MOCC", EVY "RWY 11/29 CLSD FOR NIGHT OPS" -> "...; DAYTIME VFR USE ONLY".
# spellings in REWORD_ALIASES count as the same word first (EXCP -> EXC).
REWORD_BLOCKERS = {w for w in ACTION_TEXT_WORDS if " " not in w} | {
    "NOT", "NO", "NON", "NA", "ONLY", "EXC", "UNMON", "MONITORED", "UNLGTD", "LGTD", "APVL",
    "DAY", "DAYTIME", "NIGHT", "NGT", "VFR", "IFR", "AVBL", "OTS", "USBL", "REQD",
    "MANDATORY", "UNATNDD", "ATNDD", "PERMITTED", "AUTH", "UNAUTH",
    # when and to whom it applies: days, months, seasons, and words that name one of a pair.
    # "RWY 18 CLSD MON-FRI" -> "SAT-SUN", "OVER 12500 LBS" -> "UNDER", "BEFORE ARR" -> "AFTER",
    # "TO TKOF" -> "TO LNDG", "WHEN WET" -> "WHEN DRY", "AETC FTR ACFT" -> "AETC ACFT" (SPS).
    # not MAY: it's also the verb ("DEER MAY BE ON RWY")
    "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    "WINTER", "SPRING", "SUMMER", "FALL",
    "BEFORE", "AFTER", "OVER", "UNDER", "ABOVE", "BELOW", "TKOF", "LNDG", "WET", "DRY",
    "TRAN", "BASED", "JET", "FTR", "HEL", "GLDR"}
REWORD_ALIASES = {"EXCP": "EXC", "EXCEPT": "EXC", "CLOSED": "CLSD", "UNMONITORED": "UNMON",
                  "TOWER": "TWR", "ATCT": "TWR", "REQUIRED": "REQD", "RQRD": "REQD",
                  "UNAVAILABLE": "UNAVBL", "AVAILABLE": "AVBL", "UNUSABLE": "UNUSBL", "OPNS": "OPS",
                  "UNLIGHTED": "UNLGTD", "UNLIT": "UNLGTD", "LIGHTED": "LGTD", "LIT": "LGTD",
                  # the blockers above, spelled out or contracted (BLM "OVER" -> "OVR" is a rewording)
                  "MONDAY": "MON", "TUESDAY": "TUE", "TUES": "TUE", "WEDNESDAY": "WED", "THURSDAY": "THU",
                  "THUR": "THU", "THURS": "THU", "FRIDAY": "FRI", "SATURDAY": "SAT", "SUNDAY": "SUN",
                  "JANUARY": "JAN", "FEBRUARY": "FEB", "MARCH": "MAR", "APRIL": "APR", "JUNE": "JUN",
                  "JULY": "JUL", "AUGUST": "AUG", "SEPTEMBER": "SEP", "SEPT": "SEP", "OCTOBER": "OCT",
                  "NOVEMBER": "NOV", "DECEMBER": "DEC", "AUTUMN": "FALL",
                  "BFR": "BEFORE", "AFT": "AFTER", "OVR": "OVER", "ABV": "ABOVE", "BLW": "BELOW",
                  "BLO": "BELOW", "TAKEOFF": "TKOF", "TAKEOFFS": "TKOF", "TKOFS": "TKOF",
                  "LANDING": "LNDG", "LANDINGS": "LNDG", "LNDGS": "LNDG", "LDG": "LNDG",
                  "TRANSIENT": "TRAN", "TRANSIENTS": "TRAN", "JETS": "JET", "FIGHTER": "FTR",
                  "FIGHTERS": "FTR", "HELICOPTER": "HEL", "HELICOPTERS": "HEL", "HELO": "HEL",
                  "HELOS": "HEL", "GLIDER": "GLDR", "GLIDERS": "GLDR", "GLDRS": "GLDR"}
# directions, written out or not, count as the ids they are: "N OF ARPT" -> "S OF ARPT" isn't a
# rewording, "NORTH" -> "N" (MAF) and "LEFT" -> "L" (24A) are (diff.just_reworded)
REWORD_DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE",
                     "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW", "LEFT": "L", "RIGHT": "R",
                     "LFT": "L", "RGT": "R"}
# ... and phrases, before the words are split: AKN "APPROACH NOT AUTHORIZED" = "APCH NA"
REWORD_PHRASES = {"NOT AUTHORIZED": "NA", "NOT AUTH": "NA"}

# phone numbers in remark text. a remark whose only edit is a phone number (A34 "PPR ... - AMGR
# OR 575-644-2549" -> "... - AMGR", SYR dropping "DSN 243-2399", KWA "DSN 480-2131" -> "DSN
# 315-480-2131") is fyi, like a phone change in APT_CON: what you need to do there didn't change.
# forms seen: 559-903-5372, (559) 896-1001, C940-676-2180/6474, D576-9755, DSN 736-2180/6474
# a bare 736-1843 only counts after DSN, C or D: "500-1500 FT" is a height band, not a phone
PHONE = (r"(?:(?:\bDSN\s+|\b[CD]-?)?(?:\(\d{3}\)\s?\d{3}-\d{4}|(?<!\d)(?<!\d-)\d{3}-\d{3}-\d{4})"
         r"|(?:\bDSN\s+|\b[CD]-?)\d{3}-\d{4})(?:/\d{4})*\b")

# ... and once the numbers are out, these are the only words that edit may add or drop. any other
# word is news: HSA "FOR CD CTC HOUSTON ARTCC" gaining "CTC GULFPORT APCH AT 228-265-6151" is a
# new facility to call for a clearance, not a new number
PHONE_FILLER = {"OR", "AT", "CALL", "CTC", "CONTACT", "PH", "PHONE", "TEL", "AND", "TO", "MAKE",
                "REQ", "REQUEST", "DURING", "DURG", "HOURS", "HRS", "THE"}

# empty and an explicit "none" say the same thing: the FAA filling in a blank (airframe repair
# "" -> NONE at dozens of fields, 36H, 3FL, D99 in 2026-10-01) isn't a change. on a yes/no
# column (*_FLAG) a blank that becomes N reads "none -> no" and is the same kind of fill-in.
BLANK_VALUES = {"", "NONE"}
BLANK_FLAG_VALUES = {"", "NONE", "N"}

# a whole row appearing or disappearing in these files is act even though no column name or
# value says so: a runway, a decommissioned navaid, approach radar. other files' rows carry
# column names like NAV_ID or RADAR_HRS on every row, so column words only rank "changed" rows.
ROW_ACTION = {"APT_RWY": ("added", "removed"), "NAV_BASE": ("removed",), "RDR": ("added", "removed")}
# ... and the other way: rows in act files that are fyi when they appear. a new AWOS (4MD) is a
# new weather source, nice to know; one going away is still act.
ROW_FYI = {"AWOS": ("added",)}
# ... and more rows that tell you about a field without changing how you fly it: a newly listed
# ATIS (most came from one 2025-01-23 backfill of 24-hour ATIS at towered fields), the services
# a tower lists (LAWRS, LLWAS), military ops hours, a jump area's contact frequency.
# a non-towered field's approach control listing is who you call for an IFR clearance: ifr.
ROW_TIER = {("ATC_ATIS", "added"): "fyi", ("ATC_SVC", "added"): "fyi", ("ATC_SVC", "removed"): "fyi",
            ("MIL_OPS", "added"): "fyi", ("MIL_OPS", "removed"): "fyi",
            ("PJA_CON", "added"): "fyi", ("PJA_CON", "removed"): "fyi"}
NON_ATCT_CONTROL = "ifr"
# navaid/ILS remarks filed against a survey-source column (REF_COL_NAME LAT_LONG_SOURCE_CODE,
# DIST_DIR_SOURCE_CODE): "3RD PARTY SURVEY." says who surveyed a part, not how it works.
# not APT_RMK: its remarks get filed against any column ("WIND SOCK ... UNICOM 122.9" on
# INFO_REQ_DATE)
SURVEY_REMARK_FILES = ("ILS_RMK", "NAV_RMK")

# an ATC_BASE row for a field without a tower (FACILITY_TYPE NON-ATCT) that names no tower,
# approach or departure service (P14): nothing about who you talk to changed
ATC_SERVICE_WORDS = {"TWR", "APCH", "DEP", "CTL", "PROVIDER", "HRS", "CALLS"}

# an FSS outlet note in a tower/ATC remark (T03 "COMMUNICATIONS PRVDD BY PRESCOTT RADIO ON
# FREQS 122.05R/113.5T (TUBA CITY RCO)") is fyi like any FSS outlet, unless its text has an act
# word (AVL "COMM UNAVBL BLO 6000 FT ... WHEN AVL APCH CTL CLSD")
FSS_OUTLET = r"\bPRVDD BY [A-Z .]+? (?:RADIO|FSS)\b"
# ...unless the outlet is how you get a clearance (CD/CLNC) or cancel IFR there
FSS_OUTLET_NOT = r"\b(?:CLNC|CLR|CD|CLRNC|IFR)\b"

# VOR-family navaids are aligned to a magnetic variation: when it changes (OTZ 15E -> 9E, epoch
# 2010 -> 2025) every radial moves, so it's act. on other navaids it's the area's variation.
DECLINATION_COLS = ("MAG_VARN", "MAG_VARN_HEMIS")
DECLINATION_NAV_TYPES = {"VOR", "VORTAC", "VOR/DME", "TACAN"}

# changed columns that belong to another category than their file's: tower hours on a
# frequency row (MTC) are about the tower
COL_CATEGORY = {"TOWER_HRS": "tower"}

# navaid/ILS remarks (unusable sectors, monitoring) matter to IFR flying: ifr, not act
IFR_REMARK_FILES = ("NAV_RMK", "ILS_RMK")

# numeric columns where a small change is survey rounding. (drop below, fyi below)
#   5801 -> 5800 ft runway, 1525.7 -> 1525.6 ft elevation, 40.01 -> 40 deg localizer bearing
SMALL_CHANGE = {"RWY_LEN": (10, 50), "RWY_WIDTH": (1, 10), "APCH_BEAR": (1, 1),
                "RWY_END_ELEV": (1, 1), "TDZ_ELEV": (1, 1), "ARPT_ELEV": (1, 1),
                "DISPLACED_THR_ELEV": (1, 1), "THR_CROSSING_HGT": (1, 1),
                # BNA 800 -> 801 ft with a new survey
                "DISPLACED_THR_LEN": (10, 10)}

# columns kept on a changed record so the summary can describe it ("runway 15: ...")
CONTEXT_COLS = ("Orig", "Dest", "Route String", "FREQ", "FREQ_USE", "NAV_ID", "NAV_TYPE",
                "RWY_ID", "RWY_END_ID", "ELEMENT", "SERVICED_FACILITY", "REMARK",
                "STAR_COMPUTER_CODE", "DP_COMPUTER_CODE", "NAME", "OBSTN_HGT", "DIST_FROM_THR",
                "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE", "OBSTN_TYPE", "TITLE", "_NEAR_NM", "ILS_LOC_ID", "SYSTEM_TYPE_CODE")

NAV_NAMES = {"VOT": "VOR test signal (VOT)", "VORTAC": "VORTAC", "VOR/DME": "VOR/DME",
             "DME": "DME", "NDB": "NDB", "VOR": "VOR", "TACAN": "TACAN"}

# every *_RMK file with a REMARK column is a remark: airport, tower, ILS, navaid, AWOS, frequency...
REMARK_FILES = ("APT_RMK", "ATC_RMK", "ILS_RMK", "NAV_RMK", "AWOS_RMK", "FRQ_RMK", "COM_RMK",
                "CLS_ARSP_RMK", "FIX_RMK")
# numbered remark lists (REF_COL_NAME): an airport's general remarks (APT_RMK A110-1, A110-2...),
# a tower's, an ILS's or a navaid's. the number is a place in the list, not what the remark is
# about, and the FAA puts a new remark in a freed number: SMF 2026-01-22 A110-28 "GND VEHICLE
# SURVEILLANCE SYS IN USE..." -> "WEST RAMP SPOTS 63W, 65W, 66 & F1 RSTRD TO TOW IN...". a remark
# filed against a field (a runway end's OBSTN_CLNC_SLOPE) is about that field whatever it says
LIST_REMARK_COLS = ("GENERAL_REMARK", "ATC_REMARK")
# the columns that only say where a remark sits in its list
REMARK_SLOT_COLS = ("LEGACY_ELEMENT_NUMBER", "REF_COL_SEQ_NO", "REMARK_NO")
# words too small to show two remarks are about the same thing
REMARK_LITTLE_WORDS = {"A", "AN", "THE", "OF", "TO", "AND", "OR", "FOR", "IN", "ON", "AT", "BY",
                       "WITH", "IS", "ARE", "BE", "FM", "FROM", "ALL", "NO", "NOT", "IF", "WHEN"}

# declared distances (APT_RWY_END): column -> (plain English, standard abbreviation)
DECLARED_DISTANCES = {
    "TKOF_RUN_AVBL": ("takeoff run available", "TORA"),
    "TKOF_DIST_AVBL": ("takeoff distance available", "TODA"),
    "ACLT_STOP_DIST_AVBL": ("accelerate-stop distance available", "ASDA"),
    "LNDG_DIST_AVBL": ("landing distance available", "LDA"),
}
# a declared distance shrinking by this much changes performance planning -> action
DECLARED_ACTION_FT = 500
DECLARED_ACTION_PCT = 0.10


def base(fname):
    """'APT_RMK.csv' -> 'APT_RMK'"""
    return fname.upper().replace(".CSV", "")


def is_noise_col(c):
    """rounding / bookkeeping columns stripped from every change."""
    if c in HIDDEN_ONLY_COLS:
        return True
    c = c.upper()
    return (c.startswith(("LAT_", "LONG_", "MAG_VAR", "MAG_HEMIS")) or
            "_LAT_" in c or "_LONG_" in c or          # e.g. TACAN_DME_LAT_DECIMAL
            c.endswith("_CHART_FLAG") or
            # who surveyed it and when: RWY_LEN_SOURCE OWNER -> 3RD PARTY SURVEY, RWY_END_PSN_DATE,
            # COMPONENT_STATUS_DATE, SURVEY_METHOD_CODE
            c.endswith(("_DATE", "_SOURCE", "_SRC", "_METHOD_CODE")) or
            c in {"LEGACY_ELEMENT_NUMBER", "REF_COL_SEQ_NO", "SEQ", "ALT_CODE", "ELEV", "DME_SSV",
                  "SITE_ELEVATION", "INSPECTOR_CODE", "NASP_CODE"})


def blank_fill(c, old, new):
    """true if old -> new is only a blank written as NONE (or N on a *_FLAG column)."""
    blanks = BLANK_FLAG_VALUES if c.upper().endswith("_FLAG") else BLANK_VALUES
    return (old or "").strip().upper() in blanks and (new or "").strip().upper() in blanks


def phone_format(c, old, new):
    """true if a phone column only changed how the number is written: BVN (402) 741-1290 ->
    402-741-1290, Z52 907-283-4117. -> 907-283-4117 (2026-10-01, 8 contacts)."""
    if "PHONE" not in c.upper():
        return False
    digits = lambda v: re.sub(r"\D", "", v or "")
    return bool(digits(old)) and digits(old) == digits(new)


def rwy_id(v):
    """'9/27' -> '09/27', '9' -> '09', '9L/27R' -> '09L/27R'. every runway in NASR is written
    with two digits except four new ones in 2026-10-01 (58KY, IL97, MN46, 39MN '9/27'); unpadded,
    58KY's resurveyed 09/27 read as a new runway."""
    return re.sub(r"(?<![\dA-Z])(\d)(?=[LRCW]?(?:/|$))", r"0\1", v or "")


RWY_ID_COLS = ("RWY_ID", "RWY_END_ID")


def is_hours_col(c):
    """TWR_HRS, ATIS_HRS, AIRSPACE_HRS, RADAR_HRS, OPER_HOURS, APT_ATT HOUR..."""
    return bool(set(c.upper().split("_")) & {"HRS", "HOURS", "HOUR"})


def is_helipad(rwy_id):
    """'H1', 'H2A', 'HB', 'H-A', 'H': a helipad, not a runway (APT_RWY lists both). a runway is
    numbered or named for compass points (N/S, NE/SW), never H: SLC lists its 60 x 60 ft pads as
    HB and HF, NDZ as H-A to H-F, and 4 other fields letter theirs or call it H (2026-10-01)."""
    return bool(re.fullmatch(r"H(?:\d+[A-Z]?|-?[A-Z])?", rwy_id or ""))


def is_fyi_col(c):
    """columns that are worth showing but never change how you fly."""
    return c in NAME_COLS or c in FYI_ONLY_COLS or c.endswith("PHONE_NO")


def small_change(c, old, new):
    """'drop' (survey rounding), 'fyi' (small but real) or None for a numeric column change."""
    if c not in SMALL_CHANGE:
        return None
    try:
        d = abs(float(old) - float(new))
    except (TypeError, ValueError):
        return None
    drop, fyi = SMALL_CHANGE[c]
    return "drop" if d < drop else "fyi" if d < fyi else None