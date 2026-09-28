"""
site/docs/: the docs (docs.amend.watch, see amend/subsite.py). How the whole process works, from the
FAA posting a file to a change on a pilot's screen, plus the sources, the limits and the public files.

Written for pilots and schools, not programmers: docs/data-pipeline.md and docs/architecture.md in
the repo have the same process with file and line references. When the pipeline changes, change both.
Anchors #how, #sources, #limits, #api and #open are linked from the site, the app and older pages, so
keep them.
"""
from . import subsite, web
from .web import DTPP_SEARCH, FAA_INQUIRY, NASR_PAGE, REPO_URL, REPORT_URL, SITE_URL

CSS = """<style>
.dx{display:grid;grid-template-columns:220px minmax(0,1fr);column-gap:48px;align-items:start}
.dx-toc{position:sticky;top:76px;max-height:calc(100vh - 92px);overflow-y:auto;font-size:13.5px;padding:4px 0 16px}
.dx-toc .g{font:600 11px/1.4 var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--fn);margin:18px 0 6px 12px}
.dx-toc .g:first-child{margin-top:0}
.dx-toc a{display:block;padding:5px 12px;color:var(--dm);border-radius:6px;border-left:2px solid transparent}
.dx-toc a:hover{color:var(--tx);background:var(--p2);text-decoration:none}
.dx-toc a.on{color:var(--tx);background:var(--p2);border-left-color:var(--am);font-weight:500;border-radius:0 6px 6px 0}
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
.dx-jump nav{display:grid;padding:0 14px 10px}.dx-jump a{padding:6px 0;border-top:1px solid var(--ln);font-size:14px}}
@media (max-width:479px){.dx-kv{grid-template-columns:minmax(0,1fr);gap:2px}.dx-kv dd{margin-bottom:8px}}
</style>"""

# the table of contents follows the section you're reading
TOC_JS = """<script>(()=>{const a=[...document.querySelectorAll(".dx-toc a")];if(!a.length||!("IntersectionObserver" in window))return;
const on=id=>a.forEach(x=>x.classList.toggle("on",x.getAttribute("href")==="#"+id));const seen=new Map();
const io=new IntersectionObserver(es=>{es.forEach(e=>seen.set(e.target.id,e.isIntersecting));
const first=a.map(x=>x.getAttribute("href").slice(1)).find(id=>seen.get(id));if(first)on(first)},{rootMargin:"-70px 0px -60% 0px"});
document.querySelectorAll(".dx section[id]").forEach(s=>io.observe(s))})()</script>"""


def tag(text):
    return f'<span class="ann fyi">{text}</span>'


def step(title, kind, text):
    return f'<li><div class="t">{title} {tag(kind)}</div><p>{text}</p></li>'


