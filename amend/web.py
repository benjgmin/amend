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

SITE_URL = "https://amend.watch/"
RESERVED = {"latest", "history", "assets", "watch", "list", "about", "guide", "index.html", "airports.json", "cycles.ics"}  # never an airport page
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


FONTS = ("https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600"
         "&display=swap")
# clean look: light and dark follow the device. amber = action, cyan = IFR, grey = FYI, green = nothing changed,
# the same meaning as the iOS app.
CSS = """
:root{--bg:#F6F7F9;--p:#FFFFFF;--p2:#EFF1F4;--ln:#E3E6EB;--tx:#0F1216;--dm:#5B6573;--fn:#848E9A;
--am:#B25E00;--amS:#FFF1DC;--cy:#0969B8;--cyS:#E4F0FB;--gy:#5B6573;--gyS:#EDEFF2;--gn:#15803D;--gnS:#E6F5EA;
--amber:var(--am);--cyan:var(--cy);--dim:var(--dm);--shadow:0 1px 2px rgba(16,24,40,.05);
--sans:"Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--mono:"Geist Mono",ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0D1015;--p:#151920;--p2:#1C212A;--ln:#262C36;--tx:#ECEEF1;
--dm:#9AA3AF;--fn:#6E7885;--am:#F5B040;--amS:rgba(245,176,64,.13);--cy:#5CC2FF;--cyS:rgba(92,194,255,.13);
--gy:#A3ACB8;--gyS:rgba(163,172,184,.12);--gn:#4ADE80;--gnS:rgba(74,222,128,.12);--shadow:none;color-scheme:dark}}
*{box-sizing:border-box}html{background:var(--bg)}[hidden]{display:none!important}
body{margin:0;color:var(--tx);background:var(--bg);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
a{color:var(--cy);text-decoration:none}a:hover{text-decoration:underline}
:focus-visible{outline:2px solid var(--cy);outline-offset:2px}
b,strong{font-weight:600}
.app{display:grid;grid-template-columns:minmax(0,1fr);min-height:100vh}
.sb{display:none}
.mtop{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--ln);background:var(--p);position:sticky;top:0;z-index:5}
.brand{font:600 17px var(--sans);letter-spacing:-.2px;color:var(--tx);display:inline-flex;align-items:center;gap:8px}
.brand:hover{text-decoration:none}
.brand i{width:18px;height:18px;border-radius:5px;background:var(--tx);display:inline-grid;place-items:center}
.brand i::after{content:"";width:6px;height:6px;border-radius:50%;background:var(--am)}
.nav{display:flex;gap:16px;font-size:14px}.nav a{color:var(--dm)}.nav a.on{color:var(--tx);font-weight:500}
.main{padding:20px 16px 48px;display:grid;gap:20px;grid-template-columns:minmax(0,1fr);align-content:start;width:100%;max-width:1400px;margin:0 auto}
.col,.rail{display:grid;gap:16px;align-content:start;min-width:0}
.rail .hist{display:none}
.full{min-width:0}
.eyebrow{font-size:13px;color:var(--dm)}
h1{font:600 36px/1.1 var(--sans);letter-spacing:-.9px;margin:2px 0 0;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h1 .icao{font:500 15px var(--mono);color:var(--fn);letter-spacing:0}
.aname{color:var(--dm);font-size:16px;margin-top:2px}
.h2{font:600 18px/1.3 var(--sans);letter-spacing:-.3px;margin:14px 0 0}
.hero{font:600 32px/1.15 var(--sans);letter-spacing:-.9px;margin:0;text-wrap:balance}
.lede{color:var(--dm);font-size:16px;max-width:62ch;margin:8px 0 0}
.big{font:600 26px/1.2 var(--sans);letter-spacing:-.6px}
.note{font-size:14px;color:var(--dm);margin:6px 0 0}
.foot{font-size:12.5px;color:var(--fn);margin:8px 0 0}
.card{background:var(--p);border:1px solid var(--ln);border-radius:14px;box-shadow:var(--shadow)}
.box{padding:14px 16px}.box>h3{margin:0 0 8px;font:600 14px var(--sans)}
.kv{display:flex;justify-content:space-between;gap:12px;padding:7px 0;font-size:14px;border-top:1px solid var(--ln)}
.kv:first-of-type{border-top:0}.kv>span:first-child{color:var(--dm)}.kv>span:last-child{text-align:right}
.ann{display:inline-flex;align-items:center;gap:6px;font:500 12.5px/1.6 var(--sans);padding:1px 9px 1px 8px;border-radius:999px;white-space:nowrap;color:var(--gy);background:var(--gyS)}
.ann::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.ann.plain::before{display:none}.ann.plain{padding:1px 8px}
.act{color:var(--am);background:var(--amS)}.ifr{color:var(--cy);background:var(--cyS)}
.fyi{color:var(--gy);background:var(--gyS)}.ok{color:var(--gn);background:var(--gnS)}
.ann[title]{cursor:help}
.ann.new{color:var(--bg);background:var(--tx);padding:1px 8px}.ann.new::before{display:none}
.it.new{box-shadow:inset 3px 0 0 var(--tx)}
.sbi .ann.new{font:600 11px/1.5 var(--sans);padding:0 6px}
time[data-until]{font-variant-numeric:tabular-nums;white-space:nowrap}
.nx{display:grid;gap:7px;padding:12px 16px;border-top:1px solid var(--ln);color:var(--tx)}.nx:first-child{border-top:0}
.nx:hover{background:var(--p2);text-decoration:none}
.nxh{display:flex;align-items:center;gap:6px 12px;flex-wrap:wrap}.nxh .rname{color:var(--dm);font-size:14px}.nxh .chips{margin-left:auto}
.nxi{display:grid;grid-template-columns:40px minmax(0,1fr);gap:10px;align-items:baseline;font-size:14px;overflow-wrap:anywhere}.nxi>.ann{justify-self:start}
.nxm{font-size:13px;color:var(--cy);padding-left:50px}
.nxq{padding:11px 16px;border-top:1px solid var(--ln);font-size:13.5px;color:var(--dm)}.nxq:first-child{border-top:0}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;justify-content:space-between}
.seg{display:flex;gap:2px;background:var(--p2);border-radius:10px;padding:3px;max-width:100%;overflow-x:auto}
.seg a{font:500 13.5px var(--sans);padding:5px 12px;border-radius:7px;color:var(--dm);white-space:nowrap}
.seg a b{margin-left:5px;color:var(--tx)}.seg a:hover{text-decoration:none;color:var(--tx)}
.seg a.on{background:var(--p);color:var(--tx);box-shadow:0 1px 2px rgba(0,0,0,.1)}
.banner{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;padding:12px 14px;font-size:14px;color:var(--dm)}
.banner .ann{margin-top:1px}.banner span:last-child{flex:1;min-width:200px}
.lst{background:var(--p);border:1px solid var(--ln);border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}
.gh{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 16px 10px;font:600 14px var(--sans)}
.gh .n{color:var(--fn);font-weight:500}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:8px;background:var(--fn);vertical-align:1px}
.d-action{background:var(--am)}.d-ifr{background:var(--cy)}
.it{display:grid;grid-template-columns:minmax(0,1fr);gap:2px 16px;padding:11px 16px;border-top:1px solid var(--ln)}
.it .k{font-size:12.5px;color:var(--fn)}
.it .s{font-size:15px;overflow-wrap:anywhere}
.it .m{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:13.5px;white-space:nowrap}
.it .m:empty{display:none}
.more{margin-top:3px}
.more>summary{cursor:pointer;list-style:none;font-size:13.5px;color:var(--cy);display:inline-block}
.more>summary::-webkit-details-marker{display:none}
.more>summary::after{content:" \\25BE";font-size:11px}.more[open]>summary::after{content:" \\25B4"}
.more pre{white-space:pre-wrap;font:12px/1.55 var(--mono);color:var(--dm);background:var(--p2);border-radius:8px;padding:9px 11px;margin:6px 0 0}
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
.search{display:flex;align-items:center;gap:10px;background:var(--p);border:1px solid var(--ln);border-radius:12px;padding:0 14px;box-shadow:var(--shadow);color:var(--fn)}
.search:focus-within{border-color:var(--cy)}
.search input{flex:1;border:0;background:transparent;color:var(--tx);font:16px var(--sans);padding:13px 0;outline:none;min-width:0}
.search input::placeholder{color:var(--fn)}
kbd{font:500 12px var(--mono);border:1px solid var(--ln);border-radius:5px;padding:0 6px;color:var(--fn)}
.sec{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:4px 0 8px}
.hdr{font:600 14px var(--sans);color:var(--tx)}
.rows{background:var(--p);border:1px solid var(--ln);border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}
.wrow{display:flex;align-items:stretch;border-top:1px solid var(--ln)}.wrow:first-child{border-top:0}
.wrow>a{flex:1;display:flex;align-items:center;gap:12px;padding:10px 14px;color:var(--tx);min-width:0}
.wrow>a[href]:hover{background:var(--p2);text-decoration:none}
.rid{font:600 15px var(--mono);min-width:52px}.rname{flex:1;min-width:0;font-size:14.5px}.rsub{font-size:12.5px;color:var(--dm)}
.x{background:transparent;border:0;border-left:1px solid var(--ln);color:var(--cy);min-width:48px;font:500 20px var(--sans);cursor:pointer}
.x.on{color:var(--gn)}.x:hover{background:var(--p2)}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}
.btn{display:inline-flex;align-items:center;background:var(--tx);color:var(--bg);border:1px solid var(--tx);border-radius:9px;padding:8px 14px;font:500 14px var(--sans);cursor:pointer}
.btn:hover{text-decoration:none;opacity:.88}.btn:disabled{opacity:.5;cursor:default}
.btn.ghost{background:var(--p);color:var(--tx);border-color:var(--ln)}
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
.sbh{font:500 12px var(--sans);color:var(--fn);margin:18px 8px 4px}
.sbi{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 8px;border-radius:8px;font-size:14px;color:var(--tx)}
a.sbi:hover{background:var(--p2);text-decoration:none}.sbi.on{background:var(--p2);font-weight:500}
.sbi b{font:600 13px var(--mono)}.sbi.sub{color:var(--dm);font-size:13.5px}
.sb .search{margin:14px 0 0;border-radius:9px;padding:0 10px;box-shadow:none}.sb .search input{font-size:14px;padding:7px 0}
.sbfoot{margin-top:auto;padding:16px 8px 0;font-size:12.5px;color:var(--fn)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media (max-width:639px){.wrow>a{flex-wrap:wrap;row-gap:6px}.wrow>a .chips{flex-basis:100%;padding-left:64px}}
@media (min-width:640px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.feats{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (min-width:1000px){
 .app{grid-template-columns:248px minmax(0,1fr)}
 .sb{display:flex;flex-direction:column;position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid var(--ln);background:var(--p);padding:16px 12px}
 .sb .brand{padding:4px 8px 0}
 .mtop{display:none}
 .main{padding:32px 40px 56px}
 .main.two{grid-template-columns:minmax(0,1fr) 300px;column-gap:32px;align-items:start}
 .main.two>.full{grid-column:1/-1}
 .rail{position:sticky;top:24px}.rail .hist{display:block}
 .it{grid-template-columns:104px minmax(0,1fr) auto;align-items:baseline}
 .it .k{font-size:13.5px;color:var(--dm)}.it .m{justify-content:flex-end}
 .cards{grid-template-columns:repeat(3,minmax(0,1fr))}
 .ggrid{grid-template-columns:repeat(2,minmax(0,1fr))}.ggrid>.wide{grid-column:1/-1}
 .feats{grid-template-columns:repeat(3,minmax(0,1fr))}
 h1{font-size:40px}.hero{font-size:36px}
}
@media print{:root{--bg:#fff;--p:#fff;--p2:#F2F3F5;--ln:#D5D9DF;--tx:#000;--dm:#444;--fn:#666;--am:#8A4600;--amS:#FFF1DC;
--cy:#0A5A9C;--cyS:#E4F0FB;--gy:#444;--gyS:#EDEFF2;--gn:#15803D;--gnS:#E6F5EA;--shadow:none;color-scheme:light}
 .sb,.mtop,.rail,.seg,.btns,.search,#res,#welcome,#newnote,#next .nxm{display:none!important}
 .app{display:block}.main{display:block;padding:0;max-width:none}.main>*,.col>*{margin-bottom:12px}
 body{font-size:12.5px}a{color:inherit}.it,.apthead,.nx{break-inside:avoid}.it.new{box-shadow:none}}
"""

