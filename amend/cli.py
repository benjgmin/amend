"""
command line:

  python -m amend diff OLD.zip NEW.zip VRB BJC [--dtpp FILE] [--airspace OLD NEW] [--llm] [--json] [--out DIR] [--raw]
  python -m amend diff OLD.zip NEW.zip --all-airports [--dtpp FILE] [--airspace OLD NEW] [--llm] [--out DIR] [--print]
  python -m amend latest [--no-llm]      build site/ (what the GitHub Action runs)
  python -m amend history [--llm] [--keep]   add new cycles to history/
  python -m amend scrub-history          FAA text back where history/ holds a rejected translation; the rest said as now
  python -m amend set-key                store your Anthropic API key in .env
  python -m amend check                  scheduled runs: is a rebuild needed? (build=true/false)
  python -m amend verify [DIR]           refuse to deploy an empty or half-built site/
  python -m amend archive [CYCLE ...] [--backfill] [--list]   keep raw FAA files as GitHub Releases
"""
import argparse
import sys

from .remarks import load_env, set_key


def _strip_k(a):
    a = a.upper()
    return a[1:] if len(a) == 4 and a.startswith("K") else a


def _print_airport(apt, changes, hidden, raw):
    print(f"\n==================== {apt} ====================")
    for pri, icon, title in (("action", "!!", "ACTION"), ("ifr", ">>", "IFR PROCEDURES"),
                             ("fyi", "--", "FYI")):
        group = [c for c in changes if c["priority"] == pri]
        if group:
            print(f"\n{title}")
        for c in group:
            print(f" {icon} {c['summary']}")
            if raw:
                if c.get("original"):
                    print(f"      FAA: {c['original']}")
                for f in c.get("fields", []):
                    print(f"      {f['field']}: '{f['old']}' -> '{f['new']}'")
                for d in c.get("details", []):
                    print(f"      {d}")
                if c.get("chart", {}).get("pdf"):
                    print(f"      {c['chart']['pdf']}")
    if hidden:
        print(f"\n ({hidden} noise changes hidden)")


def cmd_diff(a):
    from .output import write_diff
    from .pipeline import counts, run
    ids = None if a.all_airports else {_strip_k(x) for x in a.ids}
    if not a.all_airports and not ids:
        sys.exit("give some airport ids, or --all-airports")
    result = run(a.old, a.new, ids, a.dtpp, a.llm, airspace=a.airspace)
    if a.json or a.all_airports:
        n = write_diff(result, a.out)
        print(f"wrote {n} airport file(s) to {a.out}/")
    apts = result["airports"]
    if a.all_airports and not a.print:
        n_action = sum(1 for c in apts.values() if counts(c)["action"])
        print(f"\ndone in {result['seconds']:.0f}s. {len(apts)} airports changed, "
              f"{n_action} with action items.\nmost action items:")
        for apt, ch in sorted(apts.items(), key=lambda kv: -counts(kv[1])["action"])[:15]:
            k = counts(ch)
            print(f"  {apt:5} {k['action']:3} action, {k['ifr']:3} ifr, {k['fyi']:3} fyi")
        return
    for apt in sorted(set(apts) | set(result["hidden"])):
        _print_airport(apt, apts.get(apt, []), result["hidden"].get(apt, 0), a.raw)


