"""
The FAA's row and column order must not change what amend says. The diff sorts rows before it
pairs them (amend/diff.py), so the same FAA data written in another order has to give the same
output: same changes, ids, ranks and summaries. test_snapshot checks the hash seed; this
checks the order. one thing does follow the FAA's column order, on purpose: the `fields` list of a
whole row added or removed (pipeline.row_fields) lists the row's columns as the FAA wrote them,
so the comparison sorts that one list first.

It rewrites the two snapshot zips (tests/gold/snapshot.json) with every CSV's rows shuffled and
its columns in another order, runs the engine on them the way the snapshot does, and compares
the result with the committed snapshot. Like test_snapshot it needs the zips in data/ (python -m
amend.gold --fetch) and skips without them, except where AMEND_SNAPSHOT=required (the PR tests),
so it never runs in the deploy, which has no zips when its tests run.
run:  python -m unittest tests.test_order -v
"""
import csv
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
import zipfile

from amend import gold
from amend.nasr import decode
from amend.rules import HIDDEN_FILES, base

META = gold.snapshot_meta()
MISSING = [z["file"] for z in META["zips"].values() if not os.path.exists(os.path.join(gold.DATA, z["file"]))]
REQUIRED = os.environ.get("AMEND_SNAPSHOT") == "required"
SEED = 20261001


def shuffled_zip(src, dst, rnd):
    """src with each top-level CSV's data rows shuffled and its columns reordered, values
    untouched. every other member (layout pdfs, the change-report zip, files the engine never
    reads) is copied as it is. stored uncompressed: it's a temp file, and that's faster."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as zout:
        for info in zin.infolist():
            raw = zin.read(info)
            name = info.filename
            if not name.lower().endswith(".csv") or base(name).startswith(HIDDEN_FILES):
                info.compress_type = zipfile.ZIP_STORED
                zout.writestr(info, raw)
                continue
            rows = list(csv.reader(io.StringIO(decode(raw), newline="")))
            info.compress_type = zipfile.ZIP_STORED
            if len(rows) < 2:
                zout.writestr(info, raw)
                continue
            head, body = rows[0], rows[1:]
            cols = list(range(len(head)))
            rnd.shuffle(cols)
            rnd.shuffle(body)
            out = io.StringIO(newline="")
            w = csv.writer(out)
            w.writerow([head[i] for i in cols])
            for r in body:
                r = r + [""] * (len(head) - len(r))   # a short row keeps its blanks at the end
                w.writerow([r[i] for i in cols] + r[len(head):])
            zout.writestr(info, out.getvalue().encode("utf-8"))


def comparable(snapshot):
    """the snapshot with each added/removed row's fields in one fixed order (see the top)."""
    out = json.loads(json.dumps(snapshot))
    for changes in out["airports"].values():
        for c in changes:
            if c["kind"] in ("added", "removed") and "fields" in c:
                c["fields"] = sorted(c["fields"], key=lambda f: f["field"])
    return out


@unittest.skipIf(MISSING and not REQUIRED, f"needs the snapshot's FAA NASR zips in data/: {', '.join(MISSING)} "
                                          f"(python -m amend.gold --fetch)")
class TestFaaOrderDoesNotMatter(unittest.TestCase):
    def test_shuffled_rows_and_columns_give_the_snapshot(self):
        old, new = gold.snapshot_inputs(META)
        with open(gold.snapshot_path(META), encoding="utf-8") as f:
            expected = json.load(f)
        rnd = random.Random(SEED)
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for p in (old, new):          # same file names: the cycle dates come from them
                q = os.path.join(d, os.path.basename(p))
                shuffled_zip(p, q, rnd)
                paths.append(q)
            env = {**os.environ, "PYTHONHASHSEED": gold.HASH_SEED}
            p = subprocess.run([sys.executable, "-c", "import sys; from amend import gold; gold._child(sys.argv[1:])",
                                *paths, *META["airports"]], cwd=gold.HERE, env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr[-3000:])
            got = json.loads(p.stdout.rsplit(gold.MARK, 1)[1])
        expected, got = comparable(expected), comparable(got)
        diff = gold.snapshot_diff(expected, got)
        self.assertEqual(diff, [], "shuffling the FAA rows/columns changed the output:\n" + "\n".join(diff))
        self.assertEqual(gold.dumps(expected), gold.dumps(got))


if __name__ == "__main__":
    unittest.main()
