list.amend.watch: short links for shared lists (_worker.js). A Cloudflare Pages project with one KV namespace.
Nothing to build and no token or secret. The site only uses it once web.SHORT_LINKS = True in amend/web.py, and
falls back to the long ?w= link whenever it doesn't answer.

1. Cloudflare dashboard > Storage & Databases > KV > Create a namespace: amend-lists.
2. Workers & Pages > Create > Pages > Connect to Git > benjgmin/amend. Project name: amend-lists.
   Production branch: master. Framework preset: None. Build command: leave empty.
   Build output directory: cloudflare-lists. Save and Deploy.
3. The project's Settings > Builds: Build watch paths, include "cloudflare-lists/*", so only changes here
   redeploy it. Branch control: preview deployments None.
4. The project's Settings > Bindings > Add > KV namespace. Variable name: LISTS. Namespace: amend-lists.
   Then Deployments > the latest one > Retry deployment, so it picks up the binding.
5. Custom domains > Set up a custom domain: list.amend.watch. Cloudflare shows a CNAME.
6. Spaceship > amend.watch > DNS: add that CNAME (host "list", value amend-lists.pages.dev).
7. When it says Active, https://list.amend.watch/health should say {"ok":true}.
   Then web.SHORT_LINKS = True sends every "Copy share link" through it.

Free plan limits: 1,000 new lists a day (KV writes) and 100,000 opens. Past the write limit, sharing falls back to
long links until 00:00 UTC; links already made keep opening.
