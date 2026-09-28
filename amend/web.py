"""
Static web view: one HTML page per airport at site/<ID>/index.html, plus a searchable landing
page at site/index.html. No JavaScript needed to read a page (the landing search uses a little),
and every page has Open Graph tags so a link in iMessage or a group chat shows a preview card.

Never writes to the JSON paths in SCHEMA.md (latest/, history/, airports.json).
"""
import datetime as dt
import hashlib
import html
from urllib.parse import quote
import json
import os
import re
import shutil

from . import brand

from . import feeds

SITE_URL = "https://amend.watch/"
REPO_URL = "https://github.com/benjgmin/amend"
REPORT_URL = REPO_URL + "/issues/new"    # "report a problem" until there's an email address
# the FAA's own form for a mistake in its data (charts, procedures, airport and navaid data). Amend can't fix those
FAA_INQUIRY = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/Aeronautical_Inquiries/"
# Cloudflare Web Analytics: cookie-free visitor counts (the about page's privacy note says so). The token is
# public by design; "" turns the beacon off.
CF_BEACON = "d1ab67595c784b45827953de63a28e9a"
RESERVED = {"latest", "history", "assets", "watch", "list", "about", "guide", "docs", "changelog", "privacy", "terms", "status",
            "index.html", "airports.json", "cycles.ics"}  # never an airport page
PRIORITY = [("action", "ACT", "Action"), ("ifr", "IFR", "IFR procedures"), ("fyi", "FYI", "FYI")]
# what the labels mean, same words as the iOS guide (ios/Amend/GuideView.swift): css class, legend, tooltip,
# full text, example
TIERS = {
    "action": ("act", "changes how you fly", "Changes how you fly it: tower hours, frequencies, runways, navaids",
               "Changes how you fly the airport. Tower or Class D hours, frequencies, runways closed, renumbered or "
               "restricted, navaids removed or changed, new PPR or noise rules.",
               "Tower hours changed: 0700-2100 → 0700-0100 local"),
    "ifr": ("ifr", "instrument procedures", "Approaches, STARs, departures and IFR routes",
            "Instrument procedures: approaches amended, added or removed, STARs and departures, preferred IFR "
            "routes. Matters most if you fly IFR there.",
            "Approach ILS OR LOC RWY 04R amended (AMDT 11C)"),
    "fyi": ("fyi", "worth knowing", "Worth knowing: phone numbers, fees, obstacles, reworded remarks",
            "Worth knowing, rarely changes your flight: phone numbers, landing fees, obstacle and marking updates, "
            "name changes, reworded remarks.",
            "Airport phone number changed"),
}
NO_CHG_TIP = "Nothing changed at this airport between the two cycles"
# email alerts for named watchlists: paste a Buttondown embed-subscribe url here, e.g.
# "https://buttondown.com/api/emails/embed-subscribe/amend". Empty = no email form, only the RSS feed.
# Each signup is tagged list:<slug>, so one RSS-to-email automation per list can send just to its tag.
EMAIL_FORM = ""


# IBM Plex Sans and IBM Plex Mono (SIL OFL, amend/fonts/OFL.txt), served from amend.watch itself so a page view
# never touches Google. Split the way Google Fonts does: Plex Sans is variable, latin plus a latin-ext file a page
# loads only when it needs it; Plex Mono (airport IDs, FAA text) is latin at the three weights the site uses.
LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,"
         "U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,"
             "U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")
WEB_FONTS = [("IBM Plex Sans", "plex-sans-latin.woff2", "100 700", LATIN),
             ("IBM Plex Sans", "plex-sans-latin-ext.woff2", "100 700", LATIN_EXT),
             ("IBM Plex Mono", "plex-mono-400.woff2", "400", LATIN), ("IBM Plex Mono", "plex-mono-500.woff2", "500", LATIN),
             ("IBM Plex Mono", "plex-mono-600.woff2", "600", LATIN)]
FONT_FACES = "".join(f'@font-face{{font-family:"{fam}";font-style:normal;font-weight:{wght};font-display:swap;'
                     f'src:url(fonts/{file}) format("woff2");unicode-range:{rng}}}\n'
                     for fam, file, wght, rng in WEB_FONTS)
# light and dark follow the device. Neutrals carry the page and colour only ever means something, as on a
# sectional chart: magenta = action, blue = IFR (and links), grey = FYI, green = nothing changed, the same as the
# iOS app. The tokens keep their older names (--am was amber, --cy cyan). --on is text on a solid colour.
CSS = FONT_FACES + """
:root{--bg:#F6F8FA;--p:#FFFFFF;--p2:#EEF2F6;--ln:#DDE3EA;--ln2:#C3CCD7;--tx:#0D1B2A;--dm:#4B5B6E;--fn:#667385;
--am:#A3186E;--amS:#F8E6F0;--cy:#1A5EA6;--cyS:#E3EDF8;--gy:#4B5B6E;--gyS:#EEF2F6;--gn:#2D7A4B;--gnS:#E4F2E9;--on:#FFFFFF;
--amber:var(--am);--cyan:var(--cy);--dim:var(--dm);--shadow:none;
--mk:#FFFFFF;--mkl:#C3CCD7;--mko:#AAB5C3;--mks:#A3186E;--mkn:#0D1B2A;
--sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#09121C;--p:#0E1926;--p2:#152233;--ln:#1F3044;--ln2:#2E4460;--tx:#E6EDF5;
--dm:#9DAEC2;--fn:#7A8DA4;--am:#E26BB2;--amS:rgba(226,107,178,.14);--cy:#7FB2EC;--cyS:rgba(127,178,236,.14);
--gy:#9DAEC2;--gyS:rgba(157,174,194,.12);--gn:#67C08B;--gnS:rgba(103,192,139,.13);--on:#09121C;--shadow:none;
--mk:#0E1926;--mkl:#2E4460;--mko:#4F627B;--mks:#E26BB2;--mkn:#E6EDF5;color-scheme:dark}}
*{box-sizing:border-box}html{background:var(--bg)}[hidden]{display:none!important}
body{margin:0;color:var(--tx);background:var(--bg);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
a{color:var(--cy);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--cy);outline-offset:2px}
b,strong{font-weight:600}
.app{display:grid;grid-template-columns:minmax(0,1fr);min-height:100vh;align-content:start}
.sb{display:none}
.mtop{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);background:var(--p);position:sticky;top:0;z-index:5}
.brand{font:600 17px var(--sans);letter-spacing:-.2px;color:var(--tx);display:inline-flex;align-items:center;gap:8px}
.brand:hover{text-decoration:none}
.brand svg{width:24px;height:24px;flex:none}.brand .mk{fill:var(--mk);stroke:var(--mkl)}.brand .mo{fill:var(--mko)}
.brand .ms{fill:var(--mks)}.brand .mn{fill:var(--mkn)}
.nav{display:flex;gap:16px;font-size:14px}.nav a{color:var(--dm)}.nav a.on{color:var(--tx);font-weight:500}
.main{padding:20px 16px 48px;display:grid;gap:20px;grid-template-columns:minmax(0,1fr);align-content:start;width:100%;max-width:1400px;margin:0 auto}
.col,.rail{display:grid;gap:16px;align-content:start;min-width:0}.col>div:empty{display:none}
.rail .hist{display:none}
.full{min-width:0}
.eyebrow{font-size:12px;color:var(--dm);text-transform:uppercase;letter-spacing:.06em}
h1{font:600 36px/1.1 var(--sans);letter-spacing:-.6px;margin:2px 0 0;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1 .icao{font:500 15px var(--mono);color:var(--fn);letter-spacing:.02em}
.aname{color:var(--dm);font-size:16px;margin-top:2px}
.h2{font:600 18px/1.3 var(--sans);letter-spacing:-.2px;margin:14px 0 0}
.hero{font:600 32px/1.15 var(--sans);letter-spacing:-.6px;margin:0;text-wrap:balance}
.lede{color:var(--dm);font-size:16px;max-width:62ch;margin:8px 0 0}
.big{font:600 26px/1.2 var(--sans);letter-spacing:-.4px}
.note{font-size:14px;color:var(--dm);margin:6px 0 0}
.foot{font-size:12.5px;color:var(--fn);margin:8px 0 0}.foot a{color:var(--dm)}.foot a:hover{color:var(--cy)}
.card{background:var(--p);border:1px solid var(--ln);border-radius:8px;box-shadow:var(--shadow)}
.box{padding:14px 16px}.box>h3{margin:0 0 8px;font:600 12px var(--sans);text-transform:uppercase;letter-spacing:.06em}
.kv{display:flex;justify-content:space-between;gap:12px;padding:7px 0;font-size:14px;border-top:1px solid var(--ln)}
.kv:first-of-type{border-top:0}.kv>span:first-child{color:var(--dm)}.kv>span:last-child{text-align:right;font-variant-numeric:tabular-nums}
.ann{display:inline-flex;align-items:center;gap:5px;font:600 10.5px/1.6 var(--sans);letter-spacing:.06em;text-transform:uppercase;padding:0 6px;border:1px solid var(--ln2);border-radius:3px;white-space:nowrap;color:var(--gy)}
.act{color:var(--on);background:var(--am);border-color:var(--am)}.ifr{color:var(--cy);border-color:var(--cy)}
.fyi{color:var(--dm);border-color:var(--ln2)}.ok{color:var(--gn);border-color:var(--gn)}
.ann[title]{cursor:help}
.ann.new{color:var(--p);background:var(--tx);border-color:var(--tx)}
.it.new{box-shadow:inset 3px 0 0 var(--tx)}
.sbi .ann.new,.sbt .ann.new,.sba .ann.new{font-size:10px;padding:0 5px}
time[data-until],time[data-ago]{font-variant-numeric:tabular-nums;white-space:nowrap}
.flip{display:contents}
.pfresh{padding:7px 16px;font-size:12.5px;color:var(--dm);border-bottom:1px solid var(--ln);background:var(--p)}
.is-stale .fresh{color:var(--am)}.stale{border-color:var(--am)}
a.src{color:var(--dm)}a.src:hover{color:var(--cy)}
.nx{display:grid;gap:7px;padding:12px 16px;border-top:1px solid var(--ln);color:var(--tx)}.nx:first-child{border-top:0}
.nx:hover{background:var(--p2);text-decoration:none}
.nxh{display:flex;align-items:center;gap:6px 12px;flex-wrap:wrap}.nxh .rname{color:var(--dm);font-size:14px}.nxh .chips{margin-left:auto}
.nxi{display:grid;grid-template-columns:40px minmax(0,1fr);gap:10px;align-items:baseline;font-size:14px;overflow-wrap:anywhere}.nxi>.ann{justify-self:start}
.nxm{font-size:13px;color:var(--cy);padding-left:50px}
.nxq{padding:11px 16px;border-top:1px solid var(--ln);font-size:13.5px;color:var(--dm)}.nxq:first-child{border-top:0}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}
.seg{display:flex;gap:24px;box-shadow:inset 0 -1px 0 var(--ln);max-width:100%;overflow-x:auto}.toolbar .seg{flex:1}
.seg a{font:500 14px var(--sans);padding:9px 0 7px;border-bottom:2px solid transparent;color:var(--dm);white-space:nowrap}
.seg a b{margin-left:5px;font-weight:500;color:var(--fn)}.seg a:hover{text-decoration:none;color:var(--tx)}
.seg a.on{color:var(--tx);border-bottom-color:var(--tx)}.seg a.on b{color:var(--tx)}
.seg button{font:500 14px var(--sans);padding:9px 0 7px;border:0;border-bottom:2px solid transparent;background:none;color:var(--dm);white-space:nowrap;cursor:pointer}
.seg button b{margin-left:5px;font-weight:500;color:var(--fn)}.seg button:hover{color:var(--tx)}
.seg button.on{color:var(--tx);border-bottom-color:var(--tx)}.seg button.on b{color:var(--tx)}
.tabs{display:inline-flex;vertical-align:top;margin:0 0 10px}#ltabs .tabs{margin:12px 0 0}
.lnk{background:none;border:0;padding:0;font:inherit;color:var(--cy);cursor:pointer}.lnk:hover{text-decoration:underline}
.lnk.dim{color:var(--dm)}.sec .lnk{font-size:13.5px}
.manage{display:flex;flex-wrap:wrap;gap:4px 16px;margin-top:10px;font-size:13.5px}.manage:empty{display:none}
.nf{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0;max-width:560px}
.nf input{flex:1 1 200px;min-width:0;border:1px solid var(--ln);border-radius:6px;background:var(--p);color:var(--tx);font:15px var(--sans);padding:7px 12px}
.nf input:focus{outline:none;border-color:var(--cy)}
.addw{position:relative;display:inline-flex}
.btn.dd::after{content:"";border:4px solid transparent;border-top-color:currentColor;margin:4px 0 0 8px}
.menu{position:absolute;top:calc(100% + 6px);left:0;z-index:20;width:max-content;min-width:240px;max-width:min(340px,calc(100vw - 32px));padding:6px;box-shadow:0 10px 30px rgba(0,0,0,.18)}
.mh{font-size:12.5px;color:var(--fn);padding:6px 10px 4px}
.mi{display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border:0;border-radius:8px;background:none;color:var(--tx);font:14px var(--sans);text-align:left;cursor:pointer}
.mi:hover{background:var(--p2)}.mi input{margin:0;width:16px;height:16px;accent-color:var(--cy);flex:none}
.mi .nm,.sbi .nm,.sbt .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mi .n,.sbi .n{color:var(--fn);font-size:12.5px}
.mi.add{color:var(--cy)}.menu .nf{margin:4px 6px 6px}
.addto{display:block;margin:0 0 8px}
.addto select{font:500 14px var(--sans);color:var(--tx);background:var(--p);border:1px solid var(--ln);border-radius:8px;padding:3px 8px;margin-left:6px;max-width:60vw}
.banner{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;padding:12px 14px;font-size:14px;color:var(--dm)}
.banner .ann{margin-top:1px}.banner span:last-child{flex:1;min-width:200px}
.lst{background:var(--p);border:1px solid var(--ln);border-radius:8px;overflow:hidden;box-shadow:var(--shadow)}
.gh{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px 10px;font:600 12px var(--sans);text-transform:uppercase;letter-spacing:.06em}
.gh .n{color:var(--fn);font-weight:500}
.dot{width:3px;height:12px;border-radius:1px;display:inline-block;margin-right:9px;background:var(--fn);vertical-align:-1px}
.d-action{background:var(--am)}.d-ifr{background:var(--cy)}
.it{display:grid;grid-template-columns:minmax(0,1fr);gap:2px 16px;padding:11px 16px;border-top:1px solid var(--ln)}
.it .k{font-size:11.5px;color:var(--fn);text-transform:uppercase;letter-spacing:.05em}
.it .s{font-size:15px;overflow-wrap:anywhere}
.it .m{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13.5px;white-space:nowrap}
.it .m:empty{display:none}
.more{margin-top:3px}
.more>summary{cursor:pointer;list-style:none;font-size:13.5px;color:var(--cy);display:inline-block}
.more>summary::-webkit-details-marker{display:none}
.more>summary::after{content:" \\25BE";font-size:11px}.more[open]>summary::after{content:" \\25B4"}
.more pre{white-space:pre-wrap;font:12px/1.55 var(--mono);color:var(--dm);background:var(--p2);border-radius:6px;padding:9px 11px;margin:6px 0 0}
.cycle>summary{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px;cursor:pointer;list-style:none;font:600 14px var(--sans)}
.cycle>summary::-webkit-details-marker{display:none}
.cycle>summary .chips{margin-left:auto}
.cycle:not([open])>summary:hover{background:var(--p2)}
.chev{width:12px;color:var(--fn);transition:transform .15s;display:inline-block;font-size:11px}
.cycle[open] .chev{transform:rotate(90deg)}
.hlist{display:grid;gap:10px}
.hrow{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:7px 0;border-top:1px solid var(--ln);font-size:14px;color:var(--tx)}
.hrow:first-of-type{border-top:0}.hrow .chips{flex-wrap:nowrap}.hrow:hover{text-decoration:none;color:var(--cy)}
.none{text-align:center;padding:36px 16px;color:var(--dm)}.none b{display:block;color:var(--gn);font-size:16px;margin-bottom:4px}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;font-size:13.5px;color:var(--dm)}
.legend>span{display:inline-flex;align-items:center;gap:8px}
.rail .legend{flex-direction:column;align-items:flex-start;gap:8px}
.search{display:flex;align-items:center;gap:10px;background:var(--p);border:1px solid var(--ln2);border-radius:8px;padding:0 14px;box-shadow:var(--shadow);color:var(--fn)}
.search:focus-within{border-color:var(--cy)}
.search input{flex:1;border:0;background:transparent;color:var(--tx);font:16px var(--sans);padding:13px 0;outline:none;min-width:0}
.search input::placeholder{color:var(--fn)}
kbd{font:500 12px var(--mono);border:1px solid var(--ln);border-radius:3px;padding:0 6px;color:var(--fn)}
.sec{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:4px 0 8px}
.hdr{font:600 14px var(--sans);color:var(--tx)}
.rows{background:var(--p);border:1px solid var(--ln);border-radius:8px;overflow:hidden;box-shadow:var(--shadow)}
.wrow{display:flex;align-items:stretch;border-top:1px solid var(--ln)}.wrow:first-child{border-top:0}
.wrow>a{flex:1;display:flex;align-items:center;gap:12px;padding:10px 14px;color:var(--tx);min-width:0}
.wrow>a[href]:hover{background:var(--p2);text-decoration:none}
.rid{font:600 15px var(--mono);min-width:52px}.rname{flex:1;min-width:0;font-size:14.5px}.rsub{font-size:12.5px;color:var(--dm)}
.x{background:transparent;border:0;border-left:1px solid var(--ln);color:var(--cy);min-width:48px;font:500 20px var(--sans);cursor:pointer}
.x.on{color:var(--gn)}.x:hover{background:var(--p2)}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}
.btn{display:inline-flex;align-items:center;background:var(--cy);color:var(--on);border:1px solid var(--cy);border-radius:6px;padding:8px 14px;font:500 14px var(--sans);cursor:pointer}
.btn:hover{text-decoration:none;opacity:.88}.btn:disabled{opacity:.5;cursor:default}
.btn.ghost{background:var(--p);color:var(--tx);border-color:var(--ln2)}
.cards{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.ac{display:grid;gap:8px;align-content:start;padding:12px 14px;color:var(--tx)}
.ac:hover{text-decoration:none;border-color:var(--fn)}
.ac .h{display:flex;align-items:baseline;gap:10px;min-width:0}.ac .h b{font:600 17px var(--mono)}
.ac small{color:var(--dm);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ac .t{font-size:13.5px;color:var(--dm);border-top:1px solid var(--ln);padding-top:8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.apt>summary{list-style:none;cursor:pointer}.apt>summary::-webkit-details-marker{display:none}
.apt{display:grid;gap:12px}
.apthead{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:12px 16px}
.apthead .rid{font-size:18px;min-width:0}.apthead .rname{color:var(--dm)}
.tier{display:grid;grid-template-columns:84px 1fr;align-items:start;gap:4px 12px;margin:12px 0}.tier .ann{justify-self:start;margin-top:1px}
.tier .eg{grid-column:2;font:12.5px var(--mono)}.eg-act{color:var(--am)}.eg-ifr{color:var(--cy)}.eg-fyi{color:var(--dm)}
.guide p{margin:10px 0}.guide .card{scroll-margin-top:16px}
.ggrid{display:grid;gap:14px;grid-template-columns:minmax(0,1fr)}
.feats{display:grid;gap:12px;grid-template-columns:minmax(0,1fr)}
.feats .card h3{margin:10px 0 2px;font:600 16px var(--sans)}
.shots{display:flex;gap:12px;overflow-x:auto;padding:4px 0}.shots img{height:440px;border-radius:18px;border:1px solid var(--ln)}
.welcome{padding:20px}.welcome h2{font:600 22px var(--sans);letter-spacing:-.4px;margin:0 0 8px}
.welcome p{margin:8px 0;color:var(--dm)}.welcome .tier{font-size:14px}
.welcome .wfoot{display:flex;align-items:center;justify-content:space-between;margin-top:14px}
.welcome .wfoot .btns{margin:0}
.dots{display:flex;gap:6px}.dots i{width:8px;height:6px;border-radius:3px;background:var(--ln);transition:width .15s}
.dots i.on{width:22px;background:var(--tx)}
.sbh{font:600 11px var(--sans);color:var(--fn);margin:18px 8px 4px;text-transform:uppercase;letter-spacing:.07em}
.sbi{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 8px;border-radius:6px;font-size:14px;color:var(--tx)}
a.sbi{color:var(--dm);transition:color .15s}a.sbi:hover{color:var(--tx);text-decoration:none}
.sbi.on,a.sbi.on{background:var(--p2);color:var(--tx);font-weight:500}
.sbi b{font:600 13px var(--mono)}.sbi.sub{color:var(--dm);font-size:13.5px}
.sbt{display:flex;align-items:center;gap:8px;width:100%;padding:6px 8px;border:0;border-radius:6px;background:none;color:var(--dm);font:14px var(--sans);text-align:left;cursor:pointer;transition:color .15s}
.sbt:hover,.sbl.open>.sbt{color:var(--tx);text-decoration:none}.sbl.open>.sbt{font-weight:500}.sbl.on>.sbt{background:var(--p2);color:var(--tx)}
.sbt .n{margin-left:auto;font:12px var(--mono);color:var(--fn)}.sbt .nw{margin-left:auto}.sbt .nw+.n{display:none}
.sbl.open .sbt .nw{display:none}.sbl.open .sbt .nw+.n{display:inline}
.sbp{display:grid;grid-template-rows:0fr;transition:grid-template-rows .22s ease}.sbl.open>.sbp{grid-template-rows:1fr}
.sbq{min-height:0;overflow:hidden;margin-left:16px;border-left:1px solid var(--ln);opacity:0;transition:opacity .22s ease}
.sbl.open .sbq{opacity:1}
.sba{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-left:-1px;padding:4px 10px;border-left:2px solid transparent;font-size:13.5px;color:var(--dm);transition:color .15s,border-color .15s}
.sba b{font:500 13px var(--mono)}.sba:hover{color:var(--tx);text-decoration:none;border-left-color:var(--ln2)}
.sba.on{color:var(--tx);border-left-color:var(--tx)}.sba.go{color:var(--cy);margin-bottom:6px}.sba.go:hover{border-left-color:var(--cy)}
.sba.sub{color:var(--fn)}
.sb .search{margin:14px 0 0;border-radius:6px;padding:0 10px;box-shadow:none}.sb .search input{font-size:14px;padding:7px 0}
.sbfoot{margin-top:auto;padding:16px 8px 0;font-size:12.5px;color:var(--fn)}.sbfoot a{color:var(--dm)}
.doc{display:grid;gap:14px;max-width:780px}.doc .card,.ggrid .card{scroll-margin-top:64px}
.toc{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:14px;font-size:14px}
.prose code{font:13px var(--mono);background:var(--p2);border-radius:3px;padding:0 4px;overflow-wrap:anywhere}
.go{display:grid;gap:4px;align-content:start;color:var(--tx)}.go:hover{text-decoration:none;border-color:var(--fn)}.go .note{margin:0}
.prose p{margin:10px 0 0}.prose ul{margin:10px 0 0;padding-left:18px}.prose li{margin:6px 0}.prose li::marker{color:var(--fn)}
.pop>summary{list-style:none}.pop>summary::-webkit-details-marker{display:none}
.pop[open]>summary{border-color:var(--tx)}.pop>.menu{width:340px;padding:14px 16px}.pop .note{margin-top:0}
@media (max-width:639px){.pop[open]{flex-basis:100%;flex-wrap:wrap}.pop>.menu{position:static;width:100%;max-width:none;margin-top:8px;box-shadow:none}}
.alerts .btns{margin-top:10px}.alerts .more{margin-top:10px}
.steps{margin:10px 0 0;padding-left:20px;font-size:14px;color:var(--dm)}.steps li{margin:4px 0}.steps li::marker{color:var(--fn)}.alerts form{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.alerts input[type=email]{flex:1;min-width:0;border:1px solid var(--ln);border-radius:6px;background:var(--p);color:var(--tx);font:15px var(--sans);padding:7px 10px}
.alerts input[type=email]:focus{outline:none;border-color:var(--cy)}
@view-transition{navigation:auto}
.sb{view-transition-name:sb}.mtop{view-transition-name:mtop}
::view-transition-old(root),::view-transition-new(root){animation-duration:.16s}
@media (prefers-reduced-motion:reduce){*{transition:none!important}@view-transition{navigation:none}}
@media (max-width:359px){.nav{gap:12px;font-size:13.5px}}
@media (max-width:639px){.wrow>a{flex-wrap:wrap;row-gap:6px}.wrow>a .chips,.nxh .chips{flex-basis:100%;margin-left:0;padding-left:64px}}
@media (min-width:640px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.feats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (min-width:1000px){
 .app{grid-template-columns:248px minmax(0,1fr)}
 html{overscroll-behavior-y:none}
 .sb{display:flex;flex-direction:column;position:sticky;top:0;align-self:start;height:100vh;height:100dvh;overflow-y:auto;overscroll-behavior:contain;border-right:1px solid var(--ln);background:var(--p);padding:16px 12px}
 .sb .brand{padding:4px 8px 0}
 .mtop,.pfresh{display:none}
 .main{padding:32px 40px 56px}
 .main.two{grid-template-columns:minmax(0,1fr) 300px;column-gap:32px;align-items:start}
 .main.two>.full{grid-column:1/-1}.main.two>.foot.full{grid-column:1}
 .rail{position:sticky;top:24px}.rail .hist{display:block}
 .it{grid-template-columns:104px minmax(0,1fr) auto;align-items:baseline}
 .it .k{font-size:11.5px;color:var(--dm)}.it .m{justify-content:flex-end}
 .cards{grid-template-columns:repeat(3,minmax(0,1fr))}
 .ggrid{grid-template-columns:repeat(2,minmax(0,1fr))}.ggrid>.wide{grid-column:1/-1}
 .feats{grid-template-columns:repeat(3,minmax(0,1fr))}
 h1{font-size:40px}.hero{font-size:36px}
}
@media print{:root{--bg:#fff;--p:#fff;--p2:#F2F4F7;--ln:#D5DBE2;--ln2:#B8C2CE;--tx:#000;--dm:#444;--fn:#666;--am:#8E1560;
--amS:#F8E6F0;--cy:#15508F;--cyS:#E3EDF8;--gy:#444;--gyS:#EEF2F6;--gn:#2D7A4B;--gnS:#E4F2E9;--on:#fff;--shadow:none;
--mk:#fff;--mkl:#B8C2CE;--mko:#AAB5C3;--mks:#A3186E;--mkn:#000;color-scheme:light}
 .act{color:var(--am);background:none}.ann.new{color:var(--tx);background:none}
 .sb,.mtop,.rail,.seg,.btns,.search,#res,#welcome,#newnote,#next .nxm,.manage,.nf,.menu,.addto,#lnote,.foot .lnk{display:none!important}
 .app{display:block}.main{display:block;padding:0;max-width:none}.main>*,.col>*{margin-bottom:12px}
 body{font-size:12.5px}a{color:inherit}.it,.apthead,.nx{break-inside:avoid}.it.new{box-shadow:none}}
"""

