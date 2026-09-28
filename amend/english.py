"""Turning raw change records into plain-English summaries."""
import re

from . import fields as fl
from .rules import DECLARED_DISTANCES, NAME_COLS, NAV_NAMES, REMARK_FILES, base, is_helipad


def label(field):
    return field.replace("_", " ").lower()


# FRQ's FREQ_USE words. the meanings are the glossary's verified ones (APCH, DEP, LCL, GND, CD,
# EMERG, OPS, PMSV, D-ATIS, GCO); /P and /S are primary and secondary, the same P and S the APT layout
# uses for its APCH_P / DEP_S columns. any other word (IC, a sector name) stays as the FAA wrote it,
# and the FAA's own text is always shown next to ours.
USE_ROLES = {"APCH": "approach", "DEP": "departure", "LCL": "tower (local control)",
             "GND": "ground control", "CD": "clearance delivery"}
USE_WORDS = {"EMERG": "emergency", "OPS": "operations", "PMSV": "pilot-to-metro service",
             "D-ATIS": "digital ATIS", "GCO": "ground communication outlet (GCO)"}
PROC_USE = re.compile(r"(\S+(?: RNAV)?) (STAR|DP)")


def freq_use(use, row=None):
    """'APCH/P DEP/P IC' -> ('approach/departure', 'primary'), with the radio call in front when
    the row has it ('Cascade approach/departure'). None when no word of it is one we know."""
    roles, ps, words = [], set(), []
    for tok in use.split():
        m = re.fullmatch(r"(APCH|DEP|LCL|GND|CD)(?:/([PS]))?", tok)
        if m:
            roles.append(USE_ROLES[m[1]])
            ps.add(m[2])
        elif tok in USE_WORDS:
            words.append(USE_WORDS[tok])
    if not roles and not words:
        return None
    what = " and ".join(x for x in ("/".join(roles), ", ".join(words)) if x)
    row = row or {}
    call = (row.get("PRIMARY_APPROACH_RADIO_CALL") if set(roles) <= {"approach", "departure"}
            else row.get("TOWER_OR_COMM_CALL") if roles else "")
    if call and roles:
        what = f"{call.title()} {what}"
    note = {"P": "primary", "S": "secondary"}.get(ps.pop()) if len(ps) == 1 else None
    return what, note


def say_use(use):
    """a FREQ_USE value for 'old -> new': 'approach/departure, primary (APCH/P DEP/P)'."""
    if not use:
        return "none"
    procs = [PROC_USE.fullmatch(u.strip()) for u in use.split(",")]
    if all(procs):
        kinds = {m[2] for m in procs}
        what = "arrival" if kinds == {"STAR"} else "departure" if kinds == {"DP"} else "procedure"
        return f"{use} ({what}{'s' if len(procs) > 1 else ''})"
    u = freq_use(use)
    if not u:
        return use
    return f"{u[0]}{', ' + u[1] if u[1] else ''} ({use})"


