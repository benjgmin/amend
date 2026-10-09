// list.amend.watch: short links for shared lists.
//
// A shared list used to travel whole in its link (amend.watch/list/?w=BJC,FDK&n=Flying%20club), which grows with every
// airport. This Cloudflare Pages project saves a list under a short code instead:
//
//   POST /new  {"w": ["BJC", "FDK"], "n": "Flying club"}  ->  {"code": "x7k2mq"}
//   GET  /x7k2mq       -> 302 to amend.watch/list/?s=x7k2mq, which loads the list from:
//   GET  /x7k2mq.json  -> {"w": [...], "n": "..."}
//
// Only the airport ids and the list name are stored (KV namespace bound as LISTS), never who sent them. The code is
// a hash of the list, so the same list always gets the same code and is only written once, and a code never changes
// what it points to. The site falls back to the long link whenever this doesn't answer, so sharing never depends on
// it. amend.watch itself stays a static site on GitHub Pages.
//
// Setup: cloudflare-lists/README.txt.

const SITE = "https://amend.watch";
const ABC = "abcdefghjkmnpqrstuvwxyz23456789";   // no 0/o, 1/l/i
const CODE = /^\/([a-z2-9]{6,10})(\.json)?$/;
const MAX_IDS = 200, MAX_NAME = 60, MAX_BODY = 4096;   // the site's own caps (web.py parseW, sname)
const RATE = 20, RATE_WINDOW = 600;   // new lists per IP per 10 minutes, counted per edge location
const IDS_TTL = 3600;
let known = null, knownAt = 0;   // this isolate's copy of the airport ids

// only pages on amend.watch read these from a browser
const cors = () => ({
  "Access-Control-Allow-Origin": SITE,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  Vary: "Origin",
});
const json = (body, status, extra) => new Response(JSON.stringify(body), { status, headers: Object.assign(
  { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }, cors(), extra || {}) });
const fail = (status, error) => json({ error }, status);

// every airport id in the current FAA cycle, from amend.watch/airports.json, kept for an hour
async function airportIds() {
  if (known && Date.now() - knownAt < IDS_TTL * 1000) return known;
  const r = await fetch(SITE + "/airports.json", { cf: { cacheTtl: IDS_TTL, cacheEverything: true } });
  if (!r.ok) throw new Error("airports.json " + r.status);
  const j = await r.json();
  known = new Set((j.airports || []).map((a) => a.id));
  knownAt = Date.now();
  return known;
}

// the same cleanup as the site's parseW: upper case, KBJC -> BJC, no repeats
function cleanIds(w, ids) {
  if (!Array.isArray(w)) return null;
  const out = [];
  for (const x of w) {
    if (typeof x !== "string") return null;
    let id = x.trim().toUpperCase();
    if (/^K[A-Z]{3}$/.test(id) && !ids.has(id)) id = id.slice(1);
    if (!ids.has(id)) return null;   // any id Amend doesn't know refuses the whole list
    if (!out.includes(id)) out.push(id);
  }
  return out.length && out.length <= MAX_IDS ? out.sort() : null;
}
const cleanName = (n) => String(typeof n === "string" ? n : "").replace(/[\u0000-\u001f\u007f]/g, " ")
  .replace(/\s+/g, " ").trim().slice(0, MAX_NAME);

async function codeFor(list, len) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(list))));
  let s = "";
  for (let i = 0; i < len; i++) s += ABC[d[i] % ABC.length];
  return s;
}

// a rough per-IP count in the edge cache: free, nothing written to KV, gone after the window
async function overLimit(req) {
  const cache = typeof caches !== "undefined" ? caches.default : null;
  if (!cache) return false;
  const ip = req.headers.get("CF-Connecting-IP") || "?";
  const key = new Request("https://list.amend.watch/rate/" + encodeURIComponent(ip) + "/" +
    Math.floor(Date.now() / (RATE_WINDOW * 1000)));
  const hit = await cache.match(key);
  const n = hit ? parseInt(await hit.text(), 10) || 0 : 0;
  if (n >= RATE) return true;
  await cache.put(key, new Response(String(n + 1), { headers: { "Cache-Control": "max-age=" + RATE_WINDOW } }));
  return false;
}

async function create(req, env) {
  if (req.headers.get("Origin") !== SITE) return fail(403, "lists are shared from amend.watch");
  const text = await req.text();
  if (text.length > MAX_BODY) return fail(413, "too big");
  let body;
  try { body = JSON.parse(text); } catch (e) { return fail(400, "not json"); }
  let ids;
  try { ids = await airportIds(); } catch (e) { return fail(503, "airport list unavailable"); }
  const w = cleanIds(body && body.w, ids);
  if (!w) return fail(400, "1 to 200 airport ids Amend knows");
  const list = { w, n: cleanName(body.n) };
  const value = JSON.stringify(list);
  if (await overLimit(req)) return fail(429, "too many new lists, try again in a few minutes");
  for (let len = 6; len <= 10; len++) {
    const code = await codeFor(list, len);
    const have = await env.LISTS.get(code);
    if (have === value) return json({ code }, 200);
    if (have === null) {
      await env.LISTS.put(code, value);   // throws past the free plan's daily writes; the site uses the long link
      return json({ code }, 201);
    }
  }
  return fail(500, "no free code");
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    try {
      if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors() });
      if (url.pathname === "/new") {
        if (req.method !== "POST") return fail(405, "POST only");
        if (!env || !env.LISTS) return fail(503, "no storage bound");
        return await create(req, env);
      }
      if (req.method !== "GET" && req.method !== "HEAD") return fail(405, "GET only");
      if (url.pathname === "/health") return json({ ok: !!(env && env.LISTS) }, env && env.LISTS ? 200 : 503);
      if (url.pathname === "/") return Response.redirect(SITE + "/list/", 302);
      const m = url.pathname.match(CODE);
      if (!m) return fail(404, "not found");
      if (!m[2]) return Response.redirect(SITE + "/list/?s=" + m[1], 302);
      if (!env || !env.LISTS) return fail(503, "no storage bound");
      const v = await env.LISTS.get(m[1]);
      if (v === null) return fail(404, "no list with that code");
      // a code never changes what it points to, so browsers and the edge can keep it
      return new Response(v, { headers: Object.assign({ "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "public, max-age=86400, immutable" }, cors()) });
    } catch (e) {
      return fail(503, String((e && e.message) || e));
    }
  },
};
