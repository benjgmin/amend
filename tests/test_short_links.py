"""list.amend.watch (cloudflare-lists/_worker.js) and the site's side of short share links (web.SHORT_LINKS)."""
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest

# a fake KV store, edge cache and amend.watch/airports.json around the worker
HARNESS = """import w from "./w.mjs";
const kv=new Map(),writes=[],env={LISTS:{get:async k=>kv.has(k)?kv.get(k):null,put:async(k,v)=>{writes.push(k);kv.set(k,v)}}};
const store=new Map();globalThis.caches={default:{match:async r=>store.has(r.url)?new Response(store.get(r.url)):undefined,
  put:async(r,res)=>{store.set(r.url,await res.text())}}};
let fetches=0;globalThis.fetch=async u=>{fetches++;if(u!=="https://amend.watch/airports.json")throw new Error(u);
  return new Response(JSON.stringify({airports:[{id:"BJC"},{id:"FDK"},{id:"PAO"},{id:"VRB"}]}))};
const call=async(path,o={})=>{const h=Object.assign({Origin:"https://amend.watch","CF-Connecting-IP":"1.2.3.4"},o.headers||{});
  const r=await w.fetch(new Request("https://list.amend.watch"+path,{method:o.method||"GET",headers:h,body:o.body}),o.env===undefined?env:o.env);
  let b=await r.text();try{b=JSON.parse(b)}catch(e){}return{s:r.status,b,loc:r.headers.get("location"),
  cc:r.headers.get("cache-control"),acao:r.headers.get("access-control-allow-origin")}};
const post=(body,o={})=>call("/new",Object.assign({method:"POST",body:typeof body==="string"?body:JSON.stringify(body)},o));
const out={};
"""


