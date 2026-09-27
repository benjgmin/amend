"""
Every rule that decides what counts as a change, what's noise, and how important it is.
Tuning the output almost always means editing this file.
"""

# columns that change every cycle and are never real changes
IGNORE_COLS = {"EFF_DATE", "LAST_INFO_RESPONSE", "LAST_INFO_RESPONSE_DATE"}

# identity columns: hidden in summaries
ID_COLS = {"SITE_NO", "SITE_TYPE_CODE", "STATE_CODE", "CITY", "COUNTRY_CODE", "ARPT_ID"}

# columns that decide which airport a row belongs to, in order of preference.
# FRQ rows use SERVICED_FACILITY so "DAB approach serving NSB" goes to NSB, not DAB.
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
                     "PROHIBITED", "RSTD", "NOISE", "TRANSPONDER")

# a whole row appearing or disappearing in these files is act even though no column name or
# value says so: a runway, a decommissioned navaid, approach radar. other files' rows carry
# column names like NAV_ID or RADAR_HRS on every row, so column words only rank "changed" rows.
ROW_ACTION = {"APT_RWY": ("added", "removed"), "NAV_BASE": ("removed",), "RDR": ("added", "removed")}

# navaid/ILS remarks (unusable sectors, monitoring) matter to IFR flying: ifr, not act
IFR_REMARK_FILES = ("NAV_RMK", "ILS_RMK")

# numeric columns where a small change is survey rounding. (drop below, fyi below)
#   5801 -> 5800 ft runway, 1525.7 -> 1525.6 ft elevation, 40.01 -> 40 deg localizer bearing
SMALL_CHANGE = {"RWY_LEN": (10, 50), "RWY_WIDTH": (1, 10), "APCH_BEAR": (1, 1),
                "RWY_END_ELEV": (1, 1), "TDZ_ELEV": (1, 1), "ARPT_ELEV": (1, 1),
                "DISPLACED_THR_ELEV": (1, 1), "THR_CROSSING_HGT": (1, 1)}

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