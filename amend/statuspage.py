"""
site/status/: the public status page (status.amend.watch, see amend/subsite.py), built from the run
log (audit/runs/, amend/runlog.py).

It's brief on purpose (master spec §62.2): a headline ("is Amend up to date?"), one line per part of
the service with its state, the last 30 runs as a strip, and the blocked or crashed ones as the
incident history. Every step of the latest build (the FAA files with their checksums, the rows
read, what the diff found, the remark translations, the checks, the pre-publish verify) is folded
away underneath. How the whole process works is on the docs page (amend/docspage.py). Every value
comes from a run record. A value the run didn't record shows as "not recorded"; nothing here is
estimated.

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

from . import runlog, subsite, web
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
           ("rejected", "rejected by the no-guess check"),
           ("sent_back", "came back as the FAA text, so not kept"), ("bad_batches", "batches that came back unreadable"),
           ("cache_retired", "old cached translations retired"), ("llm_calls", "translator calls"),
           ("input_tokens", "input tokens"), ("output_tokens", "output tokens"),
           ("rejects_skipped", "not asked again: this engine version already rejected their answer"),
           ("llm_errors", "translator calls that failed (translation service unavailable)"),
           ("unanswered", "left as FAA text because a call failed or came back unreadable")]
# llm_error is the translation API's own error text: never shown on a public page (llm_errors counts it)
AI_HIDDEN = {"llm_error"}
NR = '<span class="nr">not recorded</span>'
# the page is only redeployed by a run that passes, so on the day a run is blocked it would still
# read green. the visitor's browser checks two things against the clock instead (BEHIND_JS), with
# no request to anyone: how old the newest published run is, and whether the site has the cycle
# the FAA's fixed 28-day schedule says is in effect now. a forced rebuild runs at least every 20h
# when the scheduled check fires, and GitHub drops or delays scheduled runs by hours, so a
# healthy site can reach ~26h between builds; 30h means runs really have stopped publishing
BEHIND_HOURS = 30

CSS = """<style>
.stg{display:grid;grid-template-columns:10px minmax(0,1fr);gap:0 14px;padding:14px 0;border-top:1px solid var(--ln);font-size:14px}
.stg:first-child{border-top:0}
.stg-dot{width:10px;height:10px;border-radius:50%;margin-top:6px;background:var(--gn)}
.stg.k-info .stg-dot{background:var(--cy)}.stg.k-bad .stg-dot{background:var(--am)}.stg.k-none .stg-dot{background:var(--ln2)}
.stg-h{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}
.stg .t{font-weight:600}.stg .k{font-size:11px;color:var(--fn);text-transform:uppercase;letter-spacing:.06em}
.stg .s{margin-left:auto;font-size:12.5px;font-weight:500;color:var(--gn);white-space:nowrap}
.stg.k-info .s{color:var(--cy)}.stg.k-bad .s{color:var(--am)}.stg.k-none .s{color:var(--fn)}
.stg .d{color:var(--dm);margin-top:2px;overflow-wrap:anywhere}
.stg .more{margin-top:6px}.stg .more>summary{font-size:13px}
.nr{color:var(--fn);font-style:italic}
.tw{overflow-x:auto;margin-top:8px;border:1px solid var(--ln);border-radius:6px}
.tb{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
.tb th,.tb td{text-align:left;padding:5px 8px;border-top:1px solid var(--ln);vertical-align:top}
.tb th{border-top:0;font-weight:600;color:var(--dm);white-space:nowrap}.tb td.n{text-align:right;white-space:nowrap}
.tb .h{font:11.5px/1.45 var(--mono);overflow-wrap:anywhere;min-width:16ch}
.msgs{margin:6px 0 0;padding-left:18px}.msgs li{margin:4px 0;overflow-wrap:anywhere}
.warn-row td{color:var(--am)}
.sx-hero{--c:var(--gn);--s:var(--gnS);display:flex;gap:14px;align-items:flex-start;padding:22px 24px 20px;border-radius:10px;
background:var(--s);border:1px solid color-mix(in srgb,var(--c) 28%,transparent)}
.sx-hero.is-info{--c:var(--cy);--s:var(--cyS)}.sx-hero.is-bad{--c:var(--am);--s:var(--amS)}.sx-hero.is-none{--c:var(--fn);--s:var(--gyS)}
.sx-dot{width:12px;height:12px;border-radius:50%;background:var(--c);flex:none;margin-top:9px;
box-shadow:0 0 0 5px color-mix(in srgb,var(--c) 18%,transparent)}
.sx-hero h1{font:600 23px/1.3 var(--sans);letter-spacing:-.3px;margin:0}.sx-hero p{margin:4px 0 0;color:var(--dm)}
.sx-list{margin-top:24px;border:1px solid var(--ln);border-radius:10px;background:var(--p)}
.sx-row{display:flex;gap:16px;align-items:center;padding:15px 20px;border-top:1px solid var(--ln)}.sx-row:first-child{border-top:0}
.sx-n{font-weight:600}.sx-d{color:var(--dm);font-size:13.5px;margin-top:1px}
.sx-st{margin-left:auto;display:inline-flex;align-items:center;gap:7px;font-size:13.5px;font-weight:500;white-space:nowrap;color:var(--gn)}
.sx-st::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.sx-st.info{color:var(--cy)}.sx-st.bad{color:var(--am)}.sx-st.none{color:var(--fn)}
.sx-card{border:1px solid var(--ln);border-radius:10px;background:var(--p);padding:16px 20px}
.sx-card>.sx-h{margin:0 0 12px}
.sx-bars{display:flex;gap:3px;height:34px;position:relative}
.sx-bars>*{flex:1;min-width:3px;border-radius:2px;background:var(--gn);opacity:.85;display:block}
.sx-bars>*:hover,.sx-bars>*:focus-visible{opacity:1;text-decoration:none;outline-offset:1px}
.sx-bars .info{background:var(--cy)}.sx-bars .bad{background:var(--am)}.sx-bars .none{background:var(--ln2)}
.sx-legend{display:flex;justify-content:space-between;gap:12px;color:var(--fn);font-size:12px;margin-top:8px}
.sx-tip{position:absolute;z-index:6;pointer-events:none;background:var(--tx);color:var(--bg);font-size:12.5px;line-height:1.45;
padding:8px 10px;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.25);white-space:nowrap;transform:translate(-50%,-100%);margin-top:-8px}
.sx-tip b{font-weight:600;font-variant-numeric:tabular-nums}.sx-tip .sx-sub{opacity:.75}
.sx-tip::after{content:"";position:absolute;left:50%;top:100%;margin-left:-5px;border:5px solid transparent;border-top-color:var(--tx)}
.sx-none{color:var(--dm);margin:0;font-size:14px}
.sx-inc{list-style:none;margin:0;padding:0}
.sx-inc li{display:flex;align-items:center;gap:16px;padding:12px 0;border-top:1px solid var(--ln)}
.sx-inc li:first-child{border-top:0;padding-top:0}.sx-inc li:last-child{padding-bottom:0}.sx-inc .sx-d{overflow-wrap:anywhere}
.sx-full{margin-top:28px;border:1px solid var(--ln);border-radius:10px;background:var(--p);padding:0 20px}
.sx-full>summary{cursor:pointer;padding:14px 0;font-weight:600;display:flex;align-items:center;gap:10px}
.sx-full>summary::marker{content:""}.sx-full>summary::-webkit-details-marker{display:none}
.sx-full>summary::before{content:"";width:7px;height:7px;border-right:1.5px solid var(--fn);border-bottom:1.5px solid var(--fn);transform:rotate(-45deg);transition:transform .15s;margin-left:2px}
.sx-full[open]>summary::before{transform:rotate(45deg)}
.sx-full[open]>summary{border-bottom:1px solid var(--ln)}
.sx-full .sx-meta{color:var(--fn);font-size:13px;margin:12px 0 4px}
.sx-full .stages{padding-bottom:6px}
.sx-about{color:var(--fn);font-size:13px;margin-top:28px}
@media (max-width:479px){.sx-row{flex-direction:column;align-items:flex-start;gap:6px}.sx-st{margin-left:0}
.sx-hero{padding:18px}.sx-hero h1{font-size:20px}.stg .s{margin-left:0}}
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


