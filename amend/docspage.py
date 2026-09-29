"""
site/docs/: the docs (docs.amend.watch, see amend/subsite.py). How the whole process works, from the
FAA posting a file to a change on a pilot's screen, plus the sources, the limits and the public files.

Written for pilots and schools, not programmers: docs/data-pipeline.md and docs/architecture.md in
the repo have the same process with file and line references. When the pipeline changes, change both.
Anchors #how, #sources, #limits, #api and #open are linked from the site, the app and older pages, so
keep them (MOVED_JS and MOVED_FROM forward the ones that moved to another page).
"""
import datetime as dt
import html
import json
import os
import re

from . import gold, runlog, subsite, web
from .web import DTPP_SEARCH, FAA_INQUIRY, NASR_PAGE, REPO_URL, REPORT_URL, SITE_URL

CSS = """<style>
.dx{display:grid;grid-template-columns:220px minmax(0,1fr);column-gap:48px;align-items:start}
.dx-toc{position:sticky;top:76px;max-height:calc(100vh - 92px);overflow-y:auto;font-size:13.5px;padding:4px 0 16px}
.dx-toc .g{font:600 11px/1.4 var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--fn);margin:18px 0 6px 12px}
.dx-toc .g:first-child{margin-top:0}
.dx-toc a,.dx-jump a{display:block;padding:5px 12px;color:var(--dm);border-radius:6px}
.dx-toc a:hover{color:var(--tx);background:var(--p2);text-decoration:none}
.dx-p{font-weight:500;margin-top:2px}.dx-p.on{color:var(--tx)!important;font-weight:600}
.dx-s{margin:2px 0 10px 12px;border-left:1px solid var(--ln)}.dx-s a{padding:4px 12px;font-size:13px;border-radius:0 6px 6px 0;margin-left:-1px;border-left:2px solid transparent}
.dx-s a.on{color:var(--tx);background:var(--p2);border-left-color:var(--am);font-weight:500}
.dx-crumb{font:600 12px/1.4 var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--am);margin:0 0 8px}
.dx pre{margin:10px 0 14px;padding:12px 14px;border:1px solid var(--ln);border-radius:8px;overflow-x:auto;font:12.5px/1.6 var(--mono)}
.dx pre code{background:none;padding:0;font:inherit;overflow-wrap:normal}
.dx .tw{margin:10px 0 16px;overflow-x:auto;border:1px solid var(--ln);border-radius:8px}.dx .tw.xs{--sh:var(--p)}
.dx-tb{border-collapse:collapse;width:100%;font-size:13.5px;line-height:1.55}
.dx-tb th,.dx-tb td{text-align:left;vertical-align:top;padding:8px 12px;border-top:1px solid var(--ln)}
.dx-tb th{border-top:0;background:var(--p2);font-weight:600;font-size:12.5px;color:var(--dm);white-space:nowrap}
.dx-tb td:first-child{white-space:nowrap}.dx-tb td:not(:first-child) code{overflow-wrap:anywhere}
.dx-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:6px}
.dx-card{display:block;padding:14px 16px;border:1px solid var(--ln);border-radius:10px;background:var(--p);color:var(--tx)}
.dx-card:hover{border-color:var(--ln2);text-decoration:none}.dx-card b{display:block;margin-bottom:2px}.dx-card span{color:var(--dm);font-size:14px;line-height:1.5}
@media (max-width:560px){.dx-cards{grid-template-columns:minmax(0,1fr)}}
.dx-body{max-width:46rem;min-width:0}
.dx h1{font:600 32px/1.15 var(--sans);letter-spacing:-.5px;margin:0 0 10px}
.dx .lede{font-size:17px;line-height:1.55;color:var(--dm);margin:0 0 8px}
.dx section{padding-top:28px;margin-top:28px;border-top:1px solid var(--ln);scroll-margin-top:72px}
.dx h2{font:600 21px/1.3 var(--sans);letter-spacing:-.25px;margin:0 0 12px}
.dx h2 a{color:inherit}.dx h2 a:hover{text-decoration:none}.dx h2 a::after{content:" #";color:var(--ln2);opacity:0}.dx h2:hover a::after{opacity:1}
.dx h3{font:600 16px/1.4 var(--sans);margin:22px 0 6px}
.dx p,.dx li{line-height:1.65}.dx p{margin:0 0 12px}.dx ul{padding-left:20px;margin:0 0 12px}.dx li{margin:5px 0}
.dx code{font:13px var(--mono);background:var(--p2);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
.dx-steps{list-style:none;counter-reset:s;padding:0;margin:20px 0 0}
.dx-steps>li{counter-increment:s;position:relative;padding:0 0 22px 48px;margin:0}
.dx-steps>li::before{content:counter(s);position:absolute;left:0;top:0;width:30px;height:30px;border-radius:50%;
border:1px solid var(--ln2);background:var(--p);font:600 13px/28px var(--mono);text-align:center;color:var(--dm)}
.dx-steps>li::after{content:"";position:absolute;left:15px;top:34px;bottom:4px;width:1px;background:var(--ln)}
.dx-steps>li:last-child::after{display:none}
.dx-steps .t{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-weight:600;font-size:16px;line-height:30px}
.dx-steps .t .ann{font-weight:600}.dx-steps p{margin:2px 0 0;color:var(--dm)}
.dx-kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:8px 18px;margin:14px 0;padding:14px 16px;
border:1px solid var(--ln);border-radius:8px;background:var(--p);font-size:14.5px}
.dx-kv dt{font-weight:600}.dx-kv dd{margin:0;color:var(--dm)}
.dx-nn{display:flex;justify-content:space-between;gap:16px;margin-top:40px;padding-top:20px;border-top:1px solid var(--ln);font-size:14px}
.dx-nn a{display:block}.dx-nn small{display:block;color:var(--fn);font-size:12px}.dx-nn .r{text-align:right;margin-left:auto}
@media (max-width:860px){.dx{grid-template-columns:minmax(0,1fr);gap:0}.dx-toc{display:none}.dx h1{font-size:28px}}
.dx-jump{display:none}
@media (max-width:860px){.dx-jump{display:block;margin:4px 0 0;border:1px solid var(--ln);border-radius:8px;background:var(--p)}
.dx-jump>summary{cursor:pointer;padding:10px 14px;font-size:14px;font-weight:500}
.dx-jump nav{padding:0 8px 8px}.dx-jump a{padding:7px 8px;font-size:14px}.dx-jump .dx-s{margin:0 0 6px 8px}}
@media (max-width:479px){.dx-kv{grid-template-columns:minmax(0,1fr);gap:2px}.dx-kv dd{margin-bottom:8px}}
</style>"""

