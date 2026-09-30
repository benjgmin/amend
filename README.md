<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/lockup-dark.svg">
    <img src="docs/brand/lockup-light.svg" alt="amend" height="56">
  </picture>
</p>

<h3 align="center">What changed at your airport, every FAA cycle.</h3>

<p align="center">
  <a href="https://amend.watch/"><b>amend.watch</b></a> ·
  <a href="https://docs.amend.watch/how-it-works/">How it works</a> ·
  <a href="https://amend.watch/guide/">Guide</a> ·
  <a href="mailto:hello@amend.watch">Report a problem</a>
</p>

Every 28 days the FAA publishes a new cycle of airport, airspace, frequency and chart data. The changes that matter (tower hours, a decommissioned VOR, a renumbered runway, an amended approach) are buried among tens of thousands of rows of bookkeeping noise. Amend diffs every cycle for every US airport, filters out the noise, and explains what's left in plain English, ranked by how much it matters when you fly there. It shows upcoming changes up to three weeks before they take effect.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/web/airport-dark.png">
  <img src="docs/screenshots/web/airport-light.png" alt="The Charlotte/Douglas Intl page on amend.watch: 128 changes in the 03 Sep 2026 cycle, 18 of them action items">
</picture>

## Why

Vero Beach's tower hours changed twice in six months, and nothing tells you when that happens. Amend's history shows exactly what changed:

```
VRB  Vero Beach Rgnl
 EFF 10 JUL 2025   !! tower hours: 0700-2300 -> 0700-0100 local
                   !! airspace: class d svc 0700-2300 -> class d svc 0700-0100
 EFF 23 JAN 2025   !! tower hours: 0700-2100 -> 0700-2300 local
                   !! airspace: class d svc 0700-2100 -> class d svc 0700-2300
```

## On the web

