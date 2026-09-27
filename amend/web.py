"""
Static web view: one HTML page per airport at site/<ID>/index.html, plus a searchable landing
page at site/index.html. No JavaScript needed to read a page (the landing search uses a little),
and every page has Open Graph tags so a link in iMessage or a group chat shows a preview card.

Never writes to the JSON paths in SCHEMA.md (latest/, history/, airports.json).
"""
import datetime as dt
import html
from urllib.parse import quote
import json
import os
import re

SITE_URL = "https://amend.watch/"
RESERVED = {"latest", "history", "assets", "watch", "list", "about", "guide", "index.html", "airports.json"}  # never an airport page
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
.res a,.list a,.wrow>a{display:flex;justify-content:space-between;align-items:center;gap:10px;background:var(--panel);border-radius:6px;padding:9px 12px;margin:4px 0;color:var(--text)}
.res a:hover,.list a:hover,.wrow>a:hover{text-decoration:none;background:var(--hi)}
.rid{font:700 16px var(--mono);min-width:56px}.rname{flex:1;font-size:14px}.rsub{font:10px var(--mono);color:var(--dim)}
.big{font:700 26px var(--mono)}
.shots{display:flex;gap:12px;overflow-x:auto;padding:8px 0}.shots img{height:420px;border-radius:14px;border:1px solid var(--line)}
.wrow{display:flex;align-items:stretch;gap:6px}.wrow>a{flex:1}
.x{background:var(--panel);color:var(--cyan);border:1px solid var(--line);border-radius:6px;min-width:44px;margin:4px 0;font:700 18px var(--mono);cursor:pointer}
.x.on{color:var(--green)}.x:hover{background:var(--hi)}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
.btn.ghost{background:transparent;color:var(--cyan);border:1px solid rgba(61,214,255,.5)}
.btn{background:var(--cyan);color:var(--bg);border:0;border-radius:6px;padding:10px 14px;font:700 12px var(--mono);letter-spacing:1px;cursor:pointer}
.btn:hover{text-decoration:none;opacity:.9}
details.apt>summary .panel{margin-bottom:4px}
.ann[title]{cursor:help}
.nav{display:flex;gap:14px}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:13px;color:var(--dim);margin:10px 0 4px}
.legend>span{display:inline-flex;align-items:center;gap:6px}.legend a{font:700 11px var(--mono);margin-left:auto}
.tier{display:grid;grid-template-columns:76px 1fr;align-items:start;gap:4px 12px;margin:14px 0}.tier .ann{justify-self:start;margin-top:2px}
.tier .eg{grid-column:2;font:11px var(--mono)}.eg-act{color:var(--amber)}.eg-ifr{color:var(--cyan)}.eg-fyi{color:var(--dim)}
.guide p{font-size:15px;color:rgba(240,240,240,.85);margin:10px 0}.guide .panel{scroll-margin-top:12px}
.welcome{border-color:rgba(61,214,255,.35);padding:18px}.welcome h2{font:700 20px var(--mono);letter-spacing:2px;margin:0 0 10px}
.welcome p{margin:8px 0;color:rgba(240,240,240,.85)}.welcome .tier{margin:10px 0;font-size:14px}
.welcome .wfoot{display:flex;align-items:center;justify-content:space-between;margin-top:14px}
.welcome .wfoot .btns{margin:0}
.dots{display:flex;gap:6px}.dots i{width:8px;height:6px;border-radius:3px;background:var(--faint);transition:width .15s}
.dots i.on{width:22px;background:var(--cyan)}
"""


FONT_PATHS = {  # first one that exists wins (GitHub's Ubuntu runners have DejaVu; Macs have Menlo)
    "mono": ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", "/System/Library/Fonts/Menlo.ttc"],
    "sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"],
    "reg": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Helvetica.ttc"],
}
COLORS = {"bg": (9, 12, 16), "panel": (19, 24, 31), "text": (240, 240, 240), "dim": (143, 143, 143),
          "faint": (92, 92, 92), "action": (255, 181, 0), "ifr": (61, 214, 255), "fyi": (143, 143, 143),
          "ok": (77, 224, 115)}


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
    """1200x630 link-preview image in the app's EFB style. returns False if Pillow is missing."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    W, H, P = 1200, 630, 64
    img = Image.new("RGB", (W, H), COLORS["bg"])
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([P - 24, P - 24, W - P + 24, H - P + 24], radius=18, fill=COLORS["panel"],
                        outline=(40, 46, 55), width=2)
    brand = _font("mono", 34)
    d.text((P, P), "AMEND", font=brand, fill=COLORS["text"])
    d.text((P + d.textlength("AMEND", font=brand), P), ".", font=brand, fill=COLORS["ifr"])
    small = _font("mono", 26)
    d.text((W - P - d.textlength(footer, font=small), P + 6), footer, font=small, fill=COLORS["dim"])
    size = 132
    while size > 48 and d.textlength(big, font=_font("mono", size)) > W - 2 * P:
        size -= 8
    d.text((P, P + 80 + (132 - size) // 2), big, font=_font("mono", size), fill=COLORS["text"])
    y = P + 250
    if name:
        d.text((P, y), _fit(d, name, _font("sans", 48), W - 2 * P), font=_font("sans", 48), fill=COLORS["text"])
        y += 62
    if loc:
        d.text((P, y), loc.upper(), font=small, fill=COLORS["dim"])
        y += 50
    x, cf = P, _font("mono", 34)
    for text, key in chip_list:
        tw = d.textlength(text, font=cf)
        col = COLORS[key]
        d.rounded_rectangle([x, y, x + tw + 28, y + 52], radius=6, outline=col, width=3,
                            fill=tuple(int(c * 0.15 + COLORS["panel"][i] * 0.85) for i, c in enumerate(col)))
        d.text((x + 14, y + 7), text, font=cf, fill=col)
        x += tw + 44
    if line:
        d.text((P, y + 78), _fit(d, line, _font("reg", 32), W - 2 * P), font=_font("reg", 32),
               fill=COLORS["dim"])
    img.save(path, optimize=True)
    return True


COMMON_JS = 'const TIP=' + json.dumps({**{v[0]: v[2] for v in TIERS.values()}, "ok": NO_CHG_TIP}) + ';\n' + \
    'const KEY="amend.watch";\nconst esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;"}[c]));\nconst loadW=()=>{try{return JSON.parse(localStorage.getItem(KEY)||"[]")}catch(e){return[]}};\nconst saveW=l=>{try{localStorage.setItem(KEY,JSON.stringify([...new Set(l)]))}catch(e){}};\nconst parseW=q=>[...new Set((q||"").toUpperCase().split(/[\\s,]+/).map(s=>s.replace(/^K(?=[A-Z]{3}$)/,"")).filter(s=>/^[A-Z0-9]{2,4}$/.test(s)))].slice(0,200);\nfunction chipsHtml(k){if(!k||!(k[0]||k[1]||k[2]))return \'<span class="chips"><span class="ann ok" title="\'+TIP.ok+\'">NO CHG</span></span>\';\n  const t=[[k[0],"act","ACT"],[k[1],"ifr","IFR"],[k[2],"fyi","FYI"]].filter(x=>x[0]).map(x=>\'<span class="ann \'+x[1]+\'" title="\'+TIP[x[1]]+\'">\'+x[2]+\' \'+x[0]+\'</span>\');\n  return \'<span class="chips">\'+t.join("")+\'</span>\'}\n'
LANDING_JS = 'if(new URLSearchParams(location.search).get("w")){location.replace("list/"+location.search)}\nconst A=__ROWS__;const byId=new Map(A.map(a=>[a[0],a]));\nconst NKEY="amend.watch.name";\nconst q=document.getElementById("q"),r=document.getElementById("res");\nconst params=new URLSearchParams(location.search);\nconst loadName=()=>{try{return localStorage.getItem(NKEY)||""}catch(e){return""}};\nconst saveName=n=>{try{n?localStorage.setItem(NKEY,n):localStorage.removeItem(NKEY)}catch(e){}};\nfunction sub(a){return esc([a[1],[a[3],a[4]].filter(Boolean).join(", ")].filter(Boolean).join(" · ")).toUpperCase()}\nfunction airportRow(id,btn){const a=byId.get(id)||[id,"","","","",0,null];\n  const inner=\'<span class="rid">\'+esc(a[0])+\'</span><span class="rname">\'+esc(a[2]||"Unknown airport")+\'<br><span class="rsub">\'+sub(a)+\'</span></span>\'+chipsHtml(a[6]);\n  return \'<div class="wrow">\'+(a[5]?\'<a href="\'+esc(a[0])+\'/">\'+inner+\'</a>\':\'<a>\'+inner+\'</a>\')+btn+\'</div>\'}\nconst act=id=>((byId.get(id)||[])[6]||[0])[0];\nconst sameSet=(x,y)=>x.length===y.length&&x.every(v=>y.includes(v));\nfunction shareUrl(){const n=loadName();return new URL("list/?w="+loadW().join(",")+(n?"&n="+encodeURIComponent(n):""),location.href).href}\nfunction clearShared(){history.replaceState(null,"",location.pathname);render()}\nfunction renderShared(){const s=document.getElementById("shared"),ids=parseW(params.get("w")),name=(params.get("n")||"").slice(0,60);\n  if(!ids.length||!location.search.includes("w=")){s.innerHTML="";return false}\n  if(sameSet(ids,loadW())){s.innerHTML="";return true}   // it\'s your own list: show it once, below\n  s.innerHTML=\'<div class="sec"><span class="hdr" style="color:var(--cyan)">Shared\'+(name?\': \'+esc(name):\' watchlist\')+\' · \'+ids.length+\'</span></div>\'+\n    [...ids].sort((x,y)=>act(y)-act(x)).map(id=>airportRow(id,"")).join("")+\n    \'<div class="btns"><a class="btn" href="list/?w=\'+ids.join(",")+(name?"&n="+encodeURIComponent(name):"")+\'">VIEW ALL CHANGES</a>\'+\n    \'<button class="btn" id="saveShared" data-ids="\'+ids.join(",")+\'" data-name="\'+esc(name)+\'">ADD TO MY WATCHLIST</button>\'+\n    \'<button class="btn ghost" id="closeShared">CLOSE</button></div>\';return false}\nfunction renderWatch(isMine){const l=loadW(),w=document.getElementById("watch"),n=loadName();\n  if(!l.length){w.innerHTML=\'<div class="sec"><span class="hdr">Your watchlist</span></div><div class="note">Tap <b>+</b> on airports in the search below to build your list. It’s saved in this browser; copy the link to send it to someone.</div>\';return}\n  w.innerHTML=\'<div class="sec"><span class="hdr">\'+(n?esc(n):\'Your watchlist\')+\' · \'+l.length+(isMine?\' · this link\':\'\')+\'</span></div>\'+\n    [...l].sort((x,y)=>act(y)-act(x)).map(id=>airportRow(id,\'<button class="x" data-rm="\'+esc(id)+\'" title="Remove">×</button>\')).join("")+\n    \'<div class="btns"><a class="btn" href="list/?w=\'+l.join(",")+(n?"&n="+encodeURIComponent(n):"")+\'">VIEW ALL CHANGES</a>\'+\n    \'<button class="btn" id="share">COPY SHARE LINK</button><button class="btn ghost" id="rename">\'+(n?\'RENAME\':\'NAME THIS LIST\')+\'</button></div>\'}\nfunction renderSearch(){const s=q.value.trim().toUpperCase();if(!s){r.innerHTML="";return}\n  const hit=[];for(const a of A){const[id,ic,n,c]=a;let k=-1;\n    if(id===s||ic===s)k=0;else if(id.startsWith(s)||ic.startsWith(s))k=1;\n    else if(s.length>2&&n.toUpperCase().startsWith(s))k=2;\n    else if(s.length>2&&(n.toUpperCase().includes(s)||c.toUpperCase().includes(s)))k=3;\n    if(k>=0)hit.push([k*10+(ic?0:2),a])}\n  hit.sort((x,y)=>x[0]-y[0]||x[1][0].length-y[1][0].length||(x[1][0]<y[1][0]?-1:1));\n  const w=new Set(loadW());\n  r.innerHTML=hit.slice(0,30).map(([_,a])=>airportRow(a[0],w.has(a[0])?\'<button class="x on" data-rm="\'+esc(a[0])+\'" title="Remove from watchlist">✓</button>\':\'<button class="x" data-add="\'+esc(a[0])+\'" title="Add to watchlist">+</button>\')).join("")||\'<div class="note">No airport found.</div>\'}\nfunction render(){renderWatch(false);renderSearch()}\ndocument.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;\n  if(b.dataset.add){saveW([...loadW(),b.dataset.add])}\n  else if(b.dataset.rm){saveW(loadW().filter(x=>x!==b.dataset.rm))}\n  else if(b.id==="saveShared"){saveW([...loadW(),...b.dataset.ids.split(",")]);if(!loadName()&&b.dataset.name)saveName(b.dataset.name);clearShared();return}\n  else if(b.id==="closeShared"){clearShared();return}\n  else if(b.id==="rename"){const n=prompt("Name this watchlist (shows on shared links):",loadName());if(n===null)return;saveName(n.trim().slice(0,60))}\n  else if(b.id==="share"){const u=shareUrl();\n    (navigator.clipboard?navigator.clipboard.writeText(u):Promise.reject()).then(()=>b.textContent="COPIED",()=>prompt("Copy this link:",u));return}\n  render()});\nq.addEventListener("input",renderSearch);render();\n'
WELCOME_JS = r"""(()=>{const W=document.getElementById("welcome"),K="amend.watch.welcomed",P=new URLSearchParams(location.search);
let seen=false;try{seen=!!localStorage.getItem(K)}catch(e){}
if(P.has("w")||(seen&&!P.has("welcome")))return;
const steps=[...W.querySelectorAll(".step")],dots=[...W.querySelectorAll(".dots i")],intro=document.getElementById("intro");let i=0;
const show=()=>{steps.forEach((s,j)=>s.hidden=j!==i);dots.forEach((d,j)=>d.classList.toggle("on",j===i));
  document.getElementById("wnext").textContent=i<steps.length-1?"NEXT":"GET STARTED";document.getElementById("wskip").hidden=i===steps.length-1};
const done=()=>{try{localStorage.setItem(K,"1")}catch(e){}W.hidden=true;intro.hidden=false;
  if(P.has("welcome"))history.replaceState(null,"",location.pathname)};
W.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;ev.stopPropagation();
  if(b.id==="wskip")done();else if(b.id==="wnext"){if(i<steps.length-1){i++;show()}else{done();q.scrollIntoView({block:"center"});q.focus()}}});
W.hidden=false;intro.hidden=true;show()})();
"""
WATCH_JS = 'const META=__META__,NAMES=__NAMES__,SEL=__PRI__;\nconst P=new URLSearchParams(location.search),shared=parseW(P.get("w"));\nconst ids=shared.length?shared:loadW();\nconst NKEY="amend.watch.name",myName=(()=>{try{return localStorage.getItem(NKEY)||""}catch(e){return""}})();\nconst listName=((shared.length?P.get("n"):myName)||"").slice(0,60);\nconst isMine=!shared.length||(shared.length===loadW().length&&shared.every(x=>loadW().includes(x)));\nconst out=document.getElementById("list");\nfunction changeHtml(c){const s=esc(c.summary.charAt(0).toUpperCase()+c.summary.slice(1)).replace(/ -&gt; /g," → ");\n  let meta=esc(c.category);const ch=c.chart||{};\n  if(ch.amdt)meta+=\' <span class="ann fyi">\'+(["0","ORIG"].includes(ch.amdt.toUpperCase())?"ORIG":"AMDT "+esc(ch.amdt))+\'</span>\';\n  if(ch.pdf)meta+=\' <a href="\'+esc(ch.pdf)+\'" target="_blank" rel="noopener">VIEW PLATE ›</a>\';\n  let more="";if(c.original)more=\'<details class="more"><summary>FAA TEXT ▸</summary><pre>\'+esc(c.original)+\'</pre></details>\';\n  else if(c.details&&c.details.length)more=\'<details class="more"><summary>DETAILS ▸</summary><pre class="d">\'+c.details.map(d=>esc(d).replace(/ -&gt; /g," → ")).join("\\n")+\'</pre></details>\';\n  return \'<div class="change p-\'+esc(c.priority)+\'"><div class="summary">\'+s+\'</div><div class="meta">\'+meta+\'</div>\'+more+\'</div>\'}\nasync function load(id){try{const r=await fetch("../latest/"+id+".json");return r.ok?await r.json():null}catch(e){return null}}\n(async()=>{\n  if(!ids.length){out.innerHTML=\'<div class="note">Your watchlist is empty. Add airports on the <a href="../">search page</a>.</div>\';return}\n  document.getElementById("count").textContent=ids.length+" airport"+(ids.length==1?"":"s");\n  document.getElementById("title").textContent=listName||(isMine?"Your watchlist":"Shared watchlist");\n  if(listName)document.title=listName+" · Amend watchlist";\n  const link=new URL("?w="+ids.join(",")+(listName?"&n="+encodeURIComponent(listName):""),location.href).href;\n  document.getElementById("actions").innerHTML=(isMine?\'\':\'<button class="btn" id="add">ADD TO MY WATCHLIST</button>\')+\n    \'<button class="btn" id="copy">COPY LINK</button><a class="btn ghost" href="../">SEARCH ALL AIRPORTS</a>\';\n  document.addEventListener("click",ev=>{const b=ev.target.closest("button");if(!b)return;\n    if(b.id==="add"){const l=[...new Set([...loadW(),...ids])];try{localStorage.setItem(KEY,JSON.stringify(l));\n      if(!myName&&listName)localStorage.setItem(NKEY,listName)}catch(e){}b.textContent="ADDED";b.disabled=true}\n    if(b.id==="copy"){(navigator.clipboard?navigator.clipboard.writeText(link):Promise.reject()).then(()=>b.textContent="COPIED",()=>prompt("Copy this link:",link))}});\n  const data=await Promise.all(ids.map(load));\n  const items=ids.map((id,i)=>({id,d:data[i]})).sort((a,b)=>((b.d&&b.d.counts.action)||0)-((a.d&&a.d.counts.action)||0));\n  out.innerHTML=items.map(({id,d})=>{const n=NAMES[id]||[];const k=d?[d.counts.action,d.counts.ifr,d.counts.fyi]:null;\n    const body=d?SEL.map(([p,t,col])=>{const g=d.changes.filter(c=>c.priority===p);return g.length?\'<div class="sec"><span class="hdr" style="color:\'+col+\'">\'+t+\' \'+g.length+\'</span></div>\'+g.map(changeHtml).join(""):""}).join("")\n             :\'<div class="note">No changes in this cycle.</div>\';\n    return \'<details class="apt" \'+(d?"open":"")+\'><summary><div class="panel"><div class="row"><h1 style="font-size:24px">\'+esc(id)+\'<span class="icao">\'+esc(n[0]||"")+\'</span></h1>\'+chipsHtml(k)+\'</div><div class="name" style="font-size:15px">\'+esc(n[1]||"")+\'</div></div></summary>\'+body+\'<p class="foot"><a href="../\'+esc(id)+\'/">Full page and history ›</a></p></details>\'}).join("");\n})();\n'


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
    out = [f'<span class="ann {TIERS[p][0]}" title="{e(TIERS[p][2])}">{lbl} {c[p]}</span>'
           for p, lbl, _ in PRIORITY if c.get(p)]
    if not out and no_change:
        out = [f'<span class="ann ok" title="{NO_CHG_TIP}">NO CHG</span>']
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


def legend(root):
    """one-line key to the labels, linking to the guide. root is the relative path to the site root."""
    keys = "".join(f'<span><span class="ann {cls}">{lbl}</span>{TIERS[p][1]}</span>'
                   for p, lbl, _ in PRIORITY for cls in [TIERS[p][0]])
    return f'<div class="legend">{keys}<a href="{root}guide/">WHAT DO THESE MEAN? ›</a></div>'


def tier_rows(full):
    """ACT / IFR / FYI / NO CHG with what each means; the guide's version adds an example."""
    rows = []
    for p, lbl, _ in PRIORITY:
        cls, _, short, long_, eg = TIERS[p]
        rows.append(f'<div class="tier"><span class="ann {cls}">{lbl}</span><span>{e(long_ if full else short)}</span>'
                    + (f'<span class="eg eg-{cls}">e.g. {e(eg)}</span>' if full else "") + '</div>')
    no_chg = NO_CHG_TIP if full else "Nothing changed there this cycle"
    rows.append(f'<div class="tier"><span class="ann ok">NO CHG</span><span>{no_chg}.</span></div>')
    return "".join(rows)


def page(title, description, url, body, css_href, og_title=None, image=None):
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


def airport_page(apt, info, latest, hist, meta, now, has_card=False):
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

    body = [f'<div class="top"><a class="brand" href="../">AMEND.</a><span class="hdr">{label} · EFF {efb(meta["to_cycle"])}</span></div>',
            '<div class="panel"><div class="row"><h1>', e(apt),
            f'<span class="icao">{e(info["icao"])}</span>' if info.get("icao") and info.get("icao") != apt else "",
            f'</h1>{chips(c)}</div>',
            f'<div class="name">{e(name)}</div>' if name else "",
            f'<div class="loc">{e(loc)}</div>' if loc else "", "</div>"]
    if changes or (hist and hist.get("entries")):
        body.append(legend("../"))
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
    image = (f"{SITE_URL}{apt}/card.png" if has_card
             else f"{SITE_URL}assets/nochange.png" if not changes else f"{SITE_URL}assets/card.png")
    return page(title, desc, f"{SITE_URL}{apt}/", "".join(body), "../assets/style.css", og_title, image)


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
    lc = {a: counts(ch) for a, ch in latest.items()}
    rows = [[a["id"], a.get("icao", ""), a.get("name", ""), a.get("city", ""), a.get("state", ""),
             1 if a["id"] in pages else 0,
             [lc[a["id"]]["action"], lc[a["id"]]["ifr"], lc[a["id"]]["fyi"]] if a["id"] in lc else None]
            for a in directory]
    js = COMMON_JS + LANDING_JS.replace("__ROWS__", json.dumps(rows, separators=(",", ":"))) + WELCOME_JS
    step = lambda title, inner: f'<div class="step" hidden><h2>{title}</h2>{inner}</div>'
    WELCOME = ('<div class="panel welcome" id="welcome" hidden>'
               + step("AMEND.", "<p>Every 28 days the FAA publishes a new cycle of airport, airspace and chart data. "
                      "Tower hours move, runways get renumbered, approaches get amended, and it's easy to miss.</p>"
                      "<p>Amend compares each cycle to the last one and tells you what changed at your airports, in "
                      "plain English, up to three weeks before it takes effect.</p>")
               + step("HOW TO READ IT", tier_rows(False) + "<p>Remarks are the FAA's free-text airport notes. "
                      "They're translated to plain English, and the original FAA text is always one tap away.</p>"
                      '<p><a href="guide/">Read the full guide ›</a></p>')
               + step("SET UP", "<p>Search for your home field and tap <b>+</b> to add it to your watchlist, then add "
                      "the other airports you fly to. The list is saved in this browser, and you can share it as one "
                      "link with your flight school or club.</p>"
                      '<p class="foot" style="margin-top:12px">Not for navigation. Always use official FAA publications, '
                      "NOTAMs and a proper preflight briefing.</p>")
               + '<div class="wfoot"><span class="dots"><i></i><i></i><i></i></span><span class="btns">'
               '<button class="btn ghost" id="wskip">SKIP</button><button class="btn" id="wnext">NEXT</button>'
               '</span></div></div>')
    body = f"""<div class="top"><span class="brand">AMEND.</span><span class="nav"><a class="hdr" href="guide/">Guide</a><a class="hdr" href="about/">About</a></span></div>
{WELCOME}
<div class="panel"><div class="row"><span class="hdr">NASR cycle</span>
<span class="ann {'ifr' if upcoming else 'ok'}">{'UPCOMING' if upcoming else 'IN EFFECT'}</span></div>
<div class="hdr" style="margin-top:8px">{'Next cycle takes effect 0901Z' if upcoming else 'Current cycle in effect'}</div>
<div class="big">{efb(meta['to_cycle'])}</div>
<div class="note">{meta.get('changed_airports', len(latest))} airports {'change' if upcoming else 'changed'} in this cycle. {e(landing_note(meta, now, upcoming))}</div></div>
<p id="intro">Every 28 days the FAA publishes new airport, airspace and chart data. Amend compares each cycle to the last
and shows what changed at every US airport in plain English: tower hours, frequencies, runways, navaids,
approach plates. Build a watchlist of your airports, or share one link for a whole training area.</p>
<div id="shared"></div><div id="watch"></div>
<div class="sec"><span class="hdr">Search</span></div>
<input id="q" placeholder="ID, ICAO, NAME OR CITY" autocomplete="off">
<div class="res" id="res"></div>
<div class="sec"><span class="hdr">Most action items this cycle</span></div>{legend("")}<div class="list">{top}</div>
<p class="note">An iPhone app with your saved airports and cycle alerts is on the way.</p>
<script>{js}</script>"""
    return page("Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", SITE_URL, body, "assets/style.css",
                image=f"{SITE_URL}assets/card.png")


def watch_page(meta, directory, now):
    """site/list/: every change for a watchlist (from ?w= or this browser), fully expanded."""
    upcoming, _ = status(meta, now)
    names = {a["id"]: [a.get("icao", "") if a.get("icao") != a["id"] else "", a.get("name", "")] for a in directory}
    pri = [["action", "Action", "var(--amber)"], ["ifr", "IFR procedures", "var(--cyan)"], ["fyi", "FYI", "var(--dim)"]]
    js = COMMON_JS + WATCH_JS.replace("__META__", json.dumps(meta)).replace(
        "__NAMES__", json.dumps(names, separators=(",", ":"))).replace("__PRI__", json.dumps(pri))
    body = f"""<div class="top"><a class="brand" href="../">AMEND.</a><span class="hdr">Watchlist · EFF {efb(meta['to_cycle'])}</span></div>
<div class="panel"><div class="big" id="title">Watchlist</div><div class="loc" id="count"></div>
<div class="note">{e(landing_note(meta, now, upcoming))}</div></div>
<div class="btns" id="actions"></div>{legend("../")}
<div id="list"><div class="note">Loading…</div></div><script>{js}</script>"""
    return page("Amend · watchlist", "Everything that changed at a list of airports this FAA cycle.",
                f"{SITE_URL}list/", body, "../assets/style.css", image=f"{SITE_URL}assets/card.png")


def named_watch_page(slug, wl, meta, info, latest, now, has_card):
    """static page for a named watchlist at /list/<slug>/ (amend.watch/list/erausvfr): every change, expanded."""
    upcoming, _ = status(meta, now)
    apts = sorted(wl["airports"], key=lambda a: (-counts(latest.get(a, []))["action"], -len(latest.get(a, [])), a))
    total = {p: sum(counts(latest.get(a, []))[p] for a in apts) for p, _, _ in PRIORITY}
    changed = sum(1 for a in apts if latest.get(a))
    blocks = []
    for a in apts:
        i, ch = info.get(a, {}), latest.get(a, [])
        icao = f'<span class="icao">{e(i["icao"])}</span>' if i.get("icao") and i.get("icao") != a else ""
        head = (f'<div class="panel"><div class="row"><h1 style="font-size:24px">{e(a)}{icao}</h1>{chips(counts(ch))}</div>'
                f'<div class="name" style="font-size:15px">{e(i.get("name", "Unknown airport"))}</div></div>')
        link = f'<p class="foot"><a href="../../{e(a)}/">Full page and history ›</a></p>'
        body = grouped(ch) if ch else '<div class="note">No changes in this cycle.</div>'
        blocks.append(f'<details class="apt"{" open" if ch else ""}><summary>{head}</summary>{body}{link}</details>')
    parts = [f"{lbl} {total[p]}" for p, lbl, _ in PRIORITY if total[p]]
    when = f"{'on' if upcoming else 'since'} {efb(meta['to_cycle'])[:6]}"
    desc = (f"{changed} of {len(apts)} airports change {when}" + (f" · {' · '.join(parts)}" if parts else "")
            if changed else f"No changes at these {len(apts)} airports {when}.")
    body = f"""<div class="top"><a class="brand" href="../../">AMEND.</a><span class="hdr">Watchlist · EFF {efb(meta['to_cycle'])}</span></div>
<div class="panel"><div class="row"><span class="big">{e(wl['name'])}</span>{chips(total)}</div>
{f'<div class="note">{e(wl["description"])}</div>' if wl["description"] else ''}
<div class="loc">{len(apts)} airports · {changed} with changes this cycle</div></div>
<div class="panel"><span class="ann {'ifr' if upcoming else 'ok'}">{'NOT IN EFFECT YET' if upcoming else 'IN EFFECT'}</span>
<div class="note">{e(landing_note(meta, now, upcoming))}</div></div>
<div class="btns"><a class="btn" href="../?w={','.join(apts)}&n={e(quote(wl['name']))}">ADD TO MY WATCHLIST</a><a class="btn ghost" href="../../">SEARCH ALL AIRPORTS</a></div>
{legend("../../")}{''.join(blocks)}"""
    image = f"{SITE_URL}list/{slug}/card.png" if has_card else f"{SITE_URL}assets/card.png"
    return page(f"{wl['name']} · Amend watchlist", desc, f"{SITE_URL}list/{slug}", body, "../../assets/style.css",
                f"{wl['name']}: {desc}", image)


ABOUT_AUTHOR = "Built by Ben Eccles, a student pilot at Embry-Riddle."


def about_page(meta, latest, screenshots, now):
    upcoming, _ = status(meta, now)
    shots = "".join(f'<img src="shots/{e(s)}" alt="Amend on iPhone" loading="lazy">' for s in screenshots)
    feat = lambda tag, cls, title, text: (f'<div class="panel"><span class="ann {cls}">{tag}</span>'
                                          f'<div class="name" style="font-size:17px;margin-top:8px">{title}</div>'
                                          f'<div class="note">{text}</div></div>')
    body = f"""<div class="top"><a class="brand" href="../">AMEND.</a><span class="nav"><a class="hdr" href="../guide/">Guide</a><a class="hdr" href="../">Search ›</a></span></div>
<div style="padding:28px 0 8px"><div class="big" style="font-size:40px;line-height:1.1">Know what changed at your airport.</div>
<p class="note" style="font-size:17px">Every 28 days the FAA changes tower hours, frequencies, runways, navaids and approach
plates. Amend compares every cycle for every US airport and tells you what matters, in plain English, up to three weeks
before it takes effect.</p>
<div class="btns"><a class="btn" href="../">SEARCH AN AIRPORT</a><a class="btn ghost" href="../VRB/">SEE AN EXAMPLE</a></div></div>
{f'<div class="shots">{shots}</div>' if shots else ''}
<div class="sec"><span class="hdr">Why</span></div>
<p>It started with a quiz question marked wrong. The course material said Vero Beach's tower closed at 2100. It had
changed twice: to 2300 in January 2025, then to 0100 in July. Nobody caught it, because nothing tells you what changed
from one cycle to the next. So I built something that does.</p>
<div class="sec"><span class="hdr">What you get</span></div>
{feat("ACT", "act", "Action items first", "Tower and Class D hours, frequencies, closed or renumbered runways, decommissioned navaids, new PPR rules: the changes that affect how you fly.")}
{feat("IFR", "ifr", "Instrument procedures", "Amended, new and removed approaches, STARs and departures, down to which waypoints moved, with the new plate one tap away.")}
{feat("FYI", "fyi", "Everything else, in plain English", "FAA remarks translated from contractions, with the original text always kept alongside.")}
{feat("WATCH", "ifr", "Watchlists you can share", "Save your airports, name the list, and share one link for a whole training area, like amend.watch/list/daytona-training.")}
{feat("HISTORY", "fyi", "Two years of history", "Every change at every airport since August 2024, grouped by cycle.")}
<div class="sec"><span class="hdr">iPhone app</span></div>
<p>The app keeps your home airport and watchlists on your phone and notifies you when a new cycle affects them.
A TestFlight beta is coming soon.</p>
<div class="sec"><span class="hdr">How it works</span></div>
<p class="note">A daily job downloads the FAA's 28-day NASR data and d-TPP chart index, diffs every US airport, filters
the noise with tested rules, and publishes the results here. Remarks are translated with AI; everything else is plain,
deterministic code. It's open source on <a href="https://github.com/benjgmin/amend">GitHub</a>.</p>
<p class="note">{e(ABOUT_AUTHOR)}</p>"""
    return page("About Amend · what changed at your airport", "See what changed at any US airport each FAA cycle, "
                "in plain English, before it takes effect.", f"{SITE_URL}about", body, "../assets/style.css",
                image=f"{SITE_URL}assets/card.png")


GUIDE_SECTIONS = [
    ("reading", "Reading a change",
     "<p>Changes read old → new. <b>Tower hours: 0700-2100 → 0700-0100 local</b> means it was 0700-2100 and "
     "becomes 0700-0100.</p>"
     "<p><b>FAA TEXT ▸</b> opens the original remark the FAA published. <b>DETAILS ▸</b> shows every field that "
     "changed. <b>VIEW PLATE ›</b> opens the new approach or procedure chart, and the "
     '<span class="ann fyi">AMDT 3</span> chip is its amendment number (<span class="ann fyi">ORIG</span> means '
     "a brand new procedure).</p>"),
    ("remarks", "Remarks",
     "<p>Remarks are the free-text notes in the FAA Chart Supplement (the old A/FD) for an airport: things like PPR "
     "requirements, runway restrictions, wildlife, noise abatement, when services aren't available.</p>"
     "<p>The FAA writes them in contractions (RSCD NOT MNT 2300-0600 M-F). Amend translates them to plain English "
     "with AI using a fixed FAA glossary; unknown abbreviations are left as-is instead of guessed. Open "
     "<b>FAA TEXT ▸</b> on any remark to see the original, and trust the original if they ever disagree.</p>"),
    ("cycles", "Cycles",
     "<p>The FAA publishes airport and airspace data every 28 days (NASR) and instrument charts on the same schedule "
     "(d-TPP). Each cycle has an effective date and switches over at 0901Z that day.</p>"
     '<div class="tier"><span class="ann ifr">UPCOMING</span><span>The next cycle is already published but not in '
     "effect yet, so you can see changes before they happen. Until then the value before the → is the one that "
     "applies. Great time to check your airports.</span></div>"
     '<div class="tier"><span class="ann ok">IN EFFECT</span><span>The newest cycle is active. Shows what changed '
     "compared to the one before it.</span></div>"
     "<p>History goes back to Aug 2024 for airport data. Chart history starts in fall 2026 because the FAA doesn't "
     "keep old chart indexes online.</p>"),
    ("watchlists", "Watchlists",
     '<p>Search for an airport on the <a href="../">home page</a> and tap <b>+</b> to add it to your watchlist. '
     "It's saved in this browser (no account needed), with the airports that have action items first. "
     "<b>VIEW ALL CHANGES</b> shows every change at every airport on it in one page.</p>"
     "<p><b>COPY SHARE LINK</b> gives you one link for the whole list, handy for a flight school or a training "
     "area. Anyone who opens it sees the same airports and can add them to their own list.</p>"),
    ("app", "iPhone app",
     "<p>The app adds a home airport and notifications when a new cycle changes your airports. A TestFlight beta is "
     "coming soon.</p>"),
]


def guide_page():
    """site/guide/: what the labels, remarks and cycles mean. The web copy of the iOS GuideView."""
    sec = lambda id_, title, inner: f'<div class="panel" id="{id_}"><div class="hdr">{title}</div>{inner}</div>'
    priority = sec("priority", "Priority", tier_rows(True) + "<p>Changes are listed ACT first, then IFR, then FYI, "
                   "so the ones that matter are always at the top.</p>")
    body = f"""<div class="top"><a class="brand" href="../">AMEND.</a><span class="nav"><a class="hdr" href="../about/">About</a><a class="hdr" href="../">Search ›</a></span></div>
<div class="guide"><div class="big" style="padding:12px 0 4px">Guide</div>
<p>How to read Amend: what the labels mean, where remarks come from, and how FAA cycles work.</p>
{priority}{"".join(sec(*x) for x in GUIDE_SECTIONS)}
<p><a href="../?welcome">Show the welcome again ›</a></p></div>"""
    return page("Guide · Amend", "What ACT, IFR and FYI mean, how remarks are translated, and how FAA cycles work.",
                f"{SITE_URL}guide/", body, "../assets/style.css", image=f"{SITE_URL}assets/card.png")


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
    info = {a["id"]: a for a in directory}
    card(os.path.join(site, "assets", "card.png"), "amend.", "What changed at your airport",
         "", [("ACT", "action"), ("IFR", "ifr"), ("FYI", "fyi"), ("NO CHG", "ok")],
         "Every FAA cycle, in plain English.", f"EFF {efb(meta['to_cycle'])}")
    # one shared card for the ~10k airports with nothing changing this cycle (the title names the airport)
    upcoming_now, _ = status(meta, now)
    card(os.path.join(site, "assets", "nochange.png"), "No changes", "Nothing new at this airport", "",
         [("NO CHG", "ok")],
         f"{'Nothing changes on' if upcoming_now else 'Nothing changed in the'} {efb(meta['to_cycle'])} "
         f"{'' if upcoming_now else 'cycle'}".strip(), f"EFF {efb(meta['to_cycle'])}")
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
                            f"EFF {efb(meta['to_cycle'])}")
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
        f.write(guide_page())
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
                        f"EFF {efb(meta['to_cycle'])}")
        with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
            f.write(named_watch_page(slug, wl, meta, info, latest, now, has_card))
    return len(ids)