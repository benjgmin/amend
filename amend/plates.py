"""The numbers printed on a changed chart: its courses and headings, old edition against new.

The d-TPP metafile only says a chart changed. What changed is on the plate itself: a runway
heading or final approach course moved when the FAA updated the magnetic variation (ANC ILS RWY
7R 2611: 074° and 254° became 076° and 256°), one leg of a departure turned a degree (MYCAR 2611
079° -> 080°). Neither is anywhere in NASR: it keeps true alignment and an ILS bearing that may be
decades old.

The FAA serves a chart's pdf for a few editions only (in Oct 2026: 2607 to 2611), so each changed
chart is read while both its old and new edition are still up, and what was read is kept in
plates/<edition>.json: pdf name -> {"sha256", "courses": {"072": 3, ...}} (every NNN° printed on
it and how often), null when the FAA doesn't serve that pdf, or {"failed": n} after n downloads
that broke (timeouts, 5xx); after GIVE_UP of those it stops trying. Only numbers are kept, never
the plate.

Only a clear pair is reported (see course_changes): one value gone and one new value within
SHIFT degrees, each the other's only near match. Anything else is a redraw amend can't read, and
the chart says so without a number.
"""
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request

PLATES = "plates"
URL = "https://aeronav.faa.gov/d-tpp/{edition}/{pdf}"
# a course or heading as printed: 072°, 254°, an airport diagram's 072.4°. never a glide path
# (3.00°: one digit) or a coordinate: 47°58'N has two digits, and a longitude's three are
# followed by its minutes (102°29'W)
COURSE = re.compile(r"(?<![\d.])([0-3]\d\d(?:\.\d)?)°(?!\s?\d\d?(?:\.\d+)?['’′])")
# approach minimums as printed: a DA or MDA with its RVR (680/24) or visibility (780-1½, the
# fraction one glyph). pypdf often splits a fraction into two digits ("(500-   )34"), so a
# visibility is only kept when it's one the FAA prints (VISIBILITIES)
FRACTIONS = "½¼¾⅛⅜⅝⅞"
MINIMUM = re.compile(r"(?<![\d/(.,:-])(\d{3,5})(?:/(\d{2,3})(?!\d)|-(\d{0,2}[" + FRACTIONS +
                     r"]?)(?=[\s)\d]|$|[A-Z]))")
# a whole minimums entry, "680/24 444 (500-½)": DA, height above touchdown, that height rounded
# up to 100. the DA minus the height is the touchdown zone or airport elevation, and a number
# only counts as a minimum when it sits that far above one of those (so 1496 next to a 6 that
# pypdf glued on isn't a minimum of 14966)
ENTRY = re.compile(r"(?<![\d/(.,:-])(\d{3,5})(?:/\d{2,3}|-\d{0,2}[" + FRACTIONS +
                   r"]?)\s+(\d{2,4})\s*\((\d{3,4})-")
NUMBER = re.compile(r"(?<!\d)(\d{2,5})(?!\d)")
GLUED = re.compile(r"(?<![\d(])\d{3,}(?=[/-])")     # not a (HAA-vis)
RVRS = {"16", "18", "20", "24", "26", "30", "35", "40", "45", "50", "55", "60"}
VISIBILITIES = {"½", "⅝", "¾", "⅞", "1", "1¼", "1⅜", "1½", "1¾", "2", "2¼", "2½", "2¾", "3",
                "3½", "4", "5"}
STEP = 200            # feet. a minimum that moved more than this is a redesigned approach
SHIFT = 5             # degrees. a magnetic variation update moves a course 1-3°; more is a redesign
MIN_COURSES = 3       # fewer on either edition: no text layer to read, not "no courses"
GIVE_UP = 3           # failed downloads of one pdf before a build stops asking for it
WORKERS = 8
TIMEOUT = 60
MISSING = (403, 404, 410)


def previous(day):
    """the d-TPP edition before the one effective on `day`: date(2026, 9, 3) -> '2608'. the same
    count as cycles.dtpp_id, kept here so the engine doesn't import the download code."""
    d = day - dt.timedelta(days=28)
    n, x = 1, d
    while (x - dt.timedelta(days=28)).year == d.year:
        x -= dt.timedelta(days=28)
        n += 1
    return f"{d.year % 100:02d}{n:02d}"


def path(edition, root="."):
    return os.path.join(root, PLATES, f"{edition}.json")


def load(edition, root="."):
    try:
        with open(path(edition, root)) as f:
            return json.load(f)["charts"]
    except (OSError, ValueError, KeyError):
        return {}