# each stage's state: (css colour, label). Passed and Done differ on purpose: Done means the stage ran and its
# numbers are below, Passed means a check ran and found nothing wrong
KINDS = {"pass": ("ok", "Passed"), "done": ("ok", "Done"), "warn": ("info", "Warnings"), "fail": ("bad", "Failed"),
         "skip": ("none", "Not run"), "none": ("none", "Not recorded"), "wait": ("info", "Waiting"),
         "live": ("ok", "Published"), "held": ("bad", "Not published"), "noted": ("info", "Noted")}


def chip(kind, label=None):
    """a status word with its coloured dot (the same look as the component rows)."""
    cls, text = KINDS[kind]
    return f'<span class="sx-st {cls}">{label or text}</span>'


def more(label, inner):
    return f'<details class="more"><summary>{label}</summary>{inner}</details>'


# which step of the engine-health outline in the master spec (§19) each stage is
STEPS = {"Downloaded the FAA files": "Ingestion", "Read the FAA data": "Parsing", "Normalized the records": "Normalization",
         "Compared the two cycles": "Diff", "Sorted the changes": "Classification", "Remarks in plain English": "AI",
         "Regression tests": "Validation", "Checked the change summaries": "Validation",
         "Input checks and release audit": "Validation", "Pre-publish check": "Publishing", "Published": "Publishing",
         "History": "Publishing", "Processing time": "Processing", "Engine version": "Engine"}


