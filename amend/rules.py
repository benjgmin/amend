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
}

# whole files that are noise or duplicate other files. skipped at load time.
#   PFR_SEG/PFR_BASE: routes already readable in PFR_RMT_FMT   LID: duplicate id list
#   FIX: fix definitions, not airport changes   CDR: airline coded departure routes
#   COM: duplicates the RCO/outlet info already in FRQ
HIDDEN_FILES = ("PFR_SEG", "PFR_BASE", "LID", "FIX", "CDR", "COM")

# changes that only touch these columns are hidden (stats, survey bookkeeping, pavement data)
HIDDEN_ONLY_COLS = {"AIR_TAXI_OPS", "ANNUAL_OPS_DATE", "BASED_GLIDERS", "BASED_HEL",
                    "BASED_JET_ENG", "BASED_MIL_ACFT", "BASED_MULTI_ENG", "BASED_SINGLE_ENG",
                    "BASED_ULTRALGT_ACFT", "COMMERCIAL_OPS", "COMMUTER_OPS", "ITNRNT_OPS",
                    "LOCAL_OPS", "MIL_ACFT_OPS", "LAST_INSPECTION", "LENGTH_SOURCE_DATE",
                    "PAVEMENT_CLASSIFICATION", "PCN_PCR_NUMBER", "PCN", "PAVEMENT_TYPE_CODE",
                    "SUBGRADE_STRENGTH_CODE", "TIRE_PRES_CODE", "DTRM_METHOD_CODE",
                    "GROSS_WT_SW", "GROSS_WT_DW", "GROSS_WT_DTW", "GROSS_WT_DDTW"}
NAME_COLS = {"FACILITY_NAME", "FAC_NAME", "SERVICED_FAC_NAME", "NAME", "ARPT_NAME"}
FYI_ONLY_COLS = {"OBSTN_HGT", "OBSTN_CLNC_SLOPE", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE",
                 "DIST_FROM_THR", "FREQ_USE", "RWY_MARKING_COND", "COND"}

ACTION_PREFIXES = ("ATC", "CLS_ARSP", "FRQ", "ILS", "APT_ATT", "AWOS")
ACTION_COL_WORDS = {"NAV", "PROVIDER", "HRS", "HOURS", "FREQ", "CLASS", "AIRSPACE", "CLOSED",
                    "STATUS", "LGT", "LIGHT", "LIGHTS", "LEN", "WIDTH", "TPA", "ATTEND"}
ACTION_TEXT_WORDS = ("CLSD", "CLOSED", "TWR", "PPR", "NOT AVBL", "UNAVBL", "CTAF", "TPA",
                     "PROHIBITED", "RSTD", "NOISE", "TRANSPONDER")

# columns kept on a changed record so the summary can describe it ("runway 15: ...")
CONTEXT_COLS = ("Orig", "Dest", "Route String", "FREQ", "FREQ_USE", "NAV_ID", "NAV_TYPE",
                "RWY_ID", "RWY_END_ID", "ELEMENT", "SERVICED_FACILITY", "REMARK",
                "STAR_COMPUTER_CODE", "DP_COMPUTER_CODE", "NAME", "OBSTN_HGT", "DIST_FROM_THR",
                "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE", "OBSTN_TYPE")

NAV_NAMES = {"VOT": "VOR test signal (VOT)", "VORTAC": "VORTAC", "VOR/DME": "VOR/DME",
             "DME": "DME", "NDB": "NDB", "VOR": "VOR", "TACAN": "TACAN"}

REMARK_FILES = ("APT_RMK", "ATC_RMK")

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
    return (c.startswith(("LAT_", "LONG_", "MAG_VARN")) or
            c.endswith(("SRC_DATE", "SOURCE_DATE")) or
            c in {"LEGACY_ELEMENT_NUMBER", "REF_COL_SEQ_NO", "SEQ", "ALT_CODE", "ELEV", "DME_SSV"})