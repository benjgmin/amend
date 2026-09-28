"""
RSS feeds, so pilots hear about a new cycle without visiting the site: site/<ID>/feed.xml for every airport
page and site/list/<slug>/feed.xml for every named watchlist. One item per cycle with changes, action items
first. The guid is the cycle, so a reader or an RSS-to-email service sends each cycle once, even if a later
build rewords it.
"""
import datetime as dt
import html
from email.utils import format_datetime

SITE_URL = "https://amend.watch/"
PRIORITY = [("action", "Action", "action item"), ("ifr", "IFR procedures", "IFR change"), ("fyi", "FYI", "FYI")]
LABEL = {"action": "ACT", "ifr": "IFR", "fyi": "FYI"}
NASR_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/{cycle}"
KEEP = 13            # cycles per feed, about a year; older ones stay on the page
MAX_ITEMS = 60       # changes written into one entry before "and N more"
DISCLAIMER = ("Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight "
              "briefing.")


def e(s):
    return html.escape(str(s or ""), quote=True)


def nice(cycle):
    return dt.date.fromisoformat(cycle).strftime("%d %b %Y")


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def cap(s):
    s = str(s or "")
    return s[:1].upper() + s[1:]


def published(cycle, now):
    """when an entry counts as posted. The FAA posts a cycle about three weeks early and the build keeps no
    state, so use the day the cycle before it took effect: always before the entry first shows up, never
    in the future, and the same on every build (so readers don't re-flag it)."""
    eff = dt.datetime.fromisoformat(cycle).replace(hour=9, minute=1, tzinfo=dt.timezone.utc)
    return min(eff - dt.timedelta(days=28), now)


def by_cycle(changes, hist, to_cycle):
    """{cycle: [changes]} newest first, at most KEEP. The cycle on the site right now comes from latest (it
    may be upcoming and not in history yet); older ones from history."""
    out = {}
    for x in (hist or {}).get("entries", []):
        if x.get("cycle") and not (changes and x["cycle"] == to_cycle):
            out.setdefault(x["cycle"], []).append(x)
    if changes:
        out[to_cycle] = list(changes)
    return {c: out[c] for c in sorted(out, reverse=True)[:KEEP]}


def ranked(changes):
    order = {p: i for i, (p, _, _) in enumerate(PRIORITY)}
    return sorted(changes, key=lambda c: order.get(c.get("priority"), 9))


def headline(changes):
    """'3 changes (1 action item)': what an email subject needs to say."""
    n = len(changes)
    act = sum(c.get("priority") == "action" for c in changes)
    return plural(n, "change") + f" ({plural(act, 'action item') if act else 'no action items'})"


def change_li(c, label=False):
    tag = f"<b>{LABEL.get(c.get('priority'), '')}</b> " if label else ""
    summary = e(cap(c.get("summary"))).replace(" -&gt; ", " → ")
    faa = f'<br><small>FAA text: {e(c["original"])}</small>' if c.get("original") else ""
    return f"<li>{tag}{e(cap(c.get('category')))}: {summary}{faa}</li>"


def airport_html(changes, cycle, from_cycle, link):
    parts, left = [], MAX_ITEMS
    for p, title, _ in PRIORITY:
        g = [c for c in changes if c.get("priority") == p]
        if g and left > 0:
            parts.append(f"<h3>{title} ({len(g)})</h3><ul>{''.join(change_li(c) for c in g[:left])}</ul>")
            left -= len(g)
    if left < 0:
        parts.append(f"<p>And {-left} more on the page.</p>")
    return "".join([effective_line(cycle, from_cycle)] + parts + [footer(link, cycle)])


def list_html(per_airport, cycle, link, names):
    """per_airport: [(ID, [changes])], most action items first."""
    parts, left = [], MAX_ITEMS
    for apt, ch in per_airport:
        if left <= 0:
            break
        name = names.get(apt, {}).get("name", "")
        parts.append(f'<h3><a href="{SITE_URL}{e(apt)}/">{e(apt)}</a>{" · " + e(name) if name else ""}: '
                     f"{headline(ch)}</h3><ul>{''.join(change_li(c, True) for c in ranked(ch)[:left])}</ul>")
        left -= len(ch)
    rest = sum(len(ch) for _, ch in per_airport) - MAX_ITEMS
    if rest > 0:
        parts.append(f"<p>And {rest} more on the page.</p>")
    return "".join([effective_line(cycle)] + parts + [footer(link, cycle)])


