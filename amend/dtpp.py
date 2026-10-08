"""FAA d-TPP metafile: added / amended / deleted charts (approaches, DPs, STARs, diagrams)."""
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

DTPP_KINDS = {
    "IAP": "approach", "DP": "departure", "ODP": "obstacle departure",
    "STAR": "arrival", "STR": "arrival",   # the real metafile uses STR
    "APD": "airport diagram", "HOT": "hot spot page", "MIN": "minimums page",
    "LAH": "LAHSO page", "DAU": "diverse vector area page", "CVFP": "charted visual procedure",
}
DTPP_ACTIONS = {"A": "added", "C": "changed", "D": "removed"}
PROCEDURE_CODES = ("IAP", "DP", "ODP", "STAR", "STR", "CVFP")
# a chart's extra pages are their own records: "TRISH FIVE (RNAV), CONT.1" (the 2609-2611
# metafiles have CONT.1 to CONT.3, always at the end of the name)
CONT_PAGE = re.compile(r",? CONT\.\d*$")


def load_dtpp(path, ids):
    """{airport: [record, ...]}, one per chart with a page added, changed or deleted.
    useraction is relative to the previous edition, so one file per cycle is enough.

    a chart's continuation pages fold into the chart: changed with all its pages is one change.
    a renumbered DP or STAR keeps its pdf, so its first page reads changed under the new name
    and only the pages it dropped still carry the old one (MSP 2611: MINNEAPOLIS ONE changed,
    "MINNEAPOLIS NINE, CONT.1" deleted). the FAA's procuid ties them together, and the chart
    reads "MINNEAPOLIS ONE replaces MINNEAPOLIS NINE". in the 2607-2610 metafiles procuid is
    shared by a chart's pages and never by two charts still in the edition, and the only
    deleted charts sharing one with a live chart were these renumbers (BCT/DJT MAHHI THREE ->
    FOUR, CLT CHARLOTTE FIVE -> SIX). a renumber that drops no page can't be seen from one
    metafile: it reads "<new name> changed"."""
    pages = defaultdict(list)    # (airport, code, chart name) -> its pages, in file order
    cycle, apt = "", None
    for event, el in ET.iterparse(path, events=("start", "end")):
        tag = el.tag.lower()
        if event == "start" and tag == "digital_tpp":
            cycle = el.get("cycle", "")
        elif event == "start" and tag == "airport_name":
            apt = (el.get("apt_ident") or "").upper()
        elif event == "end" and tag == "record":
            if apt in ids:
                get = lambda k: (el.findtext(k) or "").strip()
                name = get("chart_name")
                chart = CONT_PAGE.sub("", name)
                pages[(apt, get("chart_code").upper(), chart)].append(
                    {"first": name == chart, "act": get("useraction").upper(), "amdt": get("amdtnum"),
                     "pdf": get("pdf_name"), "procuid": get("procuid")})
            el.clear()
        elif event == "end" and tag == "airport_name":
            el.clear()

    live = {}                    # (airport, code, procuid) -> chart still in this edition
    for (apt, code, chart), pp in pages.items():
        if any(p["act"] != "D" for p in pp):
            for p in pp:
                if p["procuid"]:
                    live[(apt, code, p["procuid"])] = chart
    renamed, folded = {}, set()  # live chart -> its old name; old names read as the rename
    for (apt, code, chart), pp in pages.items():
        if {p["act"] for p in pp} == {"D"}:
            new = next((live[k] for k in ((apt, code, p["procuid"]) for p in pp if p["procuid"])
                        if k in live), None)
            if new:
                renamed[(apt, code, new)] = chart
                folded.add((apt, code, chart))

    out = defaultdict(list)
    for key, pp in pages.items():
        apt, code, chart = key
        acts = {p["act"] for p in pp}
        if key in folded or not (acts & DTPP_ACTIONS.keys() or key in renamed):
            continue
        act = "C" if key in renamed else "A" if acts == {"A"} else "D" if acts == {"D"} else "C"
        first = next((p for p in pp if p["first"]), pp[0])
        pdf = next((p["pdf"] for p in [first] + pp
                    if p["act"] != "D" and p["pdf"] and "DELETED" not in p["pdf"].upper()), "")
        out[apt].append(_record(apt, code, chart, act, first["amdt"], pdf, cycle, renamed.get(key)))
    return out


def _record(apt, code, name, act, amdt, pdf, cycle, was=None):
    what = DTPP_KINDS.get(code, code.lower() or "chart")
    verb = DTPP_ACTIONS[act]
    if code in PROCEDURE_CODES:
        s = f"{what} {name} {verb}"
        if was:
            s = f"{what} {name} replaces {was}"
        elif act == "C" and amdt:
            lbl = "original" if amdt.upper() in ("0", "ORIG") else f"amdt {amdt}"
            s = f"{what} {name} amended ({lbl})"
        pri = "ifr"
    else:
        s = f"{what} {verb}" if code == "APD" else f"{what} ({name}) {verb}"
        pri = "fyi" if code in ("APD", "HOT") else "ifr"
    chart = {"code": code, "name": name, "amdt": amdt}
    if was:
        chart["replaces"] = was
    if cycle and pdf and act != "D":
        chart["pdf"] = f"https://aeronav.faa.gov/d-tpp/{cycle}/{pdf}"
    return {"airport": apt, "source": "d-TPP", "kind": verb, "priority": pri,
            "summary_override": s, "chart": chart}
