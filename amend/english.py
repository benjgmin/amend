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
            phrases.append(f"tower hours changed: {hrs(f['old'])} -> {hrs(f['new'])} local")
            break
    if "AIRSPACE_HRS" in by:
        f = by["AIRSPACE_HRS"]
        phrases.append(f"airspace is now: {f['new'].lower()} (was: {f['old'].lower()})")
    prov = [by[k] for k in ("APCH_P_PROVIDER", "DEP_P_PROVIDER") if k in by]
    if prov:
        phrases.append(f"approach/departure control now provided by {prov[0]['new']} "
                       f"(was {prov[0]['old']})")
    if "HOUR" in by and base(source) == "APT_ATT":
        f = by["HOUR"]
        phrases.append(f"airport attendance hours changed: {f['old']} -> {f['new']}")
    if "PHONE_NO" in by:
        what = ("AWOS/ASOS " if base(source).startswith("AWOS")
                else "airport " if base(source).startswith("APT") else "")
        phrases.append(f"{what}phone number changed to {by['PHONE_NO']['new']}")
    if "LNDG_FEE_FLAG" in by:
        phrases.append("landing fee now charged" if by["LNDG_FEE_FLAG"]["new"] == "Y"
                       else "landing fee removed")
    if "FREQ_USE" in by:
        f = by["FREQ_USE"]
        if f["new"]:
            phrases.append(f"frequency {ctx.get('FREQ', '')} now listed for {f['new']} (was {f['old']})")
        else:
            phrases.append(f"frequency {ctx.get('FREQ', '')} no longer listed for {f['old']}")
    obst = {"OBSTN_HGT", "DIST_FROM_THR", "CNTRLN_OFFSET", "CNTRLN_DIR_CODE", "OBSTN_CLNC_SLOPE"}
    if obst & set(by):
        side = {"L": "left of", "R": "right of", "B": "either side of"}.get(
            ctx.get("CNTRLN_DIR_CODE", ""), "off")
        bits = []
        if ctx.get("OBSTN_HGT"):
            bits.append(f"{ctx['OBSTN_HGT']} ft tall")
        if ctx.get("DIST_FROM_THR"):
            bits.append(f"{ctx['DIST_FROM_THR']} ft from threshold")
        if ctx.get("CNTRLN_OFFSET"):
            bits.append(f"{ctx['CNTRLN_OFFSET']} ft {side} centerline")
        slope = f", clearance slope {ctx['OBSTN_CLNC_SLOPE']}:1" if ctx.get("OBSTN_CLNC_SLOPE") else ""
        phrases.append(f"controlling obstacle changed (now {', '.join(bits)}{slope})")
    declared = [c for c in DECLARED_DISTANCES if c in by]
    if declared:
        def ft(v):
            try:
                return f"{int(float(v)):,} ft"
            except ValueError:
                return v or "none"
        parts = [f"{DECLARED_DISTANCES[c][0]} ({DECLARED_DISTANCES[c][1]}) "
                 f"{ft(by[c]['old'])} -> {ft(by[c]['new'])}" for c in declared]
        phrases.append("declared distances changed: " + "; ".join(parts))
    if "RWY_MARKING_COND" in by:
        phrases.append(f"markings now in {by['RWY_MARKING_COND']['new'].lower()} condition")
    if "COND" in by:
        phrases.append(f"pavement now in {by['COND']['new'].lower()} condition")
    if "NAV_TYPE" in by:
        f = by["NAV_TYPE"]
        phrases.append(f"now a {NAV_NAMES.get(f['new'], f['new'])} "
                       f"(was a {NAV_NAMES.get(f['old'], f['old'])})")
    if "TACAN_DME_STATUS" in by:
        phrases.append(f"status: {by['TACAN_DME_STATUS']['new'].lower() or 'none listed'}")
    if "FREQ" in by:
        f = by["FREQ"]
        phrases.append(f"frequency changed: {f['old']} -> {f['new']}")
    if "FACILITY" in by:
        f = by["FACILITY"]
        phrases.append(f"frequency now provided by {f['new']} (was {f['old']})")

    handled = {"TWR_HRS", "TOWER_HRS", "AIRSPACE_HRS", "APCH_P_PROVIDER", "DEP_P_PROVIDER",
               "PHONE_NO", "NAV_TYPE", "FREQ", "FACILITY", "FAC_NAME", "LNDG_FEE_FLAG", "FREQ_USE",
               "RWY_MARKING_COND", "COND", "TACAN_DME_STATUS"} | obst | set(DECLARED_DISTANCES)
    if base(source) == "APT_ATT":
        handled.add("HOUR")
    for k, f in by.items():
        if k in handled:
            continue
        if k in NAME_COLS:
            phrases.append(f"{name_label(k, source, ctx)} changed: {f['old'].title()} -> {f['new'].title()}")
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
            return f"remark updated: {remarks.get(new, new)}"
        text = row.get("REMARK", "")
        rec["original"] = text
        return f"{'new remark' if kind == 'added' else 'remark removed'}: {remarks.get(text, text)}"

    if b == "PFR_RMT_FMT":
        o, d = (row or ctx).get("Orig", "?"), (row or ctx).get("Dest", "?")
        route = (row or ctx).get("Route String", "")
        if kind == "added":
            return f"new preferred IFR route {o} -> {d}: {route}"
        if kind == "removed":
            return f"preferred IFR route {o} -> {d} removed"
        return f"preferred IFR route {o} -> {d} is now: {route}"

    if b.startswith(("STAR", "DP")):
        what = "arrival (STAR)" if b.startswith("STAR") else "departure (DP)"
        return f"{what} {procedure_name(rec)} {'updated' if kind == 'changed' else kind}"

    if b == "APT_CON" and kind != "changed":
        who = row.get("NAME", "").title() or "someone"
        title = row.get("TITLE", "contact").lower()
        phone = f" ({row['PHONE_NO']})" if row.get("PHONE_NO") else ""
        return (f"new airport {title} listed: {who}{phone}" if kind == "added"
                else f"airport {title} no longer listed: {who}")

    if b == "NAV_BASE" and kind != "changed":
        t = NAV_NAMES.get(row.get("NAV_TYPE", ""), row.get("NAV_TYPE", "navaid"))
        freq = f" ({row['FREQ']})" if row.get("FREQ") else ""
        verb = "decommissioned/removed" if kind == "removed" else "added"
        return f"{row.get('NAV_ID', '')} {t}{freq} {verb}"

    if b == "FRQ" and kind != "changed":
        use = row.get("FREQ_USE", "")
        if re.search(r"\bRCO\b", use.upper()):
            where = re.sub(r"\s*RCO\b.*", "", use, flags=re.I).title()
            verb = "no longer available" if kind == "removed" else "now available"
            return f"flight service (FSS) {row.get('FREQ', '?')} via the {where} outlet {verb}"
        if kind == "added" and rec["priority"] == "fyi":
            return f"frequency {row.get('FREQ', '?')} now also listed for {use}"
        return f"frequency {row.get('FREQ', '?')} ({use}) {kind}"

    if kind == "changed":
        where = ""
        if ctx.get("RWY_END_ID"):
            where = f"runway {ctx['RWY_END_ID']}: "
        elif ctx.get("RWY_ID"):
            where = f"runway {ctx['RWY_ID']}: "
        elif ctx.get("NAV_ID"):
            nm = f" ({ctx['NAME'].title()})" if ctx.get("NAME") else ""
            where = f"{ctx['NAV_ID']}{nm} navaid: "
        phrases = field_phrases(rec["fields"], rec["source"], ctx)
        return [where + "; ".join(phrases)] if where else phrases

    shown = ", ".join(f"{label(k)}={v}" for k, v in list(row.items())[:6])
    return f"{kind} ({b.lower()}): {shown}"


def procedure_name(rec):
    """'JOKRS4' from a STAR/DP record."""
    for src in (rec.get("row", {}), rec.get("context", {})):
        for k, v in src.items():
            if k.endswith("COMPUTER_CODE") and v:
                return v.split(".")[-1]
    for f in rec.get("fields", []):
        if f["field"].endswith("COMPUTER_CODE") and f["new"]:
            return f["new"].split(".")[-1]
    return "procedure"