def effective_line(cycle, from_cycle=None):
    than = f", compared to {nice(from_cycle)}" if from_cycle else ""
    return f"<p>FAA cycle effective {nice(cycle)} at 0901Z{than}.</p>"


def footer(link, cycle):
    return (f'<p><a href="{e(link)}">See every change on Amend</a> · '
            f'<a href="{NASR_PAGE.format(cycle=cycle)}">FAA source</a></p><p><small>{DISCLAIMER}</small></p>')


def rss(title, link, self_url, description, items, now):
    """RSS 2.0. items: [{title, link, guid, date, html}] newest first."""
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">', "<channel>",
           f"<title>{e(title)}</title>", f"<link>{e(link)}</link>",
           f'<atom:link href="{e(self_url)}" rel="self" type="application/rss+xml"/>',
           f"<description>{e(description)}</description>", "<language>en-us</language>",
           f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>", "<ttl>720</ttl>"]
    for it in items:
        out += ["<item>", f"<title>{e(it['title'])}</title>", f"<link>{e(it['link'])}</link>",
                f'<guid isPermaLink="false">{e(it["guid"])}</guid>', f"<pubDate>{format_datetime(it['date'])}</pubDate>",
                f"<description>{e(it['html'])}</description>", "</item>"]
    return "\n".join(out + ["</channel>", "</rss>"]) + "\n"


def airport_feed(apt, info, changes, hist, meta, now, has_page=True):
    """has_page=False: a quiet airport with no page yet; its feed has no items and links to the home page."""
    cycles = by_cycle(changes, hist, meta["to_cycle"])
    page = f"{SITE_URL}{apt}/"
    hist_cycles = {x.get("cycle") for x in (hist or {}).get("entries", [])}
    items = []
    for cyc, ch in cycles.items():
        link = page + (f"#c-{cyc}" if cyc in hist_cycles and cyc != meta["to_cycle"] else "")
        frm = meta["from_cycle"] if cyc == meta["to_cycle"] else ch[0].get("from_cycle")
        items.append({"title": f"{apt}: {headline(ch)} on {nice(cyc)}", "link": link,
                      "guid": f"amend.watch/{apt}/{cyc}", "date": published(cyc, now),
                      "html": airport_html(ch, cyc, frm, link)})
    name = info.get("name", "")
    return rss(f"{apt}{' · ' + name if name else ''} · Amend", page if has_page else SITE_URL, f"{page}feed.xml",
               f"What changes at {apt} each FAA cycle, in plain English, action items first.", items, now)


def list_feed(slug, wl, names, latest, hists, meta, now):
    """hists: {ID: history json or None} for the list's airports."""
    per = {}   # cycle -> [(ID, changes)]
    for apt in wl["airports"]:
        for cyc, ch in by_cycle(latest.get(apt), hists.get(apt), meta["to_cycle"]).items():
            per.setdefault(cyc, []).append((apt, ch))
    page = f"{SITE_URL}list/{slug}/"
    items = []
    for cyc in sorted(per, reverse=True)[:KEEP]:
        rows = sorted(per[cyc], key=lambda r: (-sum(c.get("priority") == "action" for c in r[1]), -len(r[1]), r[0]))
        allc = [c for _, ch in rows for c in ch]
        a = sum(c.get("priority") == "action" for c in allc)
        link = page if cyc == meta["to_cycle"] else f"{SITE_URL}{rows[0][0]}/#c-{cyc}" if len(rows) == 1 else page
        items.append({"title": f"{wl['name']}: {plural(len(allc), 'change')} at {plural(len(rows), 'airport')} "
                               f"on {nice(cyc)} ({plural(a, 'action item') if a else 'no action items'})",
                      "link": link, "guid": f"amend.watch/list/{slug}/{cyc}", "date": published(cyc, now),
                      "html": list_html(rows, cyc, link, names)})
    return rss(f"{wl['name']} · Amend watchlist", page, f"{page}feed.xml",
               f"What changes at the {len(wl['airports'])} airports on {wl['name']} each FAA cycle, action items "
               "first.", items, now)
