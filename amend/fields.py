"""
What each FAA column is called in English, and what its codes mean.

Every name and code meaning here comes from the FAA's own data layouts (the "<FILE> DATA
LAYOUT.pdf" in every NASR CSV zip: APT, ATC, AWOS, CLS_ARSP, FRQ, ILS, MIL_OPS, NAV, PJA, RDR),
lowercased, never guessed. A code the layout doesn't define is shown exactly as the FAA wrote
it. A column with no name here shows as the FAA wrote it ("NEW_COL: N -> Y") and keeps its
rank; the pipeline counts it in result["checks"]["no_english"] (and the run log), and the
tests fail on any real cycle or zip header that has one.
"""
from .rules import base

YES_NO = {"Y": "yes", "N": "no"}
REGIONS = {"AAL": "Alaska", "ACE": "Central", "AEA": "Eastern", "AGL": "Great Lakes",
           "ANE": "New England", "ANM": "Northwest Mountain", "ASO": "Southern",
           "ASW": "Southwest", "AWP": "Western-Pacific"}
SITE_TYPES = {"A": "airport", "B": "balloonport", "C": "seaplane base", "G": "gliderport",
              "H": "heliport", "U": "ultralight", "V": "vertiport"}
# ATC_BASE FACILITY_TYPE, APT_BASE TWR_TYPE_CODE
FACILITY_TYPES = {
    "ATCT": "air traffic control tower",
    "NON-ATCT": "no air traffic control tower",
    "ATCT-A/C": "tower plus approach control",
    "ATCT-RAPCON": "tower plus radar approach control (Air Force operates ATCT, FAA operates approach control)",
    "ATCT-RATCF": "tower plus radar approach control (Navy operates ATCT, FAA operates approach control)",
    "ATCT-TRACON": "tower plus terminal radar approach control",
    "TRACON": "consolidated TRACON",
    "ARTCC": "air route traffic control center",
    "CERAP": "center radar approach control facility",
}
# ATC_BASE {APCH,DEP}_{P,S}_PROV_TYPE_CD
PROVIDER_TYPES = {"A": "airport with ATCT", "C": "ARTCC", "S": "special", "T": "TRACON"}
AGENCIES = {"A": "U.S. Air Force", "C": "U.S. Coast Guard", "F": "Federal Aviation Admin", "N": "U.S. Navy",
            "R": "U.S. Army"}
TOWER_OPERATORS = {**AGENCIES, "CITY": "city", "COUNTY": "county",
                   "D": "Canadian Ministry of Transport",
                   "FCT": "FAA contract tower", "G": "federal gov't, not U.S.A.",
                   "NFCT": "non-federal control tower", "O": "other", "P": "private",
                   "W": "U.S. Weather Service", "X": "Royal Canadian Air Force", "Z": "unknown"}
FUEL = {"100": "grade 100 gasoline (green)", "100LL": "100LL gasoline (low lead) (blue)",
        "100R": "unleaded grade 100 gasoline", "A": "Jet A, kerosene, without FS-II",
        "A+": "Jet A, kerosene, with FS-II", "A++": "Jet A, kerosene, with FS-II, CI/LI, SDA",
        "A++10": "Jet A, kerosene, with FS-II, CI/LI, SDA, with +100 fuel additive",
        "A1": "Jet A-1, kerosene, without FS-II", "A1+": "Jet A-1, kerosene, with FS-II",
        "G100UL": "unleaded grade 100 gasoline", "H": "hydrogen",
        "J5": "JP-5 military specification", "J8": "JP-8 military specification",
        "J8+10": "JP-8 military specification, with +100 fuel additive",
        "J": "jet fuel type unknown", "MOGAS": "automobile gasoline",
        "UL91": "unleaded grade 91 gasoline", "UL94": "unleaded grade 94 gasoline",
        "UL100": "unleaded grade 100 gasoline"}
SERVICES = {"AFRT": "air freight services", "AGRI": "crop dusting services",
            "AMB": "air ambulance services", "AVNCS": "avionics", "BCHGR": "beaching gear",
            "CARGO": "cargo handling services", "CHTR": "charter service", "GLD": "glider service",
            "INSTR": "pilot instruction", "PAJA": "parachute jump activity",
            "RNTL": "aircraft rental", "SALES": "aircraft sales", "SURV": "annual surveying",
            "TOW": "glider towing services"}
SURFACES = {"CONC": "portland cement concrete", "ASPH": "asphalt or bituminous concrete",
            "SNOW": "snow", "ICE": "ice", "MATS": "pierced steel planking; landing mats; membranes",
            "TREATED": "oiled; soil cement or lime stabilized",
            "GRAVEL": "gravel; cinders; crushed rock; coral or shells; slag", "TURF": "grass; sod",
            "DIRT": "natural soil", "PEM": "partially concrete, asphalt or bitumen-bound macadam",
            "ROOF-TOP": "roof-top", "WATER": "water"}
