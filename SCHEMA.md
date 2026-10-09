# Amend JSON format (schema_version 1)

Everything is served from `https://amend.watch/`. All airport ids are FAA
ids (`VRB`, not `KVRB`). All cycle dates are ISO dates (`2026-10-01`) of the FAA effective
date. Files are minified UTF-8 JSON.

If a field is added, `schema_version` stays the same. If a field is renamed or removed, it goes up.

## Web pages (not part of the JSON contract)
`index.html` (search), `<ID>/index.html` (one page per airport with changes or history) and
`assets/style.css` and `assets/app.js` (shared by every page), `about/`, `guide/`, `docs/`, `changelog/`, `privacy/`, `terms/`, `list/` (one of the lists saved in the
browser, `?l=<id>`, or a shared one, `?w=BJC,FDK&n=Flying%20club`) and `list/<slug>/` (named
lists from `watchlists/<slug>.json` in the repo, e.g. amend.watch/list/flying-club; slugs are
3–40 lowercase letters, digits or dashes). Old links (`watch/?w=`, `watch/<slug>/`, `<slug>/`) redirect
there. `404.html` is the not-found page: it sends `/kbjc` to `/BJC/` and says when an airport has no changes on record. `cycles.ics` is a calendar feed of the 0901Z cycle changeovers. `favicon.ico`, `site.webmanifest` and `assets/` (styles, scripts,
fonts, icons, link-preview images) are the site's own files. `build.json` records what the deploy was built from, for the pipeline's own freshness check. `<ID>/feed.xml` (every airport in `airports.json`, even ones with no page yet) and
`list/<slug>/feed.xml` are RSS 2.0 feeds with one item per cycle with changes, newest first, about a year's worth; the
item `guid` is `amend.watch/<ID>/<cycle>` (or `amend.watch/list/<slug>/<cycle>`) and never changes. Airport folders are always 2–4 uppercase letters/digits, so they never collide with the JSON paths below.

## `latest/meta.json`
Which cycles `latest/` compares.

| field | type | notes |
|---|---|---|
| `schema_version` | int | |
| `from_cycle`, `to_cycle` | string | ISO dates |
| `upcoming` | bool | `true`: `to_cycle` hadn't taken effect when this file was built. Don't show it as-is: files are rebuilt on a schedule, not at the changeover. Compare `effective` with the time now instead |
| `effective` | string | when `to_cycle` takes effect, always 0901Z on its date (`2026-10-01T09:01:00Z`). In effect once the time is at or past this, by a clock you trust (amend.watch checks the device's against the server's `Date` header) |
| `includes_charts` | bool | d-TPP chart changes included |
| `includes_plates` | bool or null | every changed chart's old and new plate has been read for the courses printed on it (null: no charts, or this build couldn't read plates) |
| `includes_airspace` | bool | class airspace shape changes (floors, ceilings, boundaries) included |
| `changed_airports` | int | |
| `engine` | string | version of the engine that made these changes (`1.2.0`) |
| `generated` | string | ISO timestamp, UTC |

## `latest/index.json`
Every airport with changes, with counts, so an app can badge saved airports without
downloading each file.

```json
{"schema_version": 1, "from_cycle": "2026-09-03", "to_cycle": "2026-10-01",
 "airports": {"VRB": {"action": 3, "ifr": 1, "fyi": 2}}}
```

## `latest/<ID>.json`
Only exists if the airport changed. **A 404 means no changes**, not an error.

```json
{"schema_version": 1, "airport": "VRB", "from_cycle": "2026-09-03", "to_cycle": "2026-10-01",
 "counts": {"action": 1, "ifr": 0, "fyi": 0},
 "changes": [Change, ...]}
```
`changes` is ordered action, then ifr, then fyi.

## Change