def main(argv=None):
    load_env()
    p = argparse.ArgumentParser(prog="amend", description="what changed at your airports "
                                "between FAA cycles")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diff", help="diff two NASR CSV zips")
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("ids", nargs="*", help="FAA airport ids (KBJC works too)")
    d.add_argument("--all-airports", action="store_true")
    d.add_argument("--dtpp", help="d-TPP metafile XML for the NEW cycle (chart changes)")
    d.add_argument("--airspace", nargs=2, metavar=("OLD", "NEW"),
                   help="class airspace shapefile zips for both cycles (floors, ceilings, boundaries)")
    d.add_argument("--llm", action="store_true", help="translate remarks with Claude")
    d.add_argument("--json", action="store_true", help="write JSON (always on with --all-airports)")
    d.add_argument("--out", default="out")
    d.add_argument("--raw", action="store_true", help="show FAA text / field values / details")
    d.add_argument("--print", action="store_true", help="with --all-airports: print every airport")

    l = sub.add_parser("latest", help="build site/ with upcoming or current changes")
    l.add_argument("--no-llm", action="store_true")

    h = sub.add_parser("history", help="add new cycles to history/")
    h.add_argument("--llm", action="store_true")
    h.add_argument("--keep", action="store_true", help="keep downloaded zips")
    sub.add_parser("scrub-history", help="run after changing the translation checks or readable(): history/ "
                                         "shows the FAA text where a stored translation now fails them, and "
                                         "says the rest the way translations are said now")

    sub.add_parser("set-key", help="save your Anthropic API key to .env")
    sub.add_parser("check", help="is a rebuild needed? writes build=true/false to $GITHUB_OUTPUT")
    v = sub.add_parser("verify", help="check a built site before it's deployed")
    v.add_argument("site", nargs="?", default="site")

    st = sub.add_parser("status", help="rewrite site/status/ from the run log (after verify)")
    st.add_argument("site", nargs="?", default="site")

    ar = sub.add_parser("archive", help="keep each cycle's raw FAA files as a GitHub Release")
    ar.add_argument("cycles", nargs="*", help="cycle dates, e.g. 2024-08-08 (default: in effect + next)")
    ar.add_argument("--backfill", action="store_true", help="every cycle since Aug 2024")
    ar.add_argument("--list", action="store_true", help="show what the FAA still serves; download nothing")

    wl = sub.add_parser("watchlist", help="create or list named watchlists (watchlists/*.json)")
    wl.add_argument("action", choices=["create", "list"])
    wl.add_argument("slug", nargs="?", help="link name, e.g. flying-club -> amend.watch/list/flying-club")
    wl.add_argument("airports", nargs="*")
    wl.add_argument("--name", help='display name, e.g. "Flying club"')
    wl.add_argument("--description", default="")

    a = p.parse_args(argv)
    if a.cmd == "diff":
        cmd_diff(a)
    elif a.cmd == "latest":
        from .latest import build
        build(llm=not a.no_llm)
    elif a.cmd == "history":
        from .history import update
        update(llm=a.llm, keep=a.keep)
    elif a.cmd == "scrub-history":
        from .remarks import scrub_history
        back, reworded, files = scrub_history()
        print(f"{back} translations in history/ fail the checks; showing the FAA text for those. "
              f"{reworded} reworded the way translations are said now ({files} airports)")
    elif a.cmd == "set-key":
        set_key()
    elif a.cmd == "check":
        from .freshness import check
        check()
    elif a.cmd == "verify":
        from .freshness import verify
        from .runlog import mark_verified
        bad = verify(a.site)
        for b in bad:
            print(f"  {b}")
        mark_verified(not bad, bad)     # the run log says whether the build got past this
        if not bad:
            # the status page again, now that this run's record says verified, so the page that
            # deploys shows its own run as published. a status page bug must never hold back FAA
            # data that passed every check: the page from the build step (checked above) stays
            try:
                from .statuspage import rebuild
                rebuild(a.site)
            except Exception as ex:
                print(f"::warning title=status page::couldn't refresh {a.site}/status/ after verify: "
                      f"{type(ex).__name__}: {ex}")
        if bad:
            sys.exit(f"{a.site}/ failed {len(bad)} check(s); not deploying, the live site stays as it was")
        print(f"{a.site}/ looks complete")
    elif a.cmd == "status":
        from .statuspage import rebuild
        print(f"{a.site}/status/ shows {rebuild(a.site)} runs")
    elif a.cmd == "archive":
        from .archive import main as archive
        archive(a)
    elif a.cmd == "watchlist":
        from . import watchlists
        if a.action == "list":
            for slug, w in watchlists.load_all().items():
                print(f"{slug:20} {w['name']:30} {len(w['airports'])} airports")
            return
        if not a.slug or not a.airports or not a.name:
            sys.exit('usage: python -m amend watchlist create <slug> --name "Name" AIRPORT ...')
        w = watchlists.save(a.slug, a.name, a.airports, a.description)
        print(f"saved watchlists/{a.slug}.json ({len(w['airports'])} airports). push it, and it'll be live at\n"
              f"  https://amend.watch/list/{a.slug}")