VGSI = {"S2L": "2-box SAVASI on left side of runway", "S2R": "2-box SAVASI on right side of runway",
        "V2L": "2-box VASI on left side of runway", "V2R": "2-box VASI on right side of runway",
        "V4L": "4-box VASI on left side of runway", "V4R": "4-box VASI on right side of runway",
        "V6L": "6-box VASI on left side of runway", "V6R": "6-box VASI on right side of runway",
        "V12": "12-box VASI on both sides of runway", "V16": "16-box VASI on both sides of runway",
        "P2L": "2-light PAPI on left side of runway", "P2R": "2-light PAPI on right side of runway",
        "P4L": "4-light PAPI on left side of runway", "P4R": "4-light PAPI on right side of runway",
        "NSTD": "nonstandard VASI system",
        "PVT": "privately owned approach slope indicator light system on a public use airport "
               "that is intended for private use only",
        "VAS": "non-specific VASI system", "NONE": "no approach slope light system",
        "N": "no approach slope light system", "TRIL": "tri-color VASI on left side of runway",
        "TRIR": "tri-color VASI on right side of runway",
        "PSIL": "pulsating/steady burning VASI on left side of runway",
        "PSIR": "pulsating/steady burning VASI on right side of runway",
        "PNIL": "system of panels on left side of runway that may or may not be lighted",
        "PNIR": "system of panels on right side of runway that may or may not be lighted"}
APPROACH_LIGHTS = {
    "AFOVRN": "Air Force overrun 1000-foot standard approach lighting system",
    "ALSAF": "3,000 foot high intensity approach lighting system with centerline sequence flashers",
    "ALSF1": "standard 2,400 foot high intensity approach lighting system with sequenced "
             "flashers, category I configuration",
    "ALSF2": "standard 2,400 foot high intensity approach lighting system with sequenced "
             "flashers, category II or III configuration",
    "MALS": "1,400 foot medium intensity approach lighting system",
    "MALSF": "1,400 foot medium intensity approach lighting system with sequenced flashers",
    "MALSR": "1,400 foot medium intensity approach lighting system with runway alignment "
             "indicator lights",
    "RAIL": "runway alignment indicator lights", "SALS": "short approach lighting system",
    "SALSF": "short approach lighting system with sequence flashing lights",
    "SSALS": "simplified short approach lighting system",
    "SSALF": "simplified short approach lighting system with sequenced flashers",
    "SSALR": "simplified short approach lighting system with runway alignment indicator lights",
    "ODALS": "omnidirectional approach lighting system", "RLLS": "runway lead-in light system",
    "MIL OVRN": "military overrun", "NSTD": "all others",
    "NONE": "no approach lighting is available"}
ILS_TYPES = {"ILS": "instrument landing system", "MLS": "microwave landing system",
             "SDF": "simplified directional facility", "LOCALIZER": "localizer",
             "LDA": "localizer-type directional aid",
             "ISMLS": "interim standard microwave landing system",
             "ILS/DME": "instrument landing system/distance measuring equipment",
             "SDF/DME": "simplified directional facility distance measuring equipment",
             "LOC/DME": "localizer/distance measuring equipment", "LOC/GS": "localizer/glide slope",
             "LDA/DME": "localizer-type directional aid distance measuring equipment"}
ILS_SYSTEM_TYPES = {"LS": "ILS", "SF": "SDF", "LC": "LOC", "LA": "LDA", "LD": "ILS/DME",
                    "SD": "SDF/DME", "LE": "LOC/DME", "LG": "LOC/GS", "DD": "LDA/DME"}
MARKINGS = {"PIR": "precision instrument", "NPI": "nonprecision instrument", "BSC": "basic",
            "NRS": "numbers only", "NSTD": "nonstandard (other than numbers only)",
            "BUOY": "buoys (seaplane base)", "STOL": "short takeoff and landing", "NONE": "none"}
PART_77 = {"A(V)": "utility runway with a visual approach",
           "B(V)": "other than utility runway with a visual approach",
           "A(NP)": "utility runway with a nonprecision approach",
           "C": "other than utility runway with a nonprecision approach having visibility "
                "minimums greater than 3/4 mile",
           "D": "other than utility runway with a nonprecision approach having visibility "
                "minimums as low as 3/4 mile",
           "PIR": "precision instrument runway"}
RVR = {"T": "touchdown", "M": "midfield", "R": "rollout", "N": "no RVR available"}
EDGE_LIGHTS = {"HIGH": "high", "MED": "medium", "LOW": "low", "FLD": "flood",
               "NSTD": "non-standard lighting system", "PERI": "perimeter", "STRB": "strobe",
               "NONE": "no edge lighting system"}
