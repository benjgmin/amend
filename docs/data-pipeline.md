# Data pipeline

What happens from the FAA posting a file to a change showing on amend.watch, as the code does it
today. The module map is in [architecture.md](architecture.md).

Line references are against `master` at `8b18fdf`.

## Sources

| Source | URL pattern | Code | Used for |
|---|---|---|---|
| NASR 28-day subscription, CSV zip | `nfdc.faa.gov/webContent/28DaySub/extra/DD_Mon_YYYY_CSV.zip` | `cycles.py:22-23` | airports, runways, frequencies, towers, navaids, remarks, STARs/DPs, preferred routes, AWOS, parachute areas |
| d-TPP metafile XML | `aeronav.faa.gov/d-tpp/YYNN/xml_data/d-tpp_Metafile.xml` | `cycles.py:26-36` | added, amended and removed charts |
| Class airspace shapefile zip | `nfdc.faa.gov/webContent/28DaySub/YYYY-MM-DD/class_airspace_shape_files.zip` | `cycles.py:39-41` | class B, C, D and E surface-area shapes |

Cycles are 28 days apart, anchored on 2026-09-03 (`cycles.py:12-19`), and change over at 0901Z
(`cycles.py:56`, `72-75`). The FAA posts the next cycle's NASR data weeks before it takes effect (the
exact lead time hasn't been measured), which is what the "upcoming" view shows. Amend's history
starts from 2024-08-08 (`FIRST_ARCHIVED`, `cycles.py:14`). The comment there calls that the oldest
cycle in the FAA archive, but the FAA still serves NASR zips back to 2022-05-19 (checked in PR #24).

## 1. Trigger

`.github/workflows/update.yml` runs:

- **every 3 hours** at :17 past the hour (`update.yml:9`). GitHub can delay or skip scheduled runs;
- on every push to `master`, except changes only to `ios/`, `docs/`, Markdown or `LICENSE`
  (`update.yml:11-17`);
- by hand from the Actions tab (`update.yml:10`).

A new FAA cycle is therefore usually live **within a few hours** of the FAA posting it, not minutes.

## 2. Check: is a rebuild needed?

Scheduled runs start with `python -m amend check` (`update.yml:41-49`, `freshness.py:78-104`). It
reads the live `latest/meta.json` and `build.json` from amend.watch and requests the first 16 bytes
of each FAA file (`cycles.py:183-195`), so it takes seconds. It rebuilds when any of these is true
(`freshness.py:45-75`):

- the live site can't be read;
- the repo's inputs (`amend/*.py`, watchlists, history, remark cache) hash differently from the
  deployed `build.json` (`freshness.py:26-36`), meaning a merge or data commit isn't live yet;
- `history/` doesn't have the cycle in effect yet;
- the live site shows a different cycle than the FAA has, including a newly posted upcoming cycle;
- charts or airspace shapes were missing from the last build and may be posted now;
- the last build is more than 20 hours old (`freshness.py:23`);
- it can't tell whether the next cycle is posted.

If the check itself throws, it says build (`freshness.py:97-98`). Pushes and manual runs always
build.

## 3. Tests

`python -m unittest discover -s tests -t .` with Pillow installed (`update.yml:63-67`). A failing
test stops the run before anything is downloaded. The same suite runs on every pull request
(`.github/workflows/tests.yml`).

## 4. Download and file checks

Raw files land in `data/`, restored from the Actions cache (`update.yml:69-75`). `cycles.download`
(`cycles.py:139-180`):

- skips the download if a valid file is already there (`cycles.py:143-147`);
- tries 3 times with a 60-second stall timeout and 10 s, 20 s backoff (`cycles.py:58-60`);
- treats HTTP 403, 404 and 410, or an HTML page in place of the file, as **"not posted"** and returns
  `False` (`cycles.py:57`, `159-171`);
- treats everything else (timeouts, 5xx, short reads against `Content-Length`, bad CRCs, a zip
  missing a required CSV, XML that doesn't parse to the end) as a **failure**: it raises
  `FetchError` and the run stops (`cycles.py:66-69`, `155-163`, `172-180`);
- only moves a file into `data/` after `check_file` passes (`cycles.py:111-131`, `163-164`). Every
  zip member's CRC is tested, nested zips included (`cycles.py:96-108`).

A NASR zip must contain `APT_BASE`, `APT_RWY`, `APT_RWY_END`, `APT_RMK`, `FRQ`, `NAV_BASE` and
`ATC_BASE` (`cycles.py:62-63`), because a missing file would make every one of its rows read as
removed.

Nothing records when a file was retrieved, its checksum, or how many files and rows it had.

## 5. History: new cycles

`python -m amend history --llm` (`update.yml:77-80`, `history.py:58-101`):

1. List every cycle from 2024-08-08 to the one in effect (`history.py:61-65`) and keep the ones not
   yet in `history/cycles.json` (`history.py:66`).
2. Find the newest earlier cycle that's still downloadable to diff against (`history.py:74-78`).
3. For each new cycle: download it. A real "not posted" (404) marks it skipped, and the next cycle
   diffs across the gap (`history.py:81-84`). A failed download stops the run.
4. Diff it against the previous cycle for every airport, with charts and airspace when available
   (`history.py:89-90`).
5. Append the changes to each airport's `history/<ID>.json`, replacing any earlier entries for the
   same cycle so re-runs are idempotent (`history.py:28-42`). Record the cycle as done
   (`history.py:92-94`).
6. **Delete the older cycle's zip, the chart metafile and the older airspace zip**
   (`history.py:95-98`), so only the newest raw data stays in `data/`.
7. Rewrite `history/index.json` (`history.py:45-55`).

History entries don't record the engine version that produced them.

## 6. Latest: the current or upcoming diff

`python -m amend latest` (`update.yml:82-85`, `latest.py:18-60`):

1. If the FAA has posted the next cycle, compare the cycle in effect with it (upcoming). Otherwise
   compare the previous cycle with the one in effect (`latest.py:22-28`). If either NASR zip can't be
   had, stop (`latest.py:29-31`).
2. Fetch that cycle's d-TPP metafile and both airspace zips when posted (`latest.py:32-33`).
3. Run the diff for every airport (`latest.py:37-38`, see section 7). Remarks go to the model only if
   `ANTHROPIC_API_KEY` is set.
4. Write `site/latest/<ID>.json`, `index.json` and `meta.json` (`latest.py:39-44`,
   `output.py:16-26`), `site/airports.json` (`latest.py:45-47`), copy `history/` into the site
   (`latest.py:48-50`), render every page (`latest.py:54`, `web.py:1008`) and write `build.json`
   with the commit sha and input hash (`latest.py:56-58`).

## 7. Inside the diff

`pipeline.run` (`pipeline.py:69-149`).

### Load

`nasr.load` (`nasr.py:123-162`) reads every CSV in the zip, nested zips included, and:

- skips the FAA's change reports and data-structure files, any file whose name was already seen,
  and whole files listed as noise: `PFR_SEG`, `PFR_BASE`, `LID`, `FIX`, `CDR`, `COM`, `HPF`, `MTR`
  (`nasr.py:130-132`, `rules.py:37-44`);
- decodes UTF-8 or Latin-1 and normalizes line endings (`nasr.py:22-28`);
- keeps only rows that mention one of the airports, and drops columns that change every cycle
  (`EFF_DATE`, `LAST_INFO_RESPONSE...`) (`nasr.py:137-142`, `rules.py:7`);
- attributes each row to an airport by the first matching column in `ATTRIB_COLS`
  (`nasr.py:31-44`, `rules.py:14-15`). In all-airports mode, FRQ and PFR rows must name the airport
  in one of those columns (`rules.py:18`), so an approach frequency listed at one airport but serving another goes to the airport it serves;
- attributes STAR/DP route points through the procedure's airport list (`nasr.py:144-148`,
  `procedures.py:98-112`);
- attaches each navaid to up to 5 public airports within 10 NM (`nasr.py:63-64`, `152-159`).

### Diff and rank

`diff.diff` (`diff.py:147-220`), per file and airport:

1. Rows are keyed by their full contents, so identical rows in both cycles drop out
   (`diff.py:151-159`).
2. Each removed row is paired with the most similar added row. Files with pair keys
   (`rules.py:21-35`, e.g. `APT_RWY_END` on runway and end id) only pair when the keys match; files
   without them need at least 50% of columns equal (`diff.py:162-173`).
3. A pair becomes one **changed** record listing each field's old and new value, minus noise
   columns (coordinates, survey dates and sources, sequence numbers: `rules.py:112-124`) and survey
   rounding (`rules.py:78-80`, `132-141`) (`diff.py:174-193`).
4. Leftover rows become **added** or **removed** records (`diff.py:197-219`). A frequency that
   still exists and only lost one listed use becomes a "use dropped" change (`diff.py:200-205`).

Each record gets a priority from `diff.priority` (`diff.py:30-59`):

- `hidden`: noise files, changes that only touch identity or bookkeeping columns, pavement ratings;
- `fyi`: only name, phone, obstacle geometry, sectorization and similar columns changed
  (`rules.py:54-60`, `127-129`), or small real survey changes;
- `action`: tower, class airspace, frequency, ILS, attendance and AWOS files (`rules.py:62`); a
  runway added or removed, or a navaid removed (`rules.py:71`); a changed column about hours,
  frequency, class, lights, length, width or pattern altitude (`rules.py:63-64`); or remark text with
  words like CLSD, PPR, NOT AVBL, UNUSBL, CTAF, TPA (`rules.py:65-66`);
- routes and procedures are never `action`; navaid and ILS remarks that would be `action` are `ifr`
  (`diff.py:53-55`, `185-186`).

Special cases on top: a remark that only got reworded (same numbers and ids, 60% similar) is `fyi`
(`diff.py:89-95`, `181-182`); a pilot-controlled lighting remark is `action` only if the keying
frequency changed or a light stopped coming on (`diff.py:113-144`); a declared distance is `action`
only when it shrinks by 500 ft or 10% (`diff.py:62-75`, `rules.py:103-104`).

### Translate remarks

Remark texts from the records (`pipeline.py:89-95`) go through `remarks.translate_remarks`
(`remarks.py:87-118`):

1. Load `remark_cache.json` and drop any cached translation that fails today's checks
   (`remarks.py:89-94`).
2. Send uncached texts in batches of 30 with a prompt that lists the glossary and says never to
   guess (`remarks.py:53-84`, `104-109`).
3. Keep a translation only if the batch came back the right length and `problems()` finds nothing
   (`remarks.py:110-113`, `133-147`). The checks: each of the 31 `MUST_KEEP` contractions
   (`remarks.py:16-50`) either stays as written or is expanded correctly; no number is lost or
   added; pilot-controlled lighting isn't described as "contact the frequency".
4. On any failure the raw FAA text is used (`remarks.py:97-101`, `114-115`). Nothing is published
   that failed a check.

Only 31 contractions are checked in code. The other glossary terms, and any term outside the
glossary, rely on the prompt alone.

### Collapse into events

`collapse.collapse` (`collapse.py:142-203`), per airport:

1. A new or removed airport becomes one line (`collapse.py:150-154`).
2. A runway removed and another added that is the same strip renumbered (one number apart, or the
   same size) or replaced becomes one "renumbered" or "new runway" line, and its runway-end rows are
   dropped (`collapse.py:156-158`, `42-88`).
3. A remark "removed" and "added" with identical text (the FAA re-filed it) drops out
   (`collapse.py:160-167`).
4. A remark repeated on the CTAF frequency row, or on a second frequency, is said once
   (`collapse.py:169-182`).
5. The end rows of a runway added or removed outright drop out (`collapse.py:184-190`).
6. All STAR and DP rows become one IFR line with waypoint detail per procedure; all preferred-route
   rows become one IFR line (`collapse.py:194-201`, `91-127`, `procedures.py:61-88`).

Then several use changes on one frequency merge into one line (`collapse.py:206-225`).

### Summarize

`english.summarize` (`english.py:137-239`) writes one plain-English line per record. Remarks show
the translation (or raw text) and keep the raw text as `original` (`english.py:148-157`). Phrases
already said at the same airport (tower hours appear in three files) are dropped, and `hidden`
records are only counted (`pipeline.py:101-117`).

### Charts and airspace

- **Charts:** every `A`, `C` or `D` record for the airport in the new cycle's d-TPP metafile
  (`dtpp.py:15-39`). Procedures are `ifr`; airport diagrams and hot-spot pages are `fyi`
  (`dtpp.py:42-58`). Changes link the new plate PDF.
- **Airspace:** class B, C, D and E2 to E4 shapes (E5 is skipped) from both cycles' shapefiles
  (`airspace.py:23-24`, `118-144`). For each public airport under the shape, the layers over the
  field are compared; for the airport the airspace belongs to, shelves added or removed and
  boundaries that moved by more than 2% of area or 0.2 NM are reported (`airspace.py:26-27`,
  `202-257`). All airspace shape changes are `action` (`airspace.py:260-262`).

### Output shape

Records are sorted `action`, `ifr`, `fyi` and turned into the public change object: `id`,
`priority`, `category`, `kind`, `summary`, `source` and, where present, `original`, `fields`,
`details`, `procedures`, `chart` (`pipeline.py:53-66`, `142-147`, `SCHEMA.md:48-62`). The `id` is
`sha1(airport|cycle|summary)[:12]` (`pipeline.py:48-50`).

## 8. Verify, commit, deploy

1. `python -m amend verify site` (`update.yml:89-90`, `freshness.py:110-158`) refuses a site where
   `index.html` is missing or nearly empty, `meta.json` compares a cycle to itself or an older one,
   `latest/index.json` lists no airports or disagrees with `meta.json`, an airport in the index has
   no JSON file or no page, `airports.json` has fewer than 5,000 airports, history has no cycles, or
   `build.json` is missing.
2. Commit `history/` and `remark_cache.json` to `master` as amend-bot (`update.yml:94-100`). If the
   push still fails after three rebase attempts, stop without deploying so the site never gets ahead
   of the repo (`update.yml:101-107`).
3. Trim `data/` to the newest three files of each kind and save it to the Actions cache
   (`update.yml:109-120`).
4. Upload `site/` and deploy it to GitHub Pages (`update.yml:122-135`).

Any failing step stops everything after it. Nothing is committed or deployed, and the last good
site stays live.

## What happens when something goes wrong

| Situation | What the pipeline does | Where |
|---|---|---|
| FAA hasn't posted the next cycle | Shows the cycle in effect instead of upcoming | `latest.py:25-28` |
| A download times out, 5xx, truncated or corrupt, 3 times | Stops the run; last good site stays up | `cycles.py:172-180` |
| A NASR zip is missing a required CSV | Treated as a failed download | `cycles.py:62-63`, `120-122` |
| The cycle in effect or the previous one isn't posted | Stops the run | `latest.py:29-31` |
| An old cycle is gone from the FAA archive | History skips it and diffs across the gap | `history.py:81-84` |
| d-TPP or airspace files not posted yet | Built without them; `meta.json` says so; a later check rebuilds | `latest.py:32-33`, `41-42`, `freshness.py:64-68` |
| Airspace shapefile can't be parsed | Logged and skipped. **`meta.json` still says `includes_airspace: true`**, so the check never retries | `pipeline.py:129-133`, `latest.py:42` |
| A CSV has a parse error partway through | **Warning only; the rest of that file is dropped and its rows read as removed** | `nasr.py:160-161` |
| Two files with the same name in the zip | **The second is skipped silently** | `nasr.py:130` |
| No API key, API error, wrong-length batch, or a failed translation check | Raw FAA remark text is shown | `remarks.py:97-115` |
| A test fails | Stops before downloading anything | `update.yml:66-67` |
| The built site fails `verify` | Not deployed | `update.yml:89-90`, `cli.py:121-127` |
| History can't be pushed | Not deployed | `update.yml:101-107` |
| The freshness check itself errors | Builds anyway | `freshness.py:97-98` |

## Known weak spots

The ones in bold in the table above, plus:

- **Raw data isn't kept.** Zips are deleted after diffing (`history.py:95-98`) and the cache holds
  three (`update.yml:109-114`). If the FAA drops old cycles, history can't be rebuilt or audited.
- **No input-side anomaly checks.** Per-file row counts aren't compared with the previous cycle.
- **Pairing is greedy.** Removed rows are paired in iteration order, first come first served
  (`diff.py:162-173`), so the result can depend on row order. Exact duplicate rows collapse into one
  (`diff.py:151-155`).
- **No normalization layer.** Formatting-only differences in hours, frequencies and runway ids can
  still read as changes, apart from the handful of remark spellings `_canon` handles
  (`diff.py:78-86`).
- **Unstable ids.** Rewording a summary or re-translating a remark changes the change id
  (`pipeline.py:48-50`), which resets "seen" state.
- **No engine version, processing log, token or cost tracking.**