# the table of contents follows the section you're reading
TOC_JS = """<script>(()=>{const a=[...document.querySelectorAll(".dx-toc .dx-s a")];if(!a.length||!("IntersectionObserver" in window))return;
const on=id=>a.forEach(x=>x.classList.toggle("on",x.getAttribute("href")==="#"+id));const seen=new Map(),ids=a.map(x=>x.getAttribute("href").slice(1));
// room under the article so the last section can scroll up to the top on its own, like every other section
const secs=[...document.querySelectorAll(".dx section[id]")],pad=document.querySelector(".dx-pad");
const fit=()=>{if(!pad||!secs.length)return;pad.style.height="0";const top=secs[secs.length-1].getBoundingClientRect().top+scrollY-72;
  pad.style.height=Math.max(0,innerHeight-(document.documentElement.scrollHeight-top))+"px"};fit();addEventListener("resize",fit);
let hold=0;const pick=()=>{if(Date.now()<hold)return;const first=ids.find(id=>seen.get(id));if(first)on(first)};
// a clicked item is the one lit, even while the page is still scrolling to it
a.forEach(x=>x.addEventListener("click",()=>{on(x.getAttribute("href").slice(1));hold=Date.now()+800}));
const io=new IntersectionObserver(es=>{es.forEach(e=>seen.set(e.target.id,e.isIntersecting));pick()},{rootMargin:"-70px 0px -60% 0px"});
secs.forEach(s=>io.observe(s))})()</script>"""


def tag(text):
    return f'<span class="ann fyi">{text}</span>'


def step(title, kind, text):
    return f'<li><div class="t">{title} {tag(kind)}</div><p>{text}</p></li>'