# changes whenever the CSS does, so a browser holding the old style.css (Pages caches it for 10 minutes)
# never pairs it with new HTML
CSS_VERSION = hashlib.sha1(CSS.encode()).hexdigest()[:10]

FONT_PATHS = {  # first one that exists wins (GitHub's Ubuntu runners have DejaVu; Macs have Menlo)
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/System/Library/Fonts/Menlo.ttc"],
    "sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"],
    "reg": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Helvetica.ttc"],
}
# the site's dark palette
COLORS = {"bg": (13, 16, 21), "panel": (21, 25, 32), "line": (38, 44, 54), "text": (236, 238, 241),
          "dim": (154, 163, 175), "faint": (110, 120, 133), "action": (245, 176, 64), "ifr": (92, 194, 255),
          "fyi": (163, 172, 184), "ok": (74, 222, 128)}


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
    """1200x630 link-preview image in the site's dark look. returns False if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H, P = 1200, 630, 64
    img = Image.new("RGB", (W, H), COLORS["bg"])
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([P - 24, P - 24, W - P + 24, H - P + 24], radius=28, fill=COLORS["panel"],
                        outline=COLORS["line"], width=2)
    # brand: a rounded square with an amber dot, then the name
    d.rounded_rectangle([P, P + 2, P + 36, P + 38], radius=9, fill=COLORS["text"])
    d.ellipse([P + 12, P + 14, P + 24, P + 26], fill=COLORS["action"])
    brand = _font("sans", 32)
    d.text((P + 50, P), "Amend", font=brand, fill=COLORS["text"])
    small = _font("reg", 26)
    d.text((W - P - d.textlength(footer, font=small), P + 6), footer, font=small, fill=COLORS["dim"])
    size = 132
    while size > 48 and d.textlength(big, font=_font("sans", size)) > W - 2 * P:
        size -= 8
    d.text((P - 4, P + 80 + (132 - size) // 2), big, font=_font("sans", size), fill=COLORS["text"])
    y = P + 250
    if name:
        d.text((P, y), _fit(d, name, _font("sans", 46), W - 2 * P), font=_font("sans", 46), fill=COLORS["text"])
        y += 62
    if loc:
        d.text((P, y), loc, font=small, fill=COLORS["dim"])
        y += 50
    x, cf = P, _font("sans", 30)
    for text, key in chip_list:
        tw = d.textlength(text, font=cf)
        col = COLORS[key]
        d.rounded_rectangle([x, y, x + tw + 64, y + 52], radius=26,
                            fill=tuple(int(c * 0.16 + COLORS["panel"][i] * 0.84) for i, c in enumerate(col)))
        d.ellipse([x + 20, y + 20, x + 32, y + 32], fill=col)
        d.text((x + 44, y + 9), text, font=cf, fill=col)
        x += tw + 80
    if line:
        d.text((P, y + 78), _fit(d, line, _font("reg", 32), W - 2 * P), font=_font("reg", 32),
               fill=COLORS["dim"])
    img.save(path, optimize=True)
    return True


COMMON_JS = 'const TIP=' + json.dumps({**{v[0]: v[2] for v in TIERS.values()}, "ok": NO_CHG_TIP}) + ';\n' + \
    'const KEY="amend.watch";\nconst esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\nconst loadW=()=>{try{return[...new Set(JSON.parse(localStorage.getItem(KEY)||"[]"))]}catch(e){return[]}};\nconst saveW=l=>{try{localStorage.setItem(KEY,JSON.stringify([...new Set(l)]))}catch(e){}};\nconst parseW=q=>[...new Set((q||"").toUpperCase().split(/[\\s,]+/).map(s=>s.replace(/^K(?=[A-Z]{3}$)/,"")).filter(s=>/^[A-Z0-9]{2,4}$/.test(s)))].slice(0,200);\nfunction chipsHtml(k){if(!k||!(k[0]||k[1]||k[2]))return \'<span class="chips"><span class="ann ok" title="\'+TIP.ok+\'">No change</span></span>\';\n  const t=[[k[0],"act","ACT"],[k[1],"ifr","IFR"],[k[2],"fyi","FYI"]].filter(x=>x[0]).map(x=>\'<span class="ann \'+x[1]+\'" title="\'+TIP[x[1]]+\'">\'+x[2]+\' \'+x[0]+\'</span>\');\n  return \'<span class="chips">\'+t.join("")+\'</span>\'}\n'
LANDING_JS = r"""if(new URLSearchParams(location.search).get("w")){location.replace("list/"+location.search)}
const A=__ROWS__;const byId=new Map(A.map(a=>[a[0],a]));
const NX=__NEXT__;let NEWC=AM.newc();
const NKEY="amend.watch.name";
const q=document.getElementById("q"),r=document.getElementById("res");
const params=new URLSearchParams(location.search);
if(params.get("q"))q.value=params.get("q");
const loadName=()=>{try{return localStorage.getItem(NKEY)||""}catch(e){return""}};
const saveName=n=>{try{n?localStorage.setItem(NKEY,n):localStorage.removeItem(NKEY)}catch(e){}};
function sub(a){return esc([a[1],[a[3],a[4]].filter(Boolean).join(", ")].filter(Boolean).join(" · "))}
function airportRow(id,btn){const a=byId.get(id)||[id,"","","","",0,null];
  const inner='<span class="rid">'+esc(a[0])+'</span><span class="rname">'+esc(a[2]||"Unknown airport")+'<br><span class="rsub">'+sub(a)+'</span></span>'+chipsHtml(a[6]).replace('<span class="chips">','<span class="chips">'+(NEWC[id]?AM.pill(NEWC[id]):""));
  return '<div class="wrow">'+(a[5]?'<a href="'+esc(a[0])+'/">'+inner+'</a>':'<a>'+inner+'</a>')+btn+'</div>'}
