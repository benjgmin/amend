# Amend master spec (engineering)

What Amend is supposed to be, the rules the engine has to follow, and where the code stands against
each rule today. Read this before changing anything in `amend/`, and keep it current when the
architecture changes.

- How the code is laid out: [docs/architecture.md](docs/architecture.md)
- What a run does, step by step: [docs/data-pipeline.md](docs/data-pipeline.md)
- The public JSON contract: [SCHEMA.md](SCHEMA.md)

Line references (`file:line`) are against `master` at `8b18fdf`. They drift as code moves, so
treat them as pointers and re-check before relying on one.

This is the engineering part of a longer project spec. Product strategy and business planning
are kept out of the repo.

---

## 1. Purpose

Every 28 days the FAA publishes a new cycle of airport, airspace, frequency and chart data. Amend
answers one question for each US airport: **what changed this cycle?** It does that without making
anyone read CSV files, old/new records or chart supplements.

The long-term product is the **data engine and the structured change data it produces**. The web
site and the iOS app are how that data is shown and tested today. They are not the product, and
the engine must never depend on them.

Amend is a change layer. It does not replace current-data delivery, charts, NOTAMs, EFBs or
official FAA publications. **The FAA is the source of truth.** Amend transforms FAA data into
structured, traceable, understandable changes, and says where each one came from.

The near-term goal is a system that is:

1. technically correct
2. auditable
3. reliable
4. measurably better at interpreting FAA changes than a general-purpose AI model
5. useful enough that real aviation organizations choose to use it

## 2. Current state (corrected)

What's true on `master` today. Where an earlier draft of this spec said something different, the
correction is noted.

| Claim | Reality in this repo |
|---|---|
| FAA cycle data is processed | Yes. Every US airport, every cycle: NASR CSVs, d-TPP chart metadata and class airspace shapefiles (`amend/pipeline.py:69-149`). |
| History since about Aug 2024 | Yes for NASR: 27 cycles diffed, 2024-09-05 through 2026-09-03 (`history/cycles.json`), starting from the oldest cycle in the FAA archive, 2024-08-08 (`amend/cycles.py:14`). Chart (d-TPP) history only starts Oct 2026 because the FAA doesn't keep old metafiles online (`SCHEMA.md:82-83`). |
| Future cycles are stored | Change history is stored and committed (`history/`). **The raw FAA files are not**: each zip is deleted after it's diffed (`amend/history.py:95-98`) and the Actions cache keeps only the newest three (`.github/workflows/update.yml:109-114`). |
| "Processed within about two minutes of publication" | **Wrong.** A scheduled job checks every 3 hours at :17 (`update.yml:9`), and GitHub can delay or drop scheduled runs. New FAA data is usually live **within a few hours** of being posted. A rebuild is also forced at least every 20 hours (`amend/freshness.py:23`). |
| "AI is implemented as part of the application" | **Wrong.** AI runs only at build time, only on remark text, through one model (`amend/remarks.py:7`). Diffing, classification, ranking and every other summary are plain deterministic code. The web pages and the iOS app never call a model. |
| An API exists | Not as a server. The public JSON on amend.watch (`SCHEMA.md`) is the de facto read-only API. There is no database, no auth and no server. |
| Tests | 90 unit tests (`tests/`). They gate every deploy (`update.yml:66-67`) and, from this change on, every pull request (`.github/workflows/tests.yml`). |

Nothing above is production-grade just because it works. The project replaces assumptions with
tests, measurements and observability, one step at a time.

## 3. Non-negotiable rules

1. **FAA data is the truth. AI is never the truth.** The chain is: the FAA says X; Amend determines
   X changed to Y; Amend validates X to Y; AI may explain X to Y. Never: AI reads FAA data and
   decides what happened.
2. **Deterministic first.** Whether two values differ, what kind of change it is and how much it
   matters are decided by code, never by a model. AI is used only where interpretation genuinely
   helps.
3. **The no-guess rule** (section 6). An unknown FAA term keeps its original text. This is enforced
   in code, not just requested in a prompt.
4. **Never publish obviously broken data.** If a run looks wrong, stop and leave the last good
   site up (section 7).
5. **Keep provenance.** Every published change should be traceable to its FAA source (section 8).
6. **No fake numbers.** Every metric shown anywhere comes from the actual processing system. No
   accuracy percentage without a dataset and method behind it.