def sections():
    guide, status = f"{SITE_URL}guide/", web.sub_url("status")
    using = web.sub_url("docs", None, "using/")
    how = "".join([
        step("Check the FAA", "every 10 minutes", (
            "A timer asks GitHub to run Amend's check every 10 minutes. The check reads only the first few bytes "
            "of each FAA file, so it takes seconds, and compares what the FAA has with what the site shows. It "
            "starts a build when the FAA has posted something new, when Amend's code or data changed, when chart "
            "or airspace files were missing last time, or when the last build is more than 20 hours old. Most "
            "checks stop here.")),
        step("Run the tests", "check", (
            "Before downloading anything, the build runs Amend's tests, including a gold set of real FAA changes "
            "with the answer each should get and a snapshot of everything Amend says about one real pair of "
            "cycles. If any test fails, the build stops.")),
        step("Download the FAA files", "code", (
            "The NASR data for the two cycles being compared, the chart index and the class airspace shapes. "
            "Each download gets three tries, and every file is checked before it's used: every entry in a zip is "
            "tested, the tables Amend needs have to be there, and the file's SHA-256 checksum goes in the run "
            "log. A file the FAA hasn't posted yet is noted as not posted; a broken or cut-off one stops the "
            "build.")),
        step("Check the inputs", "check", (
            "Row counts per table, old cycle against new. A table that loses more than 10% of its rows, gains "
            "more than 50%, goes missing or comes back empty stops the build, because a half-read file would "
            "otherwise show up as thousands of removed rows. Smaller swings are flagged for review.")),
        step("Read the data", "code", (
            "Every row is tied to the airport it's about. Columns that change every cycle for no reason "
            "(effective dates, last-response dates) are dropped, and navaids are attached to the public airports "
            "within 10 NM.")),
        step("Compare the two cycles", "code", (
            "Rows that are identical in both cycles drop out. Each removed row is paired with the added row that "
            "matches it, like the same runway end or the same frequency, and becomes one changed record listing "
            "each field's old and new value. Anything left over is an addition or a removal.")),
        step("Hide the bookkeeping", "code", (
            "Survey dates, coordinate rounding, sequence numbers, pavement ratings, remarks the FAA re-filed "
            "word for word and airspace boundaries that moved by less than 2% of their area or 0.2 NM are "
            "counted but not shown. In the 1 Oct 2026 cycle that hid 2,525 changes and left 2,026.")),
        step("Group rows into events", "code", (
            "One real event is one line: a renumbered runway instead of a dozen runway-end rows, a new STAR "
            "version with the waypoints that moved, a remark repeated on two frequencies said once.")),
        step("Sort by how it affects you", "code", (
            f'Each change gets ACT, IFR or FYI from fixed rules. <a href="{using}#labels">How the labels work</a>.')),
        step("Write it in plain English", "code", (
            "Every summary line is written from the FAA's own values. Contractions in FAA remarks are decoded "
            f'under a no-guess check. <a href="{using}#remarks">How remarks work</a>.')),
        step("Add charts and airspace", "code", (
            "Approach, STAR and departure charts added, amended or removed in the new cycle, each linked to its "
            "plate, and changes to Class B, C, D and E surface airspace over each airport.")),
        step("Audit the release", "check", (
            "No change can be listed twice, carry junk text like \"None\" or \"undefined\", or link a chart from "
            "the wrong cycle, and the cycle dates have to sit on the FAA's 28-day schedule. The number of ACT items "
            "is compared with recent cycles: 2.5 times the usual is flagged, 5 times stops the build. Fewer than 100 "
            "airports changed stops it too; every cycle since 2024 changed more than 440. Frequencies and runway "
            "names that don't look real are flagged for review.")),
        step("Check the built site", "check", (
            "Before it goes live, the finished site is checked for completeness: the home page, every airport in "
            "the index with its page and its data file, more than 5,000 airports in the directory, cycle dates "
            "that make sense, the history and the status page.")),
        step("Publish", "code", (
            "The change history and the run log are saved to the public GitHub repo, then the site is published. "
            "The website and the iPhone app read the same files. A new FAA post is usually live within about 20 "
            "minutes, as long as the timer and GitHub start the runs on time.")),
        step("Switch at 0901Z", "clock", (
            "A new cycle shows as upcoming until it takes effect at 0901Z on cycle day. Pages and the app switch "
            "to in effect on the second, even if they're open, using a clock checked against the server's in "
            "case your device's is off. No build has to run for it.")),
    ])
    return [
        ("what", "What Amend does", (
            "<p>Every 28 days the FAA publishes a new cycle of airport, frequency, navaid, airspace and chart data. "
            "The changes that matter, like new tower hours, a decommissioned VOR, a renumbered runway or an amended "
            "approach, are buried among tens of thousands of rows that changed for bookkeeping reasons.</p>"
            "<p>Amend compares every cycle with the one before for every US airport, hides the bookkeeping, and "
            "explains what's left in plain English, sorted by how much it matters when you fly there. The FAA posts each "
            "cycle before it takes effect, so Amend shows changes before they happen.</p>"
            "<p>What changed and how much it matters are decided by fixed rules, the same way every cycle.</p>")),
        ("cycle", "FAA cycles", (
            "<p>The FAA's aeronautical data runs on a fixed 28-day schedule. Each cycle takes effect at 0901Z on its "
            "effective date, and the FAA posts its files ahead of time: the chart index says 20 days ahead.</p>"
            '<dl class="dx-kv"><dt>In effect</dt><dd>The cycle that applies today.</dd>'
            "<dt>Upcoming</dt><dd>The next cycle, once the FAA has posted it. Amend shows its changes against the "
            "cycle in effect, with the current value first.</dd>"
            f'<dt>Calendar</dt><dd>Every cycle date is in <a href="{SITE_URL}cycles.ics">cycles.ics</a>, which '
            "you can add to any calendar app.</dd></dl>")),
        ("how", "How a cycle becomes a page", (
            "<p>Every run goes through the same steps, and each one is written to a public run log. If any step "
            "fails, nothing is published and the site stays on the last good build.</p>"
            f'<ol class="dx-steps">{how}</ol>')),
        ("labels", "ACT, IFR and FYI", (
            "<p>Every change gets one label, from fixed rules in the code:</p><ul>"
            "<li><b>ACT</b>: could change your plan. Tower and Class D hours, frequencies, runways opened, "
            "closed or renumbered, lighting, pattern altitude, attendance, navaids removed, airspace, and remarks "
            "with words like closed, PPR or not available.</li>"
            "<li><b>IFR</b>: instrument procedures. Approaches, STARs and departures added, amended or removed, and "
            "navaid and ILS details.</li>"
            "<li><b>FYI</b>: everything else worth knowing, like a new phone number, a reworded remark or an "
            "obstacle that moved a little.</li></ul>"
            f'<p>The <a href="{guide}">guide</a> shows how to read a change, with examples.</p>')),
        ("remarks", "Remarks in plain English", (
            "<p>FAA remarks are written in contractions (<code>RWY 18 CLSD TO ACFT OVR 12500 LBS</code>). Amend "
            "decodes them with an AI model, under rules enforced in code:</p><ul>"
            "<li><b>A verified glossary.</b> Every meaning comes word for word from the FAA's own lists: the Chart "
            "Supplement's abbreviations and FAA Order JO 7340.2, Contractions. A contraction the FAA doesn't "
            "define stays exactly as written.</li>"
            "<li><b>No guessing.</b> A translation may only expand a contraction to its verified meaning. It has to "
            "keep every number, time, runway, frequency and code, in order, and it can't add words the remark "
            "doesn't have, like \"the runway\" or \"is available\".</li>"
            "<li><b>The FAA text wins.</b> Any translation that breaks a rule is thrown out and the FAA's own text "
            "is shown instead. The original is always one tap away, translated or not.</li></ul>"
            "<p>That means some remarks show as FAA text. On the 1 Oct 2026 preview, about 94% of the changed "
            f'remarks on airport pages read in plain English. The <a href="{status}">status page</a> shows the '
            "current count.</p>")),
        ("checks", "What stops a bad update", (
            "<p>Amend would rather show nothing new than show something wrong. Each of these stops a build, and "
            "the site stays on the last version that passed everything:</p><ul>"
            "<li>a failing test, before anything is downloaded;</li>"
            "<li>an FAA file that's cut off, corrupt or missing a table;</li>"
            "<li>a table whose row count jumps or drops too far;</li>"
            "<li>a release audit error: a change listed twice, junk text, a chart from the wrong cycle, cycle dates off "
            "the FAA's schedule, or far too many ACT items;</li>"
            "<li>a built site that's incomplete or inconsistent.</li></ul>"
            "<p>What never stops a build is a remark translation failing its check: that remark just shows the FAA "
            "text. Changes whose summary would name a value the FAA record doesn't have show the FAA values "
            "instead.</p>")),
        ("status", "The status page", (
            f'<p><a href="{status}">The status page</a> is the short version of the run log.</p>'
            '<dl class="dx-kv">'
            "<dt>Headline</dt><dd>Whether Amend is up to date. It turns to <b>Amend is behind</b> on its own, in "
            "your browser, when no run has published for 30 hours or the FAA's schedule has moved past the cycle "
            "Amend shows. If the latest build found the FAA simply hasn't posted the next cycle yet, it says "
            "<b>Waiting on the FAA</b> instead: that's a delay at the FAA, not an Amend outage.</dd>"
            "<dt>FAA cycle</dt><dd>The cycle in effect and the next one.</dd>"
            "<dt>Processing</dt><dd>The latest build: when it ran, which cycles it compared and what it found.</dd>"
            "<dt>Checks</dt><dd>Errors and warnings from the input checks, the release audit and the pre-publish "
            "check.</dd>"
            "<dt>Plain-English remarks</dt><dd>How many changed remarks read in plain English, and whether the "
            "translator was reachable.</dd>"
            "<dt>Website and data files</dt><dd>When the site and its files were last published.</dd>"
            "<dt>Checks for new FAA data</dt><dd>When Amend last checked the FAA, and the recent checks, one every "
            "10 minutes. Most find nothing new and stop after a few seconds, so they build nothing.</dd>"
            "<dt>Recent builds</dt><dd>The last 30 builds, oldest on the left: green published, blue waiting, "
            "magenta blocked or crashed, grey skipped. Hover or tap one for its exact time.</dd>"
            "<dt>Problems</dt><dd>Every blocked or crashed run in the last three cycles, with the reason.</dd>"
            "</dl>"
            "<p>The status page is published with the site, so a blocked run appears there after the next run that "
            "passes. If any page is more than a day and a half old, a banner at the top says so.</p>"
            "<p>Under <b>Every step of the latest build</b>, <b>Done</b> means a step ran and its numbers are shown, "
            "<b>Passed</b> means a check ran and found nothing wrong, <b>Not recorded</b> means the run didn't log "
            "that value, and <b>Not run</b> means the run stopped before that step.</p>")),
        ("sources", "Data sources", (
            "<ul>"
            f'<li><b><a href="{NASR_PAGE.format(cycle="")}">NASR 28-day subscription</a>:</b> airports, runways, '
            "frequencies, tower hours, navaids, weather stations and the Chart Supplement remarks. Airport history "
            "on Amend goes back to Aug 2024.</li>"
            f'<li><b><a href="{DTPP_SEARCH}">d-TPP</a>:</b> the chart index for approaches, STARs and departures, '
            "with a link to each plate.</li>"
            "<li><b>FAA class airspace shapefiles:</b> Class B, C, D and E surface area floors, ceilings and "
            "boundaries.</li></ul>"
            "<p>Every change links the FAA source it came from, so you can check it against the original in one "
            "tap.</p>")),
        ("open", "Open source and reporting problems", (
            f'<p>The engine, the rules and the site are <a href="{REPO_URL}">on GitHub</a> under the MIT license. '
            f'Found something wrong? <a href="{REPORT_URL}">Open an issue</a> with the airport, the cycle and what '
            "the FAA source says. If the FAA's own data is wrong, only the FAA can fix it: "
            f'use its <a href="{FAA_INQUIRY}">Aeronautical Inquiries</a> page.</p>')),
    ]