const act=id=>((byId.get(id)||[])[6]||[0])[0];
const sameSet=(x,y)=>x.length===y.length&&x.every(v=>y.includes(v));
function shareUrl(){const n=loadName();return new URL("list/?w="+loadW().join(",")+(n?"&n="+encodeURIComponent(n):""),location.href).href}
function clearShared(){history.replaceState(null,"",location.pathname);render()}
function renderShared(){const s=document.getElementById("shared"),ids=parseW(params.get("w")),name=(params.get("n")||"").slice(0,60);
  if(!ids.length||!location.search.includes("w=")){s.innerHTML="";return false}
  if(sameSet(ids,loadW())){s.innerHTML="";return true}   // it's your own list: show it once, below
  s.innerHTML='<div class="sec"><span class="hdr" style="color:var(--cy)">Shared'+(name?': '+esc(name):' watchlist')+' · '+ids.length+'</span></div><div class="rows">'+
    [...ids].sort((x,y)=>act(y)-act(x)).map(id=>airportRow(id,"")).join("")+'</div>'+
    '<div class="btns"><a class="btn" href="list/?w='+ids.join(",")+(name?"&n="+encodeURIComponent(name):"")+'">View all changes</a>'+
    '<button class="btn ghost" id="saveShared" data-ids="'+ids.join(",")+'" data-name="'+esc(name)+'">Add to my watchlist</button>'+
    '<button class="btn ghost" id="closeShared">Close</button></div>';return false}
function renderWatch(isMine){const l=loadW(),w=document.getElementById("watch"),n=loadName();
  if(!l.length){w.innerHTML='<div class="sec"><span class="hdr">Your watchlist</span></div><div class="card box note" style="margin:0">Search below and tap <b>+</b> to add airports to your watchlist. It’s saved in this browser; copy the link to send it to someone.</div>';return}
  w.innerHTML='<div class="sec"><span class="hdr">'+(n?esc(n):'Your watchlist')+' · '+l.length+(isMine?' · this link':'')+'</span></div><div class="rows">'+
    [...l].sort((x,y)=>act(y)-act(x)).map(id=>airportRow(id,'<button class="x" data-rm="'+esc(id)+'" title="Remove" aria-label="Remove '+esc(id)+'">×</button>')).join("")+'</div>'+
    '<div class="btns"><a class="btn" href="list/?w='+l.join(",")+(n?"&n="+encodeURIComponent(n):"")+'">View all changes</a>'+
    '<button class="btn ghost" id="share">Copy share link</button><button class="btn ghost" id="rename">'+(n?'Rename':'Name this list')+'</button></div>'}
function renderSearch(){const s=q.value.trim().toUpperCase();if(!s){r.innerHTML="";return}
  const hit=[];for(const a of A){const[id,ic,n,c]=a;let k=-1;
    if(id===s||ic===s)k=0;else if(id.startsWith(s)||ic.startsWith(s))k=1;
    else if(s.length>2&&n.toUpperCase().startsWith(s))k=2;
    else if(s.length>2&&(n.toUpperCase().includes(s)||c.toUpperCase().includes(s)))k=3;
    if(k>=0)hit.push([k*10+(ic?0:2),a])}
  hit.sort((x,y)=>x[0]-y[0]||x[1][0].length-y[1][0].length||(x[1][0]<y[1][0]?-1:1));
  const w=new Set(loadW());
  r.innerHTML=hit.length?'<div class="rows">'+hit.slice(0,30).map(([_,a])=>airportRow(a[0],w.has(a[0])?'<button class="x on" data-rm="'+esc(a[0])+'" title="Remove from watchlist" aria-label="Remove '+esc(a[0])+' from watchlist">✓</button>':'<button class="x" data-add="'+esc(a[0])+'" title="Add to watchlist" aria-label="Add '+esc(a[0])+' to watchlist">+</button>')).join("")+'</div>':'<div class="note">No airport found.</div>'}