def stage(kind, title, detail, extra=""):
    cls, text = KINDS[kind]
    step = f'<span class="k">{STEPS[title]}</span>' if title in STEPS else ""
    return (f'<div class="stg k-{cls}"><span class="stg-dot" aria-hidden="true"></span><div><div class="stg-h">'
            f'<span class="t">{title}</span>{step}<span class="s">{text}</span></div>'
            f'<div class="d">{detail}</div>{extra}</div></div>')


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


def s_norm(r):
    if not reached(r):
        return stage("skip", "Normalized the records", "The run stopped before this step.")
    return stage("done", "Normalized the records", "Every record is put in one consistent form before the comparison "
                 "(the comparison can't run without it). The run log doesn't count these separately.")


def s_diff(r):
    ch = r.get("changes")
    if ch is None:
        return stage("skip" if not reached(r) else "none", "Compared the two cycles",
                     "The run stopped before the comparison." if not reached(r) else "Not recorded.")
    shown = sum(ch.get(p) or 0 for p in ("action", "ifr", "fyi"))
    return stage("done", "Compared the two cycles",
                 f"{num(shown + (ch.get('hidden') or 0))} changes detected at {num(ch.get('airports'))} airports: "
                 f"{num(shown)} shown, {num(ch.get('hidden'))} hidden as bookkeeping (survey dates, rounding, "
                 "duplicate rows).")


def s_classify(r):
    ch = r.get("changes")
    if ch is None:
        return stage("skip" if not reached(r) else "none", "Sorted the changes",
                     "The run stopped before the comparison." if not reached(r) else "Not recorded.")
    cat = ch.get("by_category") or {}
    table = ('<div class="tw"><table class="tb"><tr><th>Category</th><th>Changes</th></tr>'
             + "".join(f'<tr><td>{e(k)}</td><td class="n">{num(v)}</td></tr>' for k, v in cat.items())
             + "</table></div>") if cat else ""
    return stage("done", "Sorted the changes",
                 f"{num(ch.get('action'))} ACT, {num(ch.get('ifr'))} IFR, {num(ch.get('fyi'))} FYI, by fixed rules "
                 "(no AI).", more("Changes by category", table) if table else "")


def s_tests(r):
    if ((r.get("run") or {}).get("trigger") or "local") == "local":
        return stage("skip", "Regression tests", "They run on GitHub before every build. This was a local build.")
    return stage("pass", "Regression tests", "Every build runs all the tests (gold set and snapshot "
                 "included) first, and a failure stops the build before this step, so this build only exists "
                 "because they passed. The run log doesn't keep the count.")


