status.amend.watch and docs.amend.watch: a Cloudflare Pages project that serves amend.watch/status/ and
amend.watch/docs/ under their own names (_worker.js), plus the docs' other pages (/using/, /how-it-works/,
/api/) and status.amend.watch/checks.json, GitHub's public list of recent workflow runs, cached for 5 minutes.
Nothing to build. A token is optional but recommended: Cloudflare's outbound addresses are shared, so GitHub
often refuses its list without one. Add a secret named GITHUB_TOKEN to this Pages project (Settings > Variables and
Secrets, Production) holding a fine-grained GitHub token with public-repository read access and no permissions,
then redeploy. Without it, a refused call serves the last list GitHub sent, marked stale.

1. Cloudflare dashboard > Workers & Pages > Create > Pages > Connect to Git > benjgmin/amend.
   Production branch: master. Framework preset: None. Build command: leave empty.
   Build output directory: cloudflare. Save and Deploy.
2. The project's Settings > Builds: Build watch paths, include "cloudflare/*", so only changes here
   redeploy it. Branch control: preview deployments None.
3. The project's Custom domains > Set up a custom domain: status.amend.watch, then again for
   docs.amend.watch. Cloudflare shows a CNAME for each, pointing at <project>.pages.dev.
4. Spaceship > amend.watch > DNS: add both CNAME records exactly as Cloudflare shows them.
5. When both names say Active, open https://status.amend.watch and https://docs.amend.watch.
   Then web.SUBDOMAINS = True in amend/web.py sends every link there and forwards the old pages.