7. **When uncertain, say so. When unknown, show the source. When something fails, expose it.**

## 4. Pipeline

Target shape. Each stage should be independently observable.

```text
FAA source
  -> 1 ingestion        -> 2 raw storage       -> 3 parsing
  -> 4 normalization    -> 5 deterministic diff -> 6 change classification
  -> 7 impact ranking   -> 8 glossary           -> 9 AI interpretation
  -> 10 validation      -> 11 structured data   -> 12 API
  -> web / iOS / other consumers
```

How each stage maps to the code today. Detail is in [docs/data-pipeline.md](docs/data-pipeline.md).

| # | Stage | Requirement | Today |
|---|---|---|---|
| 1 | Ingestion | Identify the cycle, download, record retrieval time, source URL and checksums, detect incomplete downloads, malformed files, unexpected file and record counts. | Cycle math and URLs in `amend/cycles.py:12-53`. Downloads retry, check `Content-Length`, reject HTML error pages, test every zip CRC, require 7 core CSVs and parse XML to the end (`cycles.py:78-180`). **Missing:** retrieval time, checksums, file counts and record counts aren't recorded or compared. |
| 2 | Raw storage | Immutable raw source per cycle with metadata (cycle, retrieved_at, source, file and record counts, checksum, engine version). Never depend on the live FAA file alone. | **Missing.** Zips are deleted after use (`history.py:95-98`). |
| 3 | Parsing | Read every file; a parse error is a failure. | `amend/nasr.py:123-162`. **Weak:** a `csv.Error` prints a warning and drops the rest of that file (`nasr.py:160-161`), and a second file with the same name in a nested zip is skipped silently (`nasr.py:130`). |
| 4 | Normalization | Canonical values before comparison, so `1200-0400Z` and `1200Z-0400Z` don't read as a change. | **Partial and ad hoc:** noise columns (`amend/rules.py:112-124`), survey rounding (`rules.py:78-80`, `132-141`), remark spelling variants (`amend/diff.py:78-86`). No normalization layer for hours, frequencies or runway ids. |
| 5 | Diff | Structured additions, deletions and field-level modifications with old and new values, no AI. | `diff.py:147-220`. Rows are paired by per-file keys (`rules.py:21-35`) or, without keys, by at least 50% matching columns. **Weak:** pairing is greedy and order-dependent (`diff.py:162-173`), and exact duplicate rows collapse into one (`diff.py:151-155`). |
| 6 | Classification | Deterministic category from source fields. | `pipeline.py:21-33`: tower, airspace, frequency, navaid, runway, remark, procedure, route, chart, weather, airport, other. |
| 7 | Impact | Explainable ranking; never hide the underlying change. | `action` / `ifr` / `fyi` / `hidden` from `diff.py:30-59` plus special cases (lighting remarks `diff.py:134-144`, declared distances `diff.py:62-75`, runway renumbering `amend/collapse.py:42-88`). Hidden changes are counted per airport, not listed (`pipeline.py:105-106`). |
| 8 | Glossary | Verified terms with expansion, definition, source, verification status, aliases and context; unknown terms go to a review queue. | **Partial:** 78 entries (81 terms counting aliases) as a Python string and dict (`amend/remarks.py:16-70`). No source, no verified flag, no review queue. |
| 9 | AI | Structured facts in, explanation out, raw source kept alongside. | Remark text only, batched 30 at a time, cached in `remark_cache.json` (`remarks.py:87-118`). The raw FAA text is always kept as `original` (`amend/english.py:153-157`). |
| 10 | Validation | Schema-check AI output; check values against the source; halt on anomalies. | **Partial:** see sections 6 and 7. |
| 11-12 | Data layer and API | Versioned, structured, with provenance. | Static JSON per airport and cycle on GitHub Pages (`SCHEMA.md`), versioned by `schema_version` (`amend/__init__.py:3`). No engine version. |

## 5. Change output

Target record, per the spec:

```json
{"airport": "VRB", "field": "tower_hours", "old_value": "0700-2300", "new_value": "0700-0100",
 "change_type": "MODIFIED", "source_cycle": "2025-07-10"}
```

Today's public record is the `Change` object in `SCHEMA.md:48-62`: `id`, `priority`, `category`,
`kind`, `summary`, `source`, plus `fields` (`[{field, old, new}]`), `original`, `details`,
`procedures` and `chart` where they apply. Raw old and new values are already there for field
changes. What's missing is the source record key, the engine version and a validation status
(section 8).

