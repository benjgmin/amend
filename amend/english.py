"""Turning raw change records into plain-English summaries."""
import re

from .rules import DECLARED_DISTANCES, NAME_COLS, NAV_NAMES, REMARK_FILES, base


def label(field):
    return field.replace("_", " ").lower()


def field_phrases(fields, source, ctx=None):
    """one phrase per meaningful field change on a 'changed' record."""
    ctx = ctx or {}
    by = {f["field"]: f for f in fields}
    phrases = []
    hrs = lambda v: v or "none listed"

    for k in ("TWR_HRS", "TOWER_HRS"):
        if k in by:
            f = by[k]
            phrases.append(f"tower hours: {hrs(f['old'])} -> {hrs(f['new'])} local")
            break
    if "AIRSPACE_HRS" in by:
        f = by["AIRSPACE_HRS"]
        phrases.append(f"airspace: {f['old'].lower()} -> {f['new'].lower()}")
    prov = [by[k] for k in ("APCH_P_PROVIDER", "DEP_P_PROVIDER") if k in by]
    if prov:
        phrases.append(f"approach/departure control: {prov[0]['old']} -> {prov[0]['new']}")
    if "HOUR" in by and base(source) == "APT_ATT":
        f = by["HOUR"]
        phrases.append(f"airport attendance hours: {f['old']} -> {f['new']}")
    if "PHONE_NO" in by:
        what = ("AWOS/ASOS " if base(source).startswith("AWOS")
                else "airport " if base(source).startswith("APT") else "")
        phrases.append(f"{what}phone number: {by['PHONE_NO']['old'] or 'none'} -> {by['PHONE_NO']['new'] or 'none'}")
    if "LNDG_FEE_FLAG" in by:
        phrases.append("landing fee: none -> charged" if by["LNDG_FEE_FLAG"]["new"] == "Y"
                       else "landing fee: charged -> none")
    if "FREQ_USE" in by:
        f = by["FREQ_USE"]
        if f["new"]:
            phrases.append(f"frequency {ctx.get('FREQ', '')} use: {f['old']} -> {f['new']}")
        else:
            phrases.append(f"frequency {ctx.get('FREQ', '')} use: {f['old']} -> none")
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

    handled = {"TWR_HRS", "TOWER_HRS", "AIRSPACE_HRS", "APCH_P_PROVIDER", "DEP_P_PROVIDER",
               "PHONE_NO", "NAV_TYPE", "FREQ", "FACILITY", "FAC_NAME", "LNDG_FEE_FLAG", "FREQ_USE",
               "RWY_MARKING_COND", "COND", "TACAN_DME_STATUS"} | obst | set(DECLARED_DISTANCES)
    if base(source) == "APT_ATT":
        handled.add("HOUR")
    for k, f in by.items():
        if k in handled:
            continue
        if k in NAME_COLS:
            phrases.append(f"{name_label(k, source, ctx)}: {f['old'].title()} -> {f['new'].title()}")
        else:
            phrases.append(f"{label(k)}: {f['old'] or '(none)'} -> {f['new'] or '(none)'}")
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
        if kind == "changed":
            new = next((f["new"] for f in rec["fields"] if f["field"] == "REMARK"),
                       ctx.get("REMARK", ""))
            rec["original"] = new
            return f"revised remark: {remarks.get(new, new)}"
        text = row.get("REMARK", "")
        rec["original"] = text
        return f"{'new remark' if kind == 'added' else 'removed remark'}: {remarks.get(text, text)}"

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
        if kind == "added" and rec["priority"] == "fyi":
            return f"frequency {row.get('FREQ', '?')}: also listed for {use}"
        if kind == "removed":
            return f"frequency {row.get('FREQ', '?')} ({use}): discontinued"
        return f"new frequency {row.get('FREQ', '?')} ({use})"

    if kind == "changed":
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

    shown = ", ".join(f"{label(k)}={v}" for k, v in list(row.items())[:6] if not k.startswith("_"))
    return f"{kind} ({b.lower()}): {shown}"


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