def save(edition, charts, root="."):
    os.makedirs(os.path.join(root, PLATES), exist_ok=True)
    with open(path(edition, root), "w") as f:
        json.dump({"schema_version": 1, "edition": edition,
                   "charts": dict(sorted(charts.items()))}, f, indent=0, sort_keys=True)
        f.write("\n")


def courses(text):
    """{"072": 3, ...}: every course or heading printed on a chart, and how many times."""
    out = {}
    for v in COURSE.findall(text):
        if float(v) <= 360:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def minimums(text):
    """{"alts": [DA/MDA, ...], "rvr": {alt: [rvr, ...]}, "vis": {alt: [vis, ...]}, "seen": [...]}
    printed on an approach plate (RVR in hundreds of feet, as printed: 24 is 2400). "seen" is every
    number that could be a minimum once pypdf's glue is taken off: "783231-" (a split ⅞ stuck on
    the front) is 3231, so a 3231 on the next edition isn't new."""
    numbers = set(NUMBER.findall(text))
    bases = set()
    for alt, hat, rounded in ENTRY.findall(text):
        alt, hat, rounded = int(alt), int(hat), int(rounded)
        if 0 < hat < alt and rounded == -(-hat // 100) * 100:
            bases.add(alt - hat)
    alts, rvr, vis = set(), {}, {}
    for alt, r, v in MINIMUM.findall(text):
        if not any(int(alt) > b and str(int(alt) - b) in numbers for b in bases):
            continue
        alts.add(alt)
        if r in RVRS:
            rvr.setdefault(alt, set()).add(r)
        elif v in VISIBILITIES:
            vis.setdefault(alt, set()).add(v)
    seen = {str(int(m[-k:])) for m in GLUED.findall(text) for k in (3, 4, 5) if len(m) >= k}
    return {"alts": sorted(alts, key=int),
            "rvr": {a: sorted(v) for a, v in sorted(rvr.items())},
            "vis": {a: sorted(v) for a, v in sorted(vis.items())},
            "seen": sorted(seen | alts, key=int)}


# a minimums table's row labels, under its CATEGORY header: LPV DA, LNAV/VNAV DA, LNAV MDA, LP MDA,
# RNP 0.30 DA, S-ILS 7L, S-LOC 25, CIRCLING, SIDESTEP RWY 6R
LABEL = re.compile(r"^(?:LPV|LP|LNAV/?|VNAV|LNAV MDA|RNP|S-|SIDESTEP|CIRCLING|DA|MDA|RWY|\d)")
ROW = 14              # points. a value further than this above or below its row's label isn't read
CATEGORIES = "ABCDE"


def _chunks(page):
    """[(x, y, text), ...]: every piece of text on a pdf page and where it starts."""
    out = []

    def seen(text, cm, tm, font, size):
        if text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            out.append((round(x, 1), round(y, 1), text))
    text = page.extract_text(visitor_text=seen)
    return text, out


def rows(chunks):
    """{alt: "LPV DA", ...}: the minimums row each DA/MDA is printed in, from where the text sits on
    the page. a row is its label at the left of the table under CATEGORY; a value belongs to the
    row whose label is nearest it up or down, when that's clearly nearer than any other. an alt in
    two rows (LNAV MDA and circling A, both 1120) gets none. circling minimums printed one per
    category say which ("CIRCLING cat C"). {} when there's no one CATEGORY header."""
    heads = [(x, y) for x, y, t in chunks if t.strip().startswith("CATEGORY")]
    if len(heads) != 1:
        return {}
    hx, hy = heads[0]
    cols = sorted((x, t.strip()) for x, y, t in chunks
                  if abs(y - hy) < 3 and t.strip() in CATEGORIES and x > hx)
    fixes = sorted(y for x, y, t in chunks if "FIX MINIMUMS" in t and y < hy)
    pieces = sorted(((y, x, t.strip()) for x, y, t in chunks
                     if abs(x - hx) < 15 and hy - 200 < y < hy - 3 and LABEL.match(t.strip())),
                    reverse=True)
    labels = []                 # [[y, ...], [text, ...]] per row, top down
    for y, x, t in pieces:
        if labels and labels[-1][0][-1] - y < 10:
            labels[-1][0].append(y)
            labels[-1][1].append(t)
        else:
            labels.append([[y], [t]])
    named = []
    for ys, ts in labels:
        kind = [t for t in ts if t in ("DA", "MDA")]
        name = ""
        for t in ts:
            for w in t.split():
                if w in ("DA", "MDA") and t not in ("DA", "MDA") and w == t.split()[-1]:
                    kind.append(w)
                    continue
                if t in ("DA", "MDA"):
                    break
                name += ("" if name.endswith("/") or not name else " ") + w
        label = " ".join([name] + kind[:1]).strip()
        fix = [f for f in fixes if f > sum(ys) / len(ys)]
        named.append((sum(ys) / len(ys), label, fix[0] if fix else None))
    out, cells = {}, {}
    for x, y, t in chunks:
        if x <= hx + 15 or y >= hy or y < hy - 220:
            continue
        for m in MINIMUM.finditer(t.strip()):
            near = sorted((abs(y - ry), label, fix) for ry, label, fix in named)
            if not near or near[0][0] > ROW or (len(near) > 1 and near[1][0] - near[0][0] < 3):
                continue
            label = near[0][1]
            if near[0][2] is not None:
                fix = next(t2 for x2, y2, t2 in chunks if y2 == near[0][2] and "FIX MINIMUMS" in t2)
                label += f" ({fix.split('FIX')[0].strip()} fix)"
            cells.setdefault(label, []).append((x, m.group(1)))
            out.setdefault(m.group(1), set()).add(label)
    for label, vals in cells.items():
        if label.startswith("CIRCLING") and len(cols) >= 4 and len(vals) == len(cols):
            for (x, alt), (_, cat) in zip(sorted(vals), cols):
                out[alt] = out[alt] - {label} | {f"{label} cat {cat}"}
    return {a: next(iter(v)) for a, v in sorted(out.items()) if len(v) == 1}


def read(pdf_bytes):
    """what's kept of one plate."""
    import pypdf    # only the build reads plates; the rest of amend runs without it
    rec = {"sha256": hashlib.sha256(pdf_bytes).hexdigest()}
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        rec["courses"], rec["minimums"] = courses(text), minimums(text)
    except Exception as e:      # a pdf pypdf can't parse reads as no text, never stops a build
        rec["courses"], rec["minimums"], rec["error"] = {}, None, type(e).__name__
    return rec


def _angle(a, b):
    d = abs(float(a) - float(b)) % 360
    return min(d, 360 - d)


def course_changes(old, new):
    """[(old, new), ...]: courses on the old plate that became a nearby course on the new one.
    old/new are courses() counts. a value counts as gone when it's printed fewer times, as new
    when it's printed more (ANC 2611 keeps the VOR radial R-210 but its 210° feeder became 213°).
    a pair needs both values within SHIFT and each the other's only match that close, so two
    courses moving at once can't be crossed. a redesign moves many numbers, and one gone value
    can land near an unrelated new one (JZI BAGGY 2611: the ADERY leg 239° went, a SAV leg 241°
    came), so when more values come and go unpaired than pair up, nothing is reported. [] when
    either plate had no text to read."""
    if not old or not new or sum(old.values()) < MIN_COURSES or sum(new.values()) < MIN_COURSES:
        return []
    gone = [v for v in old if old[v] > new.get(v, 0)]
    came = [v for v in new if new[v] > old.get(v, 0)]
    return _pairs(gone, came, lambda a, b: 0 < _angle(a, b) <= SHIFT)


def _pairs(gone, came, close):
    """(gone, came) pairs, each the other's only close match; [] when more go unpaired than pair."""
    near = lambda v, pool: [w for w in pool if w != v and close(v, w)]
    out = []
    for g in gone:
        m = near(g, came)
        if len(m) == 1 and near(m[0], gone) == [g]:
            out.append((g, m[0]))
    if len(gone) + len(came) - 2 * len(out) > len(out):
        return []
    return sorted(out, key=lambda p: float(p[0]))


def minimum_changes(old, new):
    """what moved in an approach's minimums, as (what, old, new, at): ("minimum", "680", "700",
    None) for a DA or MDA, ("rvr", "40", "26", "1542") or ("visibility", "1", "1½", "780") for
    the RVR or visibility printed with a minimum both plates have. stricter than courses: every
    minimum that went must pair with one that came, within STEP feet and each the other's only
    match, and neither may be anywhere on the other plate (a 3460 that became both 3240 and 3280
    says nothing). an RVR or visibility only when the minimum carries exactly one on each plate."""
    if not old or not new or not old.get("alts") or not new.get("alts"):
        return []
    a, b = set(old["alts"]), set(new["alts"])
    gone = sorted(a - b - set(new.get("seen", ())), key=int)
    came = sorted(b - a - set(old.get("seen", ())), key=int)
    pairs = _pairs(gone, came, lambda x, y: abs(int(x) - int(y)) <= STEP)
    if len(pairs) * 2 != len(gone) + len(came) or len(gone) != len(a - b) or len(came) != len(b - a):
        pairs = []
    out = [("minimum", x, y, None) for x, y in pairs]
    for kind, key in (("rvr", "rvr"), ("visibility", "vis")):
        for alt in sorted(a & b, key=int):
            x, y = old.get(key, {}).get(alt), new.get(key, {}).get(alt)
            if x and y and len(x) == 1 and len(y) == 1 and x != y:
                out.append((kind, x[0], y[0], alt))
    return out


def changes_for(pdf, old_edition, new_edition, root="."):
    """(course_changes, minimum_changes) for one chart, from what plates/ holds; ([], []) if either
    side wasn't read."""
    a, b = load_cached(old_edition, root).get(pdf), load_cached(new_edition, root).get(pdf)
    if not a or not b or "courses" not in a or "courses" not in b:
        return [], []
    return course_changes(a.get("courses"), b.get("courses")), minimum_changes(a.get("minimums"), b.get("minimums"))


_cache = {}


def load_cached(edition, root="."):
    key = (edition, os.path.abspath(root))
    if key not in _cache:
        _cache[key] = load(edition, root)
    return _cache[key]


def forget():
    _cache.clear()


def _get(url):
    """pdf bytes, None if the FAA doesn't serve it. raises on anything else (retried next run)."""
    req = urllib.request.Request(url, headers={"User-Agent": "amend (https://amend.watch)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        if e.code in MISSING:
            return None
        raise
    if not b.startswith(b"%PDF"):
        raise ValueError(f"not a pdf: {url}")
    return b


def _one(get, edition, pdf, deadline):
    """one plate: what read() keeps, None if the FAA doesn't serve it, or why it wasn't read."""
    if time.time() > deadline:
        return "skipped"
    try:
        b = get(URL.format(edition=edition, pdf=pdf))
    except Exception as e:
        return f"failed: {type(e).__name__}"
    return None if b is None else read(b)


def update(old_edition, new_edition, pdfs, budget=600, root=".", log=print, get=_get):
    """read each changed chart's old and new plate that plates/ doesn't have yet.
    pdfs: the pdf names of the charts the new edition changed. stops starting new downloads
    after `budget` seconds; the next build carries on. returns how many are still unread, None if
    this machine can't read pdfs."""
    want = [(ed, pdf) for pdf in sorted(set(pdfs)) for ed in (old_edition, new_edition)]
    have = {ed: load(ed, root) for ed in (old_edition, new_edition)}
    # read before minimums were kept: read again while the FAA still serves it
    unread = lambda rec: isinstance(rec, dict) and (
        "courses" not in rec and rec.get("failed", 0) < GIVE_UP or "courses" in rec and (
            "minimums" not in rec or isinstance(rec["minimums"], dict) and "seen" not in rec["minimums"]))
    todo = [(ed, pdf) for ed, pdf in want if pdf not in have[ed] or unread(have[ed][pdf])]
    if not todo:
        return 0
    try:
        import pypdf  # noqa: F401
    except ImportError:
        log("  plates: pypdf isn't installed, not reading plates")
        return None
    t0, done, failed = time.time(), 0, 0

    pool = (concurrent.futures.ProcessPoolExecutor if get is _get     # pypdf is CPU-bound
            else concurrent.futures.ThreadPoolExecutor)
    with pool(WORKERS) as ex:
        jobs = {ex.submit(_one, get, ed, pdf, t0 + budget): (ed, pdf) for ed, pdf in todo}
        for job in concurrent.futures.as_completed(jobs):
            ed, pdf = jobs[job]
            try:
                rec = job.result()
            except Exception as e:      # a worker that died: same as a failed download
                rec = f"failed: {type(e).__name__}"
            prev = have[ed].get(pdf)
            if isinstance(prev, dict) and "courses" in prev and not isinstance(rec, dict):
                # read once already: keep its courses whatever this attempt got. gone from the
                # FAA, or failing GIVE_UP times, it has no minimums to add and isn't asked again
                if rec is None:
                    prev["minimums"] = None
                    done += 1
                elif rec != "skipped":
                    failed += 1
                    prev["failed"] = prev.get("failed", 0) + 1
                    if prev["failed"] >= GIVE_UP:
                        prev["minimums"] = None
                continue
            if isinstance(rec, str):
                if rec != "skipped":
                    failed += 1
                    have[ed][pdf] = {"failed": (prev or {}).get("failed", 0) + 1}
                continue
            have[ed][pdf] = rec
            done += 1
    for ed in (old_edition, new_edition):
        save(ed, have[ed], root)
    forget()
    left = sum(1 for ed, pdf in want if pdf not in have[ed] or unread(have[ed][pdf]))
    log(f"  plates {old_edition} -> {new_edition}: read {done} of {len(todo)} in "
        f"{time.time() - t0:.0f}s ({failed} failed, {left} left for the next build)")
    return left