// "coming up at your airports": the top changes at each watchlist airport, with the countdown to 0901Z
const got=new Map();
const latestOf=id=>{if(!got.has(id))got.set(id,fetch("latest/"+id+".json").then(r=>r.ok?r.json():null).catch(()=>null));return got.get(id)};
const PRI={action:["act","ACT"],ifr:["ifr","IFR"],fyi:["fyi","FYI"]};
async function renderNext(){const el=document.getElementById("next"),l=loadW();
  if(!l.length){el.innerHTML="";return}
  const ch=l.filter(id=>(byId.get(id)||[])[6]).slice(0,60),data=await Promise.all(ch.map(latestOf)),rows=[],nc={};
  ch.forEach((id,i)=>{const d=data[i];if(!d||!d.changes)return;const items=d.changes.map(c=>({id:c.id,c:NX.to}));
    AM.base(id,items,NX.to);const nw=AM.look(id,items,NX.to,false).nw;if(nw.size)nc[id]=nw.size;rows.push({id,d,nw})});
  l.filter(id=>!ch.includes(id)).forEach(id=>AM.base(id,[],NX.to));
  AM.setNewc(nc);NEWC=nc;
  rows.sort((x,y)=>y.d.counts.action-x.d.counts.action||y.nw.size-x.nw.size||(x.id<y.id?-1:1));
  const quiet=l.filter(id=>!rows.some(r=>r.id===id)).sort();
  const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
  const row=({id,d,nw})=>{const a=byId.get(id)||[id,"",""],top=d.changes.slice(0,3);
    return '<a class="nx" href="'+esc(id)+'/"><span class="nxh"><span class="rid">'+esc(id)+'</span><span class="rname">'+esc(a[2]||"")+'</span>'+
      chipsHtml([d.counts.action,d.counts.ifr,d.counts.fyi]).replace('<span class="chips">','<span class="chips">'+(nw.size?AM.pill(nw.size):""))+'</span>'+
      top.map(c=>'<span class="nxi"><span class="ann '+PRI[c.priority][0]+' plain">'+PRI[c.priority][1]+'</span><span>'+(nw.has(c.id)?AM.pill()+" ":"")+esc(cap(c.summary)).replace(/ -&gt; /g," → ")+'</span></span>').join("")+
      (d.changes.length>3?'<span class="nxm">'+(d.changes.length-3)+' more ›</span>':'')+'</a>'};
  el.innerHTML='<div class="sec"><span class="hdr">'+(NX.up?'Coming up at your airports':'This cycle at your airports')+'</span><span class="note" style="margin:0">'+
    (NX.up?'Takes effect ':'Next cycle ')+'<time datetime="'+NX.when+'" data-until="'+NX.when+'"></time></span></div>'+
    '<div class="rows">'+(rows.length?rows.map(row).join(""):'<div class="nxq">Nothing '+(NX.up?'changes':'changed')+' at your '+l.length+' airport'+(l.length==1?'':'s')+' this cycle.</div>')+
    (rows.length&&quiet.length?'<div class="nxq">No change at '+quiet.map(esc).join(", ")+'</div>':'')+'</div>';
  AM.tick();renderWatch(false);renderSearch();if(window.AMside)AMside()}
function render(){renderWatch(false);renderSearch()}
document.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;
  if(b.dataset.add){saveW([...loadW(),b.dataset.add]);renderNext()}
  else if(b.dataset.rm){saveW(loadW().filter(x=>x!==b.dataset.rm));renderNext()}
  else if(b.id==="saveShared"){saveW([...loadW(),...b.dataset.ids.split(",")]);if(!loadName()&&b.dataset.name)saveName(b.dataset.name);clearShared();renderNext();return}
  else if(b.id==="closeShared"){clearShared();return}
  else if(b.id==="rename"){const n=prompt("Name this watchlist (shows on shared links):",loadName());if(n===null)return;saveName(n.trim().slice(0,60))}
  else if(b.id==="share"){const u=shareUrl();
    (navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(()=>b.textContent="Copied",()=>prompt("Copy this link:",u));return}
  render()});
q.addEventListener("input",renderSearch);render();renderNext();
"""
WELCOME_JS = r"""(()=>{const W=document.getElementById("welcome"),K="amend.watch.welcomed",P=new URLSearchParams(location.search);
let seen=false;try{seen=!!localStorage.getItem(K)}catch(e){}
if(P.has("w")||P.has("q")||(seen&&!P.has("welcome")))return;
const steps=[...W.querySelectorAll(".step")],dots=[...W.querySelectorAll(".dots i")],intro=document.getElementById("intro");let i=0;
const show=()=>{steps.forEach((s,j)=>s.hidden=j!==i);dots.forEach((d,j)=>d.classList.toggle("on",j===i));
  document.getElementById("wnext").textContent=i<steps.length-1?"Next":"Get started";document.getElementById("wskip").hidden=i===steps.length-1};
const done=()=>{try{localStorage.setItem(K,"1")}catch(e){}W.hidden=true;intro.hidden=false;
  if(P.has("welcome"))history.replaceState(null,"",location.pathname)};
W.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;ev.stopPropagation();
  if(b.id==="wskip")done();else if(b.id==="wnext"){if(i<steps.length-1){i++;show()}else{done();q.scrollIntoView({block:"center"});q.focus()}}});
W.hidden=false;intro.hidden=true;show()})();
"""
WATCH_JS = r"""const META=__META__,NAMES=__NAMES__,SEL=__PRI__;
const P=new URLSearchParams(location.search),shared=parseW(P.get("w"));
const ids=shared.length?shared:loadW();
const NKEY="amend.watch.name",myName=(()=>{try{return localStorage.getItem(NKEY)||""}catch(e){return""}})();
const listName=((shared.length?P.get("n"):myName)||"").slice(0,60);
const isMine=!shared.length||(shared.length===loadW().length&&shared.every(x=>loadW().includes(x)));
const out=document.getElementById("list");
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
function changeHtml(c){const s=esc(cap(c.summary)).replace(/ -&gt; /g," → ");
  let m="";const ch=c.chart||{};
  if(ch.amdt)m+='<span class="ann fyi plain">'+(["0","ORIG"].includes(ch.amdt.toUpperCase())?"Original":"Amdt "+esc(ch.amdt))+'</span>';
  if(ch.pdf)m+='<a href="'+esc(ch.pdf)+'" target="_blank" rel="noopener">View plate ↗</a>';
  let more="";if(c.original)more='<details class="more"><summary>FAA text</summary><pre>'+esc(c.original)+'</pre></details>';
  else if(c.details&&c.details.length)more='<details class="more"><summary>Details</summary><pre>'+c.details.map(d=>esc(d).replace(/ -&gt; /g," → ")).join("\n")+'</pre></details>';
  return '<div class="it p-'+esc(c.priority)+'" data-id="'+esc(c.id)+'"><span class="k">'+esc(cap(c.category))+'</span><div class="s">'+s+more+'</div><div class="m">'+m+'</div></div>'}
