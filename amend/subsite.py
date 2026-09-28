"""
The layout of status.amend.watch and docs.amend.watch: a slim header and one column, instead of the
airport site's sidebar.

GitHub Pages gives a repo one domain, so both pages are still built with the site, at site/status/ and
site/docs/, and a small Cloudflare Pages proxy (cloudflare/_worker.js) serves each under its own name.
Links out of these pages go to amend.watch in full. The shared files (/assets/, the icons and
latest/meta.json, which app.js reads the server clock from) are asked for from the page's own origin:
on amend.watch that's the file itself, and on the subdomains the proxy passes those paths through to
amend.watch, so fonts and the clock work the same under either name.

web.SUBDOMAINS turns the names on. Then amend.watch/status/ and /docs/ forward to them, keeping the
#section, and every Status and Docs link on the site points at them.
"""
import datetime as dt
import json

from . import brand, web
from .web import e

CSS = """<style>
.sx-in{max-width:1080px;margin:0 auto;padding:0 24px}
.sx-top{border-bottom:1px solid var(--ln);background:var(--p);position:sticky;top:0;z-index:5}
.sx-top .sx-in{display:flex;align-items:center;gap:10px;height:56px}
.sx-kind{font:500 15px var(--sans);color:var(--dm);padding-left:10px;border-left:1px solid var(--ln2);line-height:20px}
.sx-nav{margin-left:auto;display:flex;gap:18px;font-size:14px}.sx-nav a{color:var(--dm)}
.sx-nav a.on{color:var(--tx);font-weight:600}
.sx-main{max-width:1080px;margin:0 auto;padding:32px 24px 56px}
.sx-main .banner{margin-bottom:20px}
.sx-foot{border-top:1px solid var(--ln);color:var(--fn);font-size:12.5px;line-height:1.6;padding:20px 0 32px}
.sx-foot a{color:var(--dm)}
.sx-h{font:600 12px/1.4 var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--fn);margin:36px 0 10px}
@media (max-width:640px){.sx-in,.sx-main{padding-left:16px;padding-right:16px}}
@media (max-width:479px){.sx-nav .sx-x{display:none}.sx-main{padding-top:20px}}
</style>"""


def forward(kind):
    """once the names are on, amend.watch/status/ (or /docs/) opens its own name, keeping ?query and #section.
    Only on amend.watch itself: the proxy serves this same page under the new name, where it must stay."""
    if not web.SUBDOMAINS:
        return ""
    host = web.SITE_URL.split("//")[1].strip("/")
    return (f'<script>if(location.hostname==={json.dumps(host)})location.replace('
            f'{json.dumps(web.SUB_URLS[kind].rstrip("/") + "/")}+location.search+location.hash)</script>')


def page(kind, title, description, body, meta, now=None, head=""):
    """a whole page for status.amend.watch (kind "status") or docs.amend.watch ("docs")."""
    now = now or dt.datetime.now(dt.timezone.utc)
    site, url = web.SITE_URL, web.sub_url(kind)
    items = ((site, "Airports", "", "sx-x"), (f"{site}guide/", "Guide", "", "sx-x"),
             (web.sub_url("docs"), "Docs", "docs", ""), (web.sub_url("status"), "Status", "status", ""))
    cur = ' aria-current="page"'
    links = "".join(f'<a class="{(cls + " on").strip() if key == kind else cls}" href="{href}"{cur if key == kind else ""}>'
                    f'{text}</a>' for href, text, key, cls in items)
    fresh = web.freshness(meta, now)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">{forward(kind)}
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Amend">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{site}assets/card.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0E1926" media="(prefers-color-scheme: dark)">
{web.head_links("/", url)}
<link rel="stylesheet" href="/assets/style.css?v={web.CSS_VERSION}">{CSS}{head}
</head><body data-root="/" data-cyc="{e(meta['to_cycle'] if meta else '')}"{web.eff_attr(meta, now)} data-built="{now:%Y-%m-%dT%H:%M:%SZ}"><script src="/assets/app.js?v={web.APP_VERSION}"></script>
<header class="sx-top"><div class="sx-in"><a class="brand" href="{site}" aria-label="Amend home">{brand.svg(classes=True)}amend</a>
<span class="sx-kind">{"Status" if kind == "status" else "Docs"}</span><nav class="sx-nav" aria-label="Amend">{links}</nav></div></header>
<main class="sx-main"><div class="card banner stale" id="stale" hidden></div>{body}</main>
<footer class="sx-foot"><div class="sx-in">{fresh}{'. ' if fresh else ''}Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight briefing.
Amend is independent and not affiliated with the FAA.<br><a href="{site}">amend.watch</a> · <a href="{site}changelog/">Changelog</a> · <a href="{site}privacy/">Privacy</a> · <a href="{site}terms/">Terms</a> · <a href="{web.REPORT_URL}">Report a problem</a> · <a href="{web.REPO_URL}">Source</a></div></footer>
</body></html>"""
