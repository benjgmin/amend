"""
Snapshot of what the engine says today about one real cycle pair, for every airport on the
watchlists and the busiest airports (tests/gold/snapshot.json lists them). Any change to diff,
collapse, rules or summaries shows up here as a diff to review.

It needs the two NASR zips named in tests/gold/snapshot.json in data/ (python -m amend.gold
--fetch gets them from this repo's releases), and skips without them, except where
AMEND_SNAPSHOT=required: the PR tests set that, so the snapshot can't quietly stop running there.
After a change you meant to make:  python -m amend.gold --update-snapshot, then review the
snapshot file's diff before committing it.
"""
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from amend import gold

META = gold.snapshot_meta()
MISSING = [z["file"] for z in META["zips"].values() if not os.path.exists(os.path.join(gold.DATA, z["file"]))]
REQUIRED = os.environ.get("AMEND_SNAPSHOT") == "required"


class TestSnapshotFile(unittest.TestCase):
    def test_matches_its_meta(self):
        with open(gold.snapshot_path(META), encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual((snap["from_cycle"], snap["to_cycle"]), (META["from_cycle"], META["to_cycle"]))
        self.assertEqual(sorted(snap["airports"]), sorted(META["airports"]))
        for z in META["zips"].values():
            self.assertRegex(z["sha256"], r"^[0-9a-f]{64}$")
            # the PR tests download from here (--fetch), so a new pair needs its release too
            self.assertTrue(z["archive"].startswith("https://github.com/benjgmin/amend/releases/download/"), z)


class TestFetch(unittest.TestCase):
    """--fetch with the download faked: it lands both files, checks their sha256, and says
    what's wrong instead of leaving the snapshot to skip."""
    def run_fetch(self, served, ok=True):
        meta = {"zips": {side: {"file": f"{side}_CSV.zip", "archive": f"https://example.invalid/{side}.zip",
                                "sha256": hashlib.sha256(b"the real zip").hexdigest()}
                         for side in ("from", "to")}}
        calls = []

        def download(url, path, required=()):
            calls.append((url, required))
            if ok:
                with open(path, "wb") as f:
                    f.write(served)
            return ok
        with tempfile.TemporaryDirectory() as d, mock.patch.object(gold.cycles, "download", download):
            return [os.path.basename(p) for p in gold.fetch(meta, d)], calls

    def test_downloads_both_and_checks_them(self):
        paths, calls = self.run_fetch(b"the real zip")
        self.assertEqual(paths, ["from_CSV.zip", "to_CSV.zip"])
        self.assertEqual([u for u, _ in calls], ["https://example.invalid/from.zip", "https://example.invalid/to.zip"])
        self.assertTrue(all(r == gold.cycles.CSV_REQUIRED for _, r in calls))

    def test_a_different_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "not the FAA file the snapshot was made from"):
            self.run_fetch(b"some other zip")

    def test_a_missing_release_is_an_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "gone from the release"):
            self.run_fetch(b"", ok=False)


@unittest.skipIf(MISSING and not REQUIRED, f"snapshot needs the FAA NASR zips in data/: {', '.join(MISSING)} "
                                          f"(python -m amend.gold --fetch)")
class TestSnapshot(unittest.TestCase):
    def test_engine_output_unchanged(self):
        with open(gold.snapshot_path(META), encoding="utf-8") as f:
            expected = json.load(f)
        got = gold.make_snapshot(META)
        diff = gold.snapshot_diff(expected, got)
        self.assertEqual(diff, [], "engine output changed:\n" + "\n".join(diff) +
                         "\nif that's intended: python -m amend.gold --update-snapshot")
        self.assertEqual(gold.dumps(expected), gold.dumps(got))


if __name__ == "__main__":
    unittest.main()
