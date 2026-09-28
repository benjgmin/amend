"""
site/status/: the public status page, built from the run log (audit/runs/, amend/runlog.py).

It answers "is Amend current, and did the latest run pass every check?" at the top, then shows
every stage each recent run went through: the FAA files it downloaded (with checksums), the
rows it read, what the diff found, the remark translations, the checks, the pre-publish verify
and whether it was published. Every value comes from a run record. A value the run didn't
record shows as "not recorded"; nothing here is estimated.

The page is rebuilt with the site (web.build) and again by `amend verify` once it passes, so
the run that deploys it shows its own verify result. A
blocked run doesn't deploy, so it shows up here after the next run that does; its record is
in audit/runs on GitHub as soon as that run ends, and the page says so.

Records are read defensively: a field another version added is shown under "Other recorded
fields" instead of being dropped, and a missing one reads "not recorded".
"""
import datetime as dt
import json
import os

from . import runlog, web
from .web import e, nice

CYCLES = 3        # cycle folders of audit/runs/ to read (the in-effect cycle and the two before)
SHOWN = 30        # runs listed, newest first
KNOWN = {"runlog_version", "engine", "engine_hash", "commit", "run", "mode", "hash_seed", "started_at",
         "finished_at", "seconds", "from_cycle", "to_cycle", "upcoming", "sources", "csv_rows",
         "airspace_shapes", "changes", "remarks", "summary_checks", "checks", "outcome", "error",
         "verified", "published", "_path"}
ROLES = {"nasr_old": "NASR, older cycle", "nasr_new": "NASR, newer cycle", "dtpp": "d-TPP chart index",
         "airspace_old": "Class airspace, older cycle", "airspace_new": "Class airspace, newer cycle"}
AI_KEYS = [("sent", "sent to the translator"), ("translated", "came back and passed the no-guess check"),
           ("rejected", "rejected by the no-guess check"), ("bad_batches", "batches that came back unreadable"),
           ("cache_retired", "old cached translations retired"), ("llm_calls", "translator calls"),
           ("input_tokens", "input tokens"), ("output_tokens", "output tokens")]
NR = '<span class="nr">not recorded</span>'
# the page is only redeployed by a run that passes, so on the day a run is blocked it would still
# read green. the visitor's browser checks two things against the clock instead (BEHIND_JS), with
# no request to anyone: how old the newest published run is, and whether the site has the cycle
# the FAA's fixed 28-day schedule says is in effect now. a forced rebuild runs at least every 20h
# when the scheduled check fires, and GitHub drops or delays scheduled runs by hours, so a
# healthy site can reach ~26h between builds; 30h means runs really have stopped publishing
BEHIND_HOURS = 30

CSS = """<style>
.st-top{display:grid;gap:10px}.st-ans{display:flex;gap:10px;align-items:flex-start}
.st-ans .ann{margin-top:6px}.st-ans b{font:600 20px/1.3 var(--sans);letter-spacing:-.3px}
.stg{display:grid;grid-template-columns:104px minmax(0,1fr);gap:4px 12px;padding:11px 0;border-top:1px solid var(--ln);font-size:14px}
.stg:first-child{border-top:0}.stg>.ann{justify-self:start;margin-top:2px}
.stg .t{font-weight:600}.stg .d{color:var(--dm);overflow-wrap:anywhere}.stg .more{grid-column:2}
.nr{color:var(--fn);font-style:italic}
.tw{overflow-x:auto;margin-top:6px;border:1px solid var(--ln);border-radius:6px}
.tb{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
.tb th,.tb td{text-align:left;padding:5px 8px;border-top:1px solid var(--ln);vertical-align:top}
.tb th{border-top:0;font-weight:600;color:var(--dm);white-space:nowrap}.tb td.n{text-align:right;white-space:nowrap}
.tb .h{font:11.5px/1.45 var(--mono);overflow-wrap:anywhere;min-width:16ch}
.msgs{margin:6px 0 0;padding-left:18px}.msgs li{margin:4px 0;overflow-wrap:anywhere}
.run>summary .when{font-variant-numeric:tabular-nums}.run>summary .sub{color:var(--dm);font-weight:400}
.run .stages{padding:0 16px 8px}
.warn-row td{color:var(--am)}
@media (max-width:479px){.stg{grid-template-columns:minmax(0,1fr)}.stg .more{grid-column:1}}
</style>"""


