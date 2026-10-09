"""FAA d-TPP metafile: added / amended / deleted charts (approaches, DPs, STARs, diagrams)."""
import datetime as dt
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

from . import plates

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


def edition_date(from_edate):
    """'0901Z  10/01/26' (digital_tpp from_edate) -> date(2026, 10, 1); None if unreadable."""
    m = re.search(r"(\d\d)/(\d\d)/(\d\d)\s*$", from_edate or "")
    return dt.date(2000 + int(m[3]), int(m[1]), int(m[2])) if m else None


def changed_pdfs(path):
    """(edition, its date, [pdf name of each changed chart's first page]): the plates whose old
    and new edition plates.update reads."""
    edition, day, out = "", None, set()
    for event, el in ET.iterparse(path, events=("start", "end")):
        if event == "start" and el.tag.lower() == "digital_tpp":
            edition, day = el.get("cycle", ""), edition_date(el.get("from_edate"))
        elif event == "end" and el.tag.lower() == "record":
            get = lambda k: (el.findtext(k) or "").strip()
            name, pdf = get("chart_name"), get("pdf_name")
            if get("useraction").upper() == "C" and pdf and not CONT_PAGE.search(name) \
                    and "DELETED" not in pdf.upper():
                out.add(pdf)
            el.clear()
    return edition, day, sorted(out)


def load_dtpp(path, ids, plates_root="."):
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
    cycle, apt, day = "", None, None
    for event, el in ET.iterparse(path, events=("start", "end")):
        tag = el.tag.lower()
        if event == "start" and tag == "digital_tpp":
            cycle, day = el.get("cycle", ""), edition_date(el.get("from_edate"))
        elif event == "start" and tag == "airport_name":
            apt = (el.get("apt_ident") or "").upper()
        elif event == "end" and tag == "record":
            if apt in ids:
                get = lambda k: (el.findtext(k) or "").strip()
                name = get("chart_name")
                chart = CONT_PAGE.sub("", name)
                pages[(apt, get("chart_code").upper(), chart)].append(
                    {"first": name == chart, "act": get("useraction").upper(), "amdt": get("amdtnum"),
                     "amdt_date": get("amdtdate"), "pdf": get("pdf_name"), "procuid": get("procuid")})
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
        moved = []
        if act == "C" and pdf and day and key not in renamed:
            moved = plates.changes_for(pdf, plates.previous(day), cycle, plates_root)
        out[apt].append(_record(apt, code, chart, act, first["amdt"], pdf, cycle, renamed.get(key),
                                amended=_amended(first["amdt_date"], day), moved=moved))
    return out


def _amended(amdt_date, day):
    """True if the chart's amendment is dated this edition (a new amendment), False if it's
    older (the FAA redrew the plate under the same amendment: 1,347 of 1,665 changed approaches
    in 2609), None if the metafile doesn't say."""
    try:
        return dt.datetime.strptime(amdt_date, "%m/%d/%Y").date() == day if day else None
    except ValueError:
        return None


def _moved(moved, most=3):
    """'074° now 076°, 254° now 256°' (at most `most`, then 'and N more')."""
    s = ", ".join(f"{a}° now {b}°" for a, b in moved[:most])
    return s + (f" and {len(moved) - most} more" if len(moved) > most else "")


def _record(apt, code, name, act, amdt, pdf, cycle, was=None, amended=None, moved=()):
    what = DTPP_KINDS.get(code, code.lower() or "chart")
    verb = DTPP_ACTIONS[act]
    if code in PROCEDURE_CODES:
        s = f"{what} {name} {verb}"
        if was:
            s = f"{what} {name} replaces {was}"
        elif act == "C" and amdt:
            lbl = "original" if amdt.upper() in ("0", "ORIG") else f"amdt {amdt}"
            s = (f"{what} {name} amended ({lbl})" if amended else
                 f"{what} {name} redrawn (still {lbl})" if amended is False else
                 f"{what} {name} changed ({lbl})")
        pri = "ifr"
    else:
        s = f"{what} {verb}" if code == "APD" else f"{what} ({name}) {verb}"
        pri = "fyi" if code in ("APD", "HOT") else "ifr"
    rec_details = None
    if moved:
        s += f": {_moved(moved)} on the chart"
        rec_details = [f"printed on the chart: {a}° -> {b}°" for a, b in moved]
    chart = {"code": code, "name": name, "amdt": amdt}
    if was:
        chart["replaces"] = was
    if cycle and pdf and act != "D":
        chart["pdf"] = f"https://aeronav.faa.gov/d-tpp/{cycle}/{pdf}"
    rec = {"airport": apt, "source": "d-TPP", "kind": verb, "priority": pri,
           "summary_override": s, "chart": chart}
    if rec_details:
        rec["details"] = rec_details
    return rec


# seconds a build spends reading plates before it carries on with what it has. a full 56-day
# edition is ~3,200 changed charts, two pdfs each; the next build (10 min later) picks up the rest
PLATE_BUDGET = 480


def read_plates(path, budget=PLATE_BUDGET, root=".", log=print):
    """read the old and new plate of every chart this metafile changed (plates.update).
    returns how many are still unread (0: every changed chart's plates are in plates/), None if
    the metafile has no edition or this machine can't read pdfs."""
    edition, day, pdfs = changed_pdfs(path)
    if not edition or not day:
        log(f"  plates: {path} doesn't say its edition, not reading plates")
        return None
    return plates.update(plates.previous(day), edition, pdfs, budget, root, log)
