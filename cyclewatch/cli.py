"""
command line:

  python -m cyclewatch diff OLD.zip NEW.zip VRB DAB [--dtpp FILE] [--llm] [--json] [--out DIR] [--raw]
  python -m cyclewatch diff OLD.zip NEW.zip --all-airports [--dtpp FILE] [--llm] [--out DIR] [--print]
  python -m cyclewatch latest [--no-llm]      build site/ (what the GitHub Action runs)
  python -m cyclewatch history [--llm] [--keep]   add new cycles to history/
  python -m cyclewatch set-key                store your Anthropic API key in .env
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
    result = run(a.old, a.new, ids, a.dtpp, a.llm)
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
    p = argparse.ArgumentParser(prog="cyclewatch", description="what changed at your airports "
                                "between FAA cycles")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diff", help="diff two NASR CSV zips")
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("ids", nargs="*", help="FAA airport ids (KDAB works too)")
    d.add_argument("--all-airports", action="store_true")
    d.add_argument("--dtpp", help="d-TPP metafile XML for the NEW cycle (chart changes)")
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

    sub.add_parser("set-key", help="save your Anthropic API key to .env")

    a = p.parse_args(argv)
    if a.cmd == "diff":
        cmd_diff(a)
    elif a.cmd == "latest":
        from .latest import build
        build(llm=not a.no_llm)
    elif a.cmd == "history":
        from .history import update
        update(llm=a.llm, keep=a.keep)
    elif a.cmd == "set-key":
        set_key()