def num(n):
    """1234 -> "1,234"; None -> not recorded. 0 stays 0 (web.e would blank it)."""
    if n is None:
        return NR
    if isinstance(n, bool):
        return "yes" if n else "no"
    if isinstance(n, (int, float)):
        return f"{n:,}"
    return e(n)


def mb(n):
    return NR if n is None else f"{n / 1e6:,.1f} MB"


def when(iso):
    """an absolute UTC time plus the page script's "2h ago"."""
    if not iso:
        return NR
    try:
        t = dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return e(iso)
    z = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'{t:%d %b %Y %H%M}Z (<time datetime="{z}" data-ago="{z}">{t:%d %b %H%M}Z</time>)'


def chip(kind, label=None):
    """the status label on a stage. Passed and Done differ on purpose: Done means the stage ran and
    its numbers are below, Passed means a check ran and found nothing wrong."""
    cls, text = {"pass": ("ok", "Passed"), "done": ("fyi", "Done"), "warn": ("ifr", "Warnings"),
                 "fail": ("act", "Failed"), "skip": ("fyi", "Not run"), "none": ("fyi", "Not recorded"),
                 "wait": ("ifr", "Waiting"), "live": ("ok", "Published"), "held": ("act", "Not published"),
                 "noted": ("ifr", "Noted")}[kind]
    return f'<span class="ann {cls}">{label or text}</span>'


def more(label, inner):
    return f'<details class="more"><summary>{label}</summary>{inner}</details>'


def stage(kind, title, detail, extra=""):
    return (f'<div class="stg">{chip(kind)}<div><div class="t">{title}</div>'
            f'<div class="d">{detail}</div></div>{extra}</div>')


def cycles(r):
    if r.get("from_cycle") and r.get("to_cycle"):
        return f"{nice(r['from_cycle'])} → {nice(r['to_cycle'])}"
    return "cycles not chosen yet"


def reached(r):
    """did the run get past the diff? (a failed or early-blocked run has no result fields)"""
    return r.get("changes") is not None or r.get("csv_rows") is not None


def s_sources(r):
    src = r.get("sources") or []
    if not src:
        return stage("skip", "Downloaded the FAA files", "The run stopped before it had any FAA files.")
    rows = "".join(
        f'<tr><td>{e(ROLES.get(s.get("role"), s.get("role")))}</td>'
        f'<td>{f"""<a href="{e(s["url"])}">{e(s.get("file"))}</a>""" if s.get("url") else e(s.get("file"))}</td>'
        f'<td class="n">{mb(s.get("bytes"))}</td><td class="h">{e(s.get("sha256")) or NR}</td>'
        f'<td>{e(s.get("last_modified")) or NR}</td><td>{when(s.get("retrieved_at"))}</td></tr>' for s in src)
    table = (f'<div class="tw"><table class="tb"><tr><th>File</th><th>Name</th><th>Size</th><th>SHA-256</th>'
             f'<th>FAA Last-Modified</th><th>Downloaded</th></tr>{rows}</table></div>'
             '<p class="note">"Not recorded" on Last-Modified or Downloaded means the file was downloaded before '
             "the run log kept those, or the FAA server didn't send it.</p>")
    total = sum(s.get("bytes") or 0 for s in src)
    return stage("done", "Downloaded the FAA files",
                 f"{len(src)} file{'s' if len(src) != 1 else ''}, {mb(total)}, each with its SHA-256 checksum.",
                 more("Files and checksums", table))