def field_phrases(fields, source, ctx=None):
    """one phrase per meaningful field change on a 'changed' record."""
    ctx = ctx or {}
    by = {f["field"]: f for f in fields}
    phrases = []
    hrs = lambda v: v or "none listed"

    for k in ("TWR_HRS", "TOWER_HRS"):
        if k in by:
            f = by[k]
            # "local" only when both sides are plain local times; 1500-0700Z++ or "OPEN 24 HRS" say it themselves
            plain = all(re.fullmatch(r"\d{4}-\d{4}", (v or "").strip()) for v in (f["old"], f["new"]))
            phrases.append(f"tower hours: {hrs(f['old'])} -> {hrs(f['new'])}{' local' if plain else ''}")
            break
    if "AIRSPACE_HRS" in by:
        f = by["AIRSPACE_HRS"]
        phrases.append(f"airspace: {f['old']} -> {f['new']}")   # keep FAA casing: 0700Z, CLASS D
    phrases += fl.control_phrases(by)
    if "PHONE_NO" in by:
        what = ("AWOS/ASOS " if base(source).startswith("AWOS")
                else "airport " if base(source).startswith("APT") else "")
        phrases.append(f"{what}phone number: {by['PHONE_NO']['old'] or 'none'} -> {by['PHONE_NO']['new'] or 'none'}")
    if "LNDG_FEE_FLAG" in by:
        phrases.append("landing fee: none -> charged" if by["LNDG_FEE_FLAG"]["new"] == "Y"
                       else "landing fee: charged -> none")
    if "FREQ_USE" in by:
        f = by["FREQ_USE"]
        phrases.append(f"frequency {ctx.get('FREQ', '')} use: {say_use(f['old'])} -> {say_use(f['new'])}")
    obst = {"OBSTN_HGT", "DIST_FROM_THR", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE"}
    if obst & set(by):
        side = {"L": "left of", "R": "right of", "B": "either side of"}.get(
            ctx.get("CNTRLN_DIR_CODE", ""), "off")
        def val(col, fmt="{}"):
            """'53 -> 25' if the field changed, else just the current value"""
            if col in by and by[col]["old"] and by[col]["new"]:
                return f"{fmt.format(by[col]['old'])} -> {fmt.format(by[col]['new'])}"
            v = ctx.get(col) or (by[col]["new"] if col in by else "")
            return fmt.format(v) if v else ""
        bits = []
        if val("OBSTN_HGT"):
            bits.append(f"{val('OBSTN_HGT')} ft tall")
        if val("DIST_FROM_THR"):
            bits.append(f"{val('DIST_FROM_THR')} ft from threshold")
        if val("CNTRLN_OFFSET"):
            bits.append(f"{val('CNTRLN_OFFSET')} ft {side} centerline")
        if val("OBSTN_CLNC_SLOPE"):
            bits.append(f"clearance slope {val('OBSTN_CLNC_SLOPE', '{}:1')}")
        phrases.append(f"controlling obstacle: {', '.join(bits)}")
    declared = [c for c in DECLARED_DISTANCES if c in by]
    if declared:
        def ft(v):
            try:
                return f"{int(float(v)):,} ft"
            except ValueError:
                return v or "none"
        parts = [f"{DECLARED_DISTANCES[c][0]} ({DECLARED_DISTANCES[c][1]}) "
                 f"{ft(by[c]['old'])} -> {ft(by[c]['new'])}" for c in declared]
        phrases.append("declared distances: " + "; ".join(parts))
    if "RWY_MARKING_COND" in by:
        phrases.append(f"marking condition: {by['RWY_MARKING_COND']['old'].lower() or 'none'} -> "
                       f"{by['RWY_MARKING_COND']['new'].lower() or 'none'}")
    if "COND" in by:
        phrases.append(f"pavement condition: {by['COND']['old'].lower() or 'none'} -> "
                       f"{by['COND']['new'].lower() or 'none'}")
    if "NAV_TYPE" in by:
        f = by["NAV_TYPE"]
        phrases.append(f"{NAV_NAMES.get(f['old'], f['old'])} -> {NAV_NAMES.get(f['new'], f['new'])}")
    if "TACAN_DME_STATUS" in by:
        f = by["TACAN_DME_STATUS"]
        phrases.append(f"TACAN/DME status: {f['old'].lower() or 'none listed'} -> "
                       f"{f['new'].lower() or 'none listed'}")
    if "FREQ" in by:
        f = by["FREQ"]
        phrases.append(f"frequency: {f['old']} -> {f['new']}")
    if "FACILITY" in by:
        f = by["FACILITY"]
        phrases.append(f"frequency provided by: {f['old']} -> {f['new']}")

    handled = {"TWR_HRS", "TOWER_HRS", "AIRSPACE_HRS", "PHONE_NO", "NAV_TYPE", "FREQ", "FACILITY",
               "FAC_NAME", "LNDG_FEE_FLAG", "FREQ_USE", "RWY_MARKING_COND", "COND",
               "TACAN_DME_STATUS"} | obst | set(DECLARED_DISTANCES) | fl.CONTROL_COLS
    # whose column it is: 'airport manager address', 'frequency 124.5 sector'
    who = (f"airport {ctx.get('TITLE', 'contact').lower()} " if base(source) == "APT_CON"
           else f"frequency {ctx['FREQ']} " if base(source) == "FRQ" and ctx.get("FREQ") else "")
    for k, f in by.items():
        if k in handled:
            continue
        if k in NAME_COLS:
            phrases.append(f"{name_label(k, source, ctx)}: {f['old'].title()} -> {f['new'].title()}")
        else:
            # every column has the FAA layout's English (fields.py); one that doesn't is
            # flagged by summarize() and never reaches act
            phrases.append(fl.phrase(k, source, f["old"], f["new"], who))
    return phrases


def name_label(col, source, ctx):
    """what a NAME column actually is, e.g. 'airport manager' instead of just 'name'."""
    b = base(source)
    if b == "APT_CON":
        return f"airport {ctx.get('TITLE', 'contact').lower()}"
    if col == "ARPT_NAME":
        return "airport name"
    if b.startswith("NAV"):
        return "navaid name"
    if col == "SERVICED_FAC_NAME":
        return "served facility name"
    return "facility name"


# a remark that is nothing but a closure: "CLOSED.", "CLSD"
CLOSED = re.compile(r"\s*(?:CLOSED|CLSD)\.?\s*", re.I)


def remark_subject(row):
    """what an airport remark is filed against, from its TAB_NAME / REF_COL_NAME / ELEMENT:
    'runway 15C/33C', 'runway 15C arresting system MA-1A', 'airport lighting schedule'. '' for a
    general airport remark, or when NASR doesn't say."""
    tab, ref, e = (row.get(c, "").strip() for c in ("TAB_NAME", "REF_COL_NAME", "ELEMENT"))
    col = fl.name(ref, "APT_BASE") if fl.known(ref, "APT_BASE") and ref not in (
        "GENERAL_REMARK", "RWY_ID", "RWY_END_ID", "FUEL_TYPE", "ARREST_DEVICE_CODE",
        "SERVICE_TYPE_CODE", "NAME") else ""
    strip = lambda t: " ".join(t.split())
    if tab == "AIRPORT":
        return "" if not col else col if col.startswith("airport") else f"airport {col}"
    if tab in ("RUNWAY", "RUNWAY_SURFACE_TYPE") and e:
        what = "helipad" if is_helipad(e) else "runway"
        return strip(f"{what} {e} {col or ('surface' if tab == 'RUNWAY_SURFACE_TYPE' else '')}")
    if tab in ("RUNWAY_END", "RUNWAY_END_OBSTN") and e:
        what = "helipad" if is_helipad(e) else "runway"
        return strip(f"{what} {e} {col or ('obstacle' if tab == 'RUNWAY_END_OBSTN' else 'end')}")
    if tab == "ARRESTING_DEVICE" and e:
        rwy, _, dev = e.partition("_")
        return strip(f"runway {rwy} arresting system {dev}") if dev else f"runway {rwy} arresting system"
    if tab == "FUEL_TYPE" and e:
        return f"fuel type {e}"
    if tab == "AIRPORT_CONTACT" and e:
        return f"airport {e.lower()} contact"
    if tab == "AIRPORT_SERVICE" and e:
        return f"airport service {fl.SERVICES[e]} ({e})" if e in fl.SERVICES else f"airport service {e}"
    if tab == "AIRPORT_ATTEND_SCHED":
        return "attendance schedule"
    return ""


def remark_label(b, row):
    """'remark', 'runway 15C/33C remark', 'ILS RWY 22 remark', 'navaid remark', ..."""
    if b == "APT_RMK":
        what = remark_subject(row)
        return f"{what} remark" if what else "remark"
    if b == "ILS_RMK":
        rwy = row.get("RWY_END_ID", "")
        kind = row.get("SYSTEM_TYPE_CODE", "")
        name = {"LD": "ILS/DME", "LS": "ILS", "LC": "localizer", "LA": "LDA", "SF": "SDF"}.get(kind, "ILS")
        return f"{name} RWY {rwy} remark" if rwy else f"{name} remark"
    return {"NAV_RMK": "navaid remark", "AWOS_RMK": "AWOS remark", "FRQ_RMK": "frequency remark",
            "ATC_RMK": "tower/ATC remark", "CLS_ARSP_RMK": "airspace remark"}.get(b, "remark")


def summarize(rec, remarks):
    """plain-English phrase(s) for one record. returns a string, or a list of phrases for
    'changed' records without a location prefix (so duplicates across files can be dropped).
    remark records also get rec['original'] set to the raw FAA text."""
    if rec.get("summary_override"):
        return rec["summary_override"]
    b = base(rec["source"])
    kind = rec["kind"]
    row = rec.get("row", {})
    ctx = rec.get("context", {})

    if b in REMARK_FILES:
        what = remark_label(b, row or ctx)
        if kind == "changed":
            new = next((f["new"] for f in rec["fields"] if f["field"] == "REMARK"),
                       ctx.get("REMARK", ""))
            rec["original"] = new
            return f"revised {what}: {remarks.get(new, new)}"
        text = row.get("REMARK", "")
        rec["original"] = text
        if kind == "removed" and b == "APT_RMK" and CLOSED.fullmatch(text) and remark_subject(row):
            # the whole remark was the closure. another remark could still close it, so: "may"
            return f"{remark_subject(row)} closure remark removed, so it may be open again: {remarks.get(text, text)}"
        return f"{'new ' + what if kind == 'added' else 'removed ' + what}: {remarks.get(text, text)}"

    if b == "FRQ" and kind == "changed" and [f["field"] for f in rec["fields"]] == ["REMARK"]:
        new = rec["fields"][0]["new"]
        rec["original"] = new
        what = " ".join(x for x in (ctx.get("FREQ_USE", ""), ctx.get("FREQ", "")) if x)
        return f"revised remark{' for ' + what if what else ''}: {remarks.get(new, new) or '(none)'}"

    if b == "PFR_RMT_FMT":
        o, d = (row or ctx).get("Orig", "?"), (row or ctx).get("Dest", "?")
        route = (row or ctx).get("Route String", "")
        if kind == "added":
            return f"new preferred IFR route {o} -> {d}: {route}"
        if kind == "removed":
            return f"preferred IFR route {o} -> {d}: discontinued"
        return f"preferred IFR route {o} -> {d}: new routing {route}"

    if b.startswith(("STAR", "DP")):
        what = "arrival (STAR)" if b.startswith("STAR") else "departure (DP)"
        return f"{what} {procedure_name(rec)} {'updated' if kind == 'changed' else kind}"

    if b == "APT_CON" and kind != "changed":
        who = row.get("NAME", "").title() or "someone"
        title = row.get("TITLE", "contact").lower()
        phone = f" ({row['PHONE_NO']})" if row.get("PHONE_NO") else ""
        return (f"new airport {title}: {who}{phone}" if kind == "added"
                else f"airport {title}: {who} -> none listed")

    if b == "NAV_BASE" and kind != "changed":
        t = NAV_NAMES.get(row.get("NAV_TYPE", ""), row.get("NAV_TYPE", "navaid"))
        freq = f" ({row['FREQ']})" if row.get("FREQ") else ""
        away = f" ({row['_NEAR_NM']} NM from the field)" if row.get("_NEAR_NM") else ""
        if kind == "removed":
            return f"{row.get('NAV_ID', '')} {t}{freq}{away}: decommissioned"
        return f"new navaid: {row.get('NAV_ID', '')} {t}{freq}{away}"

    if b == "FRQ" and kind != "changed":
        use = row.get("FREQ_USE", "")
        if re.search(r"\bRCO\b", use.upper()):
            where = re.sub(r"\s*RCO\b.*", "", use, flags=re.I).title()
            if kind == "removed":
                return f"flight service (FSS) {row.get('FREQ', '?')} via the {where} outlet: discontinued"
            return f"new flight service (FSS) {row.get('FREQ', '?')} via the {where} outlet"
        freq = row.get("FREQ", "?")
        u = freq_use(use, row)
        if kind == "added" and rec["priority"] == "fyi":
            return f"frequency {freq}: also listed for {say_use(use)}"
        if not u:
            return (f"frequency {freq} ({use}): discontinued" if kind == "removed"
                    else f"new frequency {freq} ({use})")
        what, note = u
        paren = f" ({note}; FAA: {use})" if note else f" (FAA: {use})"
        if kind == "removed":
            return f"{what} frequency {freq}{paren}: discontinued"
        return f"new {what} frequency {freq}{paren}"

    if b == "PJA_BASE" and kind != "changed":
        name = row.get("DROP_ZONE_NAME", "").title()
        ref = ""
        if row.get("NAV_ID") and row.get("RADIAL") and row.get("DISTANCE"):
            try:
                ref = f" ({row['NAV_ID']} {float(row['RADIAL']):03.0f}° {float(row['DISTANCE']):.0f} NM)"
            except ValueError:
                pass
        top = f", up to {row['MAX_ALTITUDE']} ft {row.get('MAX_ALTITUDE_TYPE_CODE', '')}".rstrip() \
            if row.get("MAX_ALTITUDE") else ""
        what = " ".join(x for x in ("parachute jump area", row.get("PJA_ID", ""), name) if x)
        return f"{'new ' if kind == 'added' else ''}{what}{ref}{top}{': removed' if kind == 'removed' else ''}"

    if b == "NAV_CKPT" and kind != "changed":
        where = row.get("CHK_DESC", "").rstrip(". ").lower()
        brg = f" {row['BRG']}°" if row.get("BRG") else ""
        what = f"{row.get('NAV_ID', '')} VOR checkpoint{brg}{': ' + where if where else ''}"
        return f"new {what}" if kind == "added" else f"{what}: removed"

    if b == "APT_ATT" and [f["field"] for f in rec.get("fields", [])] == ["ATTENDANCE"]:
        f = rec["fields"][0]
        if not f["old"]:
            return f"airport attendance listed: {f['new']}"
        return f"airport attendance: {f['old']} -> {f['new'] or 'none listed'}"

    if kind != "changed" and b in ROW_SUMMARIES:
        return ROW_SUMMARIES[b](kind, row)

    if kind == "changed":
        if any(not fl.known(f["field"], rec["source"]) for f in rec["fields"]):
            rec["no_template"] = True     # a column the FAA layouts we read don't name: counted
        where = ""
        if ctx.get("RWY_END_ID"):
            where = f"runway {ctx['RWY_END_ID']}: "
        elif ctx.get("RWY_ID"):
            where = f"runway {ctx['RWY_ID']}: "
        elif ctx.get("NAV_ID"):
            nm = f" ({ctx['NAME'].title()})" if ctx.get("NAME") else ""
            away = f", {ctx['_NEAR_NM']} NM from the field" if ctx.get("_NEAR_NM") else ""
            where = f"{ctx['NAV_ID']}{nm} navaid{away}: "
        phrases = field_phrases(rec["fields"], rec["source"], ctx)
        return [where + "; ".join(phrases)] if where else phrases

    # a file nobody wrote English for yet: the FAA's own column names and values, marked so
    # the pipeline can keep it out of act and count it (the run log shows every one)
    rec["no_template"] = True
    shown = ", ".join(f"{label(k)}={v}" for k, v in list(row.items())[:6] if not k.startswith("_"))
    return f"{kind} ({b.lower()}): {shown}"


# whole rows added or removed, one function per NASR file. codes are spelled the way the FAA's
# data layouts (the "<FILE> DATA LAYOUT.pdf" in every NASR CSV zip) spell them, never guessed:
# ILS_BASE SYSTEM_TYPE_CODE "System Type", ILS_MKR ILS_COMP_TYPE_CODE marker types.
ILS_TYPES = {"LS": "ILS", "SF": "SDF", "LC": "LOC", "LA": "LDA", "LD": "ILS/DME", "SD": "SDF/DME",
             "LE": "LOC/DME", "LG": "LOC/GS", "DD": "LDA/DME"}
MARKERS = {"IM": "inner marker", "MM": "middle marker", "OM": "outer marker"}


def ils_name(row):
    """'ILS/DME RWY 28 (NIP, 109.15)': the FAA system type, runway end, identifier, frequency."""
    code = row.get("SYSTEM_TYPE_CODE", "")
    name = ILS_TYPES.get(code, f"ILS ({code})" if code else "ILS")
    rwy = f" RWY {row['RWY_END_ID']}" if row.get("RWY_END_ID") else ""
    ids = ", ".join(v for v in (row.get("ILS_LOC_ID", ""), row.get("LOC_FREQ", "")) if v)
    return f"{name}{rwy}{f' ({ids})' if ids else ''}"


def ils_part(b, row):
    """one ILS component in a few words: 'glideslope 3°', 'DME channel 28Y', 'outer marker
    (compass locator FITZY 209)'."""
    if b == "ILS_GS":
        return f"glideslope{' ' + row['G_S_ANGLE'] + '°' if row.get('G_S_ANGLE') else ''}"
    if b == "ILS_DME":
        return f"DME{' channel ' + row['CHANNEL'] if row.get('CHANNEL') else ''}"
    if b == "ILS_MKR":
        code = row.get("ILS_COMP_TYPE_CODE", "")
        what = MARKERS.get(code, f"marker ({code})" if code else "marker")
        loc = " ".join(v for v in (row.get("COMPASS_LOCATOR_NAME", ""), row.get("FREQ", "")) if v)
        return f"{what}{f' (compass locator {loc})' if loc else ''}"
    return "localizer"


def ils(kind, row, parts=()):
    """a whole ILS, or one of its parts, appearing or going away. parts: the components that
    came or went with it ('glideslope 3°', ...)."""
    name = ils_name(row)
    if parts:
        name += f" with {', '.join(parts)}"
    return f"new {name}" if kind == "added" else f"{name}: removed"


def ils_component(b):
    def say(kind, row):
        part = ils_part(b, row)
        where = ils_name({k: v for k, v in row.items() if k != "LOC_FREQ"})
        return f"{where}: new {part}" if kind == "added" else f"{where}: {part} removed"
    return say


def runway(kind, row):
    """'new runway 18/36: 2546x60 ft turf', 'helipad H2 (80x80 ft conc): removed'."""
    rid = row.get("RWY_ID", "?")
    what = "helipad" if is_helipad(rid) else "runway"
    size = ""
    if row.get("RWY_LEN") and row.get("RWY_WIDTH"):
        size = f"{row['RWY_LEN']}x{row['RWY_WIDTH']} ft"
    size = " ".join(v for v in (size, row.get("SURFACE_TYPE_CODE", "").lower()) if v)
    if kind == "added":
        return f"new {what} {rid}{': ' + size if size else ''}"
    return f"{what} {rid}{f' ({size})' if size else ''}: removed"


def runway_end(kind, row):
    what = "helipad" if is_helipad(row.get("RWY_ID", "")) else "runway"
    end = row.get("RWY_END_ID", "")
    rid = row.get("RWY_ID", "")
    name = f"{what} {rid}" + (f" end {end}" if end and end != rid else "")
    return f"new {name}" if kind == "added" else f"{name}: removed"


def arresting_system(kind, row):
    """APT_ARS: 'runway 32: new arresting system (EMAS)'."""
    code = f" ({row['ARREST_DEVICE_CODE']})" if row.get("ARREST_DEVICE_CODE") else ""
    end = row.get("RWY_END_ID") or row.get("RWY_ID", "?")
    return (f"runway {end}: new arresting system{code}" if kind == "added"
            else f"runway {end}: arresting system{code} removed")


def control(row):
    """'ELLSWORTH (RCA), secondary DENVER ARTCC (ZDV)' from an ATC_BASE row's approach (or,
    if it names none, departure) columns."""
    for side in ("APCH", "DEP"):
        calls = [(row.get(f"PRIMARY_{side}_RADIO_CALL", ""), row.get(f"{side}_P_PROVIDER", "")),
                 (row.get(f"SECONDARY_{side}_RADIO_CALL", ""), row.get(f"{side}_S_PROVIDER", ""))]
        said = [f"{c} ({p})" if c and p and p != c else c or p for c, p in calls]
        if said[0] or said[1]:
            return ", secondary ".join(s for s in said if s)
    return ""


def atc_facility(kind, row):
    """ATC_BASE: a tower, or a non-towered field's approach/departure control listing."""
    ctl = control(row)
    if row.get("FACILITY_TYPE", "").upper() == "NON-ATCT":
        if kind == "added":
            return (f"approach/departure control listed: {ctl}" if ctl
                    else "new ATC facility entry, non-towered (it names no tower or approach control)")
        return (f"approach/departure control no longer listed (was {ctl})" if ctl
                else "ATC facility entry removed, non-towered (it named no tower or approach control)")
    what = fl.say("FACILITY_TYPE", "ATC_BASE", row.get("FACILITY_TYPE", "")) if row.get("FACILITY_TYPE") else "tower"
    bits = [b for b in (row.get("TWR_CALL", "") and f"call {row['TWR_CALL']}",
                        row.get("TWR_HRS", "") and f"hours {row['TWR_HRS']}",
                        ctl and f"approach {ctl}") if b]
    tail = f" ({'; '.join(bits)})" if bits else ""
    return f"new control tower: {what}{tail}" if kind == "added" else f"control tower {what}{tail}: removed"


def atis(kind, row):
    no = f" {row['ATIS_NO']}" if row.get("ATIS_NO") and row.get("ATIS_NO") != "1" else ""
    bits = [b for b in (row.get("DESCRIPTION", ""), row.get("ATIS_HRS", "") and f"hours {row['ATIS_HRS']}",
                        row.get("ATIS_PHONE_NO", "") and f"phone {row['ATIS_PHONE_NO']}") if b]
    tail = f" ({'; '.join(bits)})" if bits else ""
    return f"new ATIS{no}{tail}" if kind == "added" else f"ATIS{no}{tail}: removed"


def atc_service(kind, row):
    svc = row.get("CTL_SVC", "?")
    return f"ATC service listed: {svc}" if kind == "added" else f"ATC service {svc}: no longer listed"


def weather_station(kind, row):
    t = row.get("ASOS_AWOS_TYPE", "") or "weather station"
    ident = f" ({row['ASOS_AWOS_ID']})" if row.get("ASOS_AWOS_ID") else ""
    phone = f", phone {row['PHONE_NO']}" if row.get("PHONE_NO") else ""
    return f"new weather station: {t}{ident}{phone}" if kind == "added" else f"weather station {t}{ident}: removed"


def airspace_row(kind, row):
    """CLS_ARSP: 'new class D airspace: CLASS D SVC 0700-2100 ...' (hours kept as the FAA wrote them)."""
    classes = [c for c in "BCDE" if row.get(f"CLASS_{c}_AIRSPACE") == "Y"]
    what = f"class {'/'.join(classes)} airspace" if classes else "controlled airspace"
    hrs = row.get("AIRSPACE_HRS", "")
    if kind == "added":
        return f"new {what}{': ' + hrs if hrs else ''}"
    return f"{what} removed{f' (was {hrs})' if hrs else ''}"


def radar(kind, row):
    t = fl.say("RADAR_TYPE", "RDR", row.get("RADAR_TYPE", "")) if row.get("RADAR_TYPE") else "radar"
    hrs = row.get("RADAR_HRS", "")
    if kind == "added":
        return f"new radar: {t}{', hours ' + hrs if hrs else ''}"
    return f"radar {t}: removed{f' (was hours {hrs})' if hrs else ''}"


def military_ops(kind, row):
    """MIL_OPS: its REMARK starts with the column it's about, '(MIL_OPS_OPER_CODE) ARNG - OPR ...'."""
    text = re.sub(r"^\([A-Z_]+\)\s*", "", row.get("REMARK", ""))
    bits = [b for b in (row.get("MIL_OPS_CALL", ""), row.get("MIL_OPS_HRS", "") and f"hours {row['MIL_OPS_HRS']}",
                        text) if b]
    what = "military operations" + (f": {'; '.join(bits)}" if bits else "")
    return f"new {what}" if kind == "added" else f"{what}: no longer listed"


def jump_area_contact(kind, row):
    who = " ".join(v for v in (row.get("FAC_NAME", "").title(), row.get("FAC_ID") and f"({row['FAC_ID']})") if v)
    freq = row.get("COMMERCIAL_FREQ") or row.get("MIL_FREQ", "")
    what = f"parachute jump area {row.get('PJA_ID', '')} contact: {who or 'facility'}{' ' + freq if freq else ''}"
    return f"new {what}" if kind == "added" else f"{what}: removed"


ROW_SUMMARIES = {
    "ILS_BASE": lambda kind, row: ils(kind, row), "ILS_GS": ils_component("ILS_GS"),
    "ILS_DME": ils_component("ILS_DME"), "ILS_MKR": ils_component("ILS_MKR"),
    "APT_RWY": runway, "APT_RWY_END": runway_end, "APT_ARS": arresting_system,
    "ATC_BASE": atc_facility, "ATC_ATIS": atis, "ATC_SVC": atc_service, "AWOS": weather_station,
    "CLS_ARSP": airspace_row, "RDR": radar, "MIL_OPS": military_ops, "PJA_CON": jump_area_contact,
}


def procedure_name(rec):
    """'JOKRS4' from a STAR/DP record (STAR codes are FIX.NAME, DP codes are NAME.FIX)."""
    from .procedures import split_code
    for src in (rec.get("row", {}), rec.get("context", {})):
        for k, v in src.items():
            if k.endswith("COMPUTER_CODE") and v:
                return split_code(v)[0]
    for f in rec.get("fields", []):
        if f["field"].endswith("COMPUTER_CODE") and f["new"]:
            return split_code(f["new"])[0]
    return "procedure"

# --------------------------------------------------------------- checking a summary's values
# every number and identifier a summary shows must be one the FAA record it describes has, so
# a template bug can never print a runway, frequency or time the FAA didn't publish.
_WORD = re.compile(r"[A-Za-z0-9./+\-]+")


def _tokens(text, split=False):
    """the tokens of a text that contain a digit, upper-cased. split: also every piece between
    '/', '.' and '-' ('13/31' -> 13/31, 13, 31), so a summary may quote part of a value."""
    out = set()
    for w in _WORD.findall(text or ""):
        w = w.strip("./-+").upper()
        if not any(ch.isdigit() for ch in w):
            continue
        out.add(w)
        if split:
            out |= {p for p in re.split(r"[./\-]+", w) if p}
    return out


def record_values(rec):
    """every FAA value a record carries: its row, context, changed fields, folded rows."""
    vals = []
    src = rec.get("source", "")
    for d in [rec.get("row") or {}, rec.get("context") or {}] + [x["row"] for x in rec.get("folded", [])]:
        vals += [str(v) for v in d.values()]
        # a code's meaning from the FAA layout: '4-light PAPI on left side of runway (P4L)'
        vals += [fl.say(k, src, str(v)) for k, v in d.items() if fl.known(k, src)]
        vals += [fl.name(k, src) for k in d if fl.known(k, src)]
    for f in rec.get("fields", []):
        vals += [f["old"], f["new"], label(f["field"])]   # 'address1', 'far part 77 code'
        vals += fl.values(f["field"], src, f["old"], f["new"])
    for names in (rec.get("procedures") or {}).values():
        vals += names
    return vals + [str(v) for v in rec.get("values", [])]


def _num(t):
    """a plain decimal number ('193.5', '045'), else None ('28Y', '1E5', 'NAN' aren't)."""
    return float(t) if re.fullmatch(r"\d+(?:\.\d+)?", t) else None


def unsupported(summary, values):
    """tokens with a digit in the summary that none of the values has. [] means it checks out.
    '2546x60 ft' is two values, '1,234 ft' is one, '3°' is 3, a '34:1' slope is 34, and a
    bearing may be the value rounded to a whole number (193.5 -> 194, 45 -> 045)."""
    commas = lambda t: re.sub(r"(\d),(\d{3})\b", r"\1\2", t)
    s = re.sub(r"(\d)x(\d)", r"\1 \2", commas(summary))
    s = re.sub(r":1\b", "", s.replace("°", " "))
    have = set()
    for v in values:
        have |= _tokens(commas(v), split=True)
    nums = {_num(t) for t in have} - {None}
    rounded = {float(round(n)) for n in nums}
    return sorted(t for t in _tokens(s) - have
                  if _num(t) is None or not (_num(t) in nums or (_num(t).is_integer() and _num(t) in rounded)))


def plain_values(rec):
    """the FAA values themselves, for a record whose summary didn't check out."""
    b = base(rec["source"])
    src = rec["source"]
    if rec.get("fields"):
        body = "; ".join(f"{fl.name(f['field'], src)}: {f['old'] or 'none'} -> {f['new'] or 'none'}"
                         for f in rec["fields"])
    else:
        body = ", ".join(f"{fl.name(k, src)} {v}" for k, v in (rec.get("row") or {}).items()
                         if not k.startswith("_"))
    return f"{b.lower()} {rec['kind']}: {body}"
