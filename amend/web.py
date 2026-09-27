"""
Static web view: one HTML page per airport at site/<ID>/index.html, plus a searchable landing
page at site/index.html. No JavaScript needed to read a page (the landing search uses a little),
and every page has Open Graph tags so a link in iMessage or a group chat shows a preview card.

Never writes to the JSON paths in SCHEMA.md (latest/, history/, airports.json).
"""
import datetime as dt
import html
import json
import os
import re

SITE_URL = "https://benjgmin.github.io/amend/"
RESERVED = {"latest", "history", "assets", "index.html", "airports.json"}  # never an airport page
PRIORITY = [("action", "ACT", "Action"), ("ifr", "IFR", "IFR procedures"), ("fyi", "FYI", "FYI")]

CSS = """
:root{--bg:#090C10;--panel:#13181F;--hi:#1B212A;--line:rgba(255,255,255,.09);--text:#F0F0F0;
--dim:#8F8F8F;--faint:#5C5C5C;--amber:#FFB500;--cyan:#3DD6FF;--green:#4DE073;
--mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
*{box-sizing:border-box}html{background:var(--bg)}
body{margin:0 auto;max-width:760px;padding:0 16px 48px;color:var(--text);font:16px/1.45 var(--sans);background:var(--bg)}
a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
.top{display:flex;align-items:center;justify-content:space-between;padding:18px 0}
.brand{font:700 15px var(--mono);letter-spacing:3px;color:var(--text)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin:12px 0}
.hdr{font:600 11px var(--mono);letter-spacing:1.5px;text-transform:uppercase;color:var(--dim)}
h1{font:700 34px var(--mono);margin:0;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1 .icao{font:400 15px var(--mono);color:var(--faint)}
.name{font-weight:600;font-size:18px;margin-top:4px}.loc{font:11px var(--mono);color:var(--dim);text-transform:uppercase;margin-top:2px}
.chips{display:flex;gap:5px;flex-wrap:wrap}
.ann{display:inline-block;font:700 11px var(--mono);padding:2px 6px;border-radius:3px;border:1px solid;white-space:nowrap}
.act{color:var(--amber);border-color:rgba(255,181,0,.55);background:rgba(255,181,0,.12)}
.ifr{color:var(--cyan);border-color:rgba(61,214,255,.55);background:rgba(61,214,255,.12)}
.fyi{color:var(--dim);border-color:rgba(143,143,143,.55);background:rgba(143,143,143,.12)}
.ok{color:var(--green);border-color:rgba(77,224,115,.55);background:rgba(77,224,115,.12)}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px}
.sec{display:flex;align-items:center;gap:8px;margin:22px 0 6px}.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.change{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--dim);border-radius:6px;padding:10px 12px;margin:6px 0}
.change.p-action{border-left-color:var(--amber)}.change.p-ifr{border-left-color:var(--cyan)}
.summary{font-size:15px}.meta{display:flex;gap:8px;align-items:center;margin-top:6px;font:600 9px var(--mono);letter-spacing:1px;color:var(--faint);text-transform:uppercase;flex-wrap:wrap}
.meta a{font:700 11px var(--mono);letter-spacing:0}
details>summary{cursor:pointer;list-style:none}details>summary::-webkit-details-marker{display:none}
.more summary{font:700 11px var(--mono);color:var(--dim);margin-top:6px}
.more pre{white-space:pre-wrap;font:11px/1.5 var(--mono);color:var(--amber);background:var(--bg);border-radius:5px;padding:10px;margin:6px 0 0}
.more pre.d{color:var(--dim)}
.cycle>summary{display:flex;align-items:center;gap:8px;margin:18px 0 6px}
.cycle>summary .hdr{color:var(--text)}.cycle>summary::after{content:"";flex:1;height:1px;background:var(--line);order:2}
.cycle>summary .chips{order:3}.cycle[open]>summary .chips{display:none}
.chev{color:var(--cyan);font:700 11px var(--mono);transition:transform .15s}.cycle[open] .chev{transform:rotate(90deg)}
.none{text-align:center;color:var(--green);font:600 12px var(--mono);padding:28px 0}
.note{font-size:14px;color:rgba(240,240,240,.8);margin-top:6px}
.foot{font:10px var(--mono);color:var(--faint);margin-top:28px;text-transform:uppercase}
input{width:100%;background:var(--hi);color:var(--text);border:1px solid rgba(61,214,255,.4);border-radius:8px;padding:12px;font:600 16px var(--mono);text-transform:uppercase}
input::placeholder{color:var(--faint)}
.res a,.list a{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--panel);border-radius:6px;padding:9px 12px;margin:4px 0;color:var(--text)}
.res a:hover,.list a:hover{text-decoration:none;background:var(--hi)}
.rid{font:700 16px var(--mono);min-width:56px}.rname{flex:1;font-size:14px}.rsub{font:10px var(--mono);color:var(--dim)}
.big{font:700 26px var(--mono)}
"""


