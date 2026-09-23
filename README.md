# Cyclewatch

**Know what changed at your airports every FAA cycle.**

Every 28 days the FAA publishes a new cycle of airport, airspace, frequency and procedure data. Changes that matter (tower hours, a decommissioned VOR, a renumbered runway, an amended approach) are buried among tens of thousands of rows of bookkeeping noise. Cyclewatch diffs consecutive cycles, filters out the noise, and turns what's left into plain English, ranked by whether it changes how you fly.

It started with a quiz question marked wrong because the course material still had Vero Beach's tower closing at 2100. It closes at 0100 now. Cyclewatch catches that automatically:

```
==================== VRB ====================

ACTION
 !! tower hours changed: 0700-2100 -> 0700-0100 local
 !! airspace is now: class d svc 0700-0100; other times class e
 !! TRV (Treasure) navaid: now a DME (was a VORTAC)
 !! approach/departure control now provided by DJT (was PBI)
 !! new remark: Runway 04/22 not available for Part 121/Part 380 operations with ...

FYI
 -- preferred IFR routes: 4 added, 3 changed
 -- remark updated: Runway surface condition not monitored 2300-0600 Monday through Friday ...
```

## What it covers

- **Airports and airspace** from the FAA NASR 28-day subscription: tower and Class D hours, frequencies, navaids, runways (including renumbering from magnetic drift), attendance hours, phone numbers, new and removed airports, remarks
- **Charts** from the d-TPP metafile: added, amended and removed approaches, departures, STARs and airport diagrams, with links to the new PDF plates
- **Plain-English remarks**: FAA contractions ("RSCD NOT MNT 2300-0600 M-F") are translated with Claude using a fixed glossary. Unknown abbreviations are left as-is rather than guessed, and the original FAA text is always kept alongside

Each change is ranked **action** (changes how you fly), **IFR procedures**, or **fyi**. Pure noise (survey dates, pavement strength codes, coordinate rounding) is hidden.

## Data

A GitHub Action runs daily, pulls the latest FAA data, diffs every US airport (~19,000, about 15 seconds), and publishes one JSON file per changed airport:

```
https://benjgmin.github.io/cyclewatch/latest/DAB.json
https://benjgmin.github.io/cyclewatch/latest/index.json   # airports with changes
https://benjgmin.github.io/cyclewatch/latest/meta.json    # which cycles, when it ran
```

When the next cycle is already posted (the FAA publishes about three weeks early), the site shows **upcoming** changes, so you know before they take effect.

## Run it locally

```bash
# one-time: store your Anthropic API key in .env (only needed for --llm)
python nasr_diff.py --set-key

# a few airports
python nasr_diff.py 03_Sep_2026_CSV.zip 01_Oct_2026_CSV.zip VRB DAB ISM --llm

# every airport, with approach plate changes
python nasr_diff.py 03_Sep_2026_CSV.zip 01_Oct_2026_CSV.zip --all-airports --dtpp d-tpp_Metafile.xml

# the full automated pipeline (downloads everything itself)
python run_cycle.py
```

NASR CSV zips come from the [FAA 28-Day NASR Subscription](https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/). No dependencies beyond the Python standard library.

## Roadmap

- iOS app: save your airports, get notified when a new cycle affects them
- Waypoint-level detail for STAR/DP changes
- Match navaids to nearby airports in all-airports mode

## Disclaimer

**Not for navigation.** Cyclewatch is a study and awareness tool. Always use official FAA publications, NOTAMs and a proper preflight briefing.

## License

MIT. FAA data is public domain; see the FAA NASR and d-TPP pages for their terms.