TREATMENTS = {"GRVD": "saw-cut or plastic grooved", "PFC": "porous friction course",
              "AFSC": "aggregate friction seal coat", "RFSC": "rubberized friction seal coat",
              "WC": "wire comb or wire tine", "NONE": "no special surface treatment"}
BEACONS = {"WG": "white-green (lighted land airport)", "WY": "white-yellow (lighted seaplane base)",
           "WGY": "white-green-yellow (heliport)", "SWG": "split-white-green (lighted military airport)",
           "W": "white (unlighted land airport)", "Y": "yellow (unlighted seaplane base)",
           "G": "green (lighted land airport)", "N": "none"}
RADAR_TYPES = {"ARSR": "air route surveillance radar", "ASR": "airport surveillance radar",
               "ASR/PAR": "airport surveillance radar plus precision approach radar",
               "GCA": "ground control approach", "PAR": "precision approach radar",
               "SECRA": "secondary radar"}
MONITORING = {
    "1": "internal monitoring plus a status indicator installed at control point",
    "2": "internal monitoring with status indicator at control point inoperative but pilot "
         "reports indicate facility is operating normally",
    "3": "internal monitoring only, status indicator not installed at control point",
    "4": "internal monitor not installed, remote status indicator provided at control point"}
REPAIR = {"MAJOR": "major", "MINOR": "minor", "NONE": "none"}
OXYGEN = {"HIGH": "high", "LOW": "low", "HIGH/LOW": "high/low", "NONE": "none"}
SCHEDULE = {"SS-SR": "sunset-sunrise", "SEE RMK": "see remarks"}