def s_time(r):
    sec = r.get("seconds")
    if sec is None:
        return stage("none", "Processing time", "Not recorded.")
    return stage("done", "Processing time", f"{sec:,.0f} seconds ({sec / 60:,.1f} minutes), from "
                 f"{when(r.get('started_at'))} to {when(r.get('finished_at'))}.")


def s_engine(r):
    eng = f"{e(r.get('engine')) or NR}, code hash <code>{e(r.get('engine_hash')) or 'not recorded'}</code>"
    commit = r.get("commit")
    if commit:
        eng += f', built from commit <a href="{web.REPO_URL}/commit/{e(commit)}"><code>{e(commit[:7])}</code></a>'
    if r.get("hash_seed") is not None:
        eng += f", hash seed {e(r['hash_seed'])}"
    return stage("done" if r.get("engine") else "none", "Engine version", eng + ".")


def s_remarks(r):
    rm = r.get("remarks")
    if rm is None:
        return stage("skip" if not reached(r) else "none", "Remarks in plain English",
                     "The run stopped before the remarks." if not reached(r) else "Not recorded for this run.")
    detail = (f"{num(rm.get('texts'))} remarks needed plain English: {num(rm.get('plain_english'))} shown translated, "
              f"{num(rm.get('raw_fallback'))} shown as the FAA's own text.")
    ai, parts = rm.get("ai"), []
    if isinstance(ai, dict):
        fails = [ai.get(k) for k in ("rejected", "bad_batches")]
        cost = ai.get("est_cost_usd")
        detail += (f" {len(ai.get('unknown_terms') or {})} contractions with no verified meaning. "
                   + (f"{num(sum(fails))} translations failed the no-guess check or came back unreadable. "
                      if all(isinstance(x, int) for x in fails) else "Failures: not recorded. ")
                   + (f"Translator cost ${cost:,.4f}." if isinstance(cost, (int, float)) else "Cost: not recorded."))
    else:
        detail += " Unknown terms, failures and cost: not recorded."
    if isinstance(ai, dict):
        parts = [f'<tr><td>{label}</td><td class="n">{num(ai.get(k))}</td></tr>' for k, label in AI_KEYS if k in ai]
        if "est_cost_usd" in ai:
            cost = ai["est_cost_usd"]
            cost = f"${cost:,.4f}" if isinstance(cost, (int, float)) else NR
            parts.append(f'<tr><td>estimated translator cost</td><td class="n">{cost}</td></tr>')
        if "llm_stopped" in ai:
            parts.append(f'<tr><td>translator stopped after repeated failures</td><td class="n">'
                         f'{num(ai["llm_stopped"]) if ai["llm_stopped"] is not None else NR}</td></tr>')
        seen = {k for k, _ in AI_KEYS} | {"est_cost_usd", "unknown_terms", "llm_stopped"} | AI_HIDDEN
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
        inner += (f'<p class="note">These stay exactly as the FAA wrote them until the glossary has a verified '
                  f"meaning: {terms}. Not counted: addresses, and the four-letter airport codes (KSPS) and "
                  f"center codes (ZOA) in the FAA's own lists.</p>")
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
    return stage("done", "Other recorded fields", "Fields this page doesn't describe yet, as the run wrote them.",
                 more("Show", f'<div class="tw"><table class="tb">{rows}</table></div>'))


def stages(r):
    head = ""
    if (r.get("runlog_version") or 0) > runlog.RUNLOG_VERSION:
        head = (f'<p class="note">This record is format {e(r["runlog_version"])}; the page knows format '
                f'{runlog.RUNLOG_VERSION}, so some fields may show as "not recorded".</p>')
    return head + "".join(f(r) for f in (s_sources, s_rows, s_norm, s_diff, s_classify, s_remarks, s_tests,
                                          s_summaries, s_checks, s_verify, s_outcome, s_time, s_engine, s_other))


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


def ago(iso):
    """"28 Sep 1850Z", which the page script turns into "12m ago" (the full time stays in its tooltip)."""
    try:
        t = dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return NR
    return web.built_at(t)


# the one-word state of each part of the service, and its colour: ok green, info blue, bad magenta, none grey
def pill(cls, text, id_=""):
    ident = f' id="{id_}"' if id_ else ""
    return f'<span class="sx-st {cls}"{ident}>{text}</span>'


