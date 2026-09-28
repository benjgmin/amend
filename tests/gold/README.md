# gold set and snapshot

Two regression checks for the engine. Run both before and after any change to `diff.py`,
`collapse.py`, `rules.py`, `english.py` or `pipeline.py`.

```
python -m unittest discover -s tests -t .     # everything, including both checks
python -m amend.gold -v                       # gold set score, every failing case
python -m amend.gold --snapshot               # snapshot diff (needs the zips, below)
```

## gold set: `cases.jsonl`

One real FAA change per line, with the answer the engine should give. Each case carries the
FAA rows it came from, so it runs through the whole pipeline without downloading anything.
Cases run in all-airports mode, the way the site builds: a row belongs to an airport only when
its id column names it. The command line's `diff OLD NEW DAB` mode matches more loosely, so
it can show rows about other airports (see the PR that added this).

| key | what |
| --- | --- |
| `id` | unique, `g` + number |
| `source` | FAA file, e.g. `APT_RWY.csv` |
| `from_cycle`, `cycle` | the two NASR cycles (effective dates) |
| `airport` | FAA id, no K (`DAB`, `7FL6`) |
| `field` | the FAA column that changed (`ROW` when a whole row was added or removed) |
| `old`, `new` | its values ("" when there was none) |
| `kind` | `changed`, `added` or `removed` |
| `rows` | `header` (the file's columns) and the real `old` and `new` rows at that airport |
| `extra_files` | optional: other files both cycles need, same shape as `rows` without old/new |
| `expected.priority` | `action`, `ifr`, `fyi`, or `hidden` (bookkeeping, the engine should say nothing) |
| `expected.category` | `tower`, `frequency`, `runway`, `remark`, `navaid`, `airport`, ... (see SCHEMA.md) |
| `expected.summary_contains` | text the plain-English line must include (FAA values, not paraphrase) |
| `expected.summary_lacks` | optional: text it must not include (a guessed expansion, a wrong word) |
| `terms` | optional: FAA contractions in the text (`PPR`, `CLSD`, `SS-SR`) |
| `notes` | why the answer is what it is |
| `verified_by` | who checked the answer against the FAA source |
| `evidence` | where the rows came from |
| `known_failure` | `true` when the engine gets it wrong today (a candidate engine bug) |
| `why_engine_is_wrong`, `engine_says` | with `known_failure`: the rule that gets it wrong, and what the engine says today |
| `engine_was_wrong_because`, `engine_said_before_fix` | a known failure that got fixed: the same two notes, kept on record |

The test fails when a case fails, unless it's a `known_failure`. A known failure that starts
passing fails too, so whoever fixed the engine drops the flag and the fix is on record.

### status of the seed set

Every seed case says `"verified_by": "claude, against the FAA source rows; needs human check"`.
Claude read the real FAA rows for each one and set the expected answer; nobody has hand-checked
them yet. `python -m amend.gold` prints how many a person has checked.

### adding your own hand-checked airports

1. Find the change in the FAA data (the NASR CSV zip for both cycles, or amend's `--raw` output:
   `python -m amend diff OLD.zip NEW.zip DAB --raw`).
2. Copy the file's header and the old and new rows at that airport into `rows`. Keep every
   column: the engine pairs rows by how much of them match, so trimmed rows can behave
   differently.
3. Set `expected` to what a pilot needs to hear, not to what amend says today. If they differ,
   add `"known_failure": true` and `"engine_says"`.
4. Put your name or handle in `verified_by`, e.g. `"ben, hand-checked against the chart supplement"`.
   To confirm a seed case, replace its `verified_by` the same way.
5. `python -m amend.gold -v` and commit.

## snapshot: `snapshot.json` + `snapshot_<from>_<to>.json`

What the engine says today about one real cycle pair for every airport on the watchlists plus
the busiest airports (the list is frozen in `snapshot.json`, so adding a watchlist doesn't
change it). No remark translations, no charts, no airspace shapes: NASR only. It runs in
all-airports mode like the site, in a child process with a random `PYTHONHASHSEED`: the same
FAA files must give the same output on every run (the engine used to pair rows in set order,
so it didn't).

The test needs the two NASR zips named in `snapshot.json` in `data/`, checked by sha256, and
skips without them. The FAA URLs are in `snapshot.json`; they roll off the FAA site after a
while. The raw archive keeps them as GitHub releases (tag `faa-<cycle>`, e.g.
`https://github.com/benjgmin/amend/releases/download/faa-2026-08-06/06_Aug_2026_CSV.zip`),
which is also how to get them where faa.gov can't be reached.

After a change you meant to make, `python -m amend.gold --update-snapshot` rewrites the file.
Review its diff like code: every line that moved is a change in what pilots see.