def s_rows(r):
    rows, shapes = r.get("csv_rows"), r.get("airspace_shapes")
    if rows is None:
        return stage("skip" if not reached(r) else "none", "Read the FAA data",
                     "The run stopped before it read the files." if not reached(r) else "Rows read weren't recorded.")
    old, new = rows.get("old") or {}, rows.get("new") or {}
    files = sorted(set(old) | set(new))
    detail = (f"{len(files)} NASR tables: {num(sum(old.values()))} rows in the older cycle, "
              f"{num(sum(new.values()))} in the newer.")
    detail += (f" {num(shapes.get('old'))} → {num(shapes.get('new'))} class airspace shapes." if shapes
               else " Class airspace shapes weren't read (not posted, or unreadable: see the checks).")

    def line(f):
        a, b = old.get(f), new.get(f)
        pct = f"{(b - a) / a:+.1%}" if a and b is not None else ""
        return f'<tr><td>{e(f)}</td><td class="n">{num(a)}</td><td class="n">{num(b)}</td><td class="n">{pct}</td></tr>'
    table = (f'<div class="tw"><table class="tb"><tr><th>Table</th><th>Older</th><th>Newer</th><th>Change</th></tr>'
             + "".join(map(line, files)) + '</table></div>'
             '<p class="note">The input check stops a run when a table loses more than 10% of its rows, gains '
             "more than 50%, goes missing or comes back empty, and flags drops over 5% or rises over 15%. Its "
             "verdict is under the checks below.</p>")
    return stage("done", "Read the FAA data", detail, more("Rows per table", table))


def s_diff(r):
    ch = r.get("changes")
    eng = (f"Engine {e(r.get('engine')) or NR} (code hash <code>{e(r.get('engine_hash')) or 'not recorded'}</code>)")
    commit = r.get("commit")
    if commit:
        eng += f', built from commit <a href="{web.REPO_URL}/commit/{e(commit)}"><code>{e(commit[:7])}</code></a>'
    if r.get("hash_seed") is not None:
        eng += f", hash seed {e(r['hash_seed'])}"
    if ch is None:
        return stage("skip" if not reached(r) else "none", "Compared the two cycles",
                     ("The run stopped before the comparison. " if not reached(r) else "") + eng + ".")
    cat = ch.get("by_category") or {}
    table = ('<div class="tw"><table class="tb"><tr><th>Category</th><th>Changes</th></tr>'
             + "".join(f'<tr><td>{e(k)}</td><td class="n">{num(v)}</td></tr>' for k, v in cat.items())
             + "</table></div>") if cat else ""
    return stage("done", "Compared the two cycles",
                 f"{num(ch.get('airports'))} airports changed: {num(ch.get('action'))} ACT, {num(ch.get('ifr'))} IFR, "
                 f"{num(ch.get('fyi'))} FYI, and {num(ch.get('hidden'))} bookkeeping changes hidden. {eng}.",
                 more("Changes by category", table) if table else "")


def s_remarks(r):
    rm = r.get("remarks")
    if rm is None:
        return stage("skip" if not reached(r) else "none", "Remarks in plain English",
                     "The run stopped before the remarks." if not reached(r) else "Not recorded for this run.")
    detail = (f"{num(rm.get('texts'))} remarks needed plain English: {num(rm.get('plain_english'))} shown translated, "
              f"{num(rm.get('raw_fallback'))} shown as the FAA's own text.")
    ai, parts = rm.get("ai"), []
    if isinstance(ai, dict):
        parts = [f'<tr><td>{label}</td><td class="n">{num(ai.get(k))}</td></tr>' for k, label in AI_KEYS if k in ai]
        if "est_cost_usd" in ai:
            cost = ai["est_cost_usd"]
            cost = f"${cost:,.4f}" if isinstance(cost, (int, float)) else NR
            parts.append(f'<tr><td>estimated translator cost</td><td class="n">{cost}</td></tr>')
        seen = {k for k, _ in AI_KEYS} | {"est_cost_usd", "unknown_terms"}
        parts += [f'<tr><td>{e(k)}</td><td class="n">{generic(v)}</td></tr>' for k, v in ai.items() if k not in seen]
        unk = ai.get("unknown_terms") or {}
        if unk:
            parts.append(f'<tr><td>contractions with no verified meaning</td><td class="n">{len(unk)}</td></tr>')
    extra = {k: v for k, v in rm.items() if k not in ("texts", "plain_english", "raw_fallback", "ai")}
    parts += [f'<tr><td>{e(k)}</td><td class="n">{generic(v)}</td></tr>' for k, v in extra.items()]
    inner = ""
    if parts:
        inner = f'<div class="tw"><table class="tb">{"".join(parts)}</table></div>'
    if isinstance(ai, dict) and ai.get("unknown_terms"):
        terms = ", ".join(f"{e(k)} ({v})" for k, v in sorted(ai["unknown_terms"].items(), key=lambda kv: (-kv[1], kv[0])))
        inner += (f'<p class="note">Remarks using these stay in the FAA\'s words until the glossary has a verified '
                  f"meaning: {terms}.</p>")
    elif ai is None:
        inner += '<p class="note">The translator didn\'t report numbers for this run (it may not have run).</p>'
    return stage("done", "Remarks in plain English", detail, more("Translator details", inner) if inner else "")