def row(name, desc, state):
    return f'<div class="sx-row"><div><div class="sx-n">{name}</div><div class="sx-d">{desc}</div></div>{state}</div>'


def headline(top, later_bad):
    """(css class, title, sentence) for the banner at the top."""
    if top is None:
        return "is-none", "No runs recorded yet", "The run log is empty, so there's nothing to show."
    if later_bad:
        b = later_bad[0]
        how = "blocked by a check" if b.get("outcome") == "blocked" else "stopped by a crash"
        return ("is-bad", "The latest run didn't publish",
                f"A run at {when(b.get('started_at'))} was {how}, so the site stays on the last good build, from "
                f"{ago(top.get('started_at'))}. Nothing unchecked was published.")
    kind, _ = verdict(top)
    if kind == "live":
        return "is-ok", "Amend is up to date", f"The latest build passed every check, {ago(top.get('started_at'))}."
    if kind == "warn":
        n = (top.get("checks") or {}).get("warning_count")
        return ("is-ok", "Amend is up to date", f"The latest build passed, {ago(top.get('started_at'))}, with "
                f"{num(n)} warning{'s' if n != 1 else ''}. Warnings don't stop a build.")
    if kind == "wait":
        return "is-info", "The latest build is waiting on its pre-publish check", ""
    return ("is-bad", "The latest build didn't publish",
            "The site stays on the last good build until a run passes every check.")


def components(top, pub, meta, now):
    """spec §62.2: one line per part of the service, each with its state."""
    if top is None:
        return ""
    kind, _ = verdict(top)
    ok = kind in ("live", "warn")
    rows = []

    def cyc(up):
        if not meta:
            return "Not recorded."
        if up:
            return (f"In effect: {nice(meta['from_cycle'])}. The next cycle, {nice(meta['to_cycle'])}, is already on "
                    f"Amend and takes effect {web.countdown(web.effective(meta['to_cycle']))}.")
        nxt = (dt.date.fromisoformat(meta["to_cycle"]) + dt.timedelta(days=28)).isoformat()
        return (f"In effect: {nice(meta['to_cycle'])}. The next one, {nice(nxt)}, shows up once the FAA posts it; "
                "Amend checks for it every 10 minutes.")
    rows.append(row("FAA cycle", web.flip(meta, now, cyc) if meta else cyc(False),
                    pill("ok", "Up to date", "c-faa") if ok else pill("info", "Not updating", "c-faa")))
    ch = top.get("changes")
    found = (f" {num(sum(ch.get(p) or 0 for p in ('action', 'ifr', 'fyi')))} changes at {num(ch.get('airports'))} "
             "airports." if ch else "")
    state = {"live": ("ok", "Complete"), "warn": ("ok", "Complete"), "wait": ("info", "Verifying"),
             "held": ("bad", "Blocked"), "fail": ("bad", "Crashed"), "skip": ("none", "Skipped")}.get(kind, ("none", "Unknown"))
    rows.append(row("Processing", f"Latest build {ago(top.get('started_at'))}: compared {cycles(top)}.{found}",
                    pill(*state)))
    c = top.get("checks")
    if c is None:
        rows.append(row("Checks", "The run stopped before the checks.", pill("none", "Not run")))
    else:
        ne = c.get("error_count", len(c.get("errors") or []))
        nw = c.get("warning_count", len(c.get("warnings") or []))
        v = top.get("verified")
        rows.append(row("Checks", f"Input checks, release audit and the pre-publish check: {num(ne)} "
                        f"error{'s' if ne != 1 else ''}, {num(nw)} warning{'s' if nw != 1 else ''}.",
                        pill("bad", "Failed") if ne or v is False else pill("info", "Warnings") if nw
                        else pill("ok", "Passed") if v else pill("info", "Verifying")))
    rm = top.get("remarks")
    if rm is None:
        rows.append(row("Plain-English remarks", "Not recorded for this build.", pill("none", "Not recorded")))
    else:
        ai = rm.get("ai") if isinstance(rm.get("ai"), dict) else {}
        down = bool(ai.get("llm_errors")) or bool(ai.get("llm_stopped"))
        rows.append(row("Plain-English remarks", f"{num(rm.get('plain_english'))} of {num(rm.get('texts'))} remarks read "
                        f"in plain English. The other {num(rm.get('raw_fallback'))} show the FAA's own text, as "
                        "every remark does when a translation doesn't pass the no-guess check.",
                        pill("info", "Translator down") if down else pill("ok", "Working")))
    rows.append(row("Website and data files", "amend.watch, the iPhone app's data and the public JSON files. "
                    + (f"Last published {ago(pub.get('finished_at') or pub.get('started_at'))}." if pub else
                       "No published build in the run log's last three cycles."),
                    pill("ok", "Operational", "c-web") if pub else pill("none", "Not recorded", "c-web")))
    return f'<div class="sx-list">{"".join(rows)}</div>'


