"""FAA d-TPP metafile: added / amended / deleted charts (approaches, DPs, STARs, diagrams)."""
import xml.etree.ElementTree as ET
from collections import defaultdict

DTPP_KINDS = {
    "IAP": "approach", "DP": "departure", "ODP": "obstacle departure", "STAR": "arrival (STAR)",
    "APD": "airport diagram", "HOT": "hot spot page", "MIN": "minimums page",
    "LAH": "LAHSO page", "DAU": "diverse vector area page", "CVFP": "charted visual procedure",
}
DTPP_ACTIONS = {"A": "added", "C": "changed", "D": "removed"}
PROCEDURE_CODES = ("IAP", "DP", "ODP", "STAR", "CVFP")


def load_dtpp(path, ids):
    """{airport: [record, ...]} for charts marked added/changed/deleted.
    useraction is relative to the previous edition, so one file per cycle is enough."""
    out = defaultdict(list)
    cycle, apt, seen = "", None, set()
    for event, el in ET.iterparse(path, events=("start", "end")):
        tag = el.tag.lower()
        if event == "start" and tag == "digital_tpp":
            cycle = el.get("cycle", "")
        elif event == "start" and tag == "airport_name":
            apt = (el.get("apt_ident") or "").upper()
        elif event == "end" and tag == "record":
            get = lambda k: (el.findtext(k) or "").strip()
            act = get("useraction").upper()
            if apt in ids and act in DTPP_ACTIONS:
                code, name = get("chart_code").upper(), get("chart_name")
                key = (apt, code, name.replace(", CONT.", "").replace(" CONT.", ""), act)
                if key not in seen:  # continuation pages list the same chart twice
                    seen.add(key)
                    out[apt].append(_record(apt, code, name, act, get("amdtnum"),
                                            get("pdf_name"), cycle))
            el.clear()
        elif event == "end" and tag == "airport_name":
            el.clear()
    return out


def _record(apt, code, name, act, amdt, pdf, cycle):
    what = DTPP_KINDS.get(code, code.lower() or "chart")
    verb = DTPP_ACTIONS[act]
    if code in PROCEDURE_CODES:
        s = f"{what} {name} {verb}"
        if act == "C" and amdt:
            lbl = "original" if amdt.upper() in ("0", "ORIG") else f"amdt {amdt}"
            s = f"{what} {name} amended ({lbl})"
        pri = "ifr"
    else:
        s = f"{what} {verb}" if code == "APD" else f"{what} ({name}) {verb}"
        pri = "fyi" if code in ("APD", "HOT") else "ifr"
    chart = {"code": code, "name": name, "amdt": amdt}
    if cycle and pdf and act != "D" and "DELETED" not in pdf.upper():
        chart["pdf"] = f"https://aeronav.faa.gov/d-tpp/{cycle}/{pdf}"
    return {"airport": apt, "source": "d-TPP", "kind": verb, "priority": pri,
            "summary_override": s, "chart": chart}