# column -> (English name, how its values read). a value reading is a dict of FAA codes, "list"
# for a comma list of codes (what came and went is said, not the whole list), or None for
# values shown as the FAA wrote them. units come from the layout's field description.
F = {
    # common
    "CITY": ("associated city", None), "SITE_NO": ("FAA site number", None),
    "STATE_CODE": ("state", None), "COUNTRY_CODE": ("country", None),
    "ARPT_ID": ("airport identifier", None),
    "MAG_VARN": ("magnetic variation", "°"), "MAG_VARN_HEMIS": ("magnetic variation direction", None),
    "MAG_HEMIS": ("magnetic variation direction", None), "MAG_VAR": ("magnetic variation", "°"),
    "MAG_VARN_YEAR": ("magnetic variation epoch year", None),
    "REGION_CODE": ("FAA region", REGIONS), "STATE_NAME": ("state", None),
    "COUNTRY_NAME": ("country", None), "ICAO_ID": ("ICAO identifier", None),
    "SITE_TYPE_CODE": ("facility type", SITE_TYPES), "REMARK": ("remark", None),
    "TAB_NAME": ("remark table", None), "REF_COL_NAME": ("remark subject", None),
    "ELEMENT": ("remark element", None), "REMARK_NO": ("remark number", None),
    # APT_BASE
    "ADO_CODE": ("FAA district office", None), "COUNTY_NAME": ("county", None),
    "COUNTY_ASSOC_STATE": ("county's state", None),
    "OWNERSHIP_TYPE_CODE": ("ownership", {"PU": "publicly owned", "PR": "privately owned",
                                          "MA": "Air Force owned", "MN": "Navy owned",
                                          "MR": "Army owned", "CG": "Coast Guard owned"}),
    "FACILITY_USE_CODE": ("use", {"PU": "open to the public", "PR": "private"}),
    "TPA": ("traffic pattern altitude", "ft AGL"),
    "CHART_NAME": ("sectional chart", None),
    "DIST_CITY_TO_AIRPORT": ("distance from the city's business district", None),
    "DIRECTION_CODE": ("direction from the city's business district", None),
    "ACREAGE": ("land area", "acres"),
    "RESP_ARTCC_ID": ("responsible ARTCC", None), "COMPUTER_ID": ("ARTCC computer identifier", None),
    "ARTCC_NAME": ("responsible ARTCC name", None),
    "FSS_ON_ARPT_FLAG": ("tie-in FSS on the airport", YES_NO),
    "TOLL_FREE_NO": ("FSS toll-free briefing number", None),
    "ALT_FSS_ID": ("alternate FSS", None), "ALT_FSS_NAME": ("alternate FSS name", None),
    "ALT_TOLL_FREE_NO": ("alternate FSS toll-free number", None),
    "NOTAM_FLAG": ("NOTAM D service", YES_NO),
    "ARPT_STATUS": ("airport status", {"CI": "closed indefinitely", "CP": "closed permanently",
                                       "O": "operational"}),
    "FAR_139_TYPE_CODE": ("Part 139 ARFF certification", None),
    "FAR_139_CARRIER_SER_CODE": ("Part 139 carrier service",
                                 {"S": "receives scheduled air carrier service",
                                  "U": "no scheduled air carrier service"}),
    "ASP_ANLYS_DTRM_CODE": ("airspace analysis determination",
                            {"CONDL": "conditional", "NOT ANALYZED": "not analyzed",
                             "NO OBJECTION": "no objection", "OBJECTIONABLE": "objectionable"}),
    "CUST_FLAG": ("customs airport of entry", YES_NO),
    "LNDG_RIGHTS_FLAG": ("customs landing rights airport", YES_NO),
    "JOINT_USE_FLAG": ("military/civil joint use", YES_NO),
    "MIL_LNDG_FLAG": ("military landing rights", YES_NO),
    "INSPECT_METHOD_CODE": ("inspection method", {"F": "federal", "S": "state", "C": "contractor",
                                                  "1": "5010-1 public use mailout program",
                                                  "2": "5010-2 private use mailout program"}),
    "FUEL_TYPES": ("fuel", ("list", FUEL)), "OTHER_SERVICES": ("services", ("list", SERVICES)),
    "AIRFRAME_REPAIR_SER_CODE": ("airframe repair", REPAIR),
    "PWR_PLANT_REPAIR_SER": ("engine repair", REPAIR),
    "BOTTLED_OXY_TYPE": ("bottled oxygen", OXYGEN), "BULK_OXY_TYPE": ("bulk oxygen", OXYGEN),
    "LGT_SKED": ("airport lighting schedule", SCHEDULE),
    "BCN_LGT_SKED": ("beacon schedule", SCHEDULE),
    "TWR_TYPE_CODE": ("tower type", FACILITY_TYPES),
    "SEG_CIRCLE_MKR_FLAG": ("segmented circle", {"Y": "yes", "N": "no", "NONE": "none",
                                                 "Y-L": "yes, lighted"}),
    "BCN_LENS_COLOR": ("beacon", BEACONS),
    "MEDICAL_USE_FLAG": ("used for medical purposes", YES_NO),
    "CONTR_FUEL_AVBL": ("contract fuel", YES_NO),
    "TRNS_STRG_BUOY_FLAG": ("transient buoy storage", YES_NO),
    "TRNS_STRG_HGR_FLAG": ("transient hangar storage", YES_NO),
    "TRNS_STRG_TIE_FLAG": ("transient tie-down storage", YES_NO),
    "WIND_INDCR_FLAG": ("wind indicator", {"N": "no wind indicator",
                                           "Y": "unlighted wind indicator",
                                           "Y-L": "lighted wind indicator"}),
    "MIN_OP_NETWORK": ("minimum operational network (MON)", YES_NO),
    "USER_FEE_FLAG": ("customs user fee airport", None),
    "CTA": ("cold temperature airport (altitude correction at or below)", None),
    # APT_ATT (old history kept these rows one by one)
    "MONTH": ("attended months", None), "DAY": ("attended days", None),
    "HOUR": ("attended hours", None), "SKED_SEQ_NO": ("attendance schedule number", None),
    # APT_CON (read with the contact's title: "airport manager address")
    "TITLE": ("title", None), "ADDRESS1": ("address", None), "ADDRESS2": ("address line 2", None),
    "TITLE_CITY": ("city", None), "STATE": ("state", None), "ZIP_CODE": ("zip code", None),
    "ZIP_PLUS_FOUR": ("zip+4", None),
    # APT_RWY
    "RWY_ID": ("runway", None), "RWY_LEN": ("length", "ft"), "RWY_WIDTH": ("width", "ft"),
    "SURFACE_TYPE_CODE": ("surface", SURFACES), "TREATMENT_CODE": ("surface treatment", TREATMENTS),
    "RWY_LGT_CODE": ("edge light intensity", EDGE_LIGHTS),
    # APT_RWY_END
    "RWY_END_ID": ("runway end", None), "TRUE_ALIGNMENT": ("true alignment", "°"),
    "ILS_TYPE": ("instrument landing system", ILS_TYPES),
    "RIGHT_HAND_TRAFFIC_PAT_FLAG": ("right-hand traffic pattern", YES_NO),
    "RWY_MARKING_TYPE_CODE": ("markings", MARKINGS),
    "RWY_END_ELEV": ("runway end elevation", "ft MSL"),
    "THR_CROSSING_HGT": ("threshold crossing height", "ft AGL"),
    "VISUAL_GLIDE_PATH_ANGLE": ("visual glide path angle", "°"),
    "DISPLACED_THR_ELEV": ("displaced threshold elevation", "ft MSL"),
    "DISPLACED_THR_LEN": ("displaced threshold", "ft"),
    "TDZ_ELEV": ("touchdown zone elevation", "ft MSL"),
    "VGSI_CODE": ("visual glide slope indicator", VGSI),
    "RWY_VISUAL_RANGE_EQUIP_CODE": ("RVR equipment", ("letters", RVR)),
    "RWY_VSBY_VALUE_EQUIP_FLAG": ("RVV equipment", YES_NO),
    "APCH_LGT_SYSTEM_CODE": ("approach lights", APPROACH_LIGHTS),
    "RWY_END_LGTS_FLAG": ("runway end identifier lights (REIL)", YES_NO),
    "CNTRLN_LGTS_AVBL_FLAG": ("centerline lights", YES_NO),
    "TDZ_LGT_AVBL_FLAG": ("touchdown zone lights", YES_NO),
    "OBSTN_TYPE": ("controlling obstacle", None),
    "OBSTN_MRKD_CODE": ("controlling obstacle marking", {"M": "marked", "L": "lighted",
                                                         "ML": "marked and lighted",
                                                         "NONE": "none"}),
    "FAR_PART_77_CODE": ("Part 77 runway category", PART_77),
    "RWY_GRAD": ("gradient", None), "RWY_GRAD_DIRECTION": ("gradient direction", None),
    "LAHSO_ALD": ("LAHSO available landing distance", "ft"),
    "RWY_END_INTERSECT_LAHSO": ("LAHSO hold-short runway", None),
    "LAHSO_LAT": ("LAHSO hold-short point latitude", None),
    "LAHSO_LONG": ("LAHSO hold-short point longitude", None),
    "LAHSO_DESC": ("LAHSO hold-short point", None),
    # APT_ARS
    "ARREST_DEVICE_CODE": ("arresting system", None),
    # ATC_BASE
    "FACILITY_ID": ("facility", None), "FACILITY_TYPE": ("facility type", FACILITY_TYPES),
    "TWR_OPERATOR_CODE": ("tower operator", TOWER_OPERATORS), "TWR_CALL": ("tower radio call", None),
    "CTL_FAC_APCH_DEP_CALLS": ("control facility approach/departure call", None),
    "APCH_DEP_OPER_CODE": ("control facility operator", {k: AGENCIES[k] for k in "AFNR"}),
    "CTL_PRVDING_HRS": ("primary control facility hours", None),
    "SECONDARY_CTL_PRVDING_HRS": ("secondary control facility hours", None),
    # ATC_ATIS, ATC_SVC
    "ATIS_NO": ("ATIS number", None), "ATIS_HRS": ("ATIS hours", None),
    "ATIS_PHONE_NO": ("ATIS phone number", None), "CTL_SVC": ("ATC service", None),
    # AWOS
    "ASOS_AWOS_ID": ("weather station", None), "ASOS_AWOS_TYPE": ("weather station type", None),
    "NAVAID_FLAG": ("weather broadcast on a navaid", YES_NO),
    "SECOND_PHONE_NO": ("weather station second phone number", None),
    # CLS_ARSP: 'Y', else null
    "CLASS_B_AIRSPACE": ("class B airspace", {"Y": "yes", "": "no"}),
    "CLASS_C_AIRSPACE": ("class C airspace", {"Y": "yes", "": "no"}),
    "CLASS_D_AIRSPACE": ("class D airspace", {"Y": "yes", "": "no"}),
    "CLASS_E_AIRSPACE": ("class E airspace", {"Y": "yes", "": "no"}),
    # FRQ
    "ARTCC_OR_FSS_ID": ("ARTCC/FSS", None), "CPDLC": ("CPDLC", None),
    "SERVICED_FACILITY": ("served facility", None),
    "SERVICED_SITE_TYPE": ("served facility type", None),
    "SERVICED_CITY": ("served facility city", None),
    "SERVICED_STATE": ("served facility state", None),
    "SERVICED_COUNTRY": ("served facility country", None),
    "TOWER_OR_COMM_CALL": ("radio call", None),
    "PRIMARY_APPROACH_RADIO_CALL": ("approach control radio call", None),
    "SECTORIZATION": ("sector", None),
    # ILS
    "ILS_LOC_ID": ("ILS identifier", None), "SYSTEM_TYPE_CODE": ("ILS type", ILS_SYSTEM_TYPES),
    "CATEGORY": ("ILS category", None), "OWNER": ("owner", None), "OPERATOR": ("operator", None),
    "APCH_BEAR": ("approach bearing", "° magnetic"), "LOC_FREQ": ("localizer frequency", None),
    "BK_COURSE_STATUS_CODE": ("back course", {"N": "no restrictions", "R": "restricted",
                                              "U": "unusable", "Y": "usable"}),
    "G_S_TYPE_CODE": ("glideslope type", None), "G_S_ANGLE": ("glideslope angle", "°"),
    "G_S_FREQ": ("glideslope frequency", None), "CHANNEL": ("DME channel", None),
    "ILS_COMP_TYPE_CODE": ("marker", {"IM": "inner marker", "MM": "middle marker",
                                      "OM": "outer marker"}),
    "MKR_FAC_TYPE_CODE": ("marker facility type", {"M": "marker beacon only",
                                                   "C": "compass locator",
                                                   "R": "nondirectional radio beacon",
                                                   "MC": "marker/compass locator",
                                                   "MR": "marker/nondirectional radio beacon"}),
    "MARKER_ID_BEACON": ("marker beacon identifier", None),
    "COMPASS_LOCATOR_NAME": ("compass locator name", None),
    "LOW_POWERED_NDB_STATUS": ("low powered NDB status", None),
    # MIL_OPS
    "MIL_OPS_OPER_CODE": ("military operator", AGENCIES),
    "MIL_OPS_CALL": ("military operations radio call", None),
    "MIL_OPS_HRS": ("military operations hours", None),
    "AMCP_HRS": ("military command post (AMCP) hours", None),
    "PMSV_HRS": ("pilot-to-metro service (PMSV) hours", None),
    # NAV_BASE
    "NAV_ID": ("navaid", None), "NAV_STATUS": ("status", None),
    "FAN_MARKER": ("fan marker name", None),
    "NAS_USE_FLAG": ("common system usage", YES_NO), "PUBLIC_USE_FLAG": ("public use", YES_NO),
    "NDB_CLASS_CODE": ("NDB class", None), "OPER_HOURS": ("hours", None),
    "HIGH_ALT_ARTCC_ID": ("high altitude ARTCC", None), "HIGH_ARTCC_NAME": ("high altitude ARTCC name", None),
    "LOW_ALT_ARTCC_ID": ("low altitude ARTCC", None), "LOW_ARTCC_NAME": ("low altitude ARTCC name", None),
    "SIMUL_VOICE_FLAG": ("simultaneous voice", YES_NO), "PWR_OUTPUT": ("power output", "watts"),
    "AUTO_VOICE_ID_FLAG": ("automatic voice identification", YES_NO),
    "MNT_CAT_CODE": ("monitoring category", MONITORING), "VOICE_CALL": ("voice call", None),
    "CHAN": ("TACAN channel", None), "MKR_IDENT": ("marker identifier", None),
    "MKR_SHAPE": ("fan marker type", {"E": "elliptical"}), "MKR_BRG": ("fan marker bearing", "° true"),
    "Z_MKR_FLAG": ("Z marker", YES_NO),
    "SURVEY_ACCURACY_CODE": ("latitude/longitude survey accuracy",
                             {"0": "unknown", "1": "degree", "2": "10 minutes", "3": "1 minute",
                              "4": "10 seconds", "5": "1 second or better", "6": "NOS",
                              "7": "3rd order triangulation"}),
    "FSS_ID": ("FSS", None), "FSS_NAME": ("FSS name", None), "FSS_HOURS": ("FSS hours", None),
    "NOTAM_ID": ("NOTAM accountability", None), "QUAD_IDENT": ("quadrant identification", None),
    "PITCH_FLAG": ("pitch flag", YES_NO), "CATCH_FLAG": ("catch flag", YES_NO),
    "SUA_ATCAA_FLAG": ("SUA/ATCAA flag", YES_NO), "RESTRICTION_FLAG": ("restriction flag", YES_NO),
    "HIWAS_FLAG": ("HIWAS", YES_NO),
    # NAV_CKPT
    "ALTITUDE": ("checkpoint altitude", "ft"), "BRG": ("checkpoint bearing", "°"),
    "AIR_GND_CODE": ("checkpoint type", {"A": "air", "G": "ground", "G1": "ground one"}),
    "CHK_DESC": ("checkpoint description", None), "STATE_CHK_CODE": ("checkpoint state", None),
    # PJA
    "PJA_ID": ("jump area", None), "LATITUDE": ("latitude", None), "LONGITUDE": ("longitude", None), "RADIAL": ("radial from the navaid", "°"),
    "DISTANCE": ("distance from the navaid", "NM"), "NAVAID_NAME": ("navaid name", None),
    "DROP_ZONE_NAME": ("drop zone name", None), "MAX_ALTITUDE": ("maximum altitude", "ft"),
    "MAX_ALTITUDE_TYPE_CODE": ("maximum altitude type", None), "PJA_RADIUS": ("radius", "NM"),
    "CHART_REQUEST_FLAG": ("sectional charting required", YES_NO),
    "PUBLISH_CRITERIA": ("published in the chart supplement", YES_NO),
    "DESCRIPTION": ("description", None), "TIME_OF_USE": ("times of use", None),
    "PJA_USE": ("use", None), "VOLUME": ("area volume", None), "PJA_USER": ("user group", None),
    "FAC_ID": ("contact facility", None), "LOC_ID": ("related location", None),
    "COMMERCIAL_FREQ": ("commercial frequency", None), "MIL_FREQ": ("military frequency", None),
    "SECTOR": ("sector", None), "CONTACT_FREQ_ALTITUDE": ("contact altitude", None),
    # RDR
    "RADAR_TYPE": ("radar type", RADAR_TYPES), "RADAR_NO": ("radar number", None),
    "RADAR_HRS": ("radar hours", None),
}