# changes whenever the CSS does, so a browser holding the old style.css (Pages caches it for 10 minutes)
# never pairs it with new HTML
CSS_VERSION = hashlib.sha1(CSS.encode()).hexdigest()[:10]

FONT_PATHS = {  # the site's own IBM Plex Sans first; DejaVu (GitHub's Ubuntu runners) and Helvetica (Macs) as fallbacks
    "sans": [os.path.join(brand.FONTS, "IBMPlexSans-SemiBold.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Helvetica.ttc"],
    "med": [os.path.join(brand.FONTS, "IBMPlexSans-Medium.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc"],
    "reg": [os.path.join(brand.FONTS, "IBMPlexSans-Regular.ttf"), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc"],
}
# the site's light palette, and each label's colour: action is a solid tag, the rest are outlined like on the site
COLORS = {"bg": (246, 248, 250), "panel": (255, 255, 255), "line": (221, 227, 234), "text": (13, 27, 42),
          "dim": (75, 91, 110), "faint": (102, 115, 133)}
CHIP_COLORS = {"action": (163, 24, 110), "ifr": (26, 94, 166), "fyi": (195, 204, 215), "ok": (45, 122, 75)}


def _font(kind, size):
    from PIL import ImageFont
    for p in FONT_PATHS[kind]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def _fit(draw, text, font, width):
    """cut text with an ellipsis so it fits in width pixels."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def card(path, big, name, loc, chip_list, line, footer):
    """1200x630 link-preview image in the site's light look, with the logo. returns False if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H, P = 1200, 630, 64
    img = Image.new("RGB", (W, H), COLORS["bg"])
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([P - 24, P - 24, W - P + 24, H - P + 24], radius=16, fill=COLORS["panel"],
                        outline=COLORS["line"], width=2)
    # the logo: the mark, then "amend" centred on it the way the site header sets it
    mark = brand.draw(48)
    img.paste(mark, (P, P - 4), mark)
    word = _font("sans", 37)
    top, bottom = d.textbbox((0, 0), "amend", font=word, anchor="ls")[1::2]
    d.text((P + 60, P + 20 - (top + bottom) / 2), "amend", font=word, fill=COLORS["text"], anchor="ls")
    small = _font("reg", 26)
    d.text((W - P, P + 20), footer, font=small, fill=COLORS["dim"], anchor="rm")
    size = 132
    while size > 48 and d.textlength(big, font=_font("sans", size)) > W - 2 * P:
        size -= 8
    d.text((P - 4, P + 80 + (132 - size) // 2), big, font=_font("sans", size), fill=COLORS["text"])
    y = P + 250
    if name:
        d.text((P, y), _fit(d, name, _font("sans", 46), W - 2 * P), font=_font("sans", 46), fill=COLORS["text"])
        y += 62 if loc else 76
    if loc:
        d.text((P, y), loc, font=small, fill=COLORS["dim"])
        y += 50
    x, cf, track = P, _font("sans", 25), 2      # the site's labels: semibold capitals, tracked out a little
    for text, key in chip_list:
        text = text.upper()
        tw = sum(d.textlength(ch, font=cf) for ch in text) + track * (len(text) - 1)
        col = CHIP_COLORS[key]
        solid = key == "action"
        d.rounded_rectangle([x, y, x + tw + 36, y + 50], radius=6, fill=col if solid else None, outline=col,
                            width=3)
        ink = COLORS["panel"] if solid else COLORS["dim"] if key == "fyi" else col
        cx = x + 18
        for ch in text:
            d.text((cx, y + 26), ch, font=cf, fill=ink, anchor="lm")
            cx += d.textlength(ch, font=cf) + track
        x += tw + 52
    if line:
        d.text((P, y + 78), _fit(d, line, _font("reg", 32), W - 2 * P), font=_font("reg", 32),
               fill=COLORS["dim"])
    img.save(path, optimize=True)
    return True


COMMON_JS = 'const TIP=' + json.dumps({**{v[0]: v[2] for v in TIERS.values()}, "ok": NO_CHG_TIP}) + ';\n' + r"""
const parseW=q=>[...new Set((q||"").toUpperCase().split(/[\s,]+/).map(s=>s.replace(/^K(?=[A-Z]{3}$)/,"")).filter(s=>/^[A-Z0-9]{2,4}$/.test(s)))].slice(0,200);
function chipsHtml(k){if(!k||!(k[0]||k[1]||k[2]))return '<span class="chips"><span class="ann ok" title="'+TIP.ok+'">No change</span></span>';
  const t=[[k[0],"act","ACT"],[k[1],"ifr","IFR"],[k[2],"fyi","FYI"]].filter(x=>x[0]).map(x=>'<span class="ann '+x[1]+'" title="'+TIP[x[1]]+'">'+x[2]+' '+x[0]+'</span>');
  return '<span class="chips">'+t.join("")+'</span>'}
"""
LANDING_JS = r"""const A=__ROWS__;const byId=new Map(A.map(a=>[a[0],a]));
const NX=__NEXT__;let NEWC=AM.newc();
const q=document.getElementById("q"),r=document.getElementById("res"),params=new URLSearchParams(location.search);
if(params.get("w"))location.replace("list/"+location.search);   // early share links pointed here
if(params.get("q")){q.value=params.get("q");
  // the sidebar search on other pages: an exact ID or ICAO code goes straight to that airport
  const s=q.value.trim().toUpperCase(),a=params.has("go")&&A.find(x=>x[0]===s||x[1]===s);if(a&&a[5])location.replace(a[0]+"/")}
function sub(a){return esc([a[1],[a[3],a[4]].filter(Boolean).join(", ")].filter(Boolean).join(" · "))}
function airportRow(id,btn){const a=byId.get(id)||[id,"","","","",0,null];
  const inner='<span class="rid">'+esc(a[0])+'</span><span class="rname">'+esc(a[2]||"Unknown airport")+'<br><span class="rsub">'+sub(a)+'</span></span>'+chipsHtml(a[6]).replace('<span class="chips">','<span class="chips">'+(NEWC[id]?AM.pill(NEWC[id]):""));
  return '<div class="wrow">'+(a[5]?'<a href="'+esc(a[0])+'/">'+inner+'</a>':'<a>'+inner+'</a>')+btn+'</div>'}
const act=id=>((byId.get(id)||[])[6]||[0])[0];
// + / ✓ / × act on the list in use; with no list yet, + starts "My airports"
function xBtn(id,l,kind){const n=esc(l?l.name:"a new list");
  return kind==="add"?'<button class="x" data-add="'+esc(id)+'" title="Add to '+n+'" aria-label="Add '+esc(id)+' to '+n+'">+</button>'
    :'<button class="x'+(kind==="on"?' on':'')+'" data-rm="'+esc(id)+'" title="Remove from '+n+'" aria-label="Remove '+esc(id)+' from '+n+'">'+(kind==="on"?"✓":"×")+'</button>'}
function renderSearch(){const s=q.value.trim().toUpperCase();if(!s){r.innerHTML="";return}
  const hit=[];for(const a of A){const[id,ic,n,c]=a;let k=-1;
    if(id===s||ic===s)k=0;else if(id.startsWith(s)||ic.startsWith(s))k=1;
    else if(s.length>2&&n.toUpperCase().startsWith(s))k=2;
    else if(s.length>2&&(n.toUpperCase().includes(s)||c.toUpperCase().includes(s)))k=3;
    if(k>=0)hit.push([k*10+(ic?0:2),a])}
  hit.sort((x,y)=>x[0]-y[0]||x[1][0].length-y[1][0].length||(x[1][0]<y[1][0]?-1:1));
  const ls=LS.all(),l=LS.active(),on=new Set(l?l.ids:[]);
  const to=ls.length>1?'<label class="addto note">Tap + to add to <select id="addto">'+ls.map(x=>'<option value="'+esc(x.id)+'"'+(x.id===l.id?" selected":"")+'>'+esc(x.name)+'</option>').join("")+'</select></label>':"";
  r.innerHTML=hit.length?to+'<div class="rows">'+hit.slice(0,30).map(([_,a])=>airportRow(a[0],xBtn(a[0],l,on.has(a[0])?"on":"add"))).join("")+'</div>':'<div class="note">No airport found.</div>'}
function renderLists(){const w=document.getElementById("watch");if(w.querySelector("form"))return;   // never wipe a name being typed
  const ls=LS.all(),l=LS.active();
  if(!l){w.innerHTML='<div class="sec"><span class="hdr">Your lists</span><button class="lnk" id="newlist">+ New list</button></div><div id="nf" hidden></div><div class="card box note" style="margin:0">Search above and tap <b>+</b> to start a list of your airports. Lists are saved in this browser, and you can share each one as a link.</div>';return}
  w.innerHTML='<div class="sec"><span class="hdr">'+(ls.length>1?'Your lists':esc(l.name)+' · '+l.ids.length)+'</span><button class="lnk" id="newlist">+ New list</button></div><div id="nf" hidden></div>'+
    (ls.length>1?'<nav class="seg tabs" aria-label="Your lists">'+ls.map(x=>'<button class="'+(x.id===l.id?'on':'')+'" data-use="'+esc(x.id)+'" aria-pressed="'+(x.id===l.id)+'">'+esc(x.name)+'<b>'+x.ids.length+'</b></button>').join("")+'</nav>':'')+
    (l.ids.length?'<div class="rows">'+[...l.ids].sort((x,y)=>act(y)-act(x)).map(id=>airportRow(id,xBtn(id,l,"rm"))).join("")+'</div>'+
      '<div class="btns"><a class="btn" href="list/?l='+encodeURIComponent(l.id)+'">View all changes</a><button class="btn ghost" id="share">Copy share link</button><button class="btn ghost" id="rename">Rename</button></div>'
     :'<div class="card box note" style="margin:0">No airports on '+esc(l.name)+' yet. Search above and tap <b>+</b> to add some.</div>'+
      '<div class="btns"><button class="btn ghost" id="rename">Rename</button><button class="btn ghost" id="dellist">Delete list</button></div>')}
// "coming up at your airports": the top changes at every airport on your lists, with the countdown to 0901Z
const got=new Map();
const latestOf=id=>{if(!got.has(id))got.set(id,fetch("latest/"+id+".json").then(r=>r.ok?r.json():null).catch(()=>null));return got.get(id)};
const PRI={action:["act","ACT"],ifr:["ifr","IFR"],fyi:["fyi","FYI"]};
async function renderNext(){const el=document.getElementById("next"),l=LS.union();
  if(!l.length){el.innerHTML="";return}
  const busy=l.filter(id=>(byId.get(id)||[])[6]).sort((x,y)=>act(y)-act(x)),ch=busy.slice(0,60),data=await Promise.all(ch.map(latestOf)),rows=[],nc={};
  ch.forEach((id,i)=>{const d=data[i];if(!d||!d.changes)return;const items=d.changes.map(c=>({id:c.id,c:NX.to}));
    AM.base(id,items,NX.to);const nw=AM.look(id,items,NX.to,false).nw;if(nw.size)nc[id]=nw.size;rows.push({id,d,nw})});
  l.filter(id=>!busy.includes(id)).forEach(id=>AM.base(id,[],NX.to));
  AM.setNewc(nc);NEWC=nc;
  rows.sort((x,y)=>y.d.counts.action-x.d.counts.action||y.nw.size-x.nw.size||(x.id<y.id?-1:1));
  const quiet=l.filter(id=>!busy.includes(id)).sort();
  const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
  const row=({id,d,nw})=>{const a=byId.get(id)||[id,"",""],top=d.changes.slice(0,3);
    return '<a class="nx" href="'+esc(id)+'/"><span class="nxh"><span class="rid">'+esc(id)+'</span><span class="rname">'+esc(a[2]||"")+'</span>'+
      chipsHtml([d.counts.action,d.counts.ifr,d.counts.fyi]).replace('<span class="chips">','<span class="chips">'+(nw.size?AM.pill(nw.size):""))+'</span>'+
      top.map(c=>'<span class="nxi"><span class="ann '+PRI[c.priority][0]+' plain">'+PRI[c.priority][1]+'</span><span>'+(nw.has(c.id)?AM.pill()+" ":"")+esc(cap(c.summary)).replace(/ -&gt; /g," → ")+'</span></span>').join("")+
      (d.changes.length>3?'<span class="nxm">'+(d.changes.length-3)+' more ›</span>':'')+'</a>'};
  const up=NX.up&&AM.now()<Date.parse(NX.eff),when=up?NX.eff:NX.after;
  el.innerHTML='<div class="sec"><span class="hdr">'+(up?'Coming up at your airports':'This cycle at your airports')+'</span><span class="note" style="margin:0">'+
    (up?'Takes effect ':'Next cycle ')+'<time datetime="'+when+'" data-until="'+when+'"></time></span></div>'+
    '<div class="rows">'+(rows.length?rows.map(row).join(""):'<div class="nxq">Nothing '+(up?'changes':'changed')+' at your '+l.length+' airport'+(l.length==1?'':'s')+' this cycle.</div>')+
    (busy.length>ch.length?'<div class="nxq">Showing the '+ch.length+' busiest of '+busy.length+' airports with changes. Each list’s page has all of them.</div>':'')+
    (rows.length&&quiet.length?'<div class="nxq">No change at '+quiet.map(esc).join(", ")+'</div>':'')+'</div>';
  AM.tick();renderLists();renderSearch();if(window.AMside)AMside()}
function update(){renderLists();renderSearch();if(window.AMside)AMside();renderNext()}
document.addEventListener("amend:flip",()=>renderNext());
document.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b||b.closest("form,#welcome"))return;const l=LS.active();
  if(b.dataset.add)LS.set((l||LS.create("My airports",[])).id,[b.dataset.add],true);
  else if(b.dataset.rm&&l)LS.set(l.id,[b.dataset.rm],false);
  else if(b.dataset.use)LS.use(b.dataset.use);
  else if(b.id==="share"&&l)return AM.copy(LS.link(l),b);
  else if(b.id==="rename"&&l)return AM.form(document.getElementById("nf"),{value:l.name},n=>{LS.rename(l.id,n);update()});
  else if(b.id==="newlist")return AM.form(document.getElementById("nf"),{label:"Create",ph:"Name, e.g. Club SVFR or Bahamas trip"},n=>{LS.create(n,[]);update();q.focus()});
  else if(b.id==="dellist"&&l)LS.remove(l.id);
  else return;
  update()});
document.addEventListener("change",ev=>{if(ev.target.id==="addto"){LS.use(ev.target.value);update()}});
q.addEventListener("input",renderSearch);
addEventListener("storage",ev=>{if(ev.key==="amend.lists"||ev.key==="amend.list.on")update()});
// Enter opens the top result
q.addEventListener("keydown",ev=>{const a=ev.key==="Enter"&&r.querySelector(".wrow>a");if(a&&a.hasAttribute("href")){ev.preventDefault();location.href=a.getAttribute("href")}});
// the sidebar's search box searches right here instead of reloading the page
const sq=document.getElementById("sq");
if(sq){sq.addEventListener("input",()=>{q.value=sq.value;renderSearch()});
  sq.form.addEventListener("submit",ev=>{ev.preventDefault();const a=r.querySelector(".wrow>a");if(a&&a.hasAttribute("href"))location.href=a.getAttribute("href")})}
renderLists();renderSearch();renderNext();
"""
WELCOME_JS = r"""(()=>{const W=document.getElementById("welcome"),K="amend.watch.welcomed",P=new URLSearchParams(location.search);
let seen=false;try{seen=!!localStorage.getItem(K)}catch(e){}
// a first visit only: not someone following a link, and not someone who already saved airports
if(P.has("w")||P.has("q")||(!P.has("welcome")&&(seen||LS.union().length)))return;
const steps=[...W.querySelectorAll(".step")],dots=[...W.querySelectorAll(".dots i")],intro=document.getElementById("intro");let i=0;
const show=()=>{steps.forEach((s,j)=>s.hidden=j!==i);dots.forEach((d,j)=>d.classList.toggle("on",j===i));
  document.getElementById("wnext").textContent=i<steps.length-1?"Next":"Get started";document.getElementById("wskip").hidden=i===steps.length-1};
const done=()=>{try{localStorage.setItem(K,"1")}catch(e){}W.hidden=true;intro.hidden=false;
  if(P.has("welcome"))history.replaceState(null,"",location.pathname)};
W.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;ev.stopPropagation();
  if(b.id==="wskip")done();else if(b.id==="wnext"){if(i<steps.length-1){i++;show()}else{done();q.scrollIntoView({block:"center"});q.focus()}}});
W.hidden=false;intro.hidden=true;show()})();
"""
WATCH_JS = r"""const META=__META__,NAMES=__NAMES__,SEL=__PRI__,SRC=__SRC__;
const P=new URLSearchParams(location.search),sname=(P.get("n")||"").trim().slice(0,60);let shared=parseW(P.get("w"));
const $=id=>document.getElementById(id),out=$("list"),cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
const ICAO={};for(const k in NAMES)if(NAMES[k][0])ICAO[NAMES[k][0]]=k;
// one of your lists (?l=, or a link to a list you already saved), a list someone shared (?w=), or the one in use
let mine=LS.all().find(l=>l.id===P.get("l"))||(shared.length?LS.same(shared,sname):LS.active()),run=0;
function say(t){$("lnote").textContent=t||"";$("lnote").hidden=!t}
function head(){const ls=LS.all(),ids=mine?mine.ids:shared,name=mine?mine.name:sname||"Shared list";
  // your own list keeps its whole share link in the address bar too
  if(mine)history.replaceState(null,"","?l="+encodeURIComponent(mine.id)+"&w="+mine.ids.join(",")+"&n="+encodeURIComponent(mine.name)+location.hash);
  document.body.dataset.list=mine?mine.id:"";
  $("kind").textContent=mine?"Your list":ids.length?"Shared list":"Lists";
  $("title").textContent=mine||ids.length?name:"Your lists";document.title=$("title").textContent+" · Amend";
  $("count").textContent=ids.length?ids.length+" airport"+(ids.length==1?"":"s"):"";
  $("ltabs").innerHTML=mine&&ls.length>1?'<nav class="seg tabs" aria-label="Your lists">'+ls.map(l=>'<a class="'+(l.id===mine.id?"on":"")+'" href="?l='+encodeURIComponent(l.id)+'">'+esc(l.name)+'<b>'+l.ids.length+'</b></a>').join("")+'</nav>':"";
  $("actions").innerHTML=mine?(ids.length?'<button class="btn" id="copy">Copy share link</button>':'')+'<button class="btn'+(ids.length?' ghost':'')+'" id="addapt">Add airports</button>'
    :ids.length?'<button class="btn" id="save">Save to my lists</button><button class="btn ghost" id="copy">Copy link</button>':'<a class="btn" href="../">Search airports</a>';
  $("manage").innerHTML=mine?'<button class="lnk" id="rename">Rename</button><button class="lnk" id="newlist">New list</button><button class="lnk dim" id="del">Delete list</button>'
    :ids.length?'':'<button class="lnk" id="newlist">Start a new list</button>';
  // alerts: every airport has its own feed; one OPML file of the list shown adds them all to a news reader
  const om=$("opml"),ot=esc(name);$("alerts").hidden=!ids.length;
  if(om&&ids.length){if(om.href.startsWith("blob:"))URL.revokeObjectURL(om.href);
    om.href=URL.createObjectURL(new Blob(['<?xml version="1.0" encoding="utf-8"?>\n<opml version="2.0"><head><title>'+ot+'</title></head><body><outline text="'+ot+'">'+
    ids.map(id=>'<outline type="rss" text="'+id+' · Amend" xmlUrl="https://amend.watch/'+id+'/feed.xml" htmlUrl="https://amend.watch/'+id+'/"/>').join("")+
    '</outline></body></opml>\n'],{type:"text/x-opml"}))}
  if(window.AMside)AMside()}
function changeHtml(c){const s=esc(cap(c.summary)).replace(/ -&gt; /g," → ");
  let m="";const ch=c.chart||{};
  if(ch.amdt)m+='<span class="ann fyi plain">'+(["0","ORIG"].includes(ch.amdt.toUpperCase())?"Original":"Amdt "+esc(ch.amdt))+'</span>';
  if(ch.pdf)m+='<a href="'+esc(ch.pdf)+'" target="_blank" rel="noopener" title="Official FAA plate (d-TPP)">View plate ↗</a>';
  else if((c.source||"").toUpperCase()==="D-TPP"||c.chart)m+='<a class="src" href="'+SRC.dtpp+'" target="_blank" rel="noopener" title="FAA d-TPP (terminal procedures) search">FAA source ↗</a>';
  else m+='<a class="src" href="'+SRC.nasr+'" target="_blank" rel="noopener" title="FAA NASR data, file '+esc(c.source)+'">FAA source ↗</a>';
  let more="";if(c.original)more='<details class="more"><summary>FAA text</summary><pre>'+esc(c.original)+'</pre></details>';
  else if(c.details&&c.details.length)more='<details class="more"><summary>Details</summary><pre>'+c.details.map(d=>esc(d).replace(/ -&gt; /g," → ")).join("\n")+'</pre></details>';
  return '<div class="it p-'+esc(c.priority)+'" data-id="'+esc(c.id)+'"><span class="k">'+esc(cap(c.category))+'</span><div class="s">'+s+more+'</div><div class="m">'+m+'</div></div>'}
async function load(id){try{const r=await fetch("../latest/"+id+".json");return r.ok?await r.json():null}catch(e){return null}}
async function body(){const my=++run,ids=mine?mine.ids:shared;
  if(!ids.length){out.innerHTML='<div class="card box note">'+(mine?'No airports on '+esc(mine.name)+' yet. Tap <b>Add airports</b> above, or search on the <a href="../">home page</a> and tap <b>+</b>.'
    :'You don’t have any lists yet. <a href="../">Search for an airport</a> and tap <b>+</b> to start one. Lists are saved in this browser, and you can share each one as a link.')+'</div>';return}
  if(!out.querySelector("details"))out.innerHTML='<div class="note">Loading…</div>';
  const data=await Promise.all(ids.map(load));if(my!==run)return;
  const items=ids.map((id,i)=>({id,d:data[i]})).sort((a,b)=>((b.d&&b.d.counts.action)||0)-((a.d&&a.d.counts.action)||0));
  out.innerHTML=items.map(({id,d})=>{const n=NAMES[id],k=d?[d.counts.action,d.counts.ifr,d.counts.fyi]:null;
    const body=d?SEL.map(([p,t])=>{const g=d.changes.filter(c=>c.priority===p);return g.length?'<section class="lst"><div class="gh"><span><span class="dot d-'+p+'"></span>'+t+'</span><span class="n">'+g.length+'</span></div>'+g.map(changeHtml).join("")+'</section>':""}).join("")
      :'<div class="note">'+(n?'No changes in this cycle.':'Amend doesn’t know this airport ID: it isn’t in the FAA’s airport data.')+'</div>';
    const links=[n||d?'<a href="../'+esc(id)+'/">Full page and history ›</a>':'',mine?'<button class="lnk" data-rm="'+esc(id)+'">Remove from list</button>':''].filter(Boolean).join(" · ");
    return '<details class="apt" data-apt="'+esc(id)+'"'+(d?" open":"")+'><summary class="card apthead"><span><span class="rid">'+esc(id)+'</span> <span class="rname">'+esc(n?n[1]:"Unknown airport ID")+'</span></span>'+
      (n||d?chipsHtml(k):'<span class="chips"><span class="ann plain">Not found</span></span>')+'</summary>'+body+(links?'<p class="foot">'+links+'</p>':'')+'</details>'}).join("");
  out.querySelectorAll("details.apt").forEach(x=>{const r=AM.mark(x,x.dataset.apt,META.to_cycle),c=x.querySelector("summary .chips");if(r.n&&c)c.insertAdjacentHTML("afterbegin",AM.pill(r.n))});
  if(window.AMside)AMside()}
// "DAB, komn PHNL" -> the airport ids Amend knows, plus whatever didn't match
function airports(v){const ok=[],bad=[];for(const t of v.toUpperCase().split(/[\s,;]+/).filter(Boolean)){
  const id=NAMES[t]?t:ICAO[t]||(NAMES[t.replace(/^K(?=[A-Z]{3}$)/,"")]?t.slice(1):"");id?ok.push(id):bad.push(t)}return{ok:[...new Set(ok)],bad}}
document.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b||b.closest("form"))return;
  if(b.id==="copy")AM.copy(mine?LS.link(mine):new URL("?w="+shared.join(",")+(sname?"&n="+encodeURIComponent(sname):""),location.href).href,b);
  else if(b.id==="save"){mine=LS.same(shared,sname)||LS.create(sname||"Shared list",shared);LS.use(mine.id);say("Saved to your lists as “"+mine.name+"”.");head();body()}
  else if(b.id==="addapt")AM.form($("nf"),{label:"Add",ph:"Airport IDs, e.g. DAB OMN KSFB",aria:"Airport IDs to add",max:600},v=>{const{ok,bad}=airports(v),had=ok.filter(x=>mine.ids.includes(x)),add=ok.filter(x=>!had.includes(x));
    if(add.length){const l=LS.set(mine.id,add,true);if(!l)return gone();mine=l}const got=add.filter(x=>mine.ids.includes(x)),full=add.filter(x=>!got.includes(x)),few=a=>a.length>8?a.length+" airports":a.join(", ");
    say([got.length?"Added "+few(got)+".":"",had.length?"Already on it: "+few(had)+".":"",full.length?"A list holds up to 200 airports, so "+few(full)+" didn’t fit.":"",
      bad.length?"Not found: "+bad.join(", ")+".":""].filter(Boolean).join(" "));head();body()});
  else if(b.id==="rename")AM.form($("nf"),{value:mine.name},n=>{const l=LS.rename(mine.id,n);if(!l)return gone();mine=l;head()});
  else if(b.id==="newlist")AM.form($("nf"),{label:"Create",ph:"Name, e.g. Club SVFR or Bahamas trip"},n=>{mine=LS.create(n,[]);say("");head();body();$("addapt").click()});
  else if(b.id==="del"&&confirm("Delete “"+mine.name+"”? This can’t be undone.")){LS.remove(mine.id);say("");gone()}
  else if(b.dataset.rm&&mine){const l=LS.set(mine.id,[b.dataset.rm],false);if(!l)return gone();mine=l;const d=b.closest("details");if(d)d.remove();head();if(!mine.ids.length)body()}});
// after a delete, here or in another tab: show the list in use now, or none
function gone(){mine=LS.active();shared=[];if(!mine)history.replaceState(null,"",location.pathname);head();body()}
// the same list changed in another tab
addEventListener("storage",ev=>{if(ev.key!=="amend.lists"||!mine)return;const l=LS.all().find(x=>x.id===mine.id);
  if(!l)gone();else if(JSON.stringify(l)!==JSON.stringify(mine)){mine=l;head();body()}});
if(mine)LS.use(mine.id);
// a link to airports you already keep under another name opens your list; say so
if(mine&&shared.length&&sname&&mine.id!==P.get("l")&&mine.name!==sname)say("You already have these airports as “"+mine.name+"”.");
head();body();
"""
# the named-list page (/list/<slug>/): save it to your lists in one tap, or copy its link
NAMED_JS = r"""(()=>{const b=document.getElementById("savenamed"),c=document.getElementById("copynamed"),ids=b.dataset.ids.split(","),name=b.dataset.name;
const paint=()=>{const l=LS.same(ids,name);if(l){b.textContent="✓ Saved to your lists";b.href="../?l="+encodeURIComponent(l.id);b.classList.add("ghost")}};
b.addEventListener("click",ev=>{if(LS.same(ids,name))return;ev.preventDefault();LS.create(name,ids);paint();if(window.AMside)AMside()});
paint();c.hidden=false;c.addEventListener("click",()=>AM.copy(location.href.split(/[?#]/)[0],c))})();
"""
# every page loads this first, as assets/app.js: what this browser has already seen (for "New" labels), the countdown
# to the next 0901Z changeover, the lists saved in this browser, and the page chrome (the sidebar's lists, the
# add-to-list menu on airport pages, share, / to search, filter tabs, opening a linked history cycle)
APP_JS = r"""var esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
var AM=(()=>{const STALE=__STALE__,K="amend.seen",NC="amend.newc",SH="amend.newshown";
const rd=(k,st)=>{try{return JSON.parse((st||localStorage).getItem(k)||"{}")||{}}catch(e){return{}}};
const wr=(k,v,st)=>{try{(st||localStorage).setItem(k,JSON.stringify(v))}catch(e){}};
// items: [{id, c: cycle}]. new = not seen before and from a cycle at or after the last look. First look marks nothing.
function look(apt,items,cyc,save){const all=rd(K),prev=all[apt],shown=rd(SH,sessionStorage),sh=new Set(shown[apt]||[]),nw=new Set();
  if(prev){const ids=new Set(prev.ids||[]);for(const x of items)if(sh.has(x.id)||(x.c>=prev.c&&!ids.has(x.id)))nw.add(x.id)}
  if(save!==false){all[apt]={c:cyc,t:Date.now(),ids:[...new Set(items.filter(x=>x.c>=cyc).map(x=>x.id))].slice(0,400)};wr(K,all);
    shown[apt]=[...nw];wr(SH,shown,sessionStorage);const nc=rd(NC);if(apt in nc){delete nc[apt];wr(NC,nc)}}
  return{nw,prev}}
function base(apt,items,cyc){const all=rd(K);if(!all[apt]){all[apt]={c:cyc,t:Date.now(),ids:items.map(x=>x.id)};wr(K,all)}}
const pill=n=>'<span class="ann new" title="New since you last looked">'+(n?n+" new":"New")+'</span>';
function mark(root,apt,cyc){const els=[...root.querySelectorAll(".it[data-id]")];
  const r=look(apt,els.map(el=>({id:el.dataset.id,c:el.dataset.c||cyc})),cyc);
  for(const el of els)if(r.nw.has(el.dataset.id)){el.classList.add("new");const s=el.querySelector(".s");if(s)s.insertAdjacentHTML("afterbegin",pill()+" ")}
  root.querySelectorAll("details.cycle").forEach(d=>{const n=d.querySelectorAll(".it.new").length,c=d.querySelector("summary .chips");if(n&&c)c.insertAdjacentHTML("afterbegin",pill(n))});
  return{n:r.nw.size,prev:r.prev}}
// the clock the changeover runs on: this device's, unless it's more than 2s off the server's (its Date header,
// read once per page). a phone set 10 minutes fast must not show the new cycle as in effect at 0851Z
let SKEW=0;const now=()=>Date.now()+SKEW;
// nothing flips until the server has answered (or 1.5s passed without it), so a fast clock never flips early
function sync(){const t0=Date.now();Promise.race([fetch((document.body.dataset.root||"")+"latest/meta.json",{method:"HEAD",cache:"no-store"})
  .then(r=>{const d=Date.parse(r.headers.get("Date")||"");if(!d)return;const s=d+500-(t0+Date.now())/2;SKEW=Math.abs(s)>2000?s:0}),
  new Promise(ok=>setTimeout(ok,1500))]).catch(()=>{}).then(()=>{flip();arm()})}
// pages built before 0901Z carry the in-effect version of every "upcoming" bit (.flip[data-after]); swap it in
// at the changeover, to the second, whether the page was opened before it or after
function flip(){const f=document.body.dataset.eff;if(!f||now()<Date.parse(f))return false;
  document.querySelectorAll(".flip[data-after]").forEach(x=>{x.innerHTML=x.dataset.after;x.removeAttribute("data-after")});
  delete document.body.dataset.eff;tick();document.dispatchEvent(new Event("amend:flip"));return true}
function arm(){clearTimeout(arm.t);const f=document.body.dataset.eff,ms=f?Date.parse(f)-now():NaN;
  if(ms>0&&ms<2e9)arm.t=setTimeout(()=>{if(!flip())arm()},ms+25)}
const fmt=ms=>{const m=Math.floor(ms/6e4),d=Math.floor(m/1440),h=Math.floor(m%1440/60),mm=m%60;return(d?d+"d ":"")+(d||h?h+"h ":"")+mm+"m"};
function tick(){document.querySelectorAll("time[data-until]").forEach(t=>{const ms=Date.parse(t.dataset.until)-now();
  t.textContent=ms>=6e4?"in "+fmt(ms):ms>0?"in under 1m":"now";t.title=t.getAttribute("datetime").slice(0,16).replace("T"," ")+"Z"})}
const ago=ms=>{const m=Math.floor(ms/6e4),h=Math.floor(m/60),d=Math.floor(h/24);return m<2?"just now":m<60?m+"m ago":h<48?h+"h ago":d+" days ago"};
function fresh(){document.querySelectorAll("time[data-ago]").forEach(t=>{t.textContent=ago(now()-Date.parse(t.dataset.ago))});
  const b=document.body.dataset.built,age=b?now()-Date.parse(b):0,st=document.getElementById("stale");
  if(age>STALE*36e5){document.body.classList.add("is-stale");if(st){st.innerHTML='<span class="ann act">Out of date</span><span>This data was last updated '+
    ago(age)+'. Amend’s daily update may have stopped, so newer FAA changes might be missing. Check the official FAA sources before you fly.</span>';st.hidden=false}}}
function tick2(){flip();tick();fresh()}
setInterval(tick2,15000);
function copy(u,b){(navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(()=>{if(!b)return;const t=b.textContent;
  b.textContent="Copied";setTimeout(()=>{b.textContent=t},1500)},()=>prompt("Copy this link:",u))}
// a one-line form in place of prompt(): done(value) on submit, back() on cancel
function form(el,o,done,back){el.innerHTML='<form class="nf"><input maxlength="'+(o.max||60)+'" required autocomplete="off" aria-label="'+esc(o.aria||"List name")+
  '" placeholder="'+esc(o.ph||"List name")+'"><button class="btn">'+esc(o.label||"Save")+'</button><button type="button" class="btn ghost">Cancel</button></form>';
  el.hidden=false;const f=el.firstChild,i=f.firstChild,shut=()=>{el.innerHTML="";el.hidden=true},x=()=>{shut();if(back)back()};
  i.value=o.value||"";i.focus();i.select();
  f.addEventListener("submit",ev=>{ev.preventDefault();const v=i.value.trim();if(v){shut();done(v)}});
  f.lastChild.addEventListener("click",x);i.addEventListener("keydown",ev=>{if(ev.key==="Escape"){ev.stopPropagation();x()}})}
return{look,base,mark,pill,tick:tick2,newc:()=>rd(NC),setNewc:m=>wr(NC,m),copy,form,now,flip,sync}})();
// the lists saved in this browser: amend.lists = [{id, name, ids}], the one in use in amend.list.on. amend.watch was
// the single watchlist before there were lists; the first visit turns it (and its name) into the first list, and it
// keeps every saved airport after that, so nothing still reading it comes up empty
var LS=(()=>{const K="amend.lists",ON="amend.list.on",OLD="amend.watch";
const get=k=>{try{return localStorage.getItem(k)}catch(e){return null}};
const ok=x=>/^[A-Z0-9]{2,4}$/.test(x),hash=s=>{let x=5381;for(let i=0;i<s.length;i++)x=(x*33^s.charCodeAt(i))>>>0;return x.toString(36)};
const clean=l=>({id:String(l.id),name:String(l.name||"").trim().slice(0,60)||"Untitled list",
  ids:[...new Set((Array.isArray(l.ids)?l.ids:[]).map(String))].filter(ok).slice(0,200)});
function write(ls){try{localStorage.setItem(K,JSON.stringify(ls));localStorage.setItem(OLD,JSON.stringify([...new Set(ls.flatMap(l=>l.ids))]))}catch(e){}}
function all(){let v=null;try{v=JSON.parse(get(K))}catch(e){}
  if(Array.isArray(v))return v.filter(l=>l&&l.id).map(clean);
  let old=[];try{old=JSON.parse(get(OLD)||"[]")}catch(e){}
  // its id comes from what's on it: the same on every read even if saving fails, and not the same for everyone
  const nm=get(OLD+".name")||"My airports",ls=Array.isArray(old)&&old.length?[clean({id:"w"+hash(old.join()+"|"+nm),name:nm,ids:old})]:[];
  if(ls.length)write(ls);return ls}
const uid=ls=>{let i;do{i=Math.random().toString(36).slice(2,8)}while(!i||ls.some(l=>l.id===i));return i};
function uname(ls,n,skip){n=String(n||"").trim().slice(0,60)||"My airports";let m=n,k=2;
  while(ls.some(l=>l.id!==skip&&l.name.toLowerCase()===m.toLowerCase()))m=n.slice(0,56)+" "+k++;return m}
function active(){const ls=all();return ls.find(l=>l.id===get(ON))||ls[0]||null}
function use(id){try{localStorage.setItem(ON,id)}catch(e){}}
function create(name,ids){const ls=all(),l=clean({id:uid(ls),name:uname(ls,name),ids:ids||[]});ls.push(l);write(ls);use(l.id);return l}
function edit(id,fn){const ls=all(),l=ls.find(x=>x.id===id);if(!l)return null;fn(l,ls);const out=ls.map(clean);write(out);return out.find(x=>x.id===id)}
const rename=(id,n)=>edit(id,(l,ls)=>{l.name=uname(ls,n,id)});
const set=(id,apts,on)=>edit(id,l=>{l.ids=on?[...l.ids,...apts]:l.ids.filter(x=>!apts.includes(x))});
function remove(id){const ls=all().filter(l=>l.id!==id);write(ls);if(get(ON)===id&&ls[0])use(ls[0].id)}
const union=()=>[...new Set(all().flatMap(l=>l.ids))];
// a saved list with exactly these airports, the same name first
function same(ids,name){const s=new Set(ids),m=all().filter(l=>l.ids.length===s.size&&l.ids.every(x=>s.has(x)));return m.find(l=>l.name===name)||m[0]||null}
const link=l=>new URL((document.body.dataset.root||"")+"list/?w="+l.ids.join(",")+"&n="+encodeURIComponent(l.name),location.href).href;
return{all,active,use,create,rename,set,remove,union,same,link}})();
// the sidebar: every list, with the one that matches the page open. On a list's page that's the list shown, on an
// airport page a list with that airport (the one in use first), anywhere else the list in use. Clicking a list's
// name opens its page, so the sidebar and the page never disagree. The page runs SB.side() right after the
// sidebar's placeholder, so it's right on the first paint; later calls only slide the open list if nothing else changed
var SB=(()=>{
function which(ls,el){const B=document.body.dataset,R=B.root||"",P=new URLSearchParams(location.search),has=id=>ls.some(l=>l.id===id);
  if(new URL(R+"list/",location.href).pathname===location.pathname){if(B.list!==undefined)return B.list;const l=P.get("l");if(l&&has(l))return l}
  const on=LS.active(),apt=el.dataset.on;
  if(apt&&!(on&&on.ids.includes(apt))){const l=ls.find(x=>x.ids.includes(apt));if(l)return l.id}
  return on?on.id:""}
function side(){const el=document.getElementById("sbw");if(!el)return;const B=document.body.dataset,R=B.root||"",ls=LS.all(),nc=AM.newc(),op=which(ls,el);
  const sig=JSON.stringify([ls,nc]);
  if(el.dataset.sig!==sig){el.dataset.sig=sig;
    el.innerHTML=ls.length?'<div class="sbh">Your lists</div>'+ls.map(l=>{const n=l.ids.reduce((s,x)=>s+(nc[x]||0),0),u=R+'list/?l='+encodeURIComponent(l.id);
      return '<div class="sbl" data-l="'+esc(l.id)+'"><a class="sbt" href="'+u+'">'+
        '<span class="nm">'+esc(l.name)+'</span>'+(n?'<span class="nw">'+AM.pill(n)+'</span>':'')+'<span class="n">'+l.ids.length+'</span></a>'+
        '<div class="sbp"><div class="sbq">'+l.ids.slice(0,12).map(x=>'<a class="sba'+(x===el.dataset.on?' on':'')+'" href="'+R+x+'/"><b>'+x+'</b>'+(nc[x]?AM.pill(nc[x]):'')+'</a>').join("")+
        (l.ids.length?'':'<div class="sba sub">No airports yet</div>')+
        (l.ids.length>12?'<a class="sba go" href="'+u+'">All '+l.ids.length+' airports ›</a>':'')+'</div></div></div>'}).join(""):""}
  el.querySelectorAll(".sbl").forEach(b=>{const o=b.dataset.l===op;b.classList.toggle("open",o);b.classList.toggle("on",o&&b.dataset.l===B.list);
    b.firstChild.setAttribute("aria-current",o&&b.dataset.l===B.list?"page":"false");b.lastChild.inert=!o})}
return{side}})();
addEventListener("DOMContentLoaded",()=>{AM.sync();const R=document.body.dataset.root||"",B=document.body.dataset,el=document.getElementById("sbw");
const short=(s,n)=>s.length>n?s.slice(0,n-1)+"…":s;
// airport pages and named lists: label what's new since the last visit, then remember this visit
document.querySelectorAll("[data-look]").forEach(x=>{const r=AM.mark(x,x.dataset.look,B.cyc);
  const s=x.querySelector(":scope>summary .chips");if(r.n&&s)s.insertAdjacentHTML("afterbegin",AM.pill(r.n));
  const nn=document.getElementById("newnote");if(nn&&r.n&&r.prev){nn.innerHTML=AM.pill(r.n)+"<span>"+(r.n==1?"change":"changes")+
    " since you last looked here on "+new Date(r.prev.t).toLocaleDateString(undefined,{day:"numeric",month:"short"})+".</span>";nn.hidden=false}});
const side=SB.side;
// airport pages: put this airport on your lists. With one list the button adds it straight away; the menu does the rest
const wb=document.getElementById("wbtn"),wm=document.getElementById("wmenu");let paint=()=>{};
if(wb&&wm){const apt=wb.dataset.apt;
  paint=()=>{const ls=LS.all(),on=ls.filter(l=>l.ids.includes(apt));
    wb.textContent=on.length?"✓ On "+(on.length>1?on.length+" lists":short(on[0].name,26)):"+ Add to list";
    wb.classList.toggle("ghost",on.length>0);wb.classList.toggle("dd",on.length>0||ls.length>1)};
  const close=()=>{wm.hidden=true;wb.setAttribute("aria-expanded","false")};
  const menu=()=>{wm.innerHTML='<div class="mh">Lists with '+esc(apt)+'</div>'+LS.all().map(l=>'<label class="mi"><input type="checkbox" data-l="'+esc(l.id)+'"'+
    (l.ids.includes(apt)?" checked":"")+'><span class="nm">'+esc(l.name)+'</span><span class="n">'+l.ids.length+'</span></label>').join("")+
    '<div id="wnew"><button type="button" class="mi add">+ New list</button></div>';wm.hidden=false;wb.setAttribute("aria-expanded","true")};
  wb.hidden=false;paint();
  wb.addEventListener("click",()=>{if(!wm.hidden)return close();const ls=LS.all();
    if(!ls.length)LS.create("My airports",[apt]);
    else if(ls.length===1&&!ls[0].ids.includes(apt))LS.set(ls[0].id,[apt],true);
    else return menu();
    paint();side()});
  wm.addEventListener("change",ev=>{const c=ev.target.closest("input[data-l]"),l=c&&LS.set(c.dataset.l,[apt],c.checked);
    if(l)c.parentNode.querySelector(".n").textContent=l.ids.length;paint();side()});
  wm.addEventListener("click",ev=>{ev.stopPropagation();if(ev.target.closest(".add"))AM.form(document.getElementById("wnew"),{label:"Create",ph:"New list name"},
    n=>{LS.create(n,[apt]);paint();side();menu()},menu)});
  document.addEventListener("click",ev=>{if(!wm.hidden&&ev.target!==wb&&!wm.contains(ev.target))close()});
  addEventListener("keydown",ev=>{if(ev.key==="Escape"&&!wm.hidden){close();wb.focus()}})}
side();window.AMside=side;addEventListener("storage",()=>{side();paint()});
const sb=document.getElementById("sharebtn");
if(sb){sb.hidden=false;sb.addEventListener("click",()=>{const u=location.href.split("#")[0];
  if(navigator.share)navigator.share({title:document.title,url:u}).catch(()=>{});else AM.copy(u,sb)})}
document.querySelectorAll("button[data-copy]").forEach(b=>{b.hidden=false;b.addEventListener("click",()=>AM.copy(b.dataset.copy,b))});
addEventListener("keydown",e=>{if(e.key!=="/"||/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))return;
  const i=[document.getElementById("q"),document.getElementById("sq")].find(x=>x&&x.offsetParent);if(i){e.preventDefault();i.focus()}});
document.querySelectorAll(".seg a[data-f]").forEach(a=>a.addEventListener("click",ev=>{ev.preventDefault();const f=a.dataset.f;
  document.querySelectorAll(".seg a").forEach(x=>x.classList.toggle("on",x===a));
  document.querySelectorAll(".grp").forEach(g=>g.hidden=f!=="all"&&g.dataset.p!==f)}));
const open=()=>{const t=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));if(t&&t.tagName==="DETAILS")t.open=true};
document.querySelectorAll("details.pop").forEach(d=>{document.addEventListener("click",ev=>{if(d.open&&!d.contains(ev.target))d.open=false});
  d.addEventListener("keydown",ev=>{if(ev.key==="Escape"&&d.open){d.open=false;d.firstChild.focus()}})});
addEventListener("hashchange",open);open();AM.tick();
// printing a briefing: show every airport on a list, not just the open ones
addEventListener("beforeprint",()=>document.querySelectorAll("details.apt").forEach(d=>d.open=true))});
"""
STALE_HOURS = 36   # the update runs daily; past this the page says so instead of looking current
APP = APP_JS.replace("__STALE__", str(STALE_HOURS))
APP_VERSION = hashlib.sha1(APP.encode()).hexdigest()[:10]   # like CSS_VERSION: new pages never run an old cached app.js


def e(s):
    return html.escape(str(s or ""), quote=True)


def efb(cycle):
    try:
        return dt.date.fromisoformat(cycle).strftime("%d %b %Y").upper()
    except ValueError:
        return cycle


def nice(cycle, year=True):
    """2026-09-03 -> 03 Sep 2026 (or 03 Sep)"""
    try:
        return dt.date.fromisoformat(cycle).strftime("%d %b %Y" if year else "%d %b")
    except ValueError:
        return cycle


def arrow(s):
    return e(s).replace(" -&gt; ", " → ")


def cap(s):
    s = str(s or "")
    return s[:1].upper() + s[1:]


def counts(changes):
    return {p: sum(c["priority"] == p for c in changes) for p, _, _ in PRIORITY}


def chips(c, no_change=True):
    out = [f'<span class="ann {TIERS[p][0]}" title="{e(TIERS[p][2])}">{lbl} {c[p]}</span>'
           for p, lbl, _ in PRIORITY if c.get(p)]
    if not out and no_change:
        out = [f'<span class="ann ok" title="{NO_CHG_TIP}">No change</span>']
    return f'<span class="chips">{"".join(out)}</span>'


# official FAA pages, so every change can be checked against the source it came from
NASR_PAGE = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/{cycle}"
DTPP_SEARCH = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/search/"
SUPPLEMENT_SEARCH = "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dafd/search/"
NOTAM_SEARCH = "https://notams.aim.faa.gov/notamSearch/"


def source_link(c, cycle):
    """the FAA publication a change came from: the plate for charts, the NASR cycle page for the rest."""
    if (c.get("source") or "").upper() == "D-TPP" or c.get("chart"):
        if c.get("chart", {}).get("pdf"):
            return ""   # "View plate" already links the official plate
        return (f'<a class="src" href="{DTPP_SEARCH}" target="_blank" rel="noopener" '
                f'title="FAA d-TPP (terminal procedures) search">FAA source ↗</a>')
    if not cycle:
        return ""
    return (f'<a class="src" href="{NASR_PAGE.format(cycle=e(cycle))}" target="_blank" rel="noopener" '
            f'title="FAA NASR data, cycle {nice(cycle)}, file {e(c.get("source", ""))}">FAA source ↗</a>')


def change_html(c, cycle=None):
    extra = []
    if c.get("chart", {}).get("amdt"):
        a = c["chart"]["amdt"]
        extra.append(f'<span class="ann fyi plain">{"Original" if a.upper() in ("0", "ORIG") else "Amdt " + e(a)}</span>')
    if c.get("chart", {}).get("pdf"):
        extra.append(f'<a href="{e(c["chart"]["pdf"])}" target="_blank" rel="noopener" '
                     f'title="Official FAA plate (d-TPP)">View plate ↗</a>')
    more = ""
    if c.get("original"):
        more = f'<details class="more"><summary>FAA text</summary><pre>{e(c["original"])}</pre></details>'
    elif c.get("details"):
        more = ('<details class="more"><summary>Details</summary><pre>'
                + "\n".join(arrow(d) for d in c["details"]) + "</pre></details>")
    extra.append(source_link(c, c.get("cycle") or cycle))
    ids = (f' data-id="{e(c["id"])}"' if c.get("id") else "") + (f' data-c="{e(c["cycle"])}"' if c.get("cycle") else "")
    return (f'<div class="it p-{e(c["priority"])}"{ids}><span class="k">{e(cap(c["category"]))}</span>'
            f'<div class="s">{arrow(cap(c["summary"]))}{more}</div><div class="m">{"".join(extra)}</div></div>')


def grouped(changes, anchors=False, cycle=None):
    """one card per priority. anchors: give each an id and data-p so the filter tabs can find it."""
    out = []
    for p, _, title in PRIORITY:
        g = [c for c in changes if c["priority"] == p]
        if g:
            attrs = f' class="lst grp" id="{p}" data-p="{p}"' if anchors else ' class="lst"'
            out.append(f'<section{attrs}><div class="gh"><span><span class="dot d-{p}"></span>{title}</span>'
                       f'<span class="n">{len(g)}</span></div>' + "".join(change_html(c, cycle) for c in g) + "</section>")
    return "".join(out)


def legend(root):
    """key to the labels, linking to the guide. root is the relative path to the site root."""
    keys = "".join(f'<span><span class="ann {cls}">{lbl}</span>{TIERS[p][1]}</span>'
                   for p, lbl, _ in PRIORITY for cls in [TIERS[p][0]])
    return f'<div class="legend">{keys}<a href="{root}guide/">What do these mean?</a></div>'


def alerts_box(feed_url, what, tag=None, pop=False):
    """rail card: how to hear about the next change at an airport or named list, in pilot words. The feed is RSS,
    but that word and the raw link sit behind "More options". tag (named lists only) turns on the email form once
    EMAIL_FORM is set; everywhere else it points at a free service that emails a feed to you."""
    what = e(what)
    if tag and EMAIL_FORM:
        how = (f'<form action="{e(EMAIL_FORM)}" method="post" target="_blank">'
               '<input type="email" name="email" required placeholder="you@example.com" aria-label="Email address">'
               f'<input type="hidden" name="tag" value="{e(tag)}"><input type="hidden" name="embed" value="1">'
               '<button class="btn" type="submit">Email me</button></form>'
               f'<p class="foot">One email per FAA cycle when something changes at {what}. Unsubscribe anytime.</p>')
    else:
        how = ('<ol class="steps"><li>Copy the alert link.</li><li>Paste it into a news reader app like Feedly, '
               'Inoreader or NetNewsWire. It shows each update when the FAA posts it.'
               f'</li></ol><div class="btns"><button class="btn" data-copy="{e(feed_url)}" hidden>Copy alert link'
               '</button></div>')
    inner = (f'<p class="note">Hear about it when a new FAA cycle changes {what}, action items first. One update per '
             f'cycle, nothing in between.</p>{how}'
             '<details class="more"><summary>More options</summary><p class="foot">The alert link is an RSS feed, the '
             'same kind of link podcast and news apps follow. Apps like Feedly, Inoreader or NetNewsWire can follow '
             f'it too. <a href="{e(feed_url)}" type="application/rss+xml">Open the feed</a></p></details>')
    if pop:   # pop: a button that opens the options right under itself (a <details>, so it works without scripts)
        return (f'<details class="addw pop" id="alerts"><summary class="btn ghost dd">Get alerts</summary>'
                f'<div class="menu card box alerts" role="group" aria-label="Get alerts">{inner}</div></details>')
    return f'<div class="card box alerts" id="alerts"><h3>Get alerts</h3>{inner}</div>'


def tier_rows(full):
    """ACT / IFR / FYI / No change with what each means; the guide's version adds an example."""
    rows = []
    for p, lbl, _ in PRIORITY:
        cls, _, short, long_, eg = TIERS[p]
        rows.append(f'<div class="tier"><span class="ann {cls}">{lbl}</span><span>{e(long_ if full else short)}</span>'
                    + (f'<span class="eg eg-{cls}">e.g. {e(eg)}</span>' if full else "") + '</div>')
    no_chg = NO_CHG_TIP if full else "Nothing changed there this cycle"
    rows.append(f'<div class="tier"><span class="ann ok">No change</span><span>{no_chg}.</span></div>')
    return "".join(rows)


def logo(root):
    """the mark and the lowercase wordmark, linking home. The CSS recolours the mark for dark mode (--mk...)."""
    return f'<a class="brand" href="{root}" aria-label="Amend home">{brand.svg(classes=True)}amend</a>'


def head_links(root, url):
    """icons, the manifest, the font preload, the canonical url and cookie-free analytics, on every page."""
    beacon = (f"<script defer src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
              f"data-cf-beacon='{json.dumps({'token': CF_BEACON})}'></script>" if CF_BEACON else "")
    return (f'<link rel="icon" href="{root}favicon.ico" sizes="32x32">'
            f'<link rel="icon" href="{root}assets/icon.svg" type="image/svg+xml">\n'
            f'<link rel="apple-touch-icon" href="{root}assets/apple-touch-icon.png">'
            f'<link rel="manifest" href="{root}site.webmanifest"><meta name="apple-mobile-web-app-title" content="Amend">\n'
            f'<link rel="preload" href="{root}assets/fonts/plex-sans-latin.woff2" as="font" type="font/woff2" crossorigin>'
            + (f'<link rel="canonical" href="{e(url)}">' if url else "") + beacon)


def sidebar(root, active, meta=None, now=None, on=""):
    """desktop sidebar (and the phone top bar): search, pages, the lists saved in this browser, the cycle."""
    link = lambda href, text, key: f'<a class="sbi{" on" if key == active else ""}" href="{root}{href}">{text}</a>'
    # the same search in the same place on every page, the home page too, so the sidebar never shifts
    search = (
        f'<form class="search" action="{root}" method="get" role="search"><input id="sq" name="q" '
        f'placeholder="Search airports" aria-label="Search airports" autocomplete="off"><kbd>/</kbd>'
        f'<input type="hidden" name="go" value="1"></form>')   # go: an exact ID opens that airport
    cyc = ""
    if meta:
        t = now or dt.datetime.now(dt.timezone.utc)

        def rows(up):
            out = (f'<div class="sbi"><span>{nice(meta["from_cycle"] if up else meta["to_cycle"], False)}</span>'
                   f'<span class="ann ok">In effect</span></div>')
            if up:
                out += (f'<div class="sbi"><span>{nice(meta["to_cycle"], False)}</span>'
                        f'<span class="ann ifr">Upcoming</span></div>')
            return out
        cyc = (f'<div class="sbh">FAA cycle</div>{flip(meta, t, rows)}'
               f'<div class="sbi sub fresh">Updated {built_at(t)}</div>'
               '<script>AM.tick()</script>')   # "1h ago" from the first paint, so it doesn't flicker between pages
    side = (f'<nav class="sb" aria-label="Site">{logo(root)}{search}'
            f'<div class="sbh">Browse</div>{link("", "Airports", "home")}{link("list/", "Lists", "list")}'
            f'{link("guide/", "Guide", "guide")}{link("docs/", "Docs", "docs")}{link("about/", "About", "about")}'
            f'<div id="sbw" data-on="{e(on)}"></div><script>SB.side()</script>{cyc}'
            f'<div class="sbfoot">Not for navigation. Independent, not affiliated with the FAA.<br>'
            f'<a href="{root}changelog/">Changelog</a> · <a href="{root}status/">Status</a> · '
            f'<a href="{root}privacy/">Privacy</a> · <a href="{root}terms/">Terms</a><br>'
            f'<a href="{REPORT_URL}">Report a problem</a> · '
            f'<a href="{REPO_URL}">Source</a></div></nav>')
    nav = lambda href, text, key: f'<a class="{"on" if key == active else ""}" href="{root}{href}">{text}</a>'
    top = (f'<header class="mtop">{logo(root)}<nav class="nav">'
           f'{nav("", "Search", "home")}{nav("list/", "Lists", "list")}{nav("guide/", "Guide", "guide")}'
           f'{nav("about/", "About", "about")}</nav></header>')
    if meta:
        top += f'<div class="pfresh fresh">{freshness(meta, now or dt.datetime.now(dt.timezone.utc))}</div>'
    return side + top


# hovering a link to another page of the site fetches it early (Chromium browsers), so the click opens at once.
# prefetch, never prerender: prefetch only downloads the HTML and runs nothing, so the analytics beacon never counts
# a page nobody opened. Feeds, data files and calendars are left alone
SPECULATION = ('<script type="speculationrules">' + json.dumps({"prefetch": [{"where": {"and": [
    {"href_matches": "/*"}, {"not": {"href_matches": "/*.(json|xml|ics|png|pdf)"}},
    {"not": {"selector_matches": "[target=_blank],[download]"}}]}, "eagerness": "moderate"}]}) + "</script>")


def page(title, description, url, body, root, og_title=None, image=None, active="", meta=None, now=None,
         two=False, on="", feed=None, head=""):
    img = (f'<meta property="og:image" content="{e(image)}"><meta property="og:image:width" content="1200">'
           f'<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">'
           if image else '<meta name="twitter:card" content="summary">')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Amend">
<meta property="og:title" content="{e(og_title or title)}"><meta property="og:description" content="{e(description)}">
{f'<meta property="og:url" content="{e(url)}">' if url else ''}{img}
<meta name="theme-color" content="#F6F8FA" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#09121C" media="(prefers-color-scheme: dark)">
{head_links(root, url)}{SPECULATION}
<link rel="stylesheet" href="{root}assets/style.css?v={CSS_VERSION}">{
f'<link rel="alternate" type="application/rss+xml" title="{e(feed[1])}" href="{e(feed[0])}">' if feed else ""}{head}
</head><body data-root="{root}" data-cyc="{e(meta['to_cycle'] if meta else '')}"{eff_attr(meta, now)} data-built="{(now or dt.datetime.now(dt.timezone.utc)):%Y-%m-%dT%H:%M:%SZ}"><script src="{root}assets/app.js?v={APP_VERSION}"></script><div class="app">{sidebar(root, active, meta, now, on)}
<main class="main{' two' if two else ''}"><div class="card banner stale full" id="stale" hidden></div>{body}
<p class="foot full">{freshness(meta, now or dt.datetime.now(dt.timezone.utc))}{'. ' if meta else ''}Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight briefing.
Amend is independent and not affiliated with the FAA. Data: FAA NASR and d-TPP.
<a href="{root}docs/">How it works</a> · <a href="{root}status/">Status</a> · <a href="{root}changelog/">Changelog</a> · <a href="{root}privacy/">Privacy</a> · <a href="{root}terms/">Terms</a> · <a href="{REPORT_URL}">Report a problem</a> · <a href="{REPO_URL}">Source</a></p></main></div></body></html>"""


def effective(cycle):
    """a cycle switches over at 0901Z on its effective date."""
    return dt.datetime.fromisoformat(cycle).replace(hour=9, minute=1, tzinfo=dt.timezone.utc)


def next_changeover(meta, now):
    """(when, upcoming?): the upcoming cycle's 0901Z, or once it's in effect, the one 28 days later."""
    upcoming, _ = status(meta, now)
    eff = effective(meta["to_cycle"])
    return (eff, True) if upcoming else (eff + dt.timedelta(days=28), False)


def countdown(when):
    """a <time> the page script turns into "in 3d 14h 22m"; without scripts it reads "01 Oct 0901Z"."""
    iso = when.strftime("%Y-%m-%dT%H:%M:00Z")
    return f'<time datetime="{iso}" data-until="{iso}">{when:%d %b} 0901Z</time>'


def built_at(when):
    """a <time> the page script turns into "2h ago"; without scripts it reads "27 Sep 2100Z"."""
    iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'<time datetime="{iso}" data-ago="{iso}">{when:%d %b %H%M}Z</time>'


def freshness(meta, now):
    """'FAA cycle 01 Oct 2026 (upcoming) · updated 2h ago', for every page."""
    if not meta:
        return ""
    return (f'FAA cycle {nice(meta["to_cycle"])}{flip(meta, now, lambda up: " (upcoming)" if up else "")} · '
            f'updated {built_at(now)}')


def status(meta, now):
    """(upcoming?, note) using the 0901Z changeover."""
    upcoming = bool(meta.get("upcoming")) and now < effective(meta["to_cycle"])
    return upcoming, state_note(meta, now, upcoming)


def state_note(meta, now, up):
    """the banner under the changes: before the changeover (up) or after it."""
    if up:
        days = (effective(meta["to_cycle"]).date() - now.date()).days
        when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
        return (f"These changes take effect {nice(meta['to_cycle'])} 0901Z ({when}). "
                f"Until then, the current value applies: it's the one before the →.")
    return (f"In effect since {nice(meta['to_cycle'])} 0901Z, compared to the previous cycle "
            f"({nice(meta['from_cycle'])}).")


# the upcoming cycle is published weeks early, so the changeover must not wait for a build: every
# "upcoming / in effect" bit of a page carries both versions, and app.js swaps in the in-effect one at
# 0901Z by a clock checked against the server's (see AM.flip). a page built after 0901Z has only that one
def flip(meta, now, render):
    """render(up) as of the build; while the upcoming cycle isn't in effect, render(False) rides along."""
    up, _ = status(meta, now)
    if not up:
        return render(False)
    return f'<span class="flip" data-after="{e(render(False))}">{render(True)}</span>'


def eff_attr(meta, now):
    """body data-eff: when the page's flips happen (only on pages built before the changeover)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not meta or not status(meta, now)[0]:
        return ""
    return f' data-eff="{effective(meta["to_cycle"]):%Y-%m-%dT%H:%M:%SZ}"'


def state_ann(up):
    return f'<span class="ann {"ifr" if up else "ok"}">{"Not in effect yet" if up else "In effect"}</span>'


def next_kv(meta, now):
    """'Takes effect: in 3d 4h' before the changeover, 'Next cycle: in 27d 23h' after."""
    eff = effective(meta["to_cycle"])
    return flip(meta, now, lambda up: f'<div class="kv"><span>{"Takes effect" if up else "Next cycle"}</span>'
                f'<span>{countdown(eff if up else eff + dt.timedelta(days=28))}</span></div>')


def status_box(meta, now):
    """the rail box on list pages: in effect or not, what applies until then, and the countdown."""
    return (flip(meta, now, lambda up: f'{state_ann(up)}<p class="note">{e(landing_note(meta, now, up))}</p>')
            + next_kv(meta, now))


def airport_page(apt, info, latest, hist, meta, now, has_card=False):
    name = info.get("name", "")
    loc = ", ".join(x for x in (info.get("city"), info.get("state")) if x)
    changes = latest or []
    c = counts(changes)
    upcoming, note = status(meta, now)

    top = next((x["summary"] for x in changes if x["priority"] == "action"), None) or \
        (changes[0]["summary"] if changes else None)
    parts = [f"{lbl} {c[p]}" for p, lbl, _ in PRIORITY if c[p]]
    if changes:
        desc = f"{' · '.join(parts)} · {top[:1].upper() + top[1:]}".replace(" -> ", " → ")
    else:
        desc = f"No {'upcoming ' if upcoming else ''}changes at {apt} in the {efb(meta['to_cycle'])} cycle."
    title = f"{apt} · {name}" if name else apt
    when = f"{'on' if upcoming else 'since'} {efb(meta['to_cycle'])[:6]}"
    og_title = (f"{apt}: {' · '.join(parts)} {when}" if changes
                else f"{apt}: no changes on {efb(meta['to_cycle'])[:6]}" if upcoming
                else f"{apt}: no changes in the {efb(meta['to_cycle'])[:6]} cycle")
    if name:
        og_title += f" · {name}"

    by_cycle = {}
    for x in (hist or {}).get("entries", []):
        by_cycle.setdefault(x["cycle"], []).append(x)
    # once a cycle is in effect the daily job adds it to history too; it's already the list at the top, so the
    # history starts with the cycle before (and the top list, made with today's rules, is the one to trust)
    cycles = sorted((c for c in by_cycle if c != meta["to_cycle"]), reverse=True)

    icao = f' <span class="icao">{e(info["icao"])}</span>' if info.get("icao") and info.get("icao") != apt else ""
    eyebrow = ((e(loc) + " · " if loc else "") + flip(meta, now, lambda up: "Upcoming " if up else "")
               + e(f"{nice(meta['to_cycle'])} cycle"))
    body = [f'<header class="full"><div class="eyebrow">{eyebrow}</div><h1>{e(apt)}{icao}</h1>'
            + (f'<div class="aname">{e(name)}</div>' if name else "")
            + f'<div class="btns"><span class="addw"><button class="btn" id="wbtn" data-apt="{e(apt)}" hidden '
            'aria-haspopup="true" aria-expanded="false">+ Add to list</button><div class="menu card" id="wmenu" hidden></div></span>'
            '<button class="btn ghost" id="sharebtn" hidden>Share</button>'
            + alerts_box(f"{SITE_URL}{apt}/feed.xml", apt, pop=True) + '</div></header>']
    if changes:
        seg = [f'<a class="on" href="#action" data-f="all">All<b>{len(changes)}</b></a>'] + \
              [f'<a href="#{p}" data-f="{p}">{title_}<b>{c[p]}</b></a>' for p, _, title_ in PRIORITY if c[p]]
        body.append(f'<div class="full toolbar"><nav class="seg" aria-label="Filter changes">{"".join(seg)}</nav></div>')
    col = ['<div class="card banner" id="newnote" hidden></div>']
    if changes:
        col.append('<div class="card banner">' + flip(
            meta, now, lambda up: f'{state_ann(up)}<span>{e(state_note(meta, now, up))}</span>') + '</div>')
        col.append(grouped(changes, anchors=True, cycle=meta["to_cycle"]))
    else:
        col.append('<div class="card none">' + flip(meta, now, lambda up: (
            f'<b>{"No upcoming changes" if up else "Nothing changed"} at {e(apt)}</b>'
            f'{"On" if up else "In the"} {nice(meta["to_cycle"])} {"· current data stays the same" if up else "cycle"}'))
            + '</div>')
    if cycles:
        col.append('<h2 class="h2">History since Aug 2024</h2><div class="hlist">')
        for i, cyc in enumerate(cycles):
            g = by_cycle[cyc]
            col.append(f'<details class="cycle lst" id="c-{e(cyc)}"{" open" if i < 3 else ""}><summary>'
                       f'<span class="chev">▶</span>Effective {nice(cyc)}{chips(counts(g), False)}</summary>'
                       + "".join(change_html(x) for x in g) + "</details>")
        col.append("</div>")
    col.append(f'<p class="foot">Data: <a href="../latest/{e(apt)}.json">latest</a> · '
               f'<a href="../history/{e(apt)}.json">history</a> · built {now:%d %b %Y %H%MZ}</p>')
    body.append(f'<div class="col" data-look="{e(apt)}">{"".join(col)}</div>')

    rail = [f'<div class="card box"><h3>{flip(meta, now, lambda up: "Upcoming cycle" if up else "This cycle")}</h3>'
            f'<div class="kv"><span>Effective</span><span>{nice(meta["to_cycle"])} 0901Z</span></div>'
            f'<div class="kv"><span>Compared to</span><span>{nice(meta["from_cycle"])}</span></div>'
            f'{next_kv(meta, now)}'
            f'<div class="kv"><span>Updated</span><span class="fresh">{built_at(now)}</span></div></div>']
    src = lambda href, text: f'<a class="hrow" href="{href}" target="_blank" rel="noopener"><span>{text}</span><span>↗</span></a>'
    rail.append('<div class="card box"><h3>Check the official source</h3>'
                + src(SUPPLEMENT_SEARCH, f"Chart Supplement (search {e(apt)})") + src(DTPP_SEARCH, "Approach plates (d-TPP)")
                + src(NOTAM_SEARCH, "NOTAMs") + src(NASR_PAGE.format(cycle=meta["to_cycle"]), f"NASR data, {nice(meta['to_cycle'])}")
                + '<p class="foot">Amend reads these FAA files. If they ever disagree, the FAA is right. '
                f'<a href="{REPORT_URL}?title={quote(apt + ": ")}">Report a wrong change</a></p></div>')
    if cycles:
        rail.append('<div class="card box hist"><h3>History</h3>' + "".join(
            f'<a class="hrow" href="#c-{e(cyc)}"><span>{nice(cyc)}</span>{chips(counts(by_cycle[cyc]), False)}</a>'
            for cyc in cycles[:12]) + "</div>")
    if changes or cycles:
        rail.append(f'<div class="card box"><h3>What the labels mean</h3>{legend("../")}</div>')
    body.append(f'<aside class="rail">{"".join(rail)}</aside>')

    image = (f"{SITE_URL}{apt}/card.png" if has_card
             else f"{SITE_URL}assets/nochange.png" if not changes else f"{SITE_URL}assets/card.png")
    return page(title, desc, f"{SITE_URL}{apt}/", "".join(body), "../", og_title, image, meta=meta, now=now,
                two=True, on=apt, feed=(f"{SITE_URL}{apt}/feed.xml", f"{apt} changes each FAA cycle"))


def landing_note(meta, now, upcoming):
    if upcoming:
        days = (dt.date.fromisoformat(meta["to_cycle"]) - now.date()).days
        when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
        return f"Takes effect {when} at 0901Z; until then the current cycle (since {nice(meta['from_cycle'])}) applies."
    return f"In effect since {nice(meta['to_cycle'])} 0901Z."


def index_page(meta, directory, latest, pages, now):
    upcoming, note = status(meta, now)
    ranked = sorted(latest.items(), key=lambda kv: (-counts(kv[1])["action"], -len(kv[1]), kv[0]))[:24]
    names = {a["id"]: a for a in directory}

    def top_card(a, ch):
        n = names.get(a, {})
        where = " · ".join(x for x in (n.get("name", ""), ", ".join(y for y in (n.get("city"), n.get("state")) if y)) if x)
        first = next((x for x in ch if x["priority"] == "action"), ch[0])
        return (f'<a class="card ac" href="{e(a)}/"><span class="h"><b>{e(a)}</b><small>{e(where)}</small></span>'
                f'{chips(counts(ch))}<span class="t">{arrow(cap(first["summary"]))}</span></a>')
    top = "".join(top_card(a, ch) for a, ch in ranked)
    # compact directory for the search box: id, icao, name, city, state, has-page
    lc = {a: counts(ch) for a, ch in latest.items()}
    rows = [[a["id"], a.get("icao", ""), a.get("name", ""), a.get("city", ""), a.get("state", ""),
             1 if a["id"] in pages else 0,
             [lc[a["id"]]["action"], lc[a["id"]]["ifr"], lc[a["id"]]["fyi"]] if a["id"] in lc else None]
            for a in directory]
    eff = effective(meta["to_cycle"])
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:00Z")
    # the script flips "coming up" to "this cycle" at eff, like the rest of the page (AM.now: server-checked clock)
    nxt = {"to": meta["to_cycle"], "up": upcoming, "eff": iso(eff), "after": iso(eff + dt.timedelta(days=28))}
    F = lambda render: flip(meta, now, render)
    js = COMMON_JS + LANDING_JS.replace("__ROWS__", json.dumps(rows, separators=(",", ":"))).replace(
        "__NEXT__", json.dumps(nxt)) + WELCOME_JS
    step = lambda title, inner: f'<div class="step" hidden><h2>{title}</h2>{inner}</div>'
    WELCOME = ('<div class="card welcome full" id="welcome" hidden>'
               + step("Welcome to Amend", "<p>Every 28 days the FAA publishes a new cycle of airport, airspace and chart data. "
                      "Tower hours move, runways get renumbered, approaches get amended, and it's easy to miss.</p>"
                      "<p>Amend compares each cycle to the last one and tells you what changed at your airports, in "
                      "plain English, up to three weeks before it takes effect.</p>")
               + step("How to read it", tier_rows(False) + "<p>Remarks are the FAA's free-text airport notes. "
                      "They're translated to plain English, and the original FAA text is always one tap away.</p>"
                      '<p><a href="guide/">Read the full guide ›</a></p>')
               + step("Set up", "<p>Search for your home field and tap <b>+</b> to add it to a list, then add the "
                      "other airports you fly to. Lists are saved in this browser. Make one for each area or trip, and "
                      "share any of them as one link with your flight school or club.</p>"
                      '<p class="foot" style="margin-top:12px">Not for navigation. Always use official FAA publications, '
                      "NOTAMs and a proper preflight briefing.</p>")
               + '<div class="wfoot"><span class="dots"><i></i><i></i><i></i></span><span class="btns">'
               '<button class="btn ghost" id="wskip">Skip</button><button class="btn" id="wnext">Next</button>'
               '</span></div></div>')
    n = meta.get('changed_airports', len(latest))
    body = f"""{WELCOME}
<header class="full" id="intro"><h1 class="hero">What changed at your airport</h1>
<p class="lede">Every 28 days the FAA publishes new airport, airspace and chart data. Amend compares each cycle to the last
and shows what changed at every US airport in plain English: tower hours, frequencies, runways, navaids,
approach plates. Keep lists of the airports you fly to, and share one link for a whole training area.</p></header>
<div class="full"><label class="search"><span aria-hidden="true">⌕</span><input id="q" placeholder="Search by ID, ICAO, name or city" aria-label="Search airports" autocomplete="off"><kbd>/</kbd></label>
<div id="res" style="margin-top:10px"></div></div>
<div class="col"><div id="next"></div><div id="watch"></div>
<div><div class="sec"><span class="hdr">Most action items this cycle</span><span class="note" style="margin:0">{n:,} airports {F(lambda up: 'change' if up else 'changed')}</span></div>
<div class="cards">{top}</div></div></div>
<aside class="rail"><div class="card box"><h3>FAA cycle</h3><div class="big">{nice(meta['to_cycle'])}</div>
<div class="note" style="margin:2px 0 10px">{F(lambda up: 'Takes effect 0901Z' if up else 'In effect since 0901Z')}</div>
<div class="kv"><span>Status</span><span>{F(lambda up: f'<span class="ann {"ifr" if up else "ok"}">{"Upcoming" if up else "In effect"}</span>')}</span></div>
<div class="kv"><span>Airports {F(lambda up: 'changing' if up else 'changed')}</span><span>{n:,}</span></div>
<div class="kv"><span>Compared to</span><span>{nice(meta['from_cycle'])}</span></div>
{next_kv(meta, now)}
<p class="note">{F(lambda up: e(landing_note(meta, now, up)))}</p>
<p class="note"><a href="webcal://amend.watch/cycles.ics">Add cycle dates to your calendar</a> (<a href="cycles.ics">.ics</a>)</p></div>
<div class="card box"><h3>What the labels mean</h3>{legend("")}</div>
</aside>
<script>{js}</script>"""
    return page("Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", SITE_URL, body, "", image=f"{SITE_URL}assets/card.png",
                active="home", meta=meta, now=now, two=True)


def watch_page(meta, directory, now):
    """site/list/: every change at the airports on a list, fully expanded. The list is one of the lists saved in
    this browser (?l=, or the one in use) or one someone shared (?w=IDS&n=NAME); the script sorts out which."""
    upcoming, _ = status(meta, now)
    names = {a["id"]: [a.get("icao", "") if a.get("icao") != a["id"] else "", a.get("name", "")] for a in directory}
    pri = [[p, t] for p, _, t in PRIORITY]
    js = COMMON_JS + WATCH_JS.replace("__META__", json.dumps(meta)).replace(
        "__NAMES__", json.dumps(names, separators=(",", ":"))).replace("__PRI__", json.dumps(pri)).replace(
        "__SRC__", json.dumps({"nasr": NASR_PAGE.format(cycle=meta["to_cycle"]), "dtpp": DTPP_SEARCH}))
    body = f"""<header class="full"><div class="eyebrow"><span id="kind">Lists</span> · {nice(meta['to_cycle'])} cycle</div>
<h1 id="title">Your lists</h1><div class="aname" id="count"></div><div id="ltabs"></div><div class="btns" id="actions"></div>
<div class="manage" id="manage"></div><div id="nf" hidden></div><p class="note" id="lnote" role="status" hidden></p></header>
<div class="col" id="list"><div class="note">Loading…</div></div>
<aside class="rail"><div class="card box">{status_box(meta, now)}</div>
<div class="card box alerts" id="alerts" hidden><h3>Get alerts</h3><p class="note">Lists saved in this browser
don't have their own alert link, but every airport does. Open an airport and use <b>Get alerts</b> on its page.</p>
<details class="more"><summary>More options</summary><p class="foot">Using a news reader app like Feedly, Inoreader or
NetNewsWire? This file adds the alerts for every airport on this list in one go: import it in the app (it's an OPML
file).</p><div class="btns"><a class="btn ghost" id="opml" download="amend-watchlist.opml">Download all alerts</a></div></details></div>
<div class="card box"><h3>What the labels mean</h3>{legend("../")}</div></aside><script>{js}</script>"""
    return page("Airport list · Amend", "Everything that changes at a list of airports this FAA cycle.",
                f"{SITE_URL}list/", body, "../", image=f"{SITE_URL}assets/card.png", active="list", meta=meta,
                now=now, two=True)


def named_watch_page(slug, wl, meta, info, latest, now, has_card):
    """static page for a named list at /list/<slug>/ (amend.watch/list/clubsvfr): every change, expanded."""
    upcoming, _ = status(meta, now)
    apts = sorted(wl["airports"], key=lambda a: (-counts(latest.get(a, []))["action"], -len(latest.get(a, [])), a))
    total = {p: sum(counts(latest.get(a, []))[p] for a in apts) for p, _, _ in PRIORITY}
    changed = sum(1 for a in apts if latest.get(a))
    blocks = []
    for a in apts:
        i, ch = info.get(a, {}), latest.get(a, [])
        head = (f'<summary class="card apthead"><span><span class="rid">{e(a)}</span> '
                f'<span class="rname">{e(i.get("name", "Unknown airport"))}</span></span>{chips(counts(ch))}</summary>')
        link = f'<p class="foot"><a href="../../{e(a)}/">Full page and history ›</a></p>'
        body = grouped(ch, cycle=meta["to_cycle"]) if ch else '<div class="note">No changes in this cycle.</div>'
        blocks.append(f'<details class="apt" data-look="{e(a)}"{" open" if ch else ""}>{head}{body}{link}</details>')
    parts = [f"{lbl} {total[p]}" for p, lbl, _ in PRIORITY if total[p]]
    when = f"{'on' if upcoming else 'since'} {efb(meta['to_cycle'])[:6]}"
    desc = (f"{changed} of {len(apts)} airports change {when}" + (f" · {' · '.join(parts)}" if parts else "")
            if changed else f"No changes at these {len(apts)} airports {when}.")
    # saving and sharing sit under the title: on a phone the rail is below every change
    body = f"""<header class="full"><div class="eyebrow">Shared list · {nice(meta['to_cycle'])} cycle</div><h1>{e(wl['name'])}</h1>
{f'<div class="aname">{e(wl["description"])}</div>' if wl["description"] else ''}
<div class="toolbar" style="margin-top:10px">{chips(total)}<span class="note" style="margin:0">{len(apts)} airports · {changed} with changes this cycle</span></div>
<div class="btns"><a class="btn" id="savenamed" href="{e('../?w=' + ','.join(wl['airports']) + '&n=' + quote(wl['name']))}" data-ids="{e(','.join(wl['airports']))}"
data-name="{e(wl['name'])}">Save to my lists</a><button class="btn ghost" id="copynamed" hidden>Copy link</button></div></header>
<div class="col">{''.join(blocks)}</div>
<aside class="rail"><div class="card box">{status_box(meta, now)}</div>
{alerts_box(f"{SITE_URL}list/{slug}/feed.xml", wl["name"], f"list:{slug}")}
<div class="card box"><h3>What the labels mean</h3>{legend("../../")}</div></aside><script>{NAMED_JS}</script>"""
    image = f"{SITE_URL}list/{slug}/card.png" if has_card else f"{SITE_URL}assets/card.png"
    return page(f"{wl['name']} · Amend", desc, f"{SITE_URL}list/{slug}", body, "../../",
                f"{wl['name']}: {desc}", image, active="list", meta=meta, now=now, two=True,
                feed=(f"{SITE_URL}list/{slug}/feed.xml", f"{wl['name']} changes each FAA cycle"))


# what shipped, newest first, for /changelog/. Add a line when something people can see changes.
UPDATES = [
    ("Sep 2026", [
        "A ++ after a time in a remark now reads \"(one hour earlier during daylight saving time)\". The FAA's "
        "data writes ++ where the Chart Supplement prints ‡, and the Chart Supplement's legend says those "
        "hours are one hour earlier during daylight saving time. Translations may also change a word's form "
        "to read as English: \"WHEN TWR HR EXTN\" can read \"when tower hours are extended\".",
        "Moving between pages fades instead of flashing, and pages you point at load before you click. Get "
        "alerts on an airport page opens right under the button. A list's name in the sidebar opens that list, and "
        "the sidebar always has open the list you're looking at. Alerts no longer point at an outside email service: "
        "the alert link goes into a news reader app.",
        "FOD in remarks now reads \"foreign object debris\", the meaning in the FAA's contractions list, "
        "since remarks use it for loose material on the pavement. The translator is also told to write in "
        "normal capitalization instead of leaving plain words in capitals.",
        "A <a href=\"../status/\">status page</a> shows whether Amend is current and every step of each recent "
        "run: the FAA files it downloaded, the checks it ran and whether it was published.",
        "Remark translations are held to a stricter check. They have to keep every code (like 100LL or "
        "D523-4244), every + or - on a height, every ++ after a time and the order of the numbers, and they "
        "can't add words the FAA text doesn't have, like \"the runway\" or \"is available\". About 1,000 "
        "translations that failed it now show the FAA text.",
        "Pages switch from upcoming to in effect at exactly 0901Z on cycle day, even if you have the page open, "
        "using the server's clock if your device's is off. Amend also checks the FAA for new data every 10 minutes.",
        "Docs, Privacy and Terms now say how to tell the FAA when its own data is wrong, what Amend can't see "
        "between cycles, what choices you have about your data, and that other sites' rules apply when you "
        "follow a link.",
        "The sidebar stays in place while you scroll, and its lists open one at a time with a quick slide.",
        "The sidebar looks the same on every page, search included, and each list in it folds open or shut and "
        "stays the way you left it. Alerts are explained in plain words, and the old About page is now About, "
        "Docs, Changelog, Privacy and Terms.",
        "Keep as many lists of airports as you like and share any of them as one link, and get alerts for any "
        "airport or list.",
        "A new logo and a cleaner look, and pages that say how Amend works, what it doesn't cover, what it "
        "stores and how to report a problem.",
        "New FAA data is picked up within hours of being posted, and a failed download can no longer publish a "
        "half-built site.",
        "Survey bookkeeping, like a glide slope elevation rounded by a tenth of a foot, no longer counts as an action "
        "item (from the 01 Oct 2026 cycle on).",
        "About 470 remark translations that got a contraction or a number wrong were thrown out. The FAA text shows "
        "instead.",
        "A <span class=\"ann new\">New</span> label on changes you haven't seen, a countdown to each 0901Z "
        "changeover, and a calendar of cycle dates.",
        "A desktop layout, and light and dark mode that follow your device.",
        "Class B, C, D and E surface area changes, told from each airport's point of view.",
    ]),
]
POLICY_DATE = "28 Sep 2026"   # when privacy/ or terms/ last changed in substance; bump it with them

# the about page used to hold everything. Old links to its sections go on to where each one lives now
ABOUT_MOVED = {"how": "../docs/#how", "limits": "../docs/#limits", "privacy": "../privacy/", "updates": "../changelog/"}


def doc_page(slug, title, lede, sections, description, meta, now, extra=""):
    """a reading page (docs, changelog, privacy, terms): a title, a line of links to its sections, then the
    sections as cards in one readable column. sections: [(id, heading, html)]."""
    toc = ('<nav class="toc" aria-label="On this page">' + "".join(
        f'<a href="#{i}">{h}</a>' for i, h, _ in sections) + '</nav>') if len(sections) > 2 else ""
    body = (f'<header class="full"><h1>{title}</h1><p class="lede">{lede}</p>{toc}</header>'
            '<div class="full doc">' + "".join(f'<section class="card box prose" id="{i}"><h3>{h}</h3>{x}</section>'
                                               for i, h, x in sections) + f'</div>{extra}')
    return page(f"{title} · Amend", description, f"{SITE_URL}{slug}/", body, "../",
                image=f"{SITE_URL}assets/card.png", active=slug, meta=meta, now=now)


def about_page(meta, latest, screenshots, now, example="VRB"):
    """a short about page: what Amend is, what you get, and where the rest lives now.
    example: an airport with changes this cycle, so "See an example" never opens a page saying nothing changed."""
    shots = "".join(f'<img src="shots/{e(s)}" alt="Amend on iPhone" loading="lazy">' for s in screenshots)
    feat = lambda tag, cls, title, text: (f'<div class="card box"><span class="ann {cls}">{tag}</span>'
                                          f'<h3>{title}</h3><div class="note">{text}</div></div>')
    sec = lambda id_, title, inner: f'<section class="card box prose" id="{id_}"><h3>{title}</h3>{inner}</section>'
    go = lambda href, title, text: f'<a class="card box go" href="{href}"><b>{title} ›</b><span class="note">{text}</span></a>'
    independent = sec("independent", "Independent and open source", (
        "<p>Amend is an independent project. It isn't affiliated with or endorsed by the FAA. The code, including "
        f'the rules that sort every change, is <a href="{REPO_URL}">open source on GitHub</a> under the MIT '
        "license.</p>"
        "<p><b>Not for navigation.</b> Amend helps you notice changes. It doesn't replace official FAA publications, "
        "NOTAMs or a preflight briefing, and if Amend and the FAA ever disagree, the FAA is right.</p>"))
    report = sec("report", "Report a problem", (
        f'<p>Found a change that\'s wrong, missing or hard to understand? <a href="{REPORT_URL}">Open an issue on '
        "GitHub</a> with the airport, the cycle and what the FAA source says. It takes a free GitHub account.</p>"
        "<p>If Amend matches the FAA and it's the FAA's data that looks wrong, like a frequency or a chart that "
        f'doesn\'t match the real airport, Amend can\'t fix it. Tell the FAA through its <a href="{FAA_INQUIRY}">'
        "Aeronautical Inquiries</a> page.</p>"))
    moved = json.dumps(ABOUT_MOVED)
    body = f"""<script>(()=>{{const m={moved},h=location.hash.slice(1);if(m[h])location.replace(m[h])}})()</script>
<header class="full" style="padding:12px 0 4px"><h1 class="hero">Know what changed at your airport.</h1>
<p class="lede">Every 28 days the FAA changes tower hours, frequencies, runways, navaids and approach
plates. Amend compares every cycle for every US airport and tells you what matters, in plain English, up to three weeks
before it takes effect.</p>
<div class="btns"><a class="btn" href="../">Search an airport</a><a class="btn ghost" href="../{e(example)}/">See an example</a></div></header>
{f'<div class="shots full">{shots}</div>' if shots else ''}
<div class="full"><h2 class="h2" style="margin-bottom:12px">What you get</h2><div class="feats">
{feat("ACT", "act", "Action items first", "Tower and Class D hours, frequencies, closed or renumbered runways, decommissioned navaids, new PPR rules: the changes that affect how you fly.")}
{feat("IFR", "ifr", "Instrument procedures", "Amended, new and removed approaches, STARs and departures, down to which waypoints moved, with the new plate one tap away.")}
{feat("FYI", "fyi", "Everything else, in plain English", "FAA remarks translated from contractions, with the original text always kept alongside.")}
{feat("Lists", "ifr", "Lists you can share", "Keep a list for your home area, another for a trip, and share any of them as one link, like amend.watch/list/daytona-training.")}
{feat("History", "fyi", "Two years of history", "Every change at every airport since August 2024, grouped by cycle.")}
{feat("iPhone", "ok", "iPhone app", "In testing and not on the App Store yet. It keeps your home airport and lists on your phone and notifies you when a new cycle changes them.")}
</div></div>
<div class="full"><h2 class="h2" style="margin-bottom:12px">Read more</h2><div class="feats">
{go("../guide/", "Guide", "What ACT, IFR and FYI mean, how to read a change, and how FAA cycles work.")}
{go("../docs/", "Docs", "How Amend works, where the data comes from, what it doesn't cover, and the JSON files behind it.")}
{go("../changelog/", "Changelog", "What's new on Amend, newest first.")}
{go("../status/", "Status", "Whether Amend is current, and every check the latest runs went through.")}
{go("../privacy/", "Privacy", "What Amend stores (almost nothing) and who else sees a visit.")}
{go("../terms/", "Terms", "The rules for using Amend, starting with: not for navigation.")}
</div></div>
<div class="full ggrid">{independent}{report}</div>"""
    return page("About Amend · what changed at your airport", "What Amend is, what you get, and where to read "
                "more.", f"{SITE_URL}about/", body, "../",
                image=f"{SITE_URL}assets/card.png", active="about", meta=meta, now=now)


def docs_page(meta, now):
    """site/docs/: how it works, the sources, what it doesn't cover, and the public JSON, for readers who want the
    detail. #how and #limits used to be on the about page."""
    sections = [
        ("how", "How it works", (
            "<p>Amend checks the FAA for new data every 3 hours. When a new cycle is posted, it compares every US "
            "airport with the cycle before, sorts each change with fixed rules and publishes the result here. AI only "
            "rewords remarks; everything else is plain code you can read on GitHub.</p><ul>"
            "<li><b>Noise:</b> survey dates, pavement codes, coordinate rounding, re-digitized airspace boundaries "
            "and duplicate rows are hidden. One real event, like a renumbered runway or a new STAR version, is one "
            "line instead of dozens of rows.</li>"
            '<li><b>Priority:</b> ACT, IFR and FYI come from fixed rules, not AI. <a href="../guide/">The guide</a> '
            "explains each one.</li>"
            "<li><b>Remarks:</b> AI turns FAA contractions into plain English using a fixed glossary. Code checks "
            "every translation, and one that adds, drops or changes a number or gets a known contraction wrong is "
            "thrown out so the FAA text shows instead. The original is always one tap away.</li>"
            "<li><b>Tests:</b> regression tests built from real cases in FAA data run before every update. If one "
            "fails, nothing is published and the last good version stays up.</li></ul>"
            '<p>The <a href="../status/">status page</a> shows every step of every recent run: the FAA files it '
            "downloaded and their checksums, the rows it read, what it found, every check and whether it was "
            "published.</p>")),
        ("sources", "Data sources", (
            "<ul>"
            f'<li><b><a href="{NASR_PAGE.format(cycle="")}">NASR 28-day subscription</a>:</b> airports, runways, '
            "frequencies, tower hours, navaids and the Chart Supplement remarks. Airport history here goes back to "
            "Aug 2024.</li>"
            f'<li><b><a href="{DTPP_SEARCH}">d-TPP</a>:</b> the chart index for approaches, STARs and departures, '
            "with a link to each plate.</li>"
            "<li><b>FAA class airspace shapefiles:</b> Class B, C, D and E surface area floors, ceilings and "
            "boundaries.</li></ul>"
            "<p>The FAA posts each cycle's files before they take effect (the d-TPP page says 20 days ahead), which "
            "is how Amend can show a change before it happens.</p>"
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
            "<li><b>What the FAA hasn't posted yet.</b> A new cycle can take a few hours to show up here after the "
            "FAA posts it.</li></ul>"
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
            f'<p>The fields are described in <a href="{REPO_URL}/blob/master/SCHEMA.md">SCHEMA.md</a>. '
            "Airport IDs are FAA IDs (VRB, not KVRB) and dates are the FAA effective date. The data carries the same "
            'warning as the site: <a href="../terms/">not for navigation</a>.</p>')),
        ("open", "Open source", (
            f'<p>The engine, the rules and this site are <a href="{REPO_URL}">on GitHub</a> under the MIT license. '
            f'Found something wrong? <a href="{REPORT_URL}">Open an issue</a> with the airport, the cycle and what '
            "the FAA source says. If the FAA's own data is wrong, only the FAA can fix it: "
            f'use its <a href="{FAA_INQUIRY}">Aeronautical Inquiries</a> page.</p>')),
    ]
    return doc_page("docs", "Docs", "How Amend works, where the data comes from, what it doesn't cover, and the "
                    "files behind it.", sections, "How Amend compares FAA cycles, its data sources, what it doesn't "
                    "cover, and its public JSON files.", meta, now)


def changelog_page(meta, now):
    """site/changelog/: UPDATES, newest first. /about/#updates lands here."""
    sections = [(f"m-{re.sub(r'[^a-z0-9]+', '-', month.lower()).strip('-')}", e(month),
                 "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>") for month, items in UPDATES]
    return doc_page("changelog", "Changelog", "What's new on Amend, newest first. Every change to the code is "
                    f'also on <a href="{REPO_URL}/commits/master">GitHub</a>.', sections,
                    "What's new on Amend, newest first.", meta, now)


def privacy_page(meta, now):
    """site/privacy/. Every claim here has to match how the site and app really work: GitHub Pages, the Cloudflare
    Web Analytics beacon (CF_BEACON), fonts from amend.watch, lists in localStorage, an app that only talks to
    amend.watch and the FAA. Anything that adds a third party changes this page in the same PR."""
    email = ("<p>If you sign up for email on a shared list, your address goes to the email service that sends it, "
             "which keeps it until you unsubscribe. It's used for that list's updates and nothing else.</p>"
             if EMAIL_FORM else
             "<p>Amend doesn't collect email addresses. If you use a news reader app to "
             "follow an alert link, that app's own privacy policy applies to what you give it.</p>")
    sections = [
        ("short", "The short version", (
            "<p>No accounts, no cookies, no ads, and nothing sold. Your lists stay in your browser. Visitor counts "
            "come from cookie-free Cloudflare Web Analytics, and the site is hosted on GitHub Pages. Amend runs no "
            "server or database of its own; GitHub and Cloudflare keep only what's described below.</p>")),
        ("browser", "What stays in your browser", (
            "<p>Amend saves a few things in your browser's local storage so the site remembers you without an "
            "account:</p><ul><li>your lists of airports and which one you're using</li>"
            "<li>which changes you've already seen, for the <b>New</b> labels</li>"
            "<li>small settings, like which lists are open in the sidebar and whether you've seen the welcome</li>"
            "</ul><p>None of it is sent to Amend. It leaves your browser only in a share link you choose to copy, "
            "which carries that list's name and airports. Clearing this site's data in your browser deletes all of "
            "it.</p>")),
        ("analytics", "Visitor counts", (
            "<p>Amend counts visits with Cloudflare Web Analytics, which doesn't use cookies or follow you across "
            "sites. Its script loads from static.cloudflareinsights.com and reports the page you opened, the site "
            "that sent you and basic browser details. Like any request, Cloudflare sees your IP address when it "
            "loads. See <a href=\"https://www.cloudflare.com/privacypolicy/\">Cloudflare's privacy policy</a>.</p>")),
        ("hosting", "Hosting", (
            "<p>The site is hosted on GitHub Pages, which logs visitor IP addresses for security. See "
            "<a href=\"https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement\">"
            "GitHub's privacy statement</a>. Fonts, scripts and images are served by amend.watch itself, so no "
            "font or image service sees a visit either. Links out, like FAA sources and plates, only reach those sites when you "
            "open them.</p>")),
        ("alerts", "Alerts and email", email),
        ("reports", "Reporting a problem", (
            "<p>Problem reports are GitHub issues, which are public and fall under GitHub's own terms. Don't put "
            "anything private in one.</p>")),
        ("app", "The iPhone app", (
            "<p>The app has no account either. It keeps your airports and settings on your phone, and it only "
            "downloads data from amend.watch and charts from the FAA. Notifications are worked out on your phone; "
            "no server knows which airports you follow.</p>")),
        ("choices", "Your choices", (
            "<p>Since Amend keeps nothing about you, there's nothing for it to show you, correct or delete. What "
            "there is, you control:</p><ul>"
            "<li>Clear this site's data in your browser to delete your lists and settings.</li>"
            "<li>Block the Cloudflare script with a content blocker if you'd rather not be counted. Amend works the "
            "same without it.</li>"
            "<li>For what GitHub or Cloudflare keep, use their own privacy settings and requests.</li></ul>")),
        ("children", "Children", (
            "<p>Amend doesn't ask anyone for personal information, so it doesn't collect any from children "
            "either.</p>")),
        ("changes", "Changes to this page", (
            f"<p>Last changed {POLICY_DATE}. Changes are listed in the <a href=\"../changelog/\">changelog</a>, and "
            f"every edit is in the page's history <a href=\"{REPO_URL}\">on GitHub</a>. Questions go to "
            f"<a href=\"{REPORT_URL}\">GitHub issues</a>.</p>")),
    ]
    return doc_page("privacy", "Privacy", "What Amend keeps about you (almost nothing), and who else sees a visit.",
                    sections, "Amend has no accounts and no cookies. What it stores, and who else sees a visit.",
                    meta, now)


def terms_page(meta, now):
    """site/terms/. A plain-words first version; it needs a real legal review before schools rely on Amend."""
    sections = [
        ("navigation", "Not for navigation", (
            "<p>Amend is an awareness and study tool. It is not a source of flight information. Always use current "
            "official FAA publications, NOTAMs and a proper preflight briefing; under 14 CFR 91.103 the pilot in "
            "command has to know all the available information for a flight. If Amend and the FAA ever disagree, "
            "the FAA is right.</p>")),
        ("accuracy", "No guarantee", (
            "<p>Amend is provided as is, without any warranty. Its data can be wrong, late or incomplete: the FAA "
            "can correct a cycle after it's posted, an update can fail, and a rule can sort a change the wrong way. "
            "Plain-English remarks are made by AI and checked by code, and the FAA text next to them is the one "
            "that counts. The site or its data can be unavailable at any time, and features can change or stop "
            "without notice.</p>"
            f'<p>If the FAA\'s own data looks wrong, report it to the FAA through its <a href="{FAA_INQUIRY}">'
            "Aeronautical Inquiries</a> page. Amend only repeats what the FAA publishes.</p>")),
        ("liability", "Liability", (
            "<p>As far as the law allows, Amend and the people who make it aren't liable for any loss or damage "
            "that comes from using it or relying on it, including in flight planning or training.</p>")),
        ("faa", "Not the FAA", (
            "<p>Amend is independent. It isn't affiliated with, endorsed by or checked by the FAA. The data comes "
            "from public FAA publications.</p>")),
        ("use", "Using the site and data", (
            "<p>You're free to use the site, the alert feeds and the JSON files, including in your own tools and "
            "training material. Please don't present Amend's data as official FAA data, and keep automated "
            "requests reasonable: the data only changes a few times a day. Don't try to break, overload or get around "
            "how the site works.</p>"
            f'<p>The code is open source under the <a href="{REPO_URL}/blob/master/LICENSE">MIT license</a>.</p>')),
        ("links", "Other sites", (
            "<p>Amend links to sites it doesn't run, like FAA pages and plates, GitHub, and news reader apps. "
            "Their own terms and privacy policies apply there, and Amend isn't responsible for them.</p>")),
        ("changes", "Changes", (
            f"<p>Last changed {POLICY_DATE}. These terms can change as Amend does; changes are listed in the "
            f'<a href="../changelog/">changelog</a> and every edit is <a href="{REPO_URL}">on GitHub</a>. '
            f'Questions go to <a href="{REPORT_URL}">GitHub issues</a>.</p>')),
    ]
    return doc_page("terms", "Terms of use", "The rules for using Amend, in plain words.", sections,
                    "Terms of use for Amend: not for navigation, no guarantee, and how you can use the data.",
                    meta, now)


GUIDE_SECTIONS = [
    ("reading", "Reading a change",
     "<p>Changes read old → new. <b>Tower hours: 0700-2100 → 0700-0100 local</b> means it was 0700-2100 and "
     "becomes 0700-0100.</p>"
     "<p><b>FAA text</b> opens the original remark the FAA published. <b>Details</b> shows every field that "
     "changed. <b>View plate</b> opens the new approach or procedure chart, and the "
     '<span class="ann fyi plain">Amdt 3</span> chip is its amendment number (<span class="ann fyi plain">Original</span> '
     "means a brand new procedure).</p>"),
    ("remarks", "Remarks",
     "<p>Remarks are the free-text notes in the FAA Chart Supplement (the old A/FD) for an airport: things like PPR "
     "requirements, runway restrictions, wildlife, noise abatement, when services aren't available.</p>"
     "<p>The FAA writes them in contractions (RSCD NOT MNT 2300-0600 M-F). Amend translates them to plain English "
     "with AI using a fixed FAA glossary; unknown abbreviations are left as-is instead of guessed. A translation "
     "that changes a number or gets a known contraction wrong is thrown out, and the FAA text shows instead. Open "
     "<b>FAA text</b> on any remark to see the original, and trust the original if they ever disagree.</p>"),
    ("cycles", "Cycles",
     "<p>The FAA publishes airport and airspace data every 28 days (NASR) and instrument charts on the same schedule "
     "(d-TPP). Each cycle has an effective date and switches over at 0901Z that day.</p>"
     '<div class="tier"><span class="ann ifr">Upcoming</span><span>The next cycle is already published but not in '
     "effect yet, so you can see changes before they happen. Until then the value before the → is the one that "
     "applies. Great time to check your airports.</span></div>"
     '<div class="tier"><span class="ann ok">In effect</span><span>The newest cycle is active. Shows what changed '
     "compared to the one before it.</span></div>"
     '<p><a href="webcal://amend.watch/cycles.ics">Add the cycle dates to your calendar</a> to get a reminder '
     "before each changeover.</p>"
     "<p>History goes back to Aug 2024 for airport data. Chart history starts in fall 2026 because the FAA doesn't "
     "keep old chart indexes online.</p>"),
    ("lists", "Lists",
     '<p>Search for an airport on the <a href="../">home page</a> and tap <b>+</b> to add it to a list, or use '
     "<b>+ Add to list</b> on any airport page. Lists are saved in this browser (no account needed). Make as many "
     "as you like, say one for your home area and one for a trip, and switch between them on the home page or the "
     '<a href="../list/">Lists</a> page. <b>View all changes</b> shows every change at every airport on a list, '
     "action items first.</p>"
     '<p>Changes you haven\'t seen yet get a <span class="ann new">New</span> label, based on the last time you '
     "opened that airport or list in this browser. The home page shows what's coming up at all your airports and "
     "counts down to the 0901Z changeover.</p>"
     "<p><b>Copy share link</b> gives you one link for a whole list, handy for a flight school or a training area. "
     "Anyone who opens it sees the same airports and can save the list as their own.</p>"),
    ("alerts", "Alerts",
     "<p>Every airport page and shared list has a <b>Get alerts</b> box. It gives you one update per FAA cycle: "
     "what changes there, action items first, usually within a day of the FAA posting it (about three weeks before "
     "it takes effect).</p>"
     "<p>Copy the alert link and paste it into a news reader app like Feedly, Inoreader or NetNewsWire. The link is "
     "an RSS feed, the same kind podcast apps use.</p>"
     "<p>Lists saved in your browser don't have one alert link, since only your browser knows what's on them. "
     "Follow each airport instead, or use <b>More options</b> on the list's page to download all of its alerts as "
     "one file (OPML) a news reader can import.</p>"),
]


def guide_page(meta=None, now=None):
    """site/guide/: what the labels, remarks and cycles mean. The web copy of the iOS GuideView."""
    sec = lambda id_, title, inner, cls="": f'<section class="card box{cls}" id="{id_}"><h3>{title}</h3>{inner}</section>'
    priority = sec("priority", "Priority", tier_rows(True) + "<p>Changes are listed ACT first, then IFR, then FYI, "
                   "so the ones that matter are always at the top.</p>", " wide")
    body = f"""<header class="full"><h1>Guide</h1>
<p class="lede">How to read Amend: what the labels mean, where remarks come from, and how FAA cycles work.</p></header>
<div class="full guide ggrid">{priority}{"".join(sec(*x) for x in GUIDE_SECTIONS)}</div>
<p class="full"><a href="../?welcome">Show the welcome again ›</a></p>"""
    return page("Guide · Amend", "What ACT, IFR and FYI mean, how remarks are translated, and how FAA cycles work.",
                f"{SITE_URL}guide/", body, "../", image=f"{SITE_URL}assets/card.png", active="guide", meta=meta,
                now=now)


def cycles_ics(meta, now):
    """calendar feed of FAA cycle changeovers (last one + the next year), so a CFI can subscribe once."""
    first = dt.date.fromisoformat(meta["to_cycle"]) - dt.timedelta(days=28)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//amend.watch//FAA cycles//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:FAA cycles (Amend)", "X-PUBLISHED-TTL:P1D"]
    for k in range(15):
        d = first + dt.timedelta(days=28 * k)
        lines += ["BEGIN:VEVENT", f"UID:faa-cycle-{d.isoformat()}@amend.watch", f"DTSTAMP:{stamp}",
                  f"DTSTART:{d:%Y%m%d}T090100Z", f"DTEND:{d:%Y%m%d}T093100Z",
                  "SUMMARY:FAA cycle takes effect (0901Z)",
                  "DESCRIPTION:New NASR airport data and d-TPP charts take effect. What changes at your airports: "
                  "https://amend.watch/", "URL:https://amend.watch/", "TRANSP:TRANSPARENT", "END:VEVENT"]
    return "\r\n".join(lines + ["END:VCALENDAR"]) + "\r\n"


def not_found_page(meta, now):
    """site/404.html, which GitHub Pages serves for any address that doesn't exist. People type amend.watch/KDAB or
    amend.watch/dab, so those go on to /DAB/; anything else gets a way back. Links start at / because this page
    shows up at any depth."""
    body = r"""<header class="full"><div class="eyebrow">Page not found</div><h1 id="nfh">Nothing here</h1>
<p class="lede" id="nfp">There’s no page at this address.</p>
<div class="btns"><a class="btn" href="/">Search airports</a><a class="btn ghost" href="/list/">Your lists</a></div></header>
<script>(()=>{const seg=location.pathname.split("/").filter(Boolean).map(s=>{try{return decodeURIComponent(s)}catch(e){return s}}),
  f=seg[0]||"",low=f.toLowerCase(),rest=location.search+location.hash,h=document.getElementById("nfh"),p=document.getElementById("nfp");
if(seg.length===1&&["list","guide","about","docs","changelog","privacy","terms","status"].includes(low)&&f!==low)return location.replace("/"+low+"/"+rest);
if(low==="list"&&seg.length===2){const slug=seg[1].toLowerCase();if(slug!==seg[1])return location.replace("/list/"+slug+"/"+rest);
  h.textContent="No list called “"+seg[1]+"”";p.textContent="Check the link. Lists you saved yourself are under Your lists.";return}
const id=f.toUpperCase().replace(/^K(?=[A-Z]{3}$)/,"");   // KDAB -> DAB, like the search box
if(seg.length===1&&/^[A-Z0-9]{2,4}$/.test(id)){if(id!==f)return location.replace("/"+id+"/"+rest);
  h.textContent="No changes on record at "+id;
  p.innerHTML="Airports get a page here once the FAA changes something there. <a href=\"/?q="+encodeURIComponent(id)+"\">Search for "+esc(id)+"</a> to check the ID."}})()</script>"""
    return page("Page not found · Amend", "See what changed at any US airport each FAA cycle.", "", body, "/",
                meta=meta, now=now, head='<meta name="robots" content="noindex">')


def redirect(folder, to, title, keep_query=False):
    """tiny page at folder/index.html that forwards to the relative url `to`."""
    os.makedirs(folder, exist_ok=True)
    refresh = f'<meta http-equiv="refresh" content="0;url={to}">'
    if keep_query:   # a meta refresh drops ?w=..., so only use it when scripts are off
        refresh = (f'<script>location.replace({json.dumps(to)}+location.search+location.hash)</script>'
                   f'<noscript>{refresh}</noscript>')
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><meta charset="utf-8">{refresh}<a href="{to}">{e(title)}</a>')


def build(site, meta, directory, latest, history_dir, now=None, watchlists=None, screenshots_dir="docs/screenshots"):
    """write site/assets/style.css, site/<ID>/index.html for every airport with data, site/index.html."""
    now = now or dt.datetime.now(dt.timezone.utc)
    os.makedirs(os.path.join(site, "assets"), exist_ok=True)
    with open(os.path.join(site, "assets", "style.css"), "w") as f:
        f.write(CSS)
    os.makedirs(os.path.join(site, "assets", "fonts"), exist_ok=True)
    for n in [x[1] for x in WEB_FONTS] + ["OFL.txt"]:
        shutil.copy(os.path.join(brand.FONTS, n), os.path.join(site, "assets", "fonts", n))
    brand.write_site_icons(site)
    with open(os.path.join(site, "assets", "app.js"), "w", encoding="utf-8") as f:
        f.write(APP)
    with open(os.path.join(site, "cycles.ics"), "w", newline="") as f:
        f.write(cycles_ics(meta, now))
    info = {a["id"]: a for a in directory}
    card(os.path.join(site, "assets", "card.png"), "What changed at your airport",
         "Every FAA cycle, in plain English", "", [("ACT", "action"), ("IFR", "ifr"), ("FYI", "fyi"), ("No change", "ok")],
         "Tower hours, frequencies, runways, navaids and approach plates.",
         f"Effective {nice(meta['to_cycle'])}")
    # one shared card for the ~10k airports with nothing changing this cycle (the title names the airport)
    upcoming_now, _ = status(meta, now)
    card(os.path.join(site, "assets", "nochange.png"), "No changes", "Nothing new at this airport", "",
         [("No change", "ok")],
         f"{'Nothing changes on' if upcoming_now else 'Nothing changed in the'} {nice(meta['to_cycle'])} "
         f"{'' if upcoming_now else 'cycle'}".strip(), f"Effective {nice(meta['to_cycle'])}")
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
        has_card = False
        if apt in latest:  # ~700 airports: a card with this cycle's counts and top change
            a, ch = info.get(apt, {}), latest[apt]
            c = counts(ch)
            chip_list = [(f"{lbl} {c[p]}", p) for p, lbl, _ in PRIORITY if c[p]]
            top = next((x["summary"] for x in ch if x["priority"] == "action"), ch[0]["summary"])
            has_card = card(os.path.join(site, apt, "card.png"), apt, a.get("name", ""),
                            ", ".join(x for x in (a.get("city"), a.get("state")) if x), chip_list,
                            (top[:1].upper() + top[1:]).replace(" -> ", " → "),
                            f"Effective {nice(meta['to_cycle'])}")
        with open(os.path.join(site, apt, "index.html"), "w", encoding="utf-8") as f:
            f.write(airport_page(apt, info.get(apt, {}), latest.get(apt), hist, meta, now, has_card))
        with open(os.path.join(site, apt, "feed.xml"), "w", encoding="utf-8") as f:
            f.write(feeds.airport_feed(apt, info.get(apt, {}), latest.get(apt), hist, meta, now))
    # quiet airports get no page, but a feed anyone can subscribe to before the first change shows up
    for apt in sorted(info.keys() - ids - RESERVED):
        if re.fullmatch(r"[A-Z0-9]{2,4}", apt):
            os.makedirs(os.path.join(site, apt), exist_ok=True)
            with open(os.path.join(site, apt, "feed.xml"), "w", encoding="utf-8") as f:
                f.write(feeds.airport_feed(apt, info[apt], None, None, meta, now, has_page=False))
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(meta, directory, latest, ids, now))
    os.makedirs(os.path.join(site, "list"), exist_ok=True)
    with open(os.path.join(site, "list", "index.html"), "w", encoding="utf-8") as f:
        f.write(watch_page(meta, directory, now))
    # early share links were /watch/?w=...; forward them with the query intact
    redirect(os.path.join(site, "watch"), "../list/", "Your lists", keep_query=True)
    shots = []
    about = os.path.join(site, "about")
    os.makedirs(os.path.join(about, "shots"), exist_ok=True)
    if screenshots_dir and os.path.isdir(screenshots_dir):
        for n in sorted(os.listdir(screenshots_dir)):
            if n.lower().endswith((".png", ".jpg", ".jpeg")):
                shutil.copy(os.path.join(screenshots_dir, n), os.path.join(about, "shots", n))
                shots.append(n)
    # "See an example": this cycle's busiest airport with an ICAO code, so it's a real public field
    ranked = sorted((a for a in latest if a in ids), key=lambda a: (-counts(latest[a])["action"], -len(latest[a]), a))
    example = next((a for a in ranked if info.get(a, {}).get("icao")), ranked[0] if ranked else "VRB")
    with open(os.path.join(about, "index.html"), "w", encoding="utf-8") as f:
        f.write(about_page(meta, latest, shots, now, example))
    for slug, make in (("guide", guide_page), ("docs", docs_page), ("changelog", changelog_page),
                       ("privacy", privacy_page), ("terms", terms_page)):
        os.makedirs(os.path.join(site, slug), exist_ok=True)
        with open(os.path.join(site, slug, "index.html"), "w", encoding="utf-8") as f:
            f.write(make(meta, now))
    from . import statuspage   # imports web, so not at the top
    statuspage.build(site, meta, now)
    with open(os.path.join(site, "404.html"), "w", encoding="utf-8") as f:
        f.write(not_found_page(meta, now))
    for slug, wl in (watchlists or {}).items():
        # early links were /watch/<slug>/ and then /<slug>/; keep both working
        redirect(os.path.join(site, "watch", slug), f"../../list/{slug}/", wl["name"])
        redirect(os.path.join(site, slug), f"../list/{slug}/", wl["name"])
        folder = os.path.join(site, "list", slug)
        os.makedirs(folder, exist_ok=True)
        tot = {p: sum(counts(latest.get(a, []))[p] for a in wl["airports"]) for p, _, _ in PRIORITY}
        changed = sum(1 for a in wl["airports"] if latest.get(a))
        has_card = card(os.path.join(folder, "card.png"), wl["name"], "", "",
                        [(f"{lbl} {tot[p]}", p) for p, lbl, _ in PRIORITY if tot[p]] or [("No change", "ok")],
                        f"{len(wl['airports'])} airports · {changed} with changes this cycle",
                        f"Effective {nice(meta['to_cycle'])}")
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(named_watch_page(slug, wl, meta, info, latest, now, has_card))
        hists = {}
        for a in wl["airports"]:
            path = os.path.join(history_dir or "", f"{a}.json")
            if history_dir and os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    hists[a] = json.load(f)
        with open(os.path.join(folder, "feed.xml"), "w", encoding="utf-8") as f:
            f.write(feeds.list_feed(slug, wl, info, latest, hists, meta, now))
    return len(ids)