CS_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dafd/"
NOTAM_SEARCH = "https://notams.aim.faa.gov/notamSearch/"
SHOWN_REMARKS_FROM = (1, 3, 6)   # engine 1.3.6 on: remarks.texts counts only the remarks a page reads out


def gold_counts(path=gold.CASES):
    """the gold set as it stands in the repo: its size, how many a person checked, and by label."""
    cases = gold.load_cases(path)
    by = {k: sum(c["expected"].get("priority") == k for c in cases) for k in gold.PRIORITIES}
    return {"total": len(cases),
            "human": sum("needs human check" not in c.get("verified_by", "needs human check") for c in cases),
            "known": sum(bool(c.get("known_failure")) for c in cases), "by": by}


def shown_remarks(log_dir=runlog.RUNS):
    """(plain English, shown, finished_at) from the newest published build that counts shown remarks, or None."""
    for rec in reversed(runlog.runs(log_dir, last_cycles=2)):
        rm, eng = rec.get("remarks") or {}, str(rec.get("engine") or "")
        try:
            new = tuple(int(x) for x in eng.split(".")[:3]) >= SHOWN_REMARKS_FROM
        except ValueError:
            new = False
        if rec.get("published") and new and isinstance(rm.get("texts"), int) and isinstance(rm.get("plain_english"), int):
            return rm["plain_english"], rm["texts"], rec.get("finished_at") or rec.get("started_at")
    return None


