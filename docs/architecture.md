# Architecture

How Amend is built today. For what a run does step by step, see
[data-pipeline.md](data-pipeline.md).

Line references are against `master` at `8b18fdf`.

## The short version

There is no server. A GitHub Actions workflow downloads the FAA's public data, diffs it with a
Python package (`amend/`, standard library only, plus Pillow for link-preview images), commits the
change history back to the repo and publishes static JSON and HTML to GitHub Pages at amend.watch.
The web pages and the iOS app only read those files.

```text
               FAA (nfdc.faa.gov, aeronav.faa.gov)
                 |  NASR CSV zip, d-TPP metafile XML, class airspace shapefile zip
                 v
   GitHub Actions: update.yml (every 3h, on merge, or by hand)
     check  -> is a rebuild needed?            amend/freshness.py
     build  -> tests                           tests/
            -> history: new cycles             amend/history.py  --\
            -> latest: current/upcoming cycle  amend/latest.py   --+-> amend/pipeline.py
            -> verify the built site           amend/freshness.py
            -> commit history/ + remark_cache.json to master
     deploy -> GitHub Pages
                 |
                 v
   amend.watch: static JSON (SCHEMA.md) + one HTML page per airport
                 |
          +------+-------+
          v              v
     web browsers    iOS app (ios/)
```

## Where AI is used

In exactly one place: `amend/remarks.py` sends FAA remark text (the free-text `REMARK` column of
`*_RMK` files, and FRQ rows whose only change is their remark) to one model
(`amend/remarks.py:7`) to turn contractions into a plain-English sentence. It runs at build time,
results are cached in `remark_cache.json` and committed, and the raw FAA text is always kept next to
the translation. Deciding what changed, how to classify it, how important it is, and every other
summary line is deterministic code. The web pages and the app never call a model.

## Modules

| Module | Role | Key entry points |
|---|---|---|
| `amend/cli.py` | Command line: `diff`, `latest`, `history`, `check`, `verify`, `watchlist`, `set-key` | `main` (`cli.py:68-139`) |
| `amend/cycles.py` | 28-day cycle math, FAA URLs, downloading with retries and file checks | `in_effect` (`cycles.py:72-75`), `download` (`cycles.py:139-180`), `check_file` (`cycles.py:111-131`), `probe` (`cycles.py:183-195`) |
| `amend/nasr.py` | Reading NASR CSV zips; attributing rows to airports; matching navaids to nearby airports | `load` (`nasr.py:123-162`), `attribute` (`nasr.py:31-44`), `NearIndex` (`nasr.py:67-112`) |
| `amend/rules.py` | Every rule about noise, pairing keys and importance. Tuning the output happens here | constants (`rules.py:6-104`), `is_noise_col` (`rules.py:112-124`), `small_change` (`rules.py:132-141`) |
| `amend/diff.py` | Diffing two loaded cycles into raw change records and ranking each one | `diff` (`diff.py:147-220`), `priority` (`diff.py:30-59`) |
| `amend/collapse.py` | Turning piles of raw rows into one event: new or removed airport, renumbered runway, new STAR version, re-filed remark | `collapse` (`collapse.py:142-203`), `merge_freq_uses` (`collapse.py:206-225`) |
| `amend/english.py` | Plain-English summaries for each record | `summarize` (`english.py:137-239`), `field_phrases` (`english.py:11-109`) |
| `amend/remarks.py` | Remark translation, the glossary, and the checks on each translation | `translate_remarks` (`remarks.py:87-118`), `problems` (`remarks.py:133-147`) |
| `amend/procedures.py` | Waypoint-level comparison of STAR and DP versions | `describe` (`procedures.py:61-88`), `airports_by_procedure` (`procedures.py:98-112`) |
| `amend/dtpp.py` | Added, amended and removed charts from the d-TPP metafile | `load_dtpp` (`dtpp.py:15-39`) |
| `amend/airspace.py` | Class B, C, D and E surface-area floors, ceilings and boundaries from the shapefile | `load` (`airspace.py:118-144`), `diff` (`airspace.py:202-257`) |
| `amend/pipeline.py` | The whole diff in one call, and the public change shape | `run` (`pipeline.py:69-149`), `to_change` (`pipeline.py:53-66`) |
| `amend/output.py` | Writing `<ID>.json` and `index.json` | `write_diff` (`output.py:16-26`) |
| `amend/history.py` | Appending each new cycle to `history/<ID>.json` | `update` (`history.py:58-101`), `append` (`history.py:28-42`) |
| `amend/latest.py` | Building `site/`: the latest diff, airport directory, history copy, pages, `build.json` | `build` (`latest.py:18-60`) |
| `amend/airports.py` | The airport directory for names and search (`airports.json`) | `directory` (`airports.py:19-37`) |
| `amend/freshness.py` | Is a rebuild needed? Is a built site safe to deploy? | `decide` (`freshness.py:45-75`), `verify` (`freshness.py:110-158`) |
| `amend/watchlists.py` | Named watchlists from `watchlists/*.json` | `load_all` (`watchlists.py:48-70`) |
| `amend/web.py` | The HTML pages, CSS, link-preview images and calendar feed | `build` (`web.py:1008`) |
| `ios/` | SwiftUI app that reads the published JSON | |