@unittest.skipUnless(shutil.which("node"), "node isn't installed")
class TestWorker(unittest.TestCase):
    def run_js(self, js):
        d = tempfile.mkdtemp()
        shutil.copy(os.path.join("cloudflare-lists", "_worker.js"), os.path.join(d, "w.mjs"))
        with open(os.path.join(d, "t.mjs"), "w") as f:
            f.write(HARNESS + js + "\nprocess.stdout.write(JSON.stringify(out))")
        return json.loads(subprocess.run(["node", "t.mjs"], cwd=d, capture_output=True, text=True, check=True).stdout)

    def test_save_and_open(self):
        r = self.run_js("""
out.a=await post({w:["fdk","KBJC","BJC"],n:"  Club\\nSVFR  "});
out.again=await post({w:["BJC","FDK"],n:"Club SVFR"});
out.other=await post({w:["BJC","FDK"],n:"Trip"});
out.writes=writes.length;out.stored=kv.get(out.a.b.code);
out.json=await call("/"+out.a.b.code+".json");out.go=await call("/"+out.a.b.code);
out.missing=await call("/abcdefg.json");out.root=await call("/");out.health=await call("/health");
out.fetches=fetches;""")
        code = r["a"]["b"]["code"]
        self.assertRegex(code, r"^[a-hjkmnp-z2-9]{6}$")
        self.assertEqual(r["a"]["s"], 201)
        self.assertEqual(r["again"], {**r["a"], "s": 200})            # same list, same code, no second write
        self.assertNotEqual(r["other"]["b"]["code"], code)            # the name is part of the list
        self.assertEqual(r["writes"], 2)
        self.assertEqual(json.loads(r["stored"]), {"w": ["BJC", "FDK"], "n": "Club SVFR"})   # ids sorted, name cleaned
        self.assertEqual(r["json"]["b"], {"w": ["BJC", "FDK"], "n": "Club SVFR"})
        self.assertIn("immutable", r["json"]["cc"])
        self.assertEqual(r["json"]["acao"], "https://amend.watch")
        self.assertEqual((r["go"]["s"], r["go"]["loc"]), (302, "https://amend.watch/list/?s=" + code))
        self.assertEqual(r["missing"]["s"], 404)
        self.assertEqual((r["root"]["s"], r["root"]["loc"]), (302, "https://amend.watch/list/"))
        self.assertEqual((r["health"]["s"], r["health"]["b"]), (200, {"ok": True}))
        self.assertEqual(r["fetches"], 1)                             # airports.json is kept, not fetched per list

    def test_refuses(self):
        r = self.run_js("""
const many=Array.from({length:201},(_, i)=>"A"+i);
for(const [k,b,o] of [["unknown",{w:["BJC","XXXX"],n:"x"}],["empty",{w:[],n:"x"}],["notlist",{w:"BJC",n:"x"}],
  ["number",{w:[5],n:"x"}],["many",{w:many,n:"x"}],["notjson","{w:"],["big",JSON.stringify({w:["BJC"],n:"x".repeat(5000)})],
  ["origin",{w:["BJC"],n:"x"},{headers:{Origin:"https://evil.example"}}],["get",null,{method:"GET"}]])
  out[k]=(k==="get"?await call("/new"):await post(b,o||{})).s;
out.nokv=(await post({w:["BJC"]},{env:{}})).s;out.health=(await call("/health",{env:{}})).s;
out.longname=JSON.parse(kv.get((await post({w:["PAO"],n:"y".repeat(90)})).b.code)).n.length;
out.writes=writes.length;""")
        self.assertEqual({k: r[k] for k in ("unknown", "empty", "notlist", "number", "many", "notjson", "big", "origin",
                                            "get", "nokv", "health")},
                         {"unknown": 400, "empty": 400, "notlist": 400, "number": 400, "many": 400, "notjson": 400,
                          "big": 413, "origin": 403, "get": 405, "nokv": 503, "health": 503})
        self.assertEqual(r["longname"], 60)
        self.assertEqual(r["writes"], 1)

    def test_rate_limit(self):
        r = self.run_js("""out.s=[];
for(let i=0;i<22;i++)out.s.push((await post({w:["BJC"],n:"list "+i})).s);
out.otherIp=(await post({w:["BJC"],n:"z"},{headers:{"CF-Connecting-IP":"5.6.7.8"}})).s;""")
        self.assertEqual(r["s"], [201] * 20 + [429, 429])
        self.assertEqual(r["otherIp"], 201)

    def test_clash_takes_a_longer_code(self):
        r = self.run_js("""
const first=(await post({w:["VRB"],n:"a"})).b.code;kv.set(first,"something else");
out.first=first;out.next=(await post({w:["VRB"],n:"a"})).b.code;""")
        self.assertEqual(len(r["next"]), 7)
        self.assertTrue(r["next"].startswith(r["first"]))


class TestSite(unittest.TestCase):
    def tearDown(self):
        from amend import web
        importlib.reload(web)

    def test_off_keeps_long_links(self):
        from amend import web
        web.SHORT_LINKS = False
        self.assertIn('SHORT=""', web.APP_JS.replace("__SHORT__", json.dumps(web.SHORT_URL if web.SHORT_LINKS else "")))
        self.assertIn("doesn't save it anywhere", web.privacy_page(
            {"from_cycle": "2026-09-03", "to_cycle": "2026-10-01"}, None))

    def test_on(self):
        from amend import web
        self.assertTrue(web.SHORT_LINKS)      # live since list.amend.watch answered
        self.assertIn('SHORT="https://list.amend.watch/"', web.APP)
        app = web.APP_JS.replace("__STALE__", "1").replace("__SHORT__", json.dumps(web.SHORT_URL))
        self.assertIn('SHORT="https://list.amend.watch/"', app)
        self.assertIn("AM.share(link(l),l.ids,l.name,b)", app)
        # opening a short link to a list you already have keeps the short link in the address bar
        self.assertIn('same?"?s="+code', web.WATCH_JS)
        page = web.privacy_page({"from_cycle": "2026-09-03", "to_cycle": "2026-10-01"}, None)
        self.assertIn("list.amend.watch/x7k2mq", page)
        self.assertNotIn("runs no server or database", page)


if __name__ == "__main__":
    unittest.main()