BAR = {"live": "ok", "warn": "ok", "wait": "info", "held": "bad", "fail": "bad", "skip": "none", "none": "none"}


def bars(recs):
    """the last SHOWN runs as a strip, oldest on the left. Hovering (or tapping) one shows exactly when it ran, what
    it was and how it ended (TIP_JS); clicking opens its record on GitHub."""
    shown = recs[:SHOWN][::-1]
    if not shown:
        return ""
    out, tally = [], {}
    for r in shown:
        kind, label = verdict(r)
        tally[label] = tally.get(label, 0) + 1
        try:
            t = dt.datetime.fromisoformat(r.get("started_at")).astimezone(dt.timezone.utc)
            iso, exact = t.strftime("%Y-%m-%dT%H:%M:%SZ"), t.strftime("%d %b %Y %H:%M:%SZ")
        except (TypeError, ValueError):
            iso, exact = "", "time not recorded"
        run = r.get("run") or {}
        trig = {"schedule": "scheduled check", "push": "code change", "workflow_dispatch": "started by hand",
                "local": "local build"}.get(run.get("trigger"), run.get("trigger") or "")
        what = ("history" if r.get("mode") == "history" else "site build") + (f", {trig}" if trig else "")
        sec = f", {r['seconds']:,.0f}s" if r.get("seconds") is not None else ""
        tip = e(f"{exact} · {what} · {label} · {cycles(r)}")
        href = f'{web.REPO_URL}/blob/master/{e(r["_path"])}' if r.get("_path") else e(run.get("url") or "")
        attrs = (f'class="{BAR[kind]}" data-t="{iso}" data-x="{e(exact)}" data-w="{e(what + sec)}" data-l="{e(label)}" '
                 f'data-c="{e(cycles(r))}" aria-label="{tip}"')
        out.append(f'<a {attrs} href="{href}"></a>' if href else f'<span {attrs}></span>')
    counts = ", ".join(f"{n} {k.lower()}" for k, n in sorted(tally.items(), key=lambda kv: -kv[1]))
    return (f'<div class="sx-bars" id="sxbars">{"".join(out)}</div><div class="sx-legend"><span>Older</span>'
            f'<span>{len(shown)} runs: {e(counts)}</span><span>Newest</span></div>{TIP_JS}')


# the tooltip on a run bar: the exact UTC time (and how long ago, on the site's clock), what the run was, how it
# ended and which cycles it compared. Shown on hover or focus, and on a tap, where the first tap shows it and the
# second follows the link
TIP_JS = r"""<script>(()=>{const w=document.getElementById("sxbars");if(!w)return;let tip=null,cur=null;
const clock=()=>typeof AM!=="undefined"&&AM.now?AM.now():Date.now();
const ago=t=>{if(!t)return"";const m=Math.floor((clock()-Date.parse(t))/6e4),h=Math.floor(m/60),d=Math.floor(h/24);
  return m<1?"just now":m<60?m+" min ago":h<48?h+"h ago":d+" days ago"};
function show(b){hide();const d=b.dataset,a=ago(d.t);tip=document.createElement("div");tip.className="sx-tip";
  tip.innerHTML="<b>"+d.x+"</b>"+(a?' <span class="sx-sub">('+a+")</span>":"")+"<br>"+d.w+" · "+d.l+'<br><span class="sx-sub">'+d.c+"</span>";
  w.appendChild(tip);const r=b.getBoundingClientRect(),p=w.getBoundingClientRect();
  let x=r.left-p.left+r.width/2;const half=tip.offsetWidth/2;x=Math.max(half,Math.min(p.width-half,x));
  tip.style.left=x+"px";tip.style.top="0";cur=b}
function hide(){if(tip)tip.remove();tip=null;cur=null}
w.querySelectorAll("[data-x]").forEach(b=>{b.addEventListener("mouseenter",()=>show(b));b.addEventListener("mouseleave",hide);
  b.addEventListener("focus",()=>show(b));b.addEventListener("blur",hide);
  b.addEventListener("touchstart",ev=>{if(cur!==b){ev.preventDefault();show(b)}},{passive:false});
  b.addEventListener("click",ev=>{if(matchMedia("(hover:none)").matches&&cur!==b){ev.preventDefault();show(b)}})});
document.addEventListener("touchstart",ev=>{if(!w.contains(ev.target))hide()},{passive:true})})()</script>"""