| field | type | always? | notes |
|---|---|---|---|
| `id` | string | yes | 12-char stable id (airport + cycle + the FAA file, kind and values behind the change, not its wording). Use it to remember what's been seen |
| `priority` | string | yes | `action` (could change your plan), `ifr` (procedures/charts/routes), `fyi` |
| `category` | string | yes | `tower`, `airspace`, `frequency`, `navaid`, `runway`, `remark`, `procedure`, `route`, `chart`, `weather`, `airport`, `other` |
| `kind` | string | yes | `added`, `removed`, `changed` |
| `summary` | string | yes | plain-English, ready to display |
| `source` | string | yes | FAA file it came from (`ATC_BASE`, `APT_RMK`, `d-TPP`, `CLS_ARSP_SHP` for the class airspace shapefile, ...) |
| `original` | string | no | raw FAA remark text (show under translated remarks) |
| `untranslated` | string | no | why a remark's `summary` shows FAA words, ready to display: all of it ("Kept in the FAA's words: Amend has no verified meaning for RT.") or a term the translation leaves as written because remarks use it more than one way ("NA is left as the FAA wrote it: it can mean not authorized or not available, and Amend doesn't guess which."). Absent when there's nothing to explain. Older `history/` entries may lack it |
| `fields` | array | no | `[{"field", "old", "new"}]` raw before/after values. A whole row added or removed lists its columns with `old` or `new` empty. `ATTENDANCE` (source `APT_ATT`) is the airport's whole attendance schedule, its rows' MONTH DAY HOUR joined with `; ` |
| `details` | array of string | no | the lines behind a grouped summary: route-level lines behind "preferred IFR routes", or each FAA frequency row (`removed: 125.2 BETHEL RCAG (LOW)`) behind a grouped frequency change, or a changed chart's courses and headings that moved on the plate (`printed on the chart: 074° -> 076°`, old edition's plate against the new one), or an approach's minimums that moved (`minimums on the plate: LNAV MDA 680 -> 700`, `minimums on the plate: RVR 5000 -> 4500 at LPV DA 503`; the line of minimums, such as `LPV DA`, `S-LOC 25`, `circling cat C` or `S-LOC 34 (XIKCY fix)`, is named when the plate makes it clear, otherwise it reads `minimum 680 -> 700`) |
| `procedures` | object | no | `{"updated": [...], "removed": [...]}` STAR/DP names |
| `chart` | object | no | `{"code", "name", "amdt", "pdf"?, "replaces"?}`. `pdf` links the new plate; absent for removed charts. `replaces` is the old name of a renumbered DP or STAR (`"MINNEAPOLIS NINE"`). A changed approach's summary says `amended (amdt X)` when the amendment is dated this edition, `redrawn (still amdt X)` when the FAA reissued the plate under an older amendment, and `changed (amdt X)` when the FAA gives no date |

## `airports.json`
Every airport in the current FAA cycle, for names and search (~20k entries, sorted by id).
Fields other than `id`, `name` are omitted when the FAA has no value.

```json
{"schema_version": 1, "cycle": "2026-10-01",
 "airports": [{"id": "BJC", "icao": "KBJC", "name": "Rocky Mountain Metro", "city": "Denver",
               "state": "CO", "type": "airport", "lat": 39.9088, "lon": -105.1172}]}
```
`type`: `airport`, `heliport`, `seaplane base`, `gliderport`, `ultralight`, `balloonport`.

## `history/<ID>.json`
Every change at an airport since Aug 2024, newest first.

```json
{"schema_version": 1, "airport": "VRB", "first_cycle": "2025-01-23", "last_cycle": "2025-07-10",
 "entries": [Change + {"cycle": "2025-07-10", "from_cycle": "2025-06-12"}, ...]}
```
Entries added since the engine was versioned also carry `"engine"` (like `"1.2.0"`), the
engine version that made them; older entries have no `engine`.
"What changed since X" = entries with `cycle` after X. Chart (d-TPP) history starts with the
2026-07-09 cycle; the FAA doesn't keep older metafiles online.

## `history/index.json`
```json
{"schema_version": 1, "cycles": ["2024-09-05", ...],
 "airports": {"VRB": {"entries": 14, "last_cycle": "2025-07-10", "action": 6}}}
```
## Processing log (in the repo, not served)
`audit/runs/<cycle>/` holds one file per engine run (the site build and each history cycle):
the FAA source files with checksums and retrieval times, rows read per file, changes by
priority, the input checks and release audit, and whether the run was built, blocked or
failed. Its full shape is documented at the top of `amend/runlog.py`, and it has its own
`runlog_version`.