async function load(id){try{const r=await fetch("../latest/"+id+".json");return r.ok?await r.json():null}catch(e){return null}}
(async()=>{
  if(!ids.length){out.innerHTML='<div class="card box note">Your watchlist is empty. Add airports on the <a href="../">search page</a>.</div>';return}
  document.getElementById("count").textContent=ids.length+" airport"+(ids.length==1?"":"s");
  document.getElementById("title").textContent=listName||(isMine?"Your watchlist":"Shared watchlist");
  if(listName)document.title=listName+" · Amend watchlist";
  const link=new URL("?w="+ids.join(",")+(listName?"&n="+encodeURIComponent(listName):""),location.href).href;
  document.getElementById("actions").innerHTML=(isMine?'':'<button class="btn" id="add">Add to my watchlist</button>')+
    '<button class="btn'+(isMine?'':' ghost')+'" id="copy">Copy link</button><a class="btn ghost" href="../">Search all airports</a>';
  document.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;
    if(b.id==="add"){const l=[...new Set([...loadW(),...ids])];try{localStorage.setItem(KEY,JSON.stringify(l));
      if(!myName&&listName)localStorage.setItem(NKEY,listName)}catch(e){}b.textContent="Added";b.disabled=true}
    if(b.id==="copy"){(navigator.clipboard?navigator.clipboard.writeText(link):Promise.reject()).then(()=>b.textContent="Copied",()=>prompt("Copy this link:",link))}});
  const data=await Promise.all(ids.map(load));
  const items=ids.map((id,i)=>({id,d:data[i]})).sort((a,b)=>((b.d&&b.d.counts.action)||0)-((a.d&&a.d.counts.action)||0));
  out.innerHTML=items.map(({id,d})=>{const n=NAMES[id]||[];const k=d?[d.counts.action,d.counts.ifr,d.counts.fyi]:null;
    const body=d?SEL.map(([p,t])=>{const g=d.changes.filter(c=>c.priority===p);return g.length?'<section class="lst"><div class="gh"><span><span class="dot d-'+p+'"></span>'+t+'</span><span class="n">'+g.length+'</span></div>'+g.map(changeHtml).join("")+'</section>':""}).join("")
             :'<div class="note">No changes in this cycle.</div>';
    return '<details class="apt" data-apt="'+esc(id)+'" '+(d?"open":"")+'><summary class="card apthead"><span><span class="rid">'+esc(id)+'</span> <span class="rname">'+esc(n[1]||"")+'</span></span>'+chipsHtml(k)+'</summary>'+body+'<p class="foot"><a href="../'+esc(id)+'/">Full page and history ›</a></p></details>'}).join("");
  out.querySelectorAll("details.apt").forEach(x=>{const r=AM.mark(x,x.dataset.apt,META.to_cycle),c=x.querySelector("summary .chips");
    if(r.n&&c)c.insertAdjacentHTML("afterbegin",AM.pill(r.n))});
})();
"""
# every page, before anything else runs: what this browser has already seen (for "New" labels) and the
# countdown to the next 0901Z changeover. First look at an airport marks nothing, it only remembers.
SEEN_JS = r"""var AM=(()=>{const K="amend.seen",NC="amend.newc",SH="amend.newshown";
const rd=(k,st)=>{try{return JSON.parse((st||localStorage).getItem(k)||"{}")||{}}catch(e){return{}}};
const wr=(k,v,st)=>{try{(st||localStorage).setItem(k,JSON.stringify(v))}catch(e){}};
// items: [{id, c: cycle}]. new = not seen before and from a cycle at or after the last look.
function look(apt,items,cyc,save){const all=rd(K),prev=all[apt],shown=rd(SH,sessionStorage),sh=new Set(shown[apt]||[]),nw=new Set();
  if(prev){const ids=new Set(prev.ids||[]);for(const x of items)if(sh.has(x.id)||(x.c>=prev.c&&!ids.has(x.id)))nw.add(x.id)}
  if(save!==false){all[apt]={c:cyc,t:Date.now(),ids:items.filter(x=>x.c>=cyc).map(x=>x.id).slice(0,400)};wr(K,all);
    shown[apt]=[...nw];wr(SH,shown,sessionStorage);const nc=rd(NC);if(apt in nc){delete nc[apt];wr(NC,nc)}}
  return{nw,prev}}
function base(apt,items,cyc){const all=rd(K);if(!all[apt]){all[apt]={c:cyc,t:Date.now(),ids:items.map(x=>x.id)};wr(K,all)}}
const pill=n=>'<span class="ann new" title="New since you last looked">'+(n?n+" new":"New")+'</span>';
function mark(root,apt,cyc){const els=[...root.querySelectorAll(".it[data-id]")];
  const r=look(apt,els.map(el=>({id:el.dataset.id,c:el.dataset.c||cyc})),cyc);
  for(const el of els)if(r.nw.has(el.dataset.id)){el.classList.add("new");const s=el.querySelector(".s");if(s)s.insertAdjacentHTML("afterbegin",pill()+" ")}
  root.querySelectorAll("details.cycle").forEach(d=>{const n=d.querySelectorAll(".it.new").length,c=d.querySelector("summary .chips");if(n&&c)c.insertAdjacentHTML("afterbegin",pill(n))});
  return{n:r.nw.size,prev:r.prev}}
const fmt=ms=>{const m=Math.floor(ms/6e4),d=Math.floor(m/1440),h=Math.floor(m%1440/60),mm=m%60;return(d?d+"d ":"")+(d||h?h+"h ":"")+mm+"m"};
function tick(){document.querySelectorAll("time[data-until]").forEach(t=>{const ms=Date.parse(t.dataset.until)-Date.now();
  t.textContent=ms>0?"in "+fmt(ms):"now";t.title=t.getAttribute("datetime").slice(0,16).replace("T"," ")+"Z"})}
setInterval(tick,15000);
return{look,base,mark,pill,tick,newc:()=>rd(NC),setNewc:m=>wr(NC,m)}})();
"""
# every page: the sidebar watchlist, the / shortcut, filter tabs on airport pages, opening a linked history cycle
SHELL_JS = r"""(()=>{const R=document.body.dataset.root||"",B=document.body.dataset,el=document.getElementById("sbw");
const loadL=()=>{try{return[...new Set(JSON.parse(localStorage.getItem("amend.watch")||"[]"))].filter(x=>/^[A-Z0-9]{2,4}$/.test(x))}catch(e){return[]}};
// airport pages and named lists: label what's new since the last visit, then remember this visit
document.querySelectorAll("[data-look]").forEach(x=>{const r=AM.mark(x,x.dataset.look,B.cyc);
  const s=x.querySelector(":scope>summary .chips");if(r.n&&s)s.insertAdjacentHTML("afterbegin",AM.pill(r.n));
  const nn=document.getElementById("newnote");if(nn&&r.n&&r.prev){nn.innerHTML=AM.pill(r.n)+"<span>"+(r.n==1?"change":"changes")+
    " since you last looked here on "+new Date(r.prev.t).toLocaleDateString(undefined,{day:"numeric",month:"short"})+".</span>";nn.hidden=false}});
function side(){const w=loadL(),nc=AM.newc();if(!el)return;el.innerHTML=w.length?'<div class="sbh">Your watchlist</div>'+w.slice(0,15).map(id=>'<a class="sbi'+(id===el.dataset.on?' on':'')+'" href="'+R+id+'/"><b>'+id+'</b>'+(nc[id]?AM.pill(nc[id]):'')+'</a>').join("")+
  '<a class="sbi sub" href="'+R+'list/">'+(w.length>15?'All '+w.length+' airports ›':'View all changes ›')+'</a>':""}
side();window.AMside=side;addEventListener("storage",side);
// airport pages: add to / remove from the watchlist, and share
const wb=document.getElementById("wbtn");
if(wb){const id=wb.dataset.apt,paint=()=>{const on=loadL().includes(id);wb.textContent=on?"✓ On your watchlist":"+ Add to watchlist";wb.classList.toggle("ghost",on)};
  wb.hidden=false;paint();wb.addEventListener("click",()=>{const l=loadL(),on=l.includes(id);
    try{localStorage.setItem("amend.watch",JSON.stringify(on?l.filter(x=>x!==id):[...l,id]))}catch(e){}paint();side()})}
const sb=document.getElementById("sharebtn");
if(sb){sb.hidden=false;sb.addEventListener("click",()=>{const u=location.href.split("#")[0];
  if(navigator.share)navigator.share({title:document.title,url:u}).catch(()=>{});
  else(navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(()=>sb.textContent="Copied",()=>prompt("Copy this link:",u))})}
addEventListener("keydown",e=>{if(e.key!=="/"||/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))return;
  const i=[document.getElementById("q"),document.getElementById("sq")].find(x=>x&&x.offsetParent);if(i){e.preventDefault();i.focus()}});
document.querySelectorAll(".seg a[data-f]").forEach(a=>a.addEventListener("click",ev=>{ev.preventDefault();const f=a.dataset.f;
  document.querySelectorAll(".seg a").forEach(x=>x.classList.toggle("on",x===a));
  document.querySelectorAll(".grp").forEach(g=>g.hidden=f!=="all"&&g.dataset.p!==f)}));
const open=()=>{const t=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));if(t&&t.tagName==="DETAILS")t.open=true};
addEventListener("hashchange",open);open();AM.tick();
// printing a briefing: show every airport on a list, not just the open ones
addEventListener("beforeprint",()=>document.querySelectorAll("details.apt").forEach(d=>d.open=true))})();
"""


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


def change_html(c):
    extra = []
    if c.get("chart", {}).get("amdt"):
        a = c["chart"]["amdt"]
        extra.append(f'<span class="ann fyi plain">{"Original" if a.upper() in ("0", "ORIG") else "Amdt " + e(a)}</span>')
    if c.get("chart", {}).get("pdf"):
        extra.append(f'<a href="{e(c["chart"]["pdf"])}" target="_blank" rel="noopener">View plate ↗</a>')
    more = ""
    if c.get("original"):
        more = f'<details class="more"><summary>FAA text</summary><pre>{e(c["original"])}</pre></details>'
    elif c.get("details"):
        more = ('<details class="more"><summary>Details</summary><pre>'
                + "\n".join(arrow(d) for d in c["details"]) + "</pre></details>")
    ids = (f' data-id="{e(c["id"])}"' if c.get("id") else "") + (f' data-c="{e(c["cycle"])}"' if c.get("cycle") else "")
    return (f'<div class="it p-{e(c["priority"])}"{ids}><span class="k">{e(cap(c["category"]))}</span>'
            f'<div class="s">{arrow(cap(c["summary"]))}{more}</div><div class="m">{"".join(extra)}</div></div>')


def grouped(changes, anchors=False):
    """one card per priority. anchors: give each an id and data-p so the filter tabs can find it."""
    out = []
    for p, _, title in PRIORITY:
        g = [c for c in changes if c["priority"] == p]
        if g:
            attrs = f' class="lst grp" id="{p}" data-p="{p}"' if anchors else ' class="lst"'
            out.append(f'<section{attrs}><div class="gh"><span><span class="dot d-{p}"></span>{title}</span>'
                       f'<span class="n">{len(g)}</span></div>' + "".join(change_html(c) for c in g) + "</section>")
    return "".join(out)


def legend(root):
    """key to the labels, linking to the guide. root is the relative path to the site root."""
    keys = "".join(f'<span><span class="ann {cls}">{lbl}</span>{TIERS[p][1]}</span>'
                   for p, lbl, _ in PRIORITY for cls in [TIERS[p][0]])
    return f'<div class="legend">{keys}<a href="{root}guide/">What do these mean?</a></div>'


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


def sidebar(root, active, meta=None, now=None, on=""):
    """desktop sidebar (and the phone top bar): search, pages, this browser's watchlist, the cycle."""
    link = lambda href, text, key: f'<a class="sbi{" on" if key == active else ""}" href="{root}{href}">{text}</a>'
    search = "" if active == "home" else (
        f'<form class="search" action="{root}" method="get" role="search"><input id="sq" name="q" '
        f'placeholder="Search airports" aria-label="Search airports" autocomplete="off"><kbd>/</kbd></form>')
    cyc = ""
    if meta:
        upcoming, _ = status(meta, now or dt.datetime.now(dt.timezone.utc))
        cur = meta["from_cycle"] if upcoming else meta["to_cycle"]
        cyc = (f'<div class="sbh">FAA cycle</div><div class="sbi"><span>{nice(cur, False)}</span>'
               f'<span class="ann ok">In effect</span></div>')
        if upcoming:
            cyc += (f'<div class="sbi"><span>{nice(meta["to_cycle"], False)}</span>'
                    f'<span class="ann ifr">Upcoming</span></div>')
    side = (f'<nav class="sb" aria-label="Site"><a class="brand" href="{root}"><i></i>Amend</a>{search}'
            f'<div class="sbh">Browse</div>{link("", "Airports", "home")}{link("list/", "Watchlist", "list")}'
            f'{link("guide/", "Guide", "guide")}{link("about/", "About", "about")}'
            f'<div id="sbw" data-on="{e(on)}"></div>{cyc}'
            f'<div class="sbfoot">Not for navigation. <a href="https://github.com/benjgmin/amend">Source</a></div></nav>')
    nav = lambda href, text, key: f'<a class="{"on" if key == active else ""}" href="{root}{href}">{text}</a>'
    top = (f'<header class="mtop"><a class="brand" href="{root}"><i></i>Amend</a><nav class="nav">'
           f'{nav("", "Search", "home")}{nav("guide/", "Guide", "guide")}{nav("about/", "About", "about")}</nav></header>')
    return side + top