for _side, _ps, _role in (("APCH", "P", "approach control"), ("APCH", "S", "secondary approach control"),
                          ("DEP", "P", "departure control"), ("DEP", "S", "secondary departure control")):
    _call = f"{'PRIMARY' if _ps == 'P' else 'SECONDARY'}_{_side}_RADIO_CALL"
    F[_call] = (f"{_role} radio call", None)
    F[f"{_side}_{_ps}_PROVIDER"] = (f"{_role} provider", None)
    F[f"{_side}_{_ps}_PROV_TYPE_CD"] = (f"{_role} provider type", PROVIDER_TYPES)

# columns english.field_phrases words itself (tower hours, frequencies, obstacles, names ...)
F.update({
    "TWR_HRS": ("tower hours", None), "TOWER_HRS": ("tower hours", None),
    "AIRSPACE_HRS": ("airspace hours", None), "PHONE_NO": ("phone number", None),
    "NAV_TYPE": ("navaid type", None), "FREQ": ("frequency", None),
    "FACILITY": ("frequency provided by", None), "LNDG_FEE_FLAG": ("landing fee", YES_NO),
    "FREQ_USE": ("frequency use", None), "RWY_MARKING_COND": ("marking condition", None),
    "COND": ("pavement condition", None), "TACAN_DME_STATUS": ("TACAN/DME status", None),
    "OBSTN_HGT": ("controlling obstacle height", "ft AGL"),
    "DIST_FROM_THR": ("controlling obstacle distance from runway end", "ft"),
    "CNTRLN_OFFSET": ("controlling obstacle centerline offset", "ft"),
    "CNTRLN_DIR_CODE": ("controlling obstacle side of centerline", None),
    "OBSTN_CLNC_SLOPE": ("controlling obstacle clearance slope", None),
    "TKOF_RUN_AVBL": ("takeoff run available (TORA)", "ft"),
    "TKOF_DIST_AVBL": ("takeoff distance available (TODA)", "ft"),
    "ACLT_STOP_DIST_AVBL": ("accelerate-stop distance available (ASDA)", "ft"),
    "LNDG_DIST_AVBL": ("landing distance available (LDA)", "ft"),
    "FACILITY_NAME": ("facility name", None), "FAC_NAME": ("facility name", None),
    "SERVICED_FAC_NAME": ("served facility name", None), "NAME": ("name", None),
    "ARPT_NAME": ("airport name", None), "ATTENDANCE": ("airport attendance", None),
})