def generic(v):
    """a value from a field this page doesn't know yet: numbers as numbers, the rest as JSON."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return num(v)
    return f'<code>{e(json.dumps(v, ensure_ascii=False))}</code>'


def s_summaries(r):
    sc = r.get("summary_checks")
    if sc is None:
        return stage("skip" if not reached(r) else "none", "Checked the change summaries",
                     "The run stopped before this check." if not reached(r) else "Not reported by this run.")
    total, rows = 0, []
    for k, v in sc.items():
        n = sum(x for x in v.values() if isinstance(x, (int, float))) if isinstance(v, dict) else v
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            total += n
        label = {"no_english": "changes shown as FAA column names (no English wording yet)",
                 "summary_value_mismatches": "summaries naming a value the FAA record doesn't have "
                                             "(the FAA values show instead)"}.get(k, k)
        rows.append(f'<tr><td>{e(label)}</td><td class="n">{generic(n)}</td></tr>')
        if isinstance(v, dict) and v:
            rows += [f'<tr><td>&nbsp;&nbsp;{e(kk)}</td><td class="n">{generic(vv)}</td></tr>' for kk, vv in v.items()]
    table = f'<div class="tw"><table class="tb">{"".join(rows)}</table></div>' if rows else ""
    return stage("pass" if total == 0 else "noted", "Checked the change summaries",
                 "Nothing flagged." if total == 0 else f"{num(total)} flagged. These don't stop a run: each one "
                 "shows the FAA's own values instead.", more("Details", table) if table else "")


def s_checks(r):
    c = r.get("checks")
    if c is None:
        return stage("skip" if r.get("outcome") in ("failed", "skipped") else "none",
                     "Input checks and release audit", "The run stopped before the checks."
                     if r.get("outcome") in ("failed", "skipped") else "Not recorded.")
    ne, nw = c.get("error_count", len(c.get("errors") or [])), c.get("warning_count", len(c.get("warnings") or []))
    kind = "fail" if ne else "warn" if nw else "pass"

    def lst(title, items, count):
        if not items:
            return ""
        cut = f" (first {len(items)} of {count})" if count and count > len(items) else ""
        return f'<p class="note"><b>{title}{cut}</b></p><ul class="msgs">' + "".join(f"<li>{e(m)}</li>" for m in items) + "</ul>"
    inner = lst("Errors", c.get("errors"), ne) + lst("Warnings", c.get("warnings"), nw)
    detail = (f"{num(ne)} error{'s' if ne != 1 else ''}, {num(nw)} warning{'s' if nw != 1 else ''}. "
              "Row counts per table, cycle dates, duplicate or broken summaries, bad translations, chart dates "
              "and a sudden jump in action items. Any error stops the run.")
    return stage(kind, "Input checks and release audit", detail, more("Messages", inner) if inner else "")


def s_verify(r):
    if r.get("mode") != "latest":
        return ""
    v, out = r.get("verified"), r.get("outcome")
    if v is True:
        return stage("pass", "Pre-publish check", "The built site was complete: every page, every data file, "
                     "matching counts.")
    if v is False:
        return stage("fail", "Pre-publish check", e(r.get("error")) or "Failed.")
    if out == "built":
        return stage("wait", "Pre-publish check", "Hadn't run yet when this page was built.")
    return stage("skip", "Pre-publish check", "Not reached: the run stopped earlier.")


def s_outcome(r):
    out, pub, err = r.get("outcome"), r.get("published"), r.get("error")
    if r.get("mode") == "history":
        text = {"appended": f"Added the {nice(r.get('to_cycle') or '')} cycle to the history.",
                "skipped": "Skipped: " + (e(err) or "the FAA archive doesn't have that cycle.")}.get(out)
        if text:
            return stage("live" if out == "appended" else "skip", "History", text)
    if pub is True:
        return stage("live", "Published", "Passed everything above and went to the site.")
    if pub is None and out == "built":
        return stage("wait", "Published", "Waiting on the pre-publish check.")
    why = {"blocked": "Blocked by a check", "failed": "The run crashed"}.get(out, "Stopped")
    return stage("held", "Published", f"{why}: {e(err) or 'no reason recorded'}. Nothing was published, and the "
                 "site stayed on the last good build.")


def s_other(r):
    extra = {k: v for k, v in r.items() if k not in KNOWN}
    if not extra:
        return ""
    rows = "".join(f'<tr><td>{e(k)}</td><td>{generic(v)}</td></tr>' for k, v in extra.items())
    return (f'<div class="stg">{chip("done")}<div><div class="t">Other recorded fields</div><div class="d">Fields this page '
            f'doesn\'t describe yet, as the run wrote them.</div></div>'
            + more("Show", f'<div class="tw"><table class="tb">{rows}</table></div>') + "</div>")


def stages(r):
    head = ""
    if (r.get("runlog_version") or 0) > runlog.RUNLOG_VERSION:
        head = (f'<p class="note">This record is format {e(r["runlog_version"])}; the page knows format '
                f'{runlog.RUNLOG_VERSION}, so some fields may show as "not recorded".</p>')
    return head + "".join(f(r) for f in (s_sources, s_rows, s_diff, s_remarks, s_summaries, s_checks,
                                          s_verify, s_outcome, s_other))


def verdict(r):
    """(chip kind, short label) for one run."""
    out = r.get("outcome")
    if out == "blocked" or r.get("verified") is False:
        return "held", "Blocked"
    if out == "failed":
        return "fail", "Crashed"
    if out == "skipped":
        return "skip", "Skipped"
    if r.get("published") is True:
        warn = (r.get("checks") or {}).get("warning_count")
        return ("warn", "Published with warnings") if warn else ("live", "Published")
    if out == "built":
        return "wait", "Waiting on verify"
    return "none", "Unknown"


def run_meta(r):
    run = r.get("run") or {}
    trig = {"schedule": "scheduled check", "push": "a code change", "workflow_dispatch": "started by hand",
            "local": "a local build"}.get(run.get("trigger"), run.get("trigger") or "trigger not recorded")
    bits = [f"{'site build' if r.get('mode') == 'latest' else 'history'}, from {e(trig)}"]
    if r.get("seconds") is not None:
        bits.append(f"took {r['seconds']:,.0f}s")
    if run.get("url"):
        bits.append(f'<a href="{e(run["url"])}">Actions run {e(run.get("id"))}</a>')
    if r.get("_path"):
        bits.append(f'<a href="{web.REPO_URL}/blob/master/{e(r["_path"])}">raw record</a>')
    return " · ".join(bits)


def load(log_dir=runlog.RUNS):
    """recent records, newest first, each with _path (repo-relative) so the page can link it."""
    out = []
    for p in runlog.files(log_dir, last_cycles=CYCLES):
        rec = runlog._read(p)
        if isinstance(rec, dict):
            rec["_path"] = os.path.relpath(p).replace(os.sep, "/") if log_dir == runlog.RUNS else None
            out.append(rec)
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out


def page(recs, meta, now):
    builds = [r for r in recs if r.get("mode") == "latest"]
    top = builds[0] if builds else (recs[0] if recs else None)
    later_bad = [r for r in recs if top is not None and str(r.get("started_at") or "") > str(top.get("started_at") or "")
                 and r.get("outcome") in ("blocked", "failed")]
    rows = []
    if meta:
        upcoming, _ = web.status(meta, now)
        cur = meta["from_cycle"] if upcoming else meta["to_cycle"]
        rows.append(("FAA cycle in effect", nice(cur)))
        if upcoming:
            rows.append(("Next cycle", f"{nice(meta['to_cycle'])}, takes effect {web.countdown(web.effective(meta['to_cycle']))}"
                         " (already on Amend)"))
        else:
            rows.append(("Next cycle", f"{nice((dt.date.fromisoformat(meta['to_cycle']) + dt.timedelta(days=28)).isoformat())}:"
                         " shows up here once the FAA posts it"))
    if top is None:
        ans = (chip("none"), "No runs recorded yet.", "The run log is empty, so there's nothing to show.")
    else:
        kind, label = verdict(top)
        if later_bad:
            ans = (chip("held"), "The latest run didn't publish.",
                   f"A run at {when(later_bad[0].get('started_at'))} was "
                   f"{'blocked' if later_bad[0].get('outcome') == 'blocked' else 'stopped by a crash'}, so the site "
                   "is still on the last good build below. Nothing unchecked was published.")
        elif kind == "live":
            ans = (chip("pass"), "Amend is current, and the latest build passed every check.",
                   "No errors, no warnings. Details for each step are below.")
        elif kind == "warn":
            ans = (chip("warn"), "Amend is current. The latest build passed with warnings.",
                   "Warnings don't stop a build; they're listed under the checks below.")
        elif kind == "wait":
            ans = (chip("wait"), "The latest build is waiting on its pre-publish check.", "")
        else:
            ans = (chip("held"), "The latest build didn't publish.",
                   "The site stays on the last good build until a run passes every check.")
        rows += [("Latest build", when(top.get("started_at"))), ("Compared", cycles(top)),
                 ("Result", chip(kind, label))]
        if top.get("engine"):
            rows.append(("Engine", e(top["engine"])))
    behind_attrs = ""
    if meta and top is not None and top.get("published") and top.get("started_at"):
        behind_attrs = (f' data-last="{e(top["started_at"])}" data-cyc="{e(meta["to_cycle"])}"'
                        f' data-hours="{BEHIND_HOURS}" data-log="{web.REPO_URL}/tree/master/audit/runs"')
    kv = "".join(f'<div class="kv"><span>{k}</span><span>{v}</span></div>' for k, v in rows)
    body = [f"""<header class="full"><h1>Status</h1><p class="lede">Is Amend current, and did the latest run pass every check?