def page(title, description, url, body, root, og_title=None, image=None, active="", meta=None, now=None,
         two=False, on=""):
    img = (f'<meta property="og:image" content="{e(image)}"><meta property="og:image:width" content="1200">'
           f'<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">'
           if image else '<meta name="twitter:card" content="summary">')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Amend">
<meta property="og:title" content="{e(og_title or title)}"><meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(url)}">{img}
<meta name="theme-color" content="#F6F7F9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0D1015" media="(prefers-color-scheme: dark)">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}"><link rel="stylesheet" href="{root}assets/style.css?v={CSS_VERSION}">
</head><body data-root="{root}" data-cyc="{e(meta['to_cycle'] if meta else '')}"><script>{SEEN_JS}</script><div class="app">{sidebar(root, active, meta, now, on)}
<main class="main{' two' if two else ''}">{body}
<p class="foot full">Not for navigation. Always use official FAA publications, NOTAMs and a proper preflight briefing.
Data: FAA NASR and d-TPP. <a href="https://github.com/benjgmin/amend">Source</a></p></main></div>
<script>{SHELL_JS}</script></body></html>"""


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


def status(meta, now):
    """(upcoming?, note) using the 0901Z changeover."""
    eff = effective(meta["to_cycle"])
    upcoming = bool(meta.get("upcoming")) and now < eff
    if upcoming:
        days = (eff.date() - now.date()).days
        when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
        return True, (f"These changes take effect {nice(meta['to_cycle'])} 0901Z ({when}). "
                      f"Until then, the current value applies: it's the one before the →.")
    return False, (f"In effect since {nice(meta['to_cycle'])} 0901Z, compared to the previous cycle "
                   f"({nice(meta['from_cycle'])}).")


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
    cycles = sorted(by_cycle, reverse=True)

    icao = f' <span class="icao">{e(info["icao"])}</span>' if info.get("icao") and info.get("icao") != apt else ""
    eyebrow = " · ".join(x for x in (loc, f"{'Upcoming ' if upcoming else ''}{nice(meta['to_cycle'])} cycle") if x)
    body = [f'<header class="full"><div class="eyebrow">{e(eyebrow)}</div><h1>{e(apt)}{icao}</h1>'
            + (f'<div class="aname">{e(name)}</div>' if name else "")
            + f'<div class="btns"><button class="btn" id="wbtn" data-apt="{e(apt)}" hidden>+ Add to watchlist</button>'
            '<button class="btn ghost" id="sharebtn" hidden>Share</button></div></header>']
    state = (f'<span class="ann {"ifr" if upcoming else "ok"}">{"Not in effect yet" if upcoming else "In effect"}</span>')
    if changes:
        seg = [f'<a class="on" href="#action" data-f="all">All<b>{len(changes)}</b></a>'] + \
              [f'<a href="#{p}" data-f="{p}">{title_}<b>{c[p]}</b></a>' for p, _, title_ in PRIORITY if c[p]]
        body.append(f'<div class="full toolbar"><nav class="seg" aria-label="Filter changes">{"".join(seg)}</nav></div>')
    col = ['<div class="card banner" id="newnote" hidden></div>']
    if changes:
        col.append(f'<div class="card banner">{state}<span>{e(note)}</span></div>')
        col.append(grouped(changes, anchors=True))
    else:
        col.append(f'<div class="card none"><b>{"No upcoming changes" if upcoming else "Nothing changed"} at {e(apt)}</b>'
                   f'{"On" if upcoming else "In the"} {nice(meta["to_cycle"])} {"· current data stays the same" if upcoming else "cycle"}</div>')
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

    rail = [f'<div class="card box"><h3>{"Upcoming cycle" if upcoming else "This cycle"}</h3>'
            f'<div class="kv"><span>Effective</span><span>{nice(meta["to_cycle"])} 0901Z</span></div>'
            f'<div class="kv"><span>Compared to</span><span>{nice(meta["from_cycle"])}</span></div>'
            f'<div class="kv"><span>{"Takes effect" if upcoming else "Next cycle"}</span>'
            f'<span>{countdown(next_changeover(meta, now)[0])}</span></div></div>']
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
                two=True, on=apt)


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
    when, _ = next_changeover(meta, now)
    nxt = {"to": meta["to_cycle"], "up": upcoming, "when": when.strftime("%Y-%m-%dT%H:%M:00Z")}
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
               + step("Set up", "<p>Search for your home field and tap <b>+</b> to add it to your watchlist, then add "
                      "the other airports you fly to. The list is saved in this browser, and you can share it as one "
                      "link with your flight school or club.</p>"
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
approach plates. Build a watchlist of your airports, or share one link for a whole training area.</p></header>
<div class="full"><label class="search"><span aria-hidden="true">⌕</span><input id="q" placeholder="Search by ID, ICAO, name or city" aria-label="Search airports" autocomplete="off"><kbd>/</kbd></label>
<div id="res" style="margin-top:10px"></div></div>
<div class="col"><div id="shared"></div><div id="next"></div><div id="watch"></div>
<div><div class="sec"><span class="hdr">Most action items this cycle</span><span class="note" style="margin:0">{n:,} airports {'change' if upcoming else 'changed'}</span></div>
<div class="cards">{top}</div></div></div>
<aside class="rail"><div class="card box"><h3>FAA cycle</h3><div class="big">{nice(meta['to_cycle'])}</div>
<div class="note" style="margin:2px 0 10px">{'Takes effect 0901Z' if upcoming else 'In effect since 0901Z'}</div>
<div class="kv"><span>Status</span><span class="ann {'ifr' if upcoming else 'ok'}">{'Upcoming' if upcoming else 'In effect'}</span></div>
<div class="kv"><span>Airports {'changing' if upcoming else 'changed'}</span><span>{n:,}</span></div>
<div class="kv"><span>Compared to</span><span>{nice(meta['from_cycle'])}</span></div>
<div class="kv"><span>{'Takes effect' if upcoming else 'Next cycle'}</span><span>{countdown(when)}</span></div>
<p class="note">{e(landing_note(meta, now, upcoming))}</p>
<p class="note"><a href="webcal://amend.watch/cycles.ics">Add cycle dates to your calendar</a> (<a href="cycles.ics">.ics</a>)</p></div>
<div class="card box"><h3>What the labels mean</h3>{legend("")}</div>
<div class="card box note" style="margin:0">An iPhone app with your saved airports and cycle alerts is on the way.</div></aside>
<script>{js}</script>"""
    return page("Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", SITE_URL, body, "", image=f"{SITE_URL}assets/card.png",
                active="home", meta=meta, now=now, two=True)