`id` is `sha1(airport|cycle|summary)` (`pipeline.py:48-50`), so any rewording of a summary changes
the id. It needs to become a hash of the source record, not of the text.

## 6. AI and the no-guess rule

AI is an interpretation layer. It gets established facts and explains them. It never decides what
changed.

**The rule:**

- A term in the verified glossary: use the verified expansion.
- A term the system doesn't know: don't invent an expansion, don't guess. Keep the original FAA
  text. "ABCD changed from X to Y" is right; "ABCD means [guess]" is not.
- This must be enforced by code. A prompt alone is not enforcement.

**Today** (`amend/remarks.py`):

- The prompt tells the model to expand only glossary terms or ones it's certain of, and never to
  guess (`remarks.py:72-84`).
- Code rejects a translation that gets one of the 31 `MUST_KEEP` terms wrong, drops or adds a
  number, or tells pilots to "contact" a pilot-controlled lighting frequency (`remarks.py:133-147`).
  A rejected translation isn't published: the raw FAA text shows and the remark is retried next
  run. The whole cache is re-checked on every run (`remarks.py:94`).
- A wrong-length batch is discarded (`remarks.py:110-113`), and any API error falls back to raw
  text (`remarks.py:114-115`).
- **Gap:** every contraction outside `MUST_KEEP` is checked only by the prompt. A model expanding an
  unknown term passes. Enforcement means: any contraction in the raw text that isn't in the verified
  glossary must appear verbatim in the output, or the translation is rejected. The glossary needs to
  grow (verified against FAA Order JO 7340.2) before that check is switched on, or a large share of
  remarks falls back to raw text.
- **Gap:** nothing catches a dropped negation (`NOT`, `NO`, `CLSD`, `UNAVBL`), items aren't
  type-checked, and token usage and cost aren't recorded (`remarks.py:160-171` ignores `usage`).

**Cost control.** Only meaningful changes reach the model: noise is filtered and events are
collapsed first, and only remark text is sent. Outputs are cached and never regenerated for text
that was already translated. Still to do: track tokens, requests and cost per cycle.

**Failure modes to watch:** invented abbreviations, unsupported claims, wrong old or new values,
missed changes, wrong classification, malformed output, timeouts and API failures. AI output should
be schema-validated before it's published.

## 7. Validation

### Regression tests

Before changing important code: read the current code, pin its behavior with tests, make the
change, run the existing tests, add tests for the new behavior, compare benchmark results, look at
regressions, document the change. "It should work" is never evidence; the tests are.

Today: 90 unit tests, many built from real FAA cases (`tests/test_amend.py:215`,
`TestAccuracyAudit`). **Gap:** no end-to-end snapshot of a real cycle pair, so a rule change that
moves thousands of outputs still reads as "tests pass".

### Gold dataset

A hand-verified set of real changes, starting at 100 to 500. Each case records the FAA source,
cycle, airport, field, old value, new value, expected classification, expected interpretation and
the terminology involved. Every significant engine change runs against it and reports a score
("487 / 487", or whatever the real number is). **Today: doesn't exist yet.**

### Benchmark against general-purpose AI

Real FAA changes with verified answers, given to a general-purpose model and to Amend. Measure
correct and missed changes, false changes, wrong old and new values, wrong abbreviations,
hallucinations, unsupported claims and summary accuracy. Repeatable and versioned. Never claim
"Amend wins every time" unless the benchmark shows it. The point is to find Amend's weaknesses.
**Today: doesn't exist yet.**

### Anomaly detection

The engine must notice suspicious results and be able to stop publication. Examples: record counts
collapsing against the last cycle, change counts exploding, zero files, thousands of unknown terms
(warning).

Today on `master`:

- Downloads: missing required files, corrupt zips, truncated files and HTML error pages stop the
  run (`cycles.py:111-180`). A failed download is never read as "not posted" (`cycles.py:66-69`).
- Site: `verify` refuses to deploy an empty or inconsistent site (`amend/freshness.py:110-158`).
  Any failed step means nothing is committed or deployed and the last good site stays live
  (`update.yml:87-90`).