def problems(recs):
    """incident history: the blocked and crashed runs in the log (spec §62.2)."""
    bad = [r for r in recs if r.get("outcome") in ("blocked", "failed") or r.get("verified") is False]
    if not bad:
        return f'<p class="sx-none">No blocked or crashed runs in the last {CYCLES} cycles.</p>'
    def why(r):
        errs = ((r.get("checks") or {}).get("errors") or [])[:3]
        return (f'{e(r.get("error")) or "No reason recorded."}'
                + ("".join(f"<br>· {e(m)}" for m in errs))
                + " Nothing was published; the site stayed on the last good build.")
    items = "".join(f'<li><div><div class="sx-n">{when(r.get("started_at"))}</div><div class="sx-d">{why(r)}</div></div>'
                    f'{pill("bad", "Crashed" if r.get("outcome") == "failed" else "Blocked")}</li>' for r in bad[:10])
    more_ = f'<p class="note">Showing 10 of {len(bad)}.</p>' if len(bad) > 10 else ""
    return f'<ul class="sx-inc">{items}</ul>{more_}'


def page(recs, meta, now):
    builds = [r for r in recs if r.get("mode") == "latest"]
    top = builds[0] if builds else (recs[0] if recs else None)
    later_bad = [r for r in recs if top is not None and str(r.get("started_at") or "") > str(top.get("started_at") or "")
                 and r.get("outcome") in ("blocked", "failed")]
    cls, title, sentence = headline(top, later_bad)
    behind_attrs = ""
    if meta and top is not None and top.get("published") and top.get("started_at"):
        behind_attrs = (f' data-last="{e(top["started_at"])}" data-cyc="{e(meta["to_cycle"])}"'
                        f' data-hours="{BEHIND_HOURS}" data-log="{web.REPO_URL}/tree/master/audit/runs"'
                        # did that run find the next cycle posted? False: the FAA hadn't posted it yet
                        f' data-up="{"1" if top.get("upcoming") else "0" if top.get("upcoming") is False else ""}"')
    docs = web.sub_url("docs")
    body = [f'<section class="sx-hero {cls}" id="stans"{behind_attrs}><span class="sx-dot" aria-hidden="true"></span>'
            f'<div><h1>{title}</h1>{f"<p>{sentence}</p>" if sentence else ""}</div></section>'
            + (BEHIND_JS if behind_attrs else ""),
            components(top, next((r for r in builds if r.get("published")), None), meta, now)]
    if recs:
        body.append(f'<h2 class="sx-h">Recent runs</h2><div class="sx-card">{bars(recs)}</div>')
    body.append(f'<h2 class="sx-h">Incidents</h2><div class="sx-card">{problems(recs)}</div>')
    if top is not None:
        body.append(f'<details class="sx-full"><summary>Every step of the latest build</summary>'
                    f'<p class="sx-meta">{run_meta(top)}</p><div class="stages">{stages(top)}</div></details>')
    body.append(f'<p class="sx-about">Every value on this page comes from the run log Amend writes on each run; nothing '
                f'is estimated. <a href="{docs}#status">How this page works</a> · '
                f'<a href="{web.REPO_URL}/tree/master/audit/runs">All run records</a></p>')
    return subsite.page("status", "Amend Status", "Is Amend up to date? The FAA cycle, the latest build and its "
                        "checks, from Amend's run log.", "".join(body), meta, now, head=CSS)