def accuracy_sections(log_dir=runlog.RUNS, cases=gold.CASES):
    """the accuracy and limits page. Every number is read at build time: the gold set from the repo, the
    remark count from the run log. Nothing here is an estimate."""
    g, rm = gold_counts(cases), shown_remarks(log_dir)
    using, status = web.sub_url("docs", None, "using/"), web.sub_url("status")
    n = lambda x: f"{x:,}"
    known = (f" {g['known']} of them are marked as known mistakes the engine still makes; every other case has to "
             "come out right." if g["known"] else " Every case has to come out right.")
    if rm:
        try:
            when = f" ({dt.datetime.fromisoformat(rm[2]):%d %b %Y})"
        except (TypeError, ValueError):
            when = ""
        rem = (f"<p>In the latest build{when}, <b>{n(rm[0])} of the {n(rm[1])}</b> changed remarks "
               f"shown on airport pages read in plain English. The other {n(rm[1] - rm[0])} show the FAA's own text. "
               f'The <a href="{status}">status page</a> has the count for every build.</p>')
    else:
        rem = f'<p>The <a href="{status}">status page</a> shows how many remarks read in plain English in each build.</p>'
    return [
        ("measured", "What's measured", (
            "<p>Amend doesn't publish an overall accuracy percentage. A number like that would need a large, "
            "random set of changes checked by hand against the FAA source, and that set doesn't exist yet. What "
            "this page gives instead is what's actually been counted, read from the project's own files each time "
            "the site is built.</p>")),
        ("gold", "The test set", (
            f"<p>Amend keeps a test set of <b>{n(g['total'])} real FAA changes</b>, each with the FAA's own old and "
            "new rows and the answer Amend should give: its label, its category, and words the plain-English line "
            f"has to contain. It covers {n(g['by']['action'])} ACT, {n(g['by']['ifr'])} IFR and "
            f"{n(g['by']['fyi'])} FYI changes, plus {n(g['by']['hidden'])} bookkeeping edits Amend should say "
            f"nothing about.</p><p>Every build runs the whole set before it downloads anything.{known} If one "
            "comes out wrong, the build stops and the site stays on the last version that passed.</p>"
            f"<p><b>{n(g['human'])} of the {n(g['total'])}</b> have been checked by a person, with the FAA's old "
            "and new text side by side and every abbreviation decoded from the FAA's own lists. The other "
            f"{n(g['total'] - g['human'])} were written from the FAA rows and still wait for that check. Pilots and "
            "instructors who check more cases raise that number here as their checks are added.</p>"
            "<p>Passing the set means Amend gets these cases right. It doesn't prove it gets every change right, "
            "and a case is only as good as the answer written for it.</p>")),
        ("remark-count", "Plain-English remarks", (
            rem + "<p>A remark only reads in plain English when its translation passes the no-guess check: every "
            "contraction expanded to a meaning taken word for word from the FAA's own lists, every number, time, "
            "runway, frequency and code kept in order, and no words the remark doesn't have. Anything else shows "
            f'the FAA text. <a href="{using}#remarks">How remarks work</a>.</p>')),
        ("limits", "What it doesn't cover", (
            "<ul><li><b>NOTAMs.</b> Temporary changes, closures and outages are published as NOTAMs and never show "
            "up on Amend.</li>"
            "<li><b>Changes between cycles.</b> Amend only reads the FAA's 28-day files. A correction the FAA makes "
            "mid-cycle, usually by NOTAM, shows up here in a later cycle, if at all.</li>"
            "<li><b>Parts of the Chart Supplement that aren't in the FAA's data files.</b> The printed Chart "
            "Supplement also has airport sketches, its notices sections and other pages Amend never sees. Airport "
            "remarks from the data files are covered.</li>"
            "<li><b>What's drawn on a chart.</b> For approaches, departures and arrivals Amend reports that a chart "
            "was added, amended or removed, with a link to the new plate. It doesn't compare the drawings, so read "
            "the plate itself.</li>"
            "<li><b>Class E airspace above the surface</b> (E5, starting at 700 or 1,200 ft). Class B, C, D and E "
            "surface areas are covered.</li>"
            "<li><b>Chart history before fall 2026</b>, because the FAA doesn't keep old chart indexes online. "
            "Airport data goes back to Aug 2024.</li>"
            "<li><b>A plain-English version of every remark.</b> When a translation doesn't pass the check, you "
            "get the FAA text instead.</li>"
            "<li><b>What the FAA hasn't posted yet.</b> A new cycle appears after the FAA posts it and a build "
            "runs, usually within about 20 minutes.</li></ul>"
            "<p>Amend is not for navigation. Use it to see what changed, then check the official sources "
            "below.</p>")),
        ("official", "The official sources", (
            "<ul>"
            f'<li><a href="{CS_PAGE}">Chart Supplement</a>: airport information, remarks and notices.</li>'
            f'<li><a href="{DTPP_SEARCH}">Terminal procedures (d-TPP)</a>: approach, departure and arrival '
            "charts.</li>"
            f'<li><a href="{NOTAM_SEARCH}">NOTAM search</a>: temporary changes.</li>'
            f'<li><a href="{NASR_PAGE.format(cycle="")}">NASR subscription</a>: the data files Amend reads.</li>'
            "</ul>")),
        ("report", "Reporting an error", (
            f'<p>If Amend shows something wrong, <a href="{REPORT_URL}">report it</a> with the airport, the cycle '
            "and what the FAA source says. A confirmed mistake is fixed in the engine and added to the test set, "
            "so it can't come back unnoticed. If the FAA's own data is wrong, only the FAA can fix it: use its "
            f'<a href="{FAA_INQUIRY}">Aeronautical Inquiries</a> page.</p>')),
    ]