# the same column name meaning something else in one file
BY_FILE = {
    ("ATC_ATIS", "DESCRIPTION"): ("ATIS purpose", None),
    ("ILS_BASE", "COMPONENT_STATUS"): ("localizer status", None),
    ("ILS_GS", "COMPONENT_STATUS"): ("glideslope status", None),
    ("ILS_DME", "COMPONENT_STATUS"): ("DME status", None),
    ("ILS_MKR", "COMPONENT_STATUS"): ("marker status", None),
    ("ILS_BASE", "RWY_LEN"): ("ILS runway length", "ft"),
    ("ILS_BASE", "RWY_WIDTH"): ("ILS runway width", "ft"),
    ("ILS_MKR", "NAV_ID"): ("collocated navaid", None),
    ("ILS_MKR", "FREQ"): ("marker frequency", None),
    ("PJA_BASE", "NAV_ID"): ("navaid", None),
    ("PJA_BASE", "FSS_ID"): ("FSS", None),
    ("APT_BASE", "FSS_ID"): ("tie-in FSS", None), ("APT_BASE", "FSS_NAME"): ("tie-in FSS name", None),
    ("APT_BASE", "NOTAM_ID"): ("NOTAM facility", None),
    ("NAV_BASE", "FSS_ID"): ("controlling FSS", None),
    ("NAV_BASE", "FSS_NAME"): ("controlling FSS name", None),
    ("NAV_BASE", "FSS_HOURS"): ("controlling FSS hours", None),
    ("RDR", "FACILITY_TYPE"): ("radar facility type", None),
    ("FRQ", "FACILITY_TYPE"): ("facility type", FACILITY_TYPES),
}