def e(s):
    return html.escape(str(s or ""), quote=True)


def efb(cycle):
    try:
        return dt.date.fromisoformat(cycle).strftime("%d %b %Y").upper()
    except ValueError:
        return cycle


def arrow(s):
    return e(s).replace(" -&gt; ", " → ")


def counts(changes):
    return {p: sum(c["priority"] == p for c in changes) for p, _, _ in PRIORITY}


def chips(c, no_change=True):
    out = [f'<span class="ann {"act" if p == "action" else p}">{lbl} {c[p]}</span>'
           for p, lbl, _ in PRIORITY if c.get(p)]
    if not out and no_change:
        out = ['<span class="ann ok">NO CHG</span>']
    return f'<span class="chips">{"".join(out)}</span>'


def change_html(c):
    extra = []
    if c.get("chart", {}).get("amdt"):
        a = c["chart"]["amdt"]
        extra.append(f'<span class="ann fyi">{"ORIG" if a.upper() in ("0", "ORIG") else "AMDT " + e(a)}</span>')
    if c.get("chart", {}).get("pdf"):
        extra.append(f'<a href="{e(c["chart"]["pdf"])}" target="_blank" rel="noopener">VIEW PLATE ›</a>')
    more = ""
    if c.get("original"):
        more = f'<details class="more"><summary>FAA TEXT ▸</summary><pre>{e(c["original"])}</pre></details>'
    elif c.get("details"):
        more = ('<details class="more"><summary>DETAILS ▸</summary><pre class="d">'
                + "\n".join(arrow(d) for d in c["details"]) + "</pre></details>")
    s = c["summary"]
    s = s[:1].upper() + s[1:]
    return (f'<div class="change p-{e(c["priority"])}"><div class="summary">{arrow(s)}</div>'
            f'<div class="meta">{e(c["category"])} {"".join(extra)}</div>{more}</div>')


def grouped(changes):
    out = []
    for p, _, title in PRIORITY:
        g = [c for c in changes if c["priority"] == p]
        if g:
            color = {"action": "var(--amber)", "ifr": "var(--cyan)", "fyi": "var(--dim)"}[p]
            out.append(f'<div class="sec"><span class="hdr" style="color:{color}">{title} {len(g)}</span></div>')
            out += [change_html(c) for c in g]
    return "".join(out)