Every number here comes from the run log Amend writes on each run. Nothing is estimated.</p></header>
<section class="full card box st-top"><div class="st-ans" id="stans"{behind_attrs}>{ans[0]}<div><b>{ans[1]}</b>
{f'<p class="note">{ans[2]}</p>' if ans[2] else ''}</div></div><div>{kv}</div></section>{BEHIND_JS if behind_attrs else ""}"""]
    if top is not None:
        body.append(f'<section class="full card box"><h3>Latest build, step by step</h3>'
                    f'<p class="note">{run_meta(top)}</p><div class="stages">{stages(top)}</div></section>')
    others = [r for r in recs if r is not top][:SHOWN]
    if others:
        items = []
        for r in others:
            kind, label = verdict(r)
            items.append(f'<details class="card cycle run"><summary><span class="chev">▶</span>'
                         f'<span class="when">{when(r.get("started_at"))}</span>'
                         f'<span class="sub">{cycles(r)}</span><span class="chips">{chip(kind, label)}'
                         f'</span></summary><div class="stages"><p class="note">{run_meta(r)}</p>{stages(r)}</div></details>')
        body.append(f'<section class="full"><h2 class="h2" style="margin-bottom:10px">Earlier runs</h2>'
                    f'<div class="hlist">{"".join(items)}</div></section>')
    body.append(f"""<section class="full card box prose"><h3>How to read this page</h3>