def spec(col, source):
    return BY_FILE.get((base(source), col)) or F.get(col)


def known(col, source):
    return spec(col, source) is not None


def name(col, source):
    s = spec(col, source)
    return s[0] if s else col       # not in the layouts we read: the FAA column as written


def _code(codes, v):
    """'ARTCC (C)'; a code the FAA layout doesn't define stays as written."""
    m = codes.get(v)
    if m is None:
        return v
    return m if m.upper() == v.upper() or v in ("", "Y", "N") else f"{m} ({v})"


def say(col, source, v):
    """one FAA value as a pilot reads it."""
    s = spec(col, source)
    how = s[1] if s else None
    v = (v or "").strip()
    if isinstance(how, dict) and v in how:
        return _code(how, v)
    if not v:
        return "none"
    if isinstance(how, dict):
        if col == "SURFACE_TYPE_CODE" and "-" in v and all(p in how for p in v.split("-")):
            return f"{' / '.join(how[p] for p in v.split('-'))} ({v})"
        return v
    if isinstance(how, tuple) and how[0] == "list":
        return ", ".join(_code(how[1], p.strip()) for p in v.split(",") if p.strip())
    if isinstance(how, tuple) and how[0] == "letters":
        if all(ch in how[1] for ch in v):
            return f"{', '.join(how[1][ch] for ch in v)} ({v})"
        return v
    if isinstance(how, str):
        return f"{v}{'' if how.startswith('°') else ' '}{how}"
    return v