def more_sections():
    """the sections the getting-started and using pages add to the ones above."""
    site, guide = SITE_URL, f"{SITE_URL}guide/"
    card = lambda href, title, text: f'<a class="dx-card" href="{href}"><b>{title}</b><span>{text}</span></a>'
    return [
        ("start", "Quick start", (
            '<ol class="dx-steps">'
            + step("Find your airport", "search", (
                f'Search on <a href="{site}">amend.watch</a> by FAA ID (<code>DAB</code>), ICAO code '
                "(<code>KDAB</code>), name or city. If an airport has no changes on record, Amend says so."))
            + step("Read what changed", "airport page", (
                "Changes are sorted ACT first, then IFR, then FYI. Each one says what changed in plain English, "
                "shows the old and new values, and links the FAA source it came from."))
            + step("Keep a list", "lists", (
                "Add the airports you fly to a list from any airport page. Lists stay in your browser: no account, "
                "nothing sent anywhere. The home page then shows what's coming up at your airports first."))
            + step("Get alerts", "optional", (
                "Every airport and list has an alert feed (RSS). Paste its link into a news reader app and you "
                f'hear about the next change without checking. <a href="{site}cycles.ics">cycles.ics</a> puts '
                "every cycle date in your calendar."))
            + "</ol>")),
        ("next", "Where to go next", (
            '<div class="dx-cards">'
            + card(web.sub_url("docs", None, "using/"), "Using Amend",
                   "Reading a change, the labels, remarks, lists and alerts.")
            + card(web.sub_url("docs", None, "how-it-works/"), "How it works",
                   "Every step from the FAA's files to your screen, and what stops a bad update.")
            + card(web.sub_url("docs", None, "api/"), "API and data",
                   "The public JSON files behind the site, for your own tools.")
            + card(web.sub_url("status"), "Status", "Whether Amend is up to date right now.")
            + "</div>")),
        ("airport", "Reading an airport page", (
            "<p>An airport page lists what changes between the cycle in effect and the next one, or, once the new "
            "cycle is in effect, what just changed. Each change has:</p><ul>"
            "<li><b>A label</b>: ACT, IFR or FYI (below).</li>"
            "<li><b>A summary</b> in plain English, like a tower that now closes an hour earlier.</li>"
            "<li><b>The values</b> before and after, as the FAA wrote them.</li>"
            "<li><b>The FAA source</b> it came from, so you can check the original.</li></ul>"
            "<p>Below that are the airport's earlier cycles, back to Aug 2024, so you can see what changed since "
            f'you last flew there. The <a href="{guide}">guide</a> walks through real examples.</p>')),
        ("ahead", "Seeing changes ahead of time", (
            "<p>The FAA posts each cycle before it takes effect. Once it's posted, Amend shows the changes as "
            "<b>coming up</b>, with the value in effect today first and the new one after it, and a countdown to "
            "the switch.</p>"
            "<p>At 0901Z on cycle day, every page switches to <b>in effect</b> on its own, even if "
            "it's already open. They use a clock checked against the server's, in case your device's clock "
            "is off.</p>")),
        ("lists", "Lists", (
            "<p>A list is a set of airports you want to follow: your home field, a training area, a trip. You can "
            "keep several, each with up to 200 airports.</p><ul>"
            "<li><b>Add an airport</b> from its page. The home page shows what's coming up at the airports on "
            "your lists, and which list each one is on.</li>"
            "<li><b>Share a list</b> with its link. Whoever opens it sees the same airports and can save a copy "
            "to their own lists.</li>"
            f'<li><b>Named lists</b>, like <a href="{site}list/daytona-training/">daytona-training</a>, have a '
            "fixed address and their own alert feed, for a school or club.</li></ul>"
            "<p>Your own lists are stored in your browser only. Clearing site data removes them, and they don't "
            "move between devices, so share the link to yourself to copy one.</p>")),
        ("alerts", "Alerts and the cycle calendar", (
            "<p>Amend has no accounts and sends no email. Instead, every airport and every named list has an RSS "
            "feed with one item per cycle with changes. Paste the feed's link into a news reader app (Feedly, "
            "Inoreader, NetNewsWire) and new changes show up there.</p><ul>"
            f"<li><b>One airport:</b> <code>{site}DAB/feed.xml</code>, or <b>Get alerts</b> on its page.</li>"
            f"<li><b>A named list:</b> <code>{site}list/daytona-training/feed.xml</code>.</li>"
            "<li><b>Your own list:</b> its page has <b>Download all alerts</b>, one file that adds a feed for "
            "every airport on it to your reader.</li>"
            f'<li><b>Cycle dates:</b> <a href="{site}cycles.ics">cycles.ics</a> adds every changeover at 0901Z '
            "to your calendar.</li></ul>")),
    ]


# ---- the API page, built from SCHEMA.md so it can't drift from the files' real contract ----

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SCHEMA.md")
# SCHEMA.md heading -> (anchor, heading on the page). Only these are part of the JSON contract
SCHEMA_PARTS = {"`latest/meta.json`": ("meta", "latest/meta.json"), "`latest/index.json`": ("index", "latest/index.json"),
                "`latest/<ID>.json`": ("airport", "latest/<ID>.json"), "Change": ("change", "The Change object"),
                "`airports.json`": ("airports", "airports.json"), "`history/<ID>.json`": ("history", "history/<ID>.json"),
                "`history/index.json`": ("history-index", "history/index.json")}


def inline(text):
    """SCHEMA.md's inline markdown (`code`, **bold**) to HTML, escaping everything else."""
    out = []
    for i, part in enumerate(re.split(r"`([^`]*)`", text)):
        if i % 2:
            out.append(f"<code>{html.escape(part)}</code>")
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(part, quote=False)))
    return "".join(out)


