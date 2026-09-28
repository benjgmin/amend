// status.amend.watch and docs.amend.watch.
//
// GitHub Pages gives a repo one domain, so both pages are built with the rest of the site, at
// amend.watch/status/ and amend.watch/docs/ (amend/subsite.py). This Cloudflare Pages project answers
// on the two names and serves each page from there, so every deploy of amend.watch updates both, with
// nothing to sync and no token. The pages ask for their shared files (/assets/, the icons,
// latest/meta.json for the server clock) from their own name; those pass through too. Any other
// path is a link into the airport site and goes to amend.watch.
//
// Setup: cloudflare/README.txt. It only ever fetches amend.watch.

const ORIGIN = "https://amend.watch";
const PAGES = { "status.amend.watch": "/status/", "docs.amend.watch": "/docs/" };
const SHARED = /^\/(assets\/[\w./-]+|favicon\.ico|site\.webmanifest|latest\/meta\.json)$/;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const page = PAGES[url.hostname];
    // the project's own *.pages.dev name, or anything else: the site itself
    if (!page) return Response.redirect(ORIGIN + "/", 302);
    let path;
    if (url.pathname === "/" || url.pathname === "/index.html") path = page;
    else if (SHARED.test(url.pathname)) path = url.pathname;
    else return Response.redirect(ORIGIN + url.pathname + url.search, 301);
    if (request.method !== "GET" && request.method !== "HEAD")
      return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
    // the query only matters to the files (?v= cache busting); the pages don't read it on the server
    const upstream = await fetch(ORIGIN + path + (path === page ? "" : url.search), {
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