BEHIND_JS = r"""<script>(()=>{const a=document.getElementById("stans");if(!a||!a.dataset.last)return;
// the site's own clock (app.js AM.now: this device's, corrected by the server's Date header) when there is one, so
// this page and the rest of the site agree on which cycle is in effect. checked again once that clock has synced
const clock=()=>typeof AM!=="undefined"&&AM.now?AM.now():Date.now();
const set=(id,cls,t)=>{const x=document.getElementById(id);if(x){x.className="sx-st "+cls;x.textContent=t}};
function check(){if(!a.dataset.last)return;const D=86400000,now=clock(),last=Date.parse(a.dataset.last),to=Date.parse(a.dataset.cyc+"T09:01:00Z");
const M="Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" "),p2=n=>String(n).padStart(2,"0"),
  day=t=>{const d=new Date(t);return p2(d.getUTCDate())+" "+M[d.getUTCMonth()]+" "+d.getUTCFullYear()},
  fmt=t=>{const d=new Date(t);return day(t)+" "+p2(d.getUTCHours())+p2(d.getUTCMinutes())+"Z"};
let eff=to;while(eff+28*D<=now)eff+=28*D;   // the newest 0901Z changeover on the FAA's 28-day grid that has passed
const stale=now-last>+a.dataset.hours*36e5,esc=s=>s.replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])),
  log='<a href="'+esc(a.dataset.log)+'">run log on GitHub</a>';
// master spec §62.2: never show an FAA publication delay as an Amend outage. the last build (fresh, so it's the
// last word) found the next cycle not posted: the FAA is late, not Amend
if(eff>to&&!stale&&a.dataset.up==="0"){a.className="sx-hero is-info";
  a.innerHTML='<span class="sx-dot" aria-hidden="true"></span><div><h1>Waiting on the FAA</h1><p>'+esc("The FAA's "+
    "28-day schedule put the "+day(eff)+" cycle in effect at "+fmt(eff)+", but the FAA hadn't posted it when Amend last built "+
    "the site ("+fmt(last)+"). Amend keeps checking and shows the "+day(to)+" cycle until it does. This is a delay at the "+
    "FAA, not an Amend outage.")+' The '+log+' has every check.</p></div>';set("c-faa","info","Waiting on FAA");delete a.dataset.last;return}
const why=[];
if(eff>to)why.push("The "+day(eff)+" FAA cycle took effect "+fmt(eff)+" and isn't on Amend yet. Amend still shows the "+day(to)+" cycle.");
if(stale)why.push("No run has published since "+fmt(last)+". Runs normally publish at least once a day, so either the FAA's "+
  "server is down or an Amend run failed.");
if(!why.length)return;a.className="sx-hero is-bad";
if(eff>to)set("c-faa","bad","Behind");if(stale)set("c-web","bad","Behind");
a.innerHTML='<span class="sx-dot" aria-hidden="true"></span><div><h1>Amend is behind</h1><p>'+why.map(esc).join(" ")+
' The lines below are from that last published run. Every later run, including blocked ones, and which side it was, is in the '+log+'. Use official FAA sources until this clears.</p></div>';
delete a.dataset.last}
check();setTimeout(check,2000);setInterval(check,60000)})()</script>"""


def build(site, meta, now=None, log_dir=runlog.RUNS):
    """write site/status/index.html from the run log. returns the number of runs shown."""
    now = now or dt.datetime.now(dt.timezone.utc)
    recs = load(log_dir)
    os.makedirs(os.path.join(site, "status"), exist_ok=True)
    with open(os.path.join(site, "status", "index.html"), "w", encoding="utf-8") as f:
        f.write(page(recs, meta, now))
    return min(len(recs), SHOWN)


def rebuild(site="site", log_dir=runlog.RUNS):
    """rewrite the page after `amend verify` passes (also `python -m amend status`), so it shows this
    run's verify result. reads the cycle from the built site's latest/meta.json."""
    with open(os.path.join(site, "latest", "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    return build(site, meta, log_dir=log_dir)