- Output-side checks (airport counts, change counts against a 13-cycle median, impossible values)
  are in an open pull request (#19), not merged.
- **Missing:** input-side checks. Per-file row counts aren't compared with the last cycle, and a
  parse error isn't a failure (`nasr.py:160-161`).

### Processing log

Every run should write a record: cycle, source URLs, retrieved_at, file checksums and sizes, record
counts, changes by priority, AI requests, tokens, cost and rejections, unknown terms, validation
result, published or not, engine version, duration. **Today:** stdout in the Actions log, plus
`build.json` with the commit and an input hash (`amend/latest.py:56-58`). A partial per-cycle log
is in open PR #19.

### Engine health view

Overview (current and last successful cycle, status, totals, duration, engine version), each
pipeline stage's result, errors and warnings, a per-change inspector (raw record, normalized
record, classification, AI text, glossary terms, validation, engine version) and past runs. Every
number comes from the processing log. GitHub Pages can't protect a page, so this starts as a
generated report (Actions run summary, or a local command that renders the log), not a hosted
dashboard with auth. **Today: doesn't exist.**

## 8. Provenance and history

Every user-visible change should be traceable to: the FAA source, the cycle, the source record,
the engine version that processed it, the deterministic change, the AI text if any, and the
validation result. Users should be able to open the original source where practical.

Today: each change has its `source` file, raw `fields`, the raw remark as `original`, and an "FAA
source" link to that cycle's NASR page or the d-TPP plate (`amend/web.py:526-536`). **Missing:** the
source record key, engine version and validation status on each change, and the link points to the
cycle rather than the record.

History is a core asset: every cycle is kept, so "what changed at this airport since Aug 2024" and
"when did this frequency change" are answerable (`history/<ID>.json`, `SCHEMA.md:75-83`). Keeping the
raw FAA files (section 4, stage 2) is what makes that history re-checkable.

## 9. API

Eventually versioned endpoints like:

```text
GET /airports/{id}/changes           GET /cycles/latest
GET /airports/{id}/changes/latest    GET /cycles/{cycle}
GET /airports/{id}/changes/{cycle}   GET /changes/{id}
GET /search
```

Each change carries its old value, new value, summary and a source block (`provider`, `cycle`).
Don't expose internals needlessly. Today the static files in `SCHEMA.md` cover most of the reads;
`GET /changes/{id}` needs stable ids first (section 5).

Security for outside consumers (auth, rate limits, versioning, uptime monitoring, backups, retention
policy, error monitoring, documented cadence, a clear "the FAA is authoritative" disclaimer) gets
built as real demand appears, not before.

## 10. Public trust layer

Users should be able to answer: where does this data come from, when was it last updated, which
cycle am I looking at, how did Amend decide something changed, how is AI used, what happens when AI
doesn't understand something, how are errors caught, how do I report one, is Amend working right
now, and what are its limits.

Minimum before broad public testing. Status is for `master`; open PRs are noted.

