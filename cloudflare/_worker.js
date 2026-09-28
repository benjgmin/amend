// status.amend.watch and docs.amend.watch.
//
// GitHub Pages gives a repo one domain, so both pages are built with the rest of the site, at
// amend.watch/status/ and amend.watch/docs/ (amend/subsite.py). This Cloudflare Pages project answers
// on the two names and serves each page from there, so every deploy of amend.watch updates both, with
// nothing to sync and no token. The pages ask for their shared files (/assets/, the icons,
// latest/meta.json for the server clock) from their own name; those pass through too. The docs' other
// pages (/using/, /how-it-works/, /api/) come from amend.watch/docs/<name>/. Any other path is a link
// into the airport site and goes to amend.watch.
//
// Setup: cloudflare/README.txt. It only ever fetches amend.watch, and GitHub's public list of runs (checks.json).

const ORIGIN = "https://amend.watch";
const PAGES = { "status.amend.watch": "/status/", "docs.amend.watch": "/docs/" };
// the docs' other pages (amend/docspage.py PAGES), each served from amend.watch/docs/<name>/
const SUBPAGES = { "docs.amend.watch": /^\/(using|how-it-works|api)(\/|\/index\.html)?$/ };
const SHARED = /^\/(assets\/[\w./-]+|favicon\.ico|site\.webmanifest|latest\/meta\.json)$/;

// status.amend.watch/checks.json: the recent runs of the "update FAA changes" workflow, from GitHub's public API.
// Most are checks that found nothing new and built nothing, so the run log never sees them. Cached at the edge so
// GitHub gets a few calls an hour whoever visits, and a visitor's browser never talks to GitHub itself
const RUNS = "https://api.github.com/repos/benjgmin/amend/actions/workflows/update.yml/runs?per_page=40";
const CHECKS_TTL = 300;   // GitHub allows 60 calls an hour per IP without a token: this is 12 per edge location

async function checks(ctx) {
  const key = new Request("https://status.amend.watch/checks.json");
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const hit = cache && (await cache.match(key));
  if (hit) return hit;
  let body, ttl = CHECKS_TTL;
  try {
    const r = await fetch(RUNS, { headers: { "User-Agent": "amend-status", Accept: "application/vnd.github+json" } });
    if (!r.ok) throw new Error("GitHub " + r.status);
    const j = await r.json();
    body = { runs: (j.workflow_runs || []).map((x) => ({
      event: x.event, status: x.status, conclusion: x.conclusion,
      started: x.run_started_at || x.created_at, updated: x.updated_at, url: x.html_url })) };
  } catch (e) {
    body = { runs: [], error: "GitHub didn't answer" };   // the page keeps its link to GitHub instead
    ttl = 600;
  }
  const res = new Response(JSON.stringify(body), { headers: {
    "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=" + ttl } });
  if (cache) {
    const put = cache.put(key, res.clone());
    if (ctx && ctx.waitUntil) ctx.waitUntil(put); else await put;
  }
  return res;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const page = PAGES[url.hostname];
    // the project's own *.pages.dev name, or anything else: the site itself
    if (!page) return Response.redirect(ORIGIN + "/", 302);
    const sub = SUBPAGES[url.hostname] && url.pathname.match(SUBPAGES[url.hostname]);
    if (sub && !sub[2]) return Response.redirect(url.origin + url.pathname + "/" + url.search, 301);
    let path;
    if (url.pathname === "/" || url.pathname === "/index.html") path = page;
    else if (sub) path = page + sub[1] + "/";
    else if (SHARED.test(url.pathname)) path = url.pathname;
    else if (page === "/status/" && url.pathname === "/checks.json") path = null;
    else return Response.redirect(ORIGIN + url.pathname + url.search, 301);
    if (request.method !== "GET" && request.method !== "HEAD")
      return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
    if (path === null) return checks(ctx);
    // the query only matters to the files (?v= cache busting); the pages don't read it on the server
    const upstream = await fetch(ORIGIN + path + (path.endsWith("/") ? "" : url.search), {
      method: request.method,
      headers: { "User-Agent": "amend-subdomains" },
      redirect: "follow",
    });
    const res = new Response(request.method === "HEAD" ? null : upstream.body, upstream);
    // GitHub Pages sends its own caching headers; the pages still say which name is canonical in their HTML
    res.headers.delete("set-cookie");
    return res;
  },
};