def page(title, description, url, body, css_href):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Amend">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(url)}"><meta name="twitter:card" content="summary">
<meta name="theme-color" content="#090C10"><link rel="stylesheet" href="{css_href}">
</head><body>{body}
<p class="foot">Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight briefing.
Data: FAA NASR and d-TPP. <a href="https://github.com/benjgmin/amend">Source</a></p></body></html>"""


def status(meta, now):
    """(upcoming?, note) using the 0901Z changeover."""
    eff = dt.datetime.fromisoformat(meta["to_cycle"]).replace(hour=9, minute=1, tzinfo=dt.timezone.utc)
    upcoming = meta.get("upcoming") and now < eff
    if upcoming:
        days = (eff.date() - now.date()).days
        when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
        return True, (f"These changes take effect {efb(meta['to_cycle'])} 0901Z ({when}). "
                      f"Until then, the current value applies: it's the one before the →.")
    return False, (f"In effect since {efb(meta['to_cycle'])} 0901Z, compared to the previous cycle "
                   f"({efb(meta['from_cycle'])}).")


def airport_page(apt, info, latest, hist, meta, now):
    name = info.get("name", "")
    loc = ", ".join(x for x in (info.get("city"), info.get("state")) if x)
    changes = latest or []
    c = counts(changes)
    upcoming, note = status(meta, now)
    label = "Upcoming" if upcoming else "Latest"

    top = next((x["summary"] for x in changes if x["priority"] == "action"), None) or \
        (changes[0]["summary"] if changes else None)
    parts = [f"{lbl} {c[p]}" for p, lbl, _ in PRIORITY if c[p]]
    if changes:
        desc = f"{' · '.join(parts)} · {top}"
    else:
        desc = f"No {'upcoming ' if upcoming else ''}changes at {apt} in the {efb(meta['to_cycle'])} cycle."
    title = f"{apt} · {name}" if name else apt

    body = [f'<div class="top"><a class="brand" href="../">AMEND.</a><span class="hdr">{label} · EFF {efb(meta["to_cycle"])}</span></div>',
            '<div class="panel"><div class="row"><h1>', e(apt),
            f'<span class="icao">{e(info["icao"])}</span>' if info.get("icao") and info.get("icao") != apt else "",
            f'</h1>{chips(c)}</div>',
            f'<div class="name">{e(name)}</div>' if name else "",
            f'<div class="loc">{e(loc)}</div>' if loc else "", "</div>"]
    if changes:
        cls = "ifr" if upcoming else "ok"
        body.append(f'<div class="panel"><span class="ann {cls}">{"NOT IN EFFECT YET" if upcoming else "IN EFFECT"}</span>'
                    f'<div class="note">{e(note)}</div></div>')
        body.append(grouped(changes))
    else:
        body.append(f'<div class="none">{"NO UPCOMING CHANGES" if upcoming else "NOTHING CHANGED"} AT {e(apt)}'
                    f'<br>{"ON" if upcoming else "IN THE"} {efb(meta["to_cycle"])} {"· CURRENT DATA STAYS THE SAME" if upcoming else "CYCLE"}</div>')

    if hist and hist.get("entries"):
        body.append('<div class="sec"><span class="hdr">History since Aug 2024</span></div>')
        by_cycle = {}
        for x in hist["entries"]:
            by_cycle.setdefault(x["cycle"], []).append(x)
        for i, cyc in enumerate(sorted(by_cycle, reverse=True)):
            g = by_cycle[cyc]
            body.append(f'<details class="cycle"{" open" if i < 3 else ""}><summary><span class="chev">▸</span>'
                        f'<span class="hdr">EFF {efb(cyc)}</span>{chips(counts(g), False)}</summary>'
                        + "".join(change_html(x) for x in g) + "</details>")
    body.append(f'<p class="foot">Data: <a href="../latest/{e(apt)}.json">latest</a> · '
                f'<a href="../history/{e(apt)}.json">history</a> · built {now:%d %b %Y %H%MZ}</p>')
    return page(title, desc, f"{SITE_URL}{apt}/", "".join(body), "../assets/style.css")


def landing_note(meta, now, upcoming):
    if upcoming:
        days = (dt.date.fromisoformat(meta["to_cycle"]) - now.date()).days
        when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
        return f"Takes effect {when} at 0901Z; until then the current cycle (since {efb(meta['from_cycle'])}) applies."
    return f"In effect since {efb(meta['to_cycle'])} 0901Z."


def index_page(meta, directory, latest, pages, now):
    upcoming, note = status(meta, now)
    ranked = sorted(latest.items(), key=lambda kv: (-counts(kv[1])["action"], -len(kv[1]), kv[0]))[:25]
    names = {a["id"]: a for a in directory}
    top = "".join(
        f'<a href="{e(a)}/"><span class="rid">{e(a)}</span><span class="rname">{e(names.get(a, {}).get("name", ""))}'
        f'<br><span class="rsub">{e(", ".join(x for x in (names.get(a, {}).get("city"), names.get(a, {}).get("state")) if x)).upper()}</span></span>'
        f'{chips(counts(ch))}</a>' for a, ch in ranked)
    # compact directory for the search box: id, icao, name, city, state, has-page
    rows = [[a["id"], a.get("icao", ""), a.get("name", ""), a.get("city", ""), a.get("state", ""),
             1 if a["id"] in pages else 0] for a in directory]
    body = f"""<div class="top"><span class="brand">AMEND.</span><span class="hdr">FAA cycle changes</span></div>
