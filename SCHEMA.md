# Cyclewatch JSON format (schema_version 1)

Everything is served from `https://benjgmin.github.io/cyclewatch/`. All airport ids are FAA
ids (`VRB`, not `KVRB`). All cycle dates are ISO dates (`2026-10-01`) of the FAA effective
date. Files are minified UTF-8 JSON.

If a field is added, `schema_version` stays the same. If a field is renamed or removed, it goes up.

## `latest/meta.json`
Which cycles `latest/` compares.

| field | type | notes |
|---|---|---|
| `schema_version` | int | |
| `from_cycle`, `to_cycle` | string | ISO dates |
| `upcoming` | bool | `true`: `to_cycle` hasn't taken effect yet |
| `includes_charts` | bool | d-TPP chart changes included |
| `changed_airports` | int | |
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
| `id` | string | yes | 12-char stable id (airport + cycle + summary). Use it to remember what's been seen |
| `priority` | string | yes | `action` (changes how you fly), `ifr` (procedures/charts/routes), `fyi` |
| `category` | string | yes | `tower`, `airspace`, `frequency`, `navaid`, `runway`, `remark`, `procedure`, `route`, `chart`, `weather`, `airport`, `other` |
| `kind` | string | yes | `added`, `removed`, `changed` |
| `summary` | string | yes | plain-English, ready to display |
| `source` | string | yes | FAA file it came from (`ATC_BASE`, `APT_RMK`, `d-TPP`, ...) |
| `original` | string | no | raw FAA remark text (show under translated remarks) |
| `fields` | array | no | `[{"field", "old", "new"}]` raw before/after values |
| `details` | array of string | no | route-level lines behind a "preferred IFR routes" summary |
| `procedures` | object | no | `{"updated": [...], "removed": [...]}` STAR/DP names |
| `chart` | object | no | `{"code", "name", "amdt", "pdf"?}`. `pdf` links the new plate; absent for removed charts |

## `history/<ID>.json`
Every change at an airport since Aug 2024, newest first.

```json
{"schema_version": 1, "airport": "VRB", "first_cycle": "2025-01-23", "last_cycle": "2025-07-10",
 "entries": [Change + {"cycle": "2025-07-10", "from_cycle": "2025-06-12"}, ...]}
```
"What changed since X" = entries with `cycle` after X. Chart (d-TPP) history starts Oct 2026;
the FAA doesn't keep older metafiles online.

## `history/index.json`
```json
{"schema_version": 1, "cycles": ["2024-09-05", ...],
 "airports": {"VRB": {"entries": 14, "last_cycle": "2025-07-10", "action": 6}}}
```