def md(block):
    """the small slice of markdown SCHEMA.md uses: paragraphs, pipe tables and fenced code."""
    out, para, lines, i = [], [], block.split("\n"), 0
    flush = lambda: (out.append(f"<p>{inline(' '.join(para))}</p>"), para.clear()) if para else None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append(f'<pre class="xs"><code>{html.escape(chr(10).join(lines[i + 1:j]))}</code></pre>')
            i = j + 1
            continue
        if ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    rows.append(cells)
                i += 1
            head, *body = rows
            out.append('<div class="tw xs"><table class="tb dx-tb"><tr>' + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</table></div>")
            continue
        if ln.strip():
            para.append(ln.strip())
        else:
            flush()
        i += 1
    flush()
    return "".join(out)


def schema():
    """SCHEMA.md as {heading: markdown body}, plus the intro (key "")."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        text = f.read()
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    out = {"": parts[0].split("\n", 1)[1] if "\n" in parts[0] else ""}
    for k in range(1, len(parts), 2):
        out[parts[k].strip()] = parts[k + 1].strip()
    return out


def api_sections():
    site = SITE_URL
    sch = schema()
    missing = [h for h in SCHEMA_PARTS if h not in sch]
    if missing:   # a renamed heading in SCHEMA.md would otherwise drop that file from the docs without a word
        raise ValueError(f"SCHEMA.md has no section {missing}; update SCHEMA_PARTS in docspage.py")
    files = [("latest/meta.json", "meta", "Which two cycles are compared, and when the newer one takes effect."),
             ("latest/index.json", "index", "Every airport with changes, with its ACT, IFR and FYI counts."),
             ("latest/<ID>.json", "airport", "Every change at one airport. A 404 means nothing changed there."),
             ("airports.json", "airports", "Every airport in the current cycle, for names and search."),
             ("history/<ID>.json", "history", "Every change at one airport since Aug 2024."),
             ("history/index.json", "history-index", "Which cycles and airports have history."),
             ("<ID>/feed.xml", "feeds", "An airport's alert feed (RSS 2.0)."),
             ("cycles.ics", "feeds", "Every cycle changeover, as a calendar.")]
    table = ('<div class="tw xs"><table class="tb dx-tb"><tr><th>File</th><th>What it holds</th></tr>'
             + "".join(f'<tr><td><a href="#{a}"><code>{html.escape(p)}</code></a></td><td>{t}</td></tr>' for p, a, t in files)
             + "</table></div>")
    fetch_js = html.escape(
        'const base = "https://amend.watch/";\n'
        'const meta = await (await fetch(base + "latest/meta.json")).json();\n'
        'const res = await fetch(base + "latest/DAB.json");\n'
        'if (res.status === 404) {\n'
        '  console.log("No changes at DAB for", meta.to_cycle);\n'
        '} else {\n'
        '  const { changes } = await res.json();\n'
        '  for (const c of changes) console.log(c.priority.toUpperCase(), c.summary);\n'
        '}')
    out = [
        ("overview", "Overview", (
            "<p>Everything Amend shows is built from plain JSON files that anyone can download. There's no key, "
            "no sign-up and nothing to install, and you're welcome to build on them.</p>"
            '<dl class="dx-kv">'
            f"<dt>Base URL</dt><dd><code>{site}</code></dd>"
            "<dt>Format</dt><dd>Minified UTF-8 JSON, one file per question. Just <code>GET</code> it.</dd>"
            "<dt>From a browser</dt><dd>The files are on GitHub Pages, which lets any website fetch them (CORS).</dd>"
            "<dt>Airport IDs</dt><dd>FAA IDs, like <code>VRB</code>, not <code>KVRB</code>. "
            "<code>airports.json</code> maps them to ICAO codes.</dd>"
            "<dt>Dates</dt><dd>Cycles are ISO dates of the FAA effective date (<code>2026-10-01</code>). Times are "
            "UTC.</dd>"
            "<dt>Updates</dt><dd>The files change when a build publishes: when the FAA posts a new cycle, usually "
            "within about 20 minutes. The cycle itself takes effect at 0901Z on its date, by the clock, with no "
            "new files needed.</dd></dl>"
            f'<p>The data carries the same warning as the site: <a href="{site}terms/">not for navigation</a>. '
            "Always use official FAA publications and NOTAMs to fly.</p>")),
        ("quickstart", "Quick start", (
            "<p>Which cycles are compared, then every change coming up at Daytona Beach (DAB):</p>"
            f"<pre class=\"xs\"><code>curl {site}latest/meta.json\ncurl {site}latest/DAB.json</code></pre>"
            f"<p>The same in JavaScript, in a browser or Node 18 and later:</p><pre class=\"xs\"><code>{fetch_js}</code></pre>"
            "<p>A <b>404 on an airport file means no changes</b> at that airport, not an error.</p>")),
        ("files", "Files", table),
    ]
    for head, (anchor, title) in SCHEMA_PARTS.items():
        out.append((anchor, html.escape(title), md(sch[head])))
    out += [
        ("recipes", "Recipes", (
            "<h3>Badge the airports someone saved</h3>"
            "<p>Download <code>latest/index.json</code> once and look each airport up in <code>airports</code>. "
            "Only fetch <code>latest/&lt;ID&gt;.json</code> for the ones that are there.</p>"
            "<h3>Is the new cycle in effect yet?</h3>"
            "<p>Compare <code>effective</code> in <code>latest/meta.json</code> with the time now. Don't rely on "
            "<code>upcoming</code> alone: it was true when the file was built, and the files aren't rebuilt at "
            "the changeover.</p>"
            "<h3>What changed since I last flew there?</h3>"
            "<p>Fetch <code>history/&lt;ID&gt;.json</code> and keep the entries whose <code>cycle</code> is after "
            "that date.</p>"
            "<h3>Remember what someone has already seen</h3>"
            "<p>Every change has a stable 12-character <code>id</code>. Store the ids a user has seen and highlight "
            "the rest.</p>")),
        ("feeds", "Feeds and calendar", (
            "<ul>"
            f"<li><code>{site}&lt;ID&gt;/feed.xml</code>: RSS 2.0 for any airport in <code>airports.json</code>, "
            "one item per cycle with changes, newest first, about a year of them. An item's <code>guid</code> "
            "never changes.</li>"
            f"<li><code>{site}list/&lt;name&gt;/feed.xml</code>: the same for a named list.</li>"
            f"<li><code>{site}cycles.ics</code>: every cycle changeover at 0901Z, as a calendar feed.</li></ul>")),
        ("versions", "Versions and changes", (
            "<p>Every JSON file has a <code>schema_version</code>, now 1. A new field can appear at any time without "
            "changing it, so ignore fields you don't know. Renaming or removing a field raises it.</p>"
            "<p>Each change also records the <code>engine</code> version that made it. The engine's rules, and "
            f'the full contract in <a href="{REPO_URL}/blob/master/SCHEMA.md">SCHEMA.md</a>, are on GitHub. '
            f'If you build on the files and something breaks, <a href="{REPORT_URL}">open an issue</a>.</p>')),
    ]
    return out


# the four pages: (path under docs.amend.watch, title in the menu, h1, lede, description, section ids)
PAGES = [
    ("", "Getting started", "Getting started with Amend",
     "Amend shows what changes in each FAA data cycle at every US airport, in plain English, before it takes effect.",
     "What Amend is, how FAA cycles work, and how to find, follow and get alerts for your airports.",
     ["what", "start", "cycle", "next", "open"]),
    ("using/", "Using Amend", "Using Amend",
     "How to read a change, what the labels mean, how remarks are translated, and how lists and alerts work.",
     "Reading an airport page, ACT, IFR and FYI, plain-English remarks, lists and alerts.",
     ["airport", "labels", "remarks", "ahead", "lists", "alerts"]),
    ("how-it-works/", "How it works", "How it works",
     "From the FAA posting a new cycle to a change on your screen: every step, what's checked along the way, and "
     "where the data comes from.",
     "Every step from the FAA's files to your screen, what stops a bad update, the status page and the sources.",
     ["how", "checks", "status", "sources"]),
    ("accuracy/", "Accuracy and limits", "Accuracy and limits",
     "What's been measured about Amend's answers, what it doesn't cover, and where to check the official source.",
     "Amend's test set, how many cases a person has checked, the plain-English remark count, and its limits.",
     "accuracy"),   # "accuracy": accuracy_sections()
    ("api/", "API and data", "API and data",
     "The public JSON files behind Amend: what each one holds, every field, and how to use them in your own tools.",
     "Amend's public JSON files: URLs, fields, examples and recipes. No key needed.",
     None),   # None: api_sections()
]

# sections that moved off a page since it was published: its old #anchor goes on to the new page
MOVED_FROM = {"how-it-works/": {"limits": "accuracy/"}}

# old single-page links (docs.amend.watch/#api, the about page's #how) go on to the page that section is on now
MOVED_JS = """<script>(()=>{const m=%s[location.hash.slice(1)];if(m)location.replace(%s+m+location.hash)})()</script>"""


def all_sections():
    return {i: (h, x) for i, h, x in sections() + more_sections()}


def nav(cur, secs):
    """the sidebar: every page, and the current page's sections under it."""
    out = []
    for path, name, *_ in PAGES:
        on = path == cur
        out.append(f'<a class="dx-p{" on" if on else ""}" href="{web.sub_url("docs", None, path)}"'
                   f'{" aria-current=page" if on else ""}>{name}</a>')
        if on:
            out.append('<div class="dx-s">' + "".join(f'<a href="#{i}">{h}</a>' for i, h, _ in secs) + "</div>")
    return "".join(out)


def one_page(n, meta, now):
    path, name, h1, lede, desc, ids = PAGES[n]
    every = all_sections()
    secs = (api_sections() if ids is None else accuracy_sections() if ids == "accuracy"
            else [(i, *every[i]) for i in ids])
    prev = PAGES[n - 1] if n else None
    nxt = PAGES[n + 1] if n + 1 < len(PAGES) else None
    pn = ((f'<a href="{web.sub_url("docs", None, prev[0])}"><small>Previous</small>{prev[1]}</a>' if prev else "")
          + (f'<a class="r" href="{web.sub_url("docs", None, nxt[0])}"><small>Next</small>{nxt[1]}</a>' if nxt
             else f'<a class="r" href="{web.sub_url("status")}"><small>See also</small>Status</a>'))
    body = ('<div class="dx"><nav class="dx-toc" aria-label="Docs">' + nav(path, secs) + '</nav><article class="dx-body">'
            f'<p class="dx-crumb">Docs · {name}</p><h1>{h1}</h1><p class="lede">{lede}</p>'
            + '<details class="dx-jump"><summary>Docs menu</summary><nav>' + nav(path, secs) + "</nav></details>"
            + "".join(f'<section id="{i}"><h2><a href="#{i}">{h}</a></h2>{x}</section>' for i, h, x in secs)
            + f'<nav class="dx-nn">{pn}</nav><div class="dx-pad" aria-hidden="true"></div></article></div>{TOC_JS}')
    early = ""
    if not path:
        moved = {i: p for p, *_, ids in PAGES if p and isinstance(ids, list) for i in ids}
        moved.update(api="api/", limits="accuracy/")   # the old one-page docs' "Data files", and the limits
        early = MOVED_JS % (json.dumps(moved, sort_keys=True), json.dumps(web.sub_url("docs")))
    elif path in MOVED_FROM:
        early = MOVED_JS % (json.dumps(MOVED_FROM[path], sort_keys=True), json.dumps(web.sub_url("docs")))
    title = "Amend Docs" if not path else f"{name} · Amend Docs"
    return subsite.page("docs", title, desc, body, meta, now, head=CSS, path=path, early=early)


def page(meta, now):
    """site/docs/index.html (getting started). build() writes the rest."""
    return one_page(0, meta, now)


def build(site, meta, now):
    """write every docs page: site/docs/index.html, site/docs/using/ and so on."""
    for n, (path, *_) in enumerate(PAGES):
        folder = os.path.join(site, "docs", path)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(one_page(n, meta, now))