<div class="panel"><div class="row"><span class="hdr">NASR cycle</span>
<span class="ann {'ifr' if upcoming else 'ok'}">{'UPCOMING' if upcoming else 'IN EFFECT'}</span></div>
<div class="hdr" style="margin-top:8px">{'Next cycle takes effect 0901Z' if upcoming else 'Current cycle in effect'}</div>
<div class="big">{efb(meta['to_cycle'])}</div>
<div class="note">{meta.get('changed_airports', len(latest))} airports {'change' if upcoming else 'changed'} in this cycle. {e(landing_note(meta, now, upcoming))}</div></div>
<p>Every 28 days the FAA publishes new airport, airspace and chart data. Amend compares each cycle to the last
and shows what changed at every US airport in plain English: tower hours, frequencies, runways, navaids,
approach plates. Search an airport:</p>
<input id="q" placeholder="ID, ICAO, NAME OR CITY" autocomplete="off" autofocus>
<div class="res" id="res"></div>
<div class="sec"><span class="hdr">Most action items this cycle</span></div><div class="list">{top}</div>
<p class="note">An iPhone app with your saved airports and cycle alerts is on the way.</p>
<script>
const A={json.dumps(rows, separators=(",", ":"))};
const q=document.getElementById("q"),r=document.getElementById("res");
const esc=s=>s.replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
q.addEventListener("input",()=>{{
  const s=q.value.trim().toUpperCase();if(!s){{r.innerHTML="";return}}
  const hit=[];for(const a of A){{const[id,ic,n,c]=a;let k=-1;
    if(id===s||ic===s)k=0;else if(id.startsWith(s)||ic.startsWith(s))k=1;
    else if(s.length>2&&n.toUpperCase().startsWith(s))k=2;
    else if(s.length>2&&(n.toUpperCase().includes(s)||c.toUpperCase().includes(s)))k=3;
    if(k>=0)hit.push([k*10+(ic?0:2),a])}}
  hit.sort((x,y)=>x[0]-y[0]||x[1][0].length-y[1][0].length||(x[1][0]<y[1][0]?-1:1));
  r.innerHTML=hit.slice(0,30).map(([_,a])=>{{const[id,ic,n,c,st,p]=a;const sub=[ic,[c,st].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
    return p?`<a href="${{esc(id)}}/"><span class="rid">${{esc(id)}}</span><span class="rname">${{esc(n)}}<br><span class="rsub">${{esc(sub).toUpperCase()}}</span></span><span class="ann ifr">VIEW</span></a>`
            :`<a><span class="rid">${{esc(id)}}</span><span class="rname">${{esc(n)}}<br><span class="rsub">${{esc(sub).toUpperCase()}}</span></span><span class="ann ok">NO CHG</span></a>`}}).join("")||'<div class="note">No airport found.</div>'}});
</script>"""
    return page("Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", SITE_URL, body, "assets/style.css")


def build(site, meta, directory, latest, history_dir, now=None):
    """write site/assets/style.css, site/<ID>/index.html for every airport with data, site/index.html."""
    now = now or dt.datetime.now(dt.timezone.utc)
    os.makedirs(os.path.join(site, "assets"), exist_ok=True)
    with open(os.path.join(site, "assets", "style.css"), "w") as f:
        f.write(CSS)
    info = {a["id"]: a for a in directory}
    hist_ids = set()
    if history_dir and os.path.isdir(history_dir):
        hist_ids = {n[:-5] for n in os.listdir(history_dir)
                    if n.endswith(".json") and n not in ("index.json", "cycles.json")}
    ids = (set(latest) | hist_ids) - RESERVED
    ids = {i for i in ids if re.fullmatch(r"[A-Z0-9]{2,4}", i)}   # never collides with latest/, history/, ...
    for apt in sorted(ids):
        hist = None
        if apt in hist_ids:
            with open(os.path.join(history_dir, f"{apt}.json"), encoding="utf-8") as f:
                hist = json.load(f)
        os.makedirs(os.path.join(site, apt), exist_ok=True)
        with open(os.path.join(site, apt, "index.html"), "w", encoding="utf-8") as f:
            f.write(airport_page(apt, info.get(apt, {}), latest.get(apt), hist, meta, now))
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(meta, directory, latest, ids, now))
    return len(ids)