def watch_page(meta, directory, now):
    """site/list/: every change for a watchlist (from ?w= or this browser), fully expanded."""
    upcoming, _ = status(meta, now)
    names = {a["id"]: [a.get("icao", "") if a.get("icao") != a["id"] else "", a.get("name", "")] for a in directory}
    pri = [[p, t] for p, _, t in PRIORITY]
    js = COMMON_JS + WATCH_JS.replace("__META__", json.dumps(meta)).replace(
        "__NAMES__", json.dumps(names, separators=(",", ":"))).replace("__PRI__", json.dumps(pri))
    body = f"""<header class="full"><div class="eyebrow">Watchlist · {nice(meta['to_cycle'])} cycle</div><h1 id="title">Watchlist</h1>
<div class="aname" id="count"></div></header>
<div class="col" id="list"><div class="note">Loading…</div></div>
<aside class="rail"><div class="card box"><span class="ann {'ifr' if upcoming else 'ok'}">{'Not in effect yet' if upcoming else 'In effect'}</span>
<p class="note">{e(landing_note(meta, now, upcoming))}</p>
<div class="kv"><span>{'Takes effect' if upcoming else 'Next cycle'}</span><span>{countdown(next_changeover(meta, now)[0])}</span></div>
<div class="btns" id="actions"></div></div>
<div class="card box"><h3>What the labels mean</h3>{legend("../")}</div></aside><script>{js}</script>"""
    return page("Amend · watchlist", "Everything that changed at a list of airports this FAA cycle.",
                f"{SITE_URL}list/", body, "../", image=f"{SITE_URL}assets/card.png", active="list", meta=meta,
                now=now, two=True)


def named_watch_page(slug, wl, meta, info, latest, now, has_card):
    """static page for a named watchlist at /list/<slug>/ (amend.watch/list/clubsvfr): every change, expanded."""
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
        body = grouped(ch) if ch else '<div class="note">No changes in this cycle.</div>'
        blocks.append(f'<details class="apt" data-look="{e(a)}"{" open" if ch else ""}>{head}{body}{link}</details>')
    parts = [f"{lbl} {total[p]}" for p, lbl, _ in PRIORITY if total[p]]
    when = f"{'on' if upcoming else 'since'} {efb(meta['to_cycle'])[:6]}"
    desc = (f"{changed} of {len(apts)} airports change {when}" + (f" · {' · '.join(parts)}" if parts else "")
            if changed else f"No changes at these {len(apts)} airports {when}.")
    body = f"""<header class="full"><div class="eyebrow">Watchlist · {nice(meta['to_cycle'])} cycle</div><h1>{e(wl['name'])}</h1>
{f'<div class="aname">{e(wl["description"])}</div>' if wl["description"] else ''}
<div class="toolbar" style="margin-top:10px">{chips(total)}<span class="note" style="margin:0">{len(apts)} airports · {changed} with changes this cycle</span></div></header>
<div class="col">{''.join(blocks)}</div>
<aside class="rail"><div class="card box"><span class="ann {'ifr' if upcoming else 'ok'}">{'Not in effect yet' if upcoming else 'In effect'}</span>
<p class="note">{e(landing_note(meta, now, upcoming))}</p>
<div class="kv"><span>{'Takes effect' if upcoming else 'Next cycle'}</span><span>{countdown(next_changeover(meta, now)[0])}</span></div>
<div class="btns"><a class="btn" href="../?w={','.join(apts)}&n={e(quote(wl['name']))}">Add to my watchlist</a><a class="btn ghost" href="../../">Search all airports</a></div></div>
<div class="card box"><h3>What the labels mean</h3>{legend("../../")}</div></aside>"""
    image = f"{SITE_URL}list/{slug}/card.png" if has_card else f"{SITE_URL}assets/card.png"
    return page(f"{wl['name']} · Amend watchlist", desc, f"{SITE_URL}list/{slug}", body, "../../",
                f"{wl['name']}: {desc}", image, active="list", meta=meta, now=now, two=True)