def sections():
    guide, status = f"{SITE_URL}guide/", web.sub_url("status")
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
            f'Each change gets ACT, IFR or FYI from fixed rules, not AI. <a href="#labels">More below</a>.')),
        step("Write it in plain English", "code + AI", (
            "Code writes every summary line from the FAA's own values. The only AI step is decoding the "
            'contractions in FAA remarks, under a no-guess check. <a href="#remarks">More below</a>.')),
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
            "explains what's left in plain English, sorted by whether it changes how you fly. The FAA posts each "
            "cycle before it takes effect, so Amend shows changes before they happen.</p>"
            "<p>Everything that decides what changed and how much it matters is plain code anyone can read on "
            f'<a href="{REPO_URL}">GitHub</a>. AI only decodes FAA remark contractions, and code checks every '
            "answer it gives.</p>")),
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
            "<li><b>ACT</b>: changes how you fly the airport. Tower and Class D hours, frequencies, runways opened, "
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
            "<p>That means plenty of remarks show as FAA text. On the 1 Oct 2026 build, 723 of the 1,591 changed "
            f'remarks read in plain English. The <a href="{status}">status page</a> shows the current count.</p>')),
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
            "<dt>Recent runs</dt><dd>The last 30 runs, oldest on the left: green published, blue waiting, magenta "
            "blocked or crashed, grey skipped. Each opens its record.</dd>"
            "<dt>Problems</dt><dd>Every blocked or crashed run in the last three cycles, with the reason.</dd>"
            "</dl>"
            "<p>The status page is published with the site, so a blocked run appears there after the next run that "
            "passes. Its record is on GitHub as soon as it ends: every run is in "
            f'<a href="{REPO_URL}/tree/master/audit/runs">audit/runs</a>. If any page is more than a day and a '
            "half old, a banner at the top says so.</p>"
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
        ("limits", "What it doesn't cover", (
            "<ul><li><b>NOTAMs.</b> Temporary changes are published as NOTAMs and never show up here.</li>"
            "<li><b>Corrections between cycles.</b> The FAA sometimes fixes data mid-cycle, usually by NOTAM. Amend "
            "only reads the 28-day files, so a fix like that shows up here in a later cycle, if at all.</li>"
            "<li><b>Chart Supplement pages that aren't in the FAA data files</b>, like its special notices. Airport "
            "remarks are covered.</li>"
            "<li><b>Class E airspace above the surface</b> (E5). Surface areas are covered.</li>"
            "<li><b>Chart history before fall 2026</b>, because the FAA doesn't keep old chart indexes online. "
            "Airport data goes back to Aug 2024.</li>"
            "<li><b>A plain-English version of every remark.</b> When a translation doesn't pass the checks, you "
            "get the FAA text instead.</li>"
            "<li><b>What the FAA hasn't posted yet.</b> A new cycle shows up here after the FAA posts it and a "
            "build runs, usually within about 20 minutes.</li></ul>"
            "<p>Amend doesn't publish an accuracy percentage. It would need a large set of changes checked by hand "
            "against the FAA source, and that set is still being built.</p>")),
        ("api", "Data files", (
            "<p>Everything on the site is built from plain JSON files anyone can download. No key and no sign-up, "
            "and you're welcome to build on them.</p><ul>"
            "<li><code>latest/meta.json</code>: which two cycles are being compared, and whether the newer one is in "
            "effect yet.</li>"
            "<li><code>latest/index.json</code>: every airport with changes, with its ACT, IFR and FYI counts.</li>"
            "<li><code>latest/&lt;ID&gt;.json</code>: every change at one airport. A 404 means nothing changed "
            "there.</li>"
            "<li><code>history/&lt;ID&gt;.json</code>: earlier cycles at one airport.</li>"
            "<li><code>airports.json</code>: every airport ID with its name and location.</li>"
            "<li><code>&lt;ID&gt;/feed.xml</code> and <code>list/&lt;name&gt;/feed.xml</code>: the alert feeds "
            "(RSS), and <code>cycles.ics</code>, the cycle dates as a calendar.</li></ul>"
            f'<p>They all live under <code>{SITE_URL}</code>. The fields are described in '
            f'<a href="{REPO_URL}/blob/master/SCHEMA.md">SCHEMA.md</a>. Airport IDs are FAA IDs (VRB, not KVRB) '
            "and dates are the FAA effective date. The data carries the same warning as the site: "
            f'<a href="{SITE_URL}terms/">not for navigation</a>.</p>')),
        ("open", "Open source and reporting problems", (
            f'<p>The engine, the rules and the site are <a href="{REPO_URL}">on GitHub</a> under the MIT license. '
            f'Found something wrong? <a href="{REPORT_URL}">Open an issue</a> with the airport, the cycle and what '
            "the FAA source says. If the FAA's own data is wrong, only the FAA can fix it: "
            f'use its <a href="{FAA_INQUIRY}">Aeronautical Inquiries</a> page.</p>')),
    ]


GROUPS = [("Overview", ["what", "cycle"]), ("The process", ["how", "labels", "remarks", "checks"]),
          ("Reference", ["status", "sources", "limits", "api", "open"])]


def page(meta, now):
    secs = sections()
    heads = {i: h for i, h, _ in secs}
    toc = "".join(f'<div class="g">{g}</div>' + "".join(f'<a href="#{i}">{heads[i]}</a>' for i in ids) for g, ids in GROUPS)
    body = ('<div class="dx"><nav class="dx-toc" aria-label="On this page">' + toc + '</nav><article class="dx-body">'
            '<h1>How Amend works</h1><p class="lede">From the FAA posting a new cycle to a change on your screen: '
            "every step, what's checked along the way, and what Amend doesn't cover.</p>"
            + '<details class="dx-jump"><summary>On this page</summary><nav>'
            + "".join(f'<a href="#{i}">{h}</a>' for i, h, _ in secs) + "</nav></details>"
            + "".join(f'<section id="{i}"><h2><a href="#{i}">{h}</a></h2>{x}</section>' for i, h, x in secs)
            + f'<nav class="dx-nn"><a href="{SITE_URL}guide/"><small>Next</small>Guide: how to read a change</a>'
            f'<a class="r" href="{web.sub_url("status")}"><small>See also</small>Status</a></nav>'
            f"</article></div>{TOC_JS}")
    return subsite.page("docs", "Amend Docs", "How Amend turns each FAA cycle into plain-English changes: every "
                        "step, the checks, the sources, what it doesn't cover and the public data files.",
                        body, meta, now, head=CSS)