<p>Amend checks the FAA every 3 hours and rebuilds when there's new data or new code, and at least every 20 hours
anyway. Each run downloads the FAA files, checks them, compares the cycles and runs every check before anything
goes live. If any check fails, nothing is published and the site stays on the last good build.</p>
<p>This page is published with the site, so a blocked run shows up here after the next run that passes. Its record
is on GitHub as soon as it ends: every run, blocked ones included, is in
<a href="{web.REPO_URL}/tree/master/audit/runs">audit/runs</a>, and the fields are described at the top of
<a href="{web.REPO_URL}/blob/master/amend/runlog.py">runlog.py</a>. If this page itself is more than a day and a
half old, a banner at the top says so.</p>
<p><b>Done</b> means a step ran and its numbers are shown. <b>Passed</b> means a check ran and found nothing wrong.
<b>Not recorded</b> means the run didn't log that value, and <b>Not run</b> means the run stopped before that step.</p>
</section>""")
    return web.page("Status · Amend", "Is Amend current, and did the latest run pass every check? Every step of every "
                    "recent run, from the run log.", f"{web.SITE_URL}status/", "".join(body), "../",
                    image=f"{web.SITE_URL}assets/card.png", active="status", meta=meta, now=now, head=CSS)


BEHIND_JS = r"""<script>(()=>{const a=document.getElementById("stans");if(!a||!a.dataset.last)return;
const D=86400000,now=Date.now(),last=Date.parse(a.dataset.last),to=Date.parse(a.dataset.cyc+"T09:01:00Z");
const M="Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" "),p2=n=>String(n).padStart(2,"0"),
  day=t=>{const d=new Date(t);return p2(d.getUTCDate())+" "+M[d.getUTCMonth()]+" "+d.getUTCFullYear()},
  fmt=t=>{const d=new Date(t);return day(t)+" "+p2(d.getUTCHours())+p2(d.getUTCMinutes())+"Z"};
let eff=to;while(eff+28*D<=now)eff+=28*D;   // the newest 0901Z changeover on the FAA's 28-day grid that has passed
const why=[];
if(eff>to)why.push("The "+day(eff)+" FAA cycle took effect "+fmt(eff)+" and isn't on Amend yet. Amend still shows the "+day(to)+" cycle.");
if(now-last>+a.dataset.hours*36e5)why.push("No run has published since "+fmt(last)+". Runs normally publish at least once a day.");
if(!why.length)return;
const esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
a.innerHTML='<span class="ann act">Behind</span><div><b>Amend is behind.</b><p class="note">'+why.map(esc).join(" ")+
' The checks below are from that last published run. Every later run, including blocked ones, is in the <a href="'+esc(a.dataset.log)+'">run log on GitHub</a>. Use official FAA sources until this clears.</p></div>'})()</script>"""


def build(site, meta, now=None, log_dir=runlog.RUNS):
    """write site/status/index.html from the run log. returns the number of runs shown."""
    now = now or dt.datetime.now(dt.timezone.utc)
    recs = load(log_dir)
    os.makedirs(os.path.join(site, "status"), exist_ok=True)
    with open(os.path.join(site, "status", "index.html"), "w", encoding="utf-8") as f:
        f.write(page(recs, meta, now))
    return min(len(recs), SHOWN + 1)


def rebuild(site="site", log_dir=runlog.RUNS):
    """rewrite the page after `amend verify` passes (also `python -m amend status`), so it shows this
    run's verify result. reads the cycle from the built site's latest/meta.json."""
    with open(os.path.join(site, "latest", "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    return build(site, meta, log_dir=log_dir)