def about_page(meta, latest, screenshots, now):
    shots = "".join(f'<img src="shots/{e(s)}" alt="Amend on iPhone" loading="lazy">' for s in screenshots)
    feat = lambda tag, cls, title, text: (f'<div class="card box"><span class="ann {cls}">{tag}</span>'
                                          f'<h3>{title}</h3><div class="note">{text}</div></div>')
    body = f"""<header class="full" style="padding:12px 0 4px"><h1 class="hero">Know what changed at your airport.</h1>
<p class="lede">Every 28 days the FAA changes tower hours, frequencies, runways, navaids and approach
plates. Amend compares every cycle for every US airport and tells you what matters, in plain English, up to three weeks
before it takes effect.</p>
<div class="btns"><a class="btn" href="../">Search an airport</a><a class="btn ghost" href="../VRB/">See an example</a></div></header>
{f'<div class="shots full">{shots}</div>' if shots else ''}
<div class="full"><h2 class="h2" style="margin-bottom:12px">What you get</h2><div class="feats">
{feat("ACT", "act", "Action items first", "Tower and Class D hours, frequencies, closed or renumbered runways, decommissioned navaids, new PPR rules: the changes that affect how you fly.")}
{feat("IFR", "ifr", "Instrument procedures", "Amended, new and removed approaches, STARs and departures, down to which waypoints moved, with the new plate one tap away.")}
{feat("FYI", "fyi", "Everything else, in plain English", "FAA remarks translated from contractions, with the original text always kept alongside.")}
{feat("Watchlists", "ifr", "Watchlists you can share", "Save your airports, name the list, and share one link for a whole training area, like amend.watch/list/daytona-training.")}
{feat("History", "fyi", "Two years of history", "Every change at every airport since August 2024, grouped by cycle.")}
{feat("iPhone", "ok", "iPhone app", "Keeps your home airport and watchlists on your phone and notifies you when a new cycle affects them. A TestFlight beta is coming soon.")}
</div></div>
<div class="full card box" style="max-width:760px"><h3>How it works</h3><p class="note">A daily job downloads the FAA's 28-day NASR data and d-TPP chart index, diffs every US airport, filters
the noise with tested rules, and publishes the results here. Remarks are translated with AI; everything else is plain,
deterministic code. It's open source on <a href="https://github.com/benjgmin/amend">GitHub</a>.</p></div>"""
    return page("About Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", f"{SITE_URL}about", body, "../",
                image=f"{SITE_URL}assets/card.png", active="about", meta=meta, now=now)


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
     "with AI using a fixed FAA glossary; unknown abbreviations are left as-is instead of guessed. Open "
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
    ("watchlists", "Watchlists",
     '<p>Search for an airport on the <a href="../">home page</a> and tap <b>+</b> to add it to your watchlist. '
     "It's saved in this browser (no account needed), with the airports that have action items first. "
     "<b>View all changes</b> shows every change at every airport on it in one page.</p>"
     '<p>Changes you haven\'t seen yet get a <span class="ann new">New</span> label, based on the last time you '
     "opened that airport or your watchlist in this browser. The home page shows what's coming up at your "
     "airports and counts down to the 0901Z changeover.</p>"
     "<p><b>Copy share link</b> gives you one link for the whole list, handy for a flight school or a training "
     "area. Anyone who opens it sees the same airports and can add them to their own list.</p>"),
    ("app", "iPhone app",
     "<p>The app adds a home airport and notifications when a new cycle changes your airports. A TestFlight beta is "
     "coming soon.</p>"),
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
    with open(os.path.join(site, "cycles.ics"), "w", newline="") as f:
        f.write(cycles_ics(meta, now))
    info = {a["id"]: a for a in directory}
    card(os.path.join(site, "assets", "card.png"), "amend.", "What changed at your airport",
         "", [("ACT", "action"), ("IFR", "ifr"), ("FYI", "fyi"), ("NO CHG", "ok")],
         "Every FAA cycle, in plain English.", f"Effective {nice(meta['to_cycle'])}")
    # one shared card for the ~10k airports with nothing changing this cycle (the title names the airport)
    upcoming_now, _ = status(meta, now)
    card(os.path.join(site, "assets", "nochange.png"), "No changes", "Nothing new at this airport", "",
         [("NO CHG", "ok")],
         f"{'Nothing changes on' if upcoming_now else 'Nothing changed in the'} {efb(meta['to_cycle'])} "
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
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(meta, directory, latest, ids, now))
    os.makedirs(os.path.join(site, "list"), exist_ok=True)
    with open(os.path.join(site, "list", "index.html"), "w", encoding="utf-8") as f:
        f.write(watch_page(meta, directory, now))
    # early share links were /watch/?w=...; forward them with the query intact
    redirect(os.path.join(site, "watch"), "../list/", "Watchlist", keep_query=True)
    shots = []
    about = os.path.join(site, "about")
    os.makedirs(os.path.join(about, "shots"), exist_ok=True)
    if screenshots_dir and os.path.isdir(screenshots_dir):
        import shutil
        for n in sorted(os.listdir(screenshots_dir)):
            if n.lower().endswith((".png", ".jpg", ".jpeg")):
                shutil.copy(os.path.join(screenshots_dir, n), os.path.join(about, "shots", n))
                shots.append(n)
    with open(os.path.join(about, "index.html"), "w", encoding="utf-8") as f:
        f.write(about_page(meta, latest, shots, now))
    os.makedirs(os.path.join(site, "guide"), exist_ok=True)
    with open(os.path.join(site, "guide", "index.html"), "w", encoding="utf-8") as f:
        f.write(guide_page(meta, now))
    for slug, wl in (watchlists or {}).items():
        # early links were /watch/<slug>/ and then /<slug>/; keep both working
        redirect(os.path.join(site, "watch", slug), f"../../list/{slug}/", wl["name"])
        redirect(os.path.join(site, slug), f"../list/{slug}/", wl["name"])
        folder = os.path.join(site, "list", slug)
        os.makedirs(folder, exist_ok=True)
        tot = {p: sum(counts(latest.get(a, []))[p] for a in wl["airports"]) for p, _, _ in PRIORITY}
        changed = sum(1 for a in wl["airports"] if latest.get(a))
        has_card = card(os.path.join(folder, "card.png"), wl["name"], "", "",
                        [(f"{lbl} {tot[p]}", p) for p, lbl, _ in PRIORITY if tot[p]] or [("NO CHG", "ok")],
                        f"{len(wl['airports'])} airports · {changed} with changes this cycle",
                        f"Effective {nice(meta['to_cycle'])}")
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(named_watch_page(slug, wl, meta, info, latest, now, has_card))
    return len(ids)