| Item | Requirement | Status |
|---|---|---|
| Changelog | Dated technical history: data, engine, glossary, validation and infra changes, known issues. Not marketing. | Missing (a short "recent updates" list is in PR #21) |
| Status page | Site, FAA ingestion, latest cycle, processing, history. **Must tell an FAA delay apart from an Amend failure**, and show last success and incidents. Written by every run, including failed ones. | Missing. The page footer shows the cycle and build time (`web.py:669-675`), and pages flag themselves after 36h (`web.py:660`). |
| How Amend works | FAA source, then Amend processing, then AI interpretation, clearly separated. AI is never presented as the source. | Short version on the About page (`web.py:918-920`) and README. Its "a daily job" wording is out of date: the job checks every 3 hours. |
| Data sources | Datasets, cycles, retrieval, coverage, latency. | Partial: README links, per-change FAA source link. |
| Disclaimer | Independent, processes public FAA data, verify against official sources, not error-free, no FAA affiliation. | Exists: "Not for navigation" on every page (`web.py:610`, `web.py:637`). Have it reviewed before public testing. |
| Terms of use | What the service is, acceptable use, availability, user responsibility, third-party sources. | Missing |
| Privacy policy | Only what the system actually does: hosting logs, analytics, local storage, fonts, any form. | Missing on `master` (drafted in PR #21) |
| Report an error | Wrong, missing or stale change, wrong term or AI text, broken link. No account required. | Missing on `master` (PR #21 links GitHub issues, which need an account) |
| Accuracy and validation | How results are checked, with real numbers only. No invented percentages. | Missing |
| Known limitations | Supported and unsupported data, AI limits, latency, coverage, edge cases. | Partial (PR #21) |
| Provenance | Where practical, on each change. | Partial (section 8) |
| Health monitoring | Real monitoring of the running service. | Partial: deploy gate and a daily failure check; no external uptime check. |

Accounts, auth, email collection, server-side watchlists, payments and API keys don't exist and
shouldn't be built just to look mature. When any of them, or any new third-party service, is added,
update the privacy policy and terms first. Never say "we collect no data" unless the infrastructure
backs it up.

## 11. Working on this repo

### Workflow

Every significant task: understand, plan, test, implement, run tests, validate, document. For big
passes: audit, then plan, then an approval checkpoint, then implement. This spec is the
destination, not permission to build everything at once.

A feature is done when it's implemented, tested, validated, observable and documented. For
data-processing changes add integration tests, the gold dataset, a regression run on real FAA
data and a check of the health output.

### Ownership

When several agents or people work at once, each owns a subsystem (ingestion and diff; AI and
glossary; data and API; health view; web and iOS). Don't let two change the same files at the same
time. If a task crosses a boundary, write the dependency down.

### Rules for Claude and anyone else changing Amend

1. Don't invent data.
2. Don't invent FAA terminology.
3. Don't silently change behavior.
4. Don't remove or weaken tests to make them pass.
5. Don't disable validation.
6. Don't fabricate metrics.
7. Don't treat AI output as authoritative FAA data.
8. Don't rewrite unrelated systems.
9. Preserve existing behavior unless the change is explicitly about it.
10. Explain important architectural changes.
11. Add tests for meaningful new behavior.
12. Run the relevant tests.
13. Report failures honestly.
14. Update the docs when the architecture changes.
15. Prefer deterministic logic over AI whenever it's enough.
16. Preserve source provenance.
17. Never guess an unknown FAA abbreviation.
18. If uncertain, keep the original source text.
19. Never claim production readiness without evidence.
20. Never say something works without testing it.

### Model and effort

Pick model strength by the cost of a mistake, not the size of the task. Strongest reasoning for
anything that can corrupt data: ingestion, normalization, diff, classification, validation,
regression architecture, provenance, AI interpretation, security, the data contract and correctness
bugs. Strong reasoning for planning, backend work, test design and review. Lighter settings for UI,
docs, simple tests and mechanical refactors. For critical work, prefer fewer careful passes over
many shallow ones, and never merge a worker's change without inspecting it and running the tests.

### Docs

The repo, not a conversation, is where decisions live. `AMEND_MASTER_SPEC.md` plus `docs/`
(architecture and data pipeline now; ingestion, normalization, diff engine, classification, AI
system, glossary, validation, health view, API, security and decisions as those parts are built).

## 12. Phase 1: make the engine trustworthy

In order. Status is for `master`.

| # | Item | Status |
|---|---|---|
| 1 | Understand the current architecture | Done (audit, Sep 2026) |
| 2 | Document the current pipeline | This change |
| 3 | Regression test infrastructure | Partial: 90 tests, now on every PR; no snapshot test |
| 4 | Gold-standard dataset | Missing |
| 5 | Harden the deterministic diff | Partial (section 4, stages 4-5) |
| 6 | Verified glossary | Partial (section 4, stage 8) |
| 7 | No-guess enforced in code | Partial (section 6) |
| 8 | Provenance | Partial (section 8) |
| 9 | AI output validation | Partial (section 6) |
| 10 | Processing logs | Missing on `master` (partial in PR #19) |
| 11 | Anomaly detection | Download and deploy gates on `master`; output checks in PR #19; input checks missing |
| 12 | Engine health view | Missing |

Not in phase 1, and not until there's demand: accounts, a server, a database, a hosted API,
protected dashboards.

## 13. Operating principle

**Never ask the user to trust something the system could prove.** If the system can prove what the
FAA published, what changed, how Amend interpreted it, which terms it used, which engine version
processed it and whether validation passed, show that. If something is uncertain, say so. If it's
unknown, show the source. If something fails, expose it. When the AI gets something wrong, catch
it, log it, fix the system and add the case to the regression set.

The goal isn't for Amend to look perfect. It's for Amend to be reliably correct, and transparent
when it isn't.