def phrase(col, source, old, new, who=""):
    """'approach lights: none -> MALSR (1,400 foot ...)'. a comma list says what came and went."""
    s = spec(col, source)
    label = f"{who}{name(col, source)}"
    if s and isinstance(s[1], tuple) and s[1][0] == "list":
        o = [p.strip() for p in (old or "").split(",") if p.strip()]
        n = [p.strip() for p in (new or "").split(",") if p.strip()]
        added = [_code(s[1][1], p) for p in n if p not in o]
        dropped = [_code(s[1][1], p) for p in o if p not in n]
        bits = ([f"added {', '.join(added)}"] if added else []) + \
               ([f"dropped {', '.join(dropped)}"] if dropped else [])
        if bits:
            return f"{label}: {'; '.join(bits)}"
    unit = s[1] if s and isinstance(s[1], str) else ""
    if unit and old and new:     # 'width: 100 -> 75 ft', the way the FAA values read side by side
        return f"{label}: {old.strip()} -> {say(col, source, new)}"
    return f"{label}: {say(col, source, old)} -> {say(col, source, new)}"


# approach and departure control on an ATC_BASE row: who you call, who provides it, what it is
CONTROL_ROLES = (("APCH", "P", "approach control"), ("APCH", "S", "secondary approach control"),
                 ("DEP", "P", "departure control"), ("DEP", "S", "secondary departure control"))


def control_cols(side, ps):
    order = "PRIMARY" if ps == "P" else "SECONDARY"
    return f"{order}_{side}_RADIO_CALL", f"{side}_{ps}_PROVIDER", f"{side}_{ps}_PROV_TYPE_CD"


CONTROL_COLS = {c for side, ps, _ in CONTROL_ROLES for c in control_cols(side, ps)}


def control_phrases(by):
    """'approach/departure control: none -> ZAN (ARTCC)' from the changed ATC_BASE columns.
    approach and departure changing the same way read as one line."""
    said = []
    for side, ps, role in CONTROL_ROLES:
        cols = control_cols(side, ps)
        if not any(c in by for c in cols):
            continue

        def desc(which):
            call, prov, typ = (by[c][which] if c in by else "" for c in cols)
            typ = PROVIDER_TYPES.get(typ, typ)
            if typ and call and typ.upper() in call.upper().split():
                typ = ""                    # 'ANCHORAGE ARTCC' says it already
            main = call or prov
            paren = [x for x in (prov if call and prov and prov != call else "", typ) if x]
            if not main:
                return typ or "none"
            return f"{main} ({', '.join(paren)})" if paren else main

        said.append((side, ps, role, desc("old"), desc("new")))
    out = []
    for side, ps, role, o, n in said:
        twin = next((x for x in said if x[0] == "APCH" and x[1] == ps and x[3:] == (o, n)), None)
        if side == "DEP" and twin:
            continue
        if side == "APCH" and any(x[0] == "DEP" and x[1] == ps and x[3:] == (o, n) for x in said):
            role = "approach/departure control" if ps == "P" else "secondary approach/departure control"
        out.append(f"{role}: {o} -> {n}")
    return out


def values(col, source, *vs):
    """the English a value reads as, for the summary value check: a code's meaning has digits
    of its own ('4-light PAPI', '1,400 foot') that come from the table, not a template bug."""
    return [say(col, source, v) for v in vs] + [name(col, source)]


def generic(col, old, new):
    """the phrase the old engine wrote for a column it had no English for."""
    return f"{col.replace('_', ' ').lower()}: {old or '(none)'} -> {new or '(none)'}"