**[amend.watch](https://amend.watch/)** is the whole tool, no account needed.

- **Any airport:** search by FAA id, ICAO, name or city, or go straight to one like [amend.watch/VRB](https://amend.watch/VRB/) (amend.watch/kvrb works too). Every airport shows what changed this cycle, what's coming next cycle, and its history back to Aug 2024
- **Ranked:** `ACT` (could change your plan), `IFR` (approaches, STARs, departures, routes) and `FYI`, with the FAA's original text behind every translated remark
- **Lists:** keep as many lists of airports as you like (one for your training area, one per trip), saved in your browser. Share any list as one link, or give it a name under /list/, like [amend.watch/list/daytona-training](https://amend.watch/list/daytona-training/)
- **Alerts:** every airport and named list has an RSS feed (like [amend.watch/VRB/feed.xml](https://amend.watch/VRB/feed.xml)), one update per FAA cycle, action items first. There's also a [calendar of cycle dates](https://amend.watch/cycles.ics)
- **Link previews:** a page shared in iMessage or a group chat shows what changed

## The iPhone app

In testing, not on the App Store yet. SwiftUI, iOS 17+, light and dark.

- **Your airports** with a home field pinned on top, each showing its `ACT`, `IFR` and `FYI` counts
- **Search, upcoming and history** for every US airport, same data as the site
- **Approach plates in the app:** amended charts open right inside Amend, with zoom and share
- **Notifications** once per cycle when your airports are affected: any change at your home field, action items elsewhere

## How it runs

There is no server. A GitHub Actions workflow checks the FAA every 10 minutes and rebuilds only when something is new. It downloads the NASR 28-day subscription, the d-TPP chart metadata and the class airspace shapefiles, diffs every US airport, audits the result, and publishes static JSON and HTML to GitHub Pages. The site and the app only read those files.

- **Fast:** new FAA data is usually live about 20 minutes after the FAA posts it
- **Weeks ahead:** the FAA posts each cycle weeks before it takes effect, so Amend shows it as upcoming. Pages and the app switch it to in effect at exactly 0901Z on cycle day, by the clock, even with the page open
- **Checked before it ships:** tests built from real FAA cases run on every pull request and before every deploy. Each cycle is audited before it's published (dates off the 28-day schedule, duplicates, a chart link from the wrong cycle, action counts wildly off from past cycles), and a failed check keeps the last good version up. [status.amend.watch](https://status.amend.watch/) shows every recent run
- **Every raw FAA cycle is kept:** the untouched FAA files from Mar 2022 on are archived as [GitHub releases](https://github.com/benjgmin/amend/releases) tagged `faa-<cycle>`

### What it catches

- **Airports:** tower and Class D hours, frequencies, runways (renumbering, replacements, declared distances), attendance hours, contacts, new and closed airports, remarks
- **Airspace:** class B, C, D and E surface area floors, ceilings and boundaries, told from each airport's point of view ("Orlando class B over the field: 3,000-10,000 ft MSL -> 2,500-10,000 ft MSL")
- **Navaids:** decommissioned or changed VORs, VORTACs and DMEs within 10 NM of an airport
- **Charts:** added, amended and removed approaches, departures, STARs and airport diagrams, with links to the new plates. Amended STARs and DPs are compared down to the waypoint ("MINEE6 (was MINEE5): waypoints removed FUPGE, LBV, RINSE")
- **Not the noise:** survey dates, pavement codes, coordinate rounding, duplicate files and reworded remarks are hidden or demoted, and one real event (a renumbered runway, a new STAR version) becomes one line instead of dozens of raw rows

What it doesn't cover (NOTAMs, anything between cycles) is on [docs.amend.watch/accuracy](https://docs.amend.watch/accuracy/).

### Where AI is used

Only to turn FAA remark contractions ("RSCD NOT MNT 2300-0600 M-F") into plain English. Code checks every translation against the FAA's own contraction list and the original numbers and codes; one that fails shows the FAA's words instead. In the Oct 2026 preview, 94% of the remarks you see on Amend read in plain English. Everything that decides what changed and how it ranks is code.

## Data and API

The public JSON behind the site is the API: one file per airport, documented in [SCHEMA.md](SCHEMA.md) and at [docs.amend.watch/api](https://docs.amend.watch/api/).

## Found something wrong?

Email [hello@amend.watch](mailto:hello@amend.watch) with the airport, the cycle and what the FAA source says. No GitHub account needed. Developers can also [open an issue](https://github.com/benjgmin/amend/issues/new).

## Independence and privacy

- Amend is an independent project, not affiliated with or endorsed by the FAA.
- No accounts and no cookies. Lists live in your browser. Visitor counts come from Cloudflare Web Analytics, which is cookie-free. Details at [amend.watch/privacy](https://amend.watch/privacy/).

## Repo layout

| path | what |
|---|---|
| `amend/nasr.py`, `diff.py` | reading FAA zips and diffing two cycles |
| `amend/rules.py` | what counts as noise and how much each change matters. tuning happens here |
| `amend/collapse.py`, `english.py` | raw rows into events and plain-English lines |
| `amend/remarks.py`, `glossary.py` | remark translation and the checks it has to pass |
| `amend/dtpp.py`, `procedures.py`, `airspace.py` | charts, waypoint-level STAR / DP changes, class airspace |
| `amend/pipeline.py` | the whole diff in one call, public JSON shape |
| `amend/history.py`, `latest.py` | history timeline and the published site |
| `amend/freshness.py`, `audit.py`, `runlog.py` | "anything new?", the checks that stop a bad cycle, the run log in `audit/runs/` |
| `amend/archive.py` | the raw FAA cycle releases |
| `amend/web.py`, `feeds.py` | the web pages and RSS feeds |
| `ios/` | the SwiftUI app |
| `cloudflare/` | the proxy that serves status.amend.watch and docs.amend.watch |
| `tests/` | regression tests from real FAA cases, plus the gold set in `tests/gold/` |
| `docs/` | [architecture](docs/architecture.md), [data pipeline](docs/data-pipeline.md), brand |

## Run it locally

Python 3.11+, standard library only. Pillow is optional and draws the link-preview images.

```bash
python -m amend set-key            # one time: Anthropic key for --llm, saved to .env

python -m amend diff 03_Sep_2026_CSV.zip 01_Oct_2026_CSV.zip VRB DAB ISM --llm
python -m amend diff 03_Sep_2026_CSV.zip 01_Oct_2026_CSV.zip --all-airports --dtpp d-tpp_Metafile.xml

python -m amend history            # build/extend history/ back to Aug 2024
python -m amend latest             # build site/ (what the workflow runs)

python -m unittest discover -s tests -t .
```

App: open `ios/Amend.xcodeproj` in Xcode and run.

NASR data comes from the [FAA 28-Day NASR Subscription](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/), charts from the [FAA d-TPP](https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/).

## Roadmap

- TestFlight
- Home screen widget for your home airport
- Night mode for plates
- Route and trip lists

## Disclaimer

**Not for navigation.** Amend is a study and awareness tool. Always use official FAA publications, NOTAMs and a proper preflight briefing.

## License

MIT. FAA data is public domain. IBM Plex Sans and IBM Plex Mono are under the SIL Open Font License ([amend/fonts/OFL.txt](amend/fonts/OFL.txt)).
