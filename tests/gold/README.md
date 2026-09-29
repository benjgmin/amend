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
| `reviews` | optional: flight instructors' answers, added by `--record` (below): `by`, `date`, `verdict` (`right`, `wrong`, `unsure`), optional `why` (`too_high`, `too_low`, `wording`, `missed`), `note`, `packet`, `response` |
| `expected_was` | a gold expectation that was changed after the case was written: the old `priority` and `changed_because`. a person should confirm these |

The test fails when a case fails, unless it's a `known_failure`. A known failure that starts
passing fails too, so whoever fixed the engine drops the flag and the fix is on record.

### status of the seed set

Every seed case started as `"verified_by": "claude, against the FAA source rows; needs human check"`.
Claude read the real FAA rows for each one and set the expected answer. `python -m amend.gold`
prints how many a person has checked.

On 2026-09-28 ben hand-checked 21 of them (17 seed cases plus g124-g127, the judgment calls the
diff fixes flagged at TIX, PAM, SBM and 5A6). Each was shown with the FAA's old and new text side by
side, abbreviations decoded only from the FAA's lists, next to amend's line and priority. All 21
came back right. Only cases a person answered count: "not sure" leaves a case unchecked, and g084
(LUF class D hours) stays unchecked because it was okayed without the FAA text in view.

### instructor reviews

Flight instructors check cases with a review packet: each case shows what the FAA changed (FAA
abbreviations decoded only from the FAA's lists) and what amend shows, and the instructor answers
right, wrong or not sure. The packet saves the answers as JSON:

```
{"id": "r-7f3a", "packet": "instructor-review-v1", "date": "2026-09-30",
 "reviewer": {"credit": "J.S.", "certificates": "CFII"},
 "answers": {"g002": {"verdict": "right"},
             "g005": {"verdict": "wrong", "why": ["too_low"], "note": "..."}}}
```

```
python -m amend.gold --record answers.json --dry-run   # what it would add
python -m amend.gold --record answers.json             # add them to cases.jsonl, then commit
```

- only a case with an answer is recorded. a blank one is skipped and never counts as checked.
- `right` counts the case as checked by a person. `unsure` is kept on record and doesn't count.
- `wrong` marks the case disputed (`python -m amend.gold` lists it) and leaves `expected` alone:
  someone reads the note against the FAA rows, then fixes the engine or the case in its own PR.
- `credit` is how the instructor agreed to be named in this public file: a name, initials, or
  empty for "not named". Contact details are never written here.
- the same packet recorded twice adds nothing.

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

The test needs the two NASR zips named in `snapshot.json` in `data/`, checked by sha256. The
FAA's links roll off its site after a while, but both files are kept byte for byte on this
repo's releases (the `archive` urls in `snapshot.json`):

```
python -m amend.gold --fetch                  # both zips into data/, sha256-checked
python -m unittest tests.test_snapshot -v     # about a minute
```

Every PR's tests do the same (`.github/workflows/tests.yml`), so a PR that changes what the
engine says at these airports fails there until the snapshot is updated in the same PR. Locally
the test skips without the zips; in PR tests (`AMEND_SNAPSHOT=required`) it fails instead. The
deploy (`update.yml`) runs its tests before it restores any FAA files, so the snapshot never
blocks an FAA update. If `--fetch` can't verify certificates (some macOS Pythons), `curl -L
--create-dirs -o data/<file> <archive url>` does the same, and the test checks the sha256.

Moving the snapshot to a newer cycle pair: both cycles need a `faa-<cycle>` release (the
"archive raw FAA files" workflow makes them). Put the new pair's cycles, files, urls, archive
urls, sha256 and bytes in `snapshot.json` (the release's `manifest.json` has them), run
`--fetch` and `--update-snapshot`, delete the old snapshot file, and commit both.

Output no longer depends on Python's string hashing at all, so it gives the same file on any
seed and any Python version (checked on 3.10, which hashes strings differently from 3.11+).

After a change you meant to make, `python -m amend.gold --update-snapshot` rewrites the file.
Review its diff like code: every line that moved is a change in what pilots see.