Dependencies run one way: `cli` calls `latest`, `history` and `freshness`; those call `pipeline`,
which calls `nasr`, `diff`, `collapse`, `english`, `remarks`, `procedures`, `dtpp` and `airspace`;
everything reads its rules from `rules`. `web` only formats results. Nothing in the engine imports
`web`.

## Data flow inside one diff

`pipeline.run(old_zip, new_zip, ids=None, dtpp, llm, airspace)` (`pipeline.py:69-149`):

1. **Airports.** With no `ids`, every airport id in either cycle's `APT_BASE` (`pipeline.py:74-77`).
2. **Load.** Both zips are read into `{file: [(airport, row)]}`, keeping only rows about those
   airports, with bookkeeping columns dropped (`nasr.py:123-162`). Route rows are attributed through
   `STAR_APT`/`DP_APT` (`nasr.py:144-148`); navaids to public airports within 10 NM
   (`nasr.py:152-159`, `nasr.py:63`).
3. **Diff.** Removed and added rows are paired into "changed" records with field-level old and new
   values, and every record gets a priority (`diff.py:147-220`).
4. **Remarks.** Remark texts from the records are translated or read from the cache
   (`pipeline.py:89-96`).
5. **Collapse.** Raw rows become events (`pipeline.py:97-98`, `collapse.py:142-203`).
6. **Summaries.** One plain-English line per record; phrases already said at the same airport are
   dropped, and hidden records are only counted (`pipeline.py:101-117`).
7. **Charts and airspace.** d-TPP chart records and airspace shape records are added
   (`pipeline.py:119-140`).
8. **Shape.** Records are sorted action, ifr, fyi and converted to the public change shape
   (`pipeline.py:142-147`, `SCHEMA.md:48-62`).

## Outputs and state

| Path | Written by | Kept where | What |
|---|---|---|---|
| `history/<ID>.json`, `history/index.json` | `history.py` | committed to `master` by the workflow | every change per airport since Aug 2024 |
| `history/cycles.json` | `history.py:92-94` | committed | which cycles are done, which were skipped as missing |
| `remark_cache.json` | `remarks.py:116-117` | committed | raw remark to translation, re-checked every run |
| `site/latest/<ID>.json`, `index.json`, `meta.json` | `output.py`, `latest.py:39-44` | GitHub Pages | the current or upcoming diff |
| `site/airports.json` | `latest.py:45-47` | GitHub Pages | airport directory |
| `site/history/` | copied by `latest.py:48-50` | GitHub Pages | same as `history/`, minus `cycles.json` |
| `site/build.json` | `latest.py:56-58` | GitHub Pages | commit sha and a hash of the inputs, used by the freshness check |
| `site/**/index.html`, `assets/`, `cycles.ics` | `web.py` | GitHub Pages | the web pages |
| `data/` | `cycles.py` | Actions cache, newest 3 of each kind (`update.yml:109-114`) | raw FAA downloads. **Not archived** |

`schema_version` (`amend/__init__.py:3`) versions the JSON contract. There is no version for the
engine that produced a given history entry.

## Runtime and hosting

- **Runner:** GitHub-hosted Ubuntu, Python 3.12 (`update.yml:37-39`, `59-61`). Locally, Python 3.11+
  works.
- **Secrets:** `ANTHROPIC_API_KEY` for remark translation (`update.yml:78-85`). Without it, remarks
  show as raw FAA text (`latest.py:37`, `remarks.py:99-101`).
- **Hosting:** GitHub Pages, custom domain amend.watch. The status page and the docs are built with the site
  (`amend/statuspage.py`, `amend/docspage.py`, layout in `amend/subsite.py`) and served at status.amend.watch
  and docs.amend.watch by a Cloudflare Pages proxy (`cloudflare/_worker.js`, setup in `cloudflare/README.txt`).
  `web.SUBDOMAINS` turns the names on for every link. The docs are five pages (`docspage.PAGES`); the accuracy page
  reads the gold set and the run log at build time, and the API page
  is rendered from `SCHEMA.md` at build time. The proxy also serves `status.amend.watch/checks.json`, GitHub's
  public list of recent `update.yml` runs (cached 5 min), so the status page can show the 10-minute checks that
  build nothing and never reach the run log. An optional `GITHUB_TOKEN` secret on the Pages project lifts GitHub's
  limit; without one, a refused call serves the last list GitHub sent, marked stale.
- **Concurrency:** one deploy at a time (`update.yml:24-26`).
- **Pull requests:** `.github/workflows/tests.yml` runs the unit tests on every PR. It has read-only
  permissions, no secrets and never downloads FAA data or deploys.

## What isn't here

No database, no API server, no accounts or auth, no raw FAA archive, no engine version on outputs,
no processing log beyond the Actions output, no health dashboard.
