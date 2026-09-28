"""
Snapshot of what the engine says today about one real cycle pair, for every airport on the
watchlists and the busiest airports (tests/gold/snapshot.json lists them). Any change to diff,
collapse, rules or summaries shows up here as a diff to review.

It needs Python 3.11+ and the two NASR zips named in tests/gold/snapshot.json in data/
(download lines in tests/gold/README.md), and skips without them.
After a change you meant to make:  python -m amend.gold --update-snapshot, then review the
snapshot file's diff before committing it.
"""
import json
import os
import sys
import unittest

from amend import gold

META = gold.snapshot_meta()
MISSING = [z["file"] for z in META["zips"].values() if not os.path.exists(os.path.join(gold.DATA, z["file"]))]


class TestSnapshotFile(unittest.TestCase):
    def test_matches_its_meta(self):
        with open(gold.snapshot_path(META), encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual((snap["from_cycle"], snap["to_cycle"]), (META["from_cycle"], META["to_cycle"]))
        self.assertEqual(sorted(snap["airports"]), sorted(META["airports"]))
        for z in META["zips"].values():
            self.assertRegex(z["sha256"], r"^[0-9a-f]{64}$")


@unittest.skipIf(MISSING, f"snapshot needs the FAA NASR zips in data/: {', '.join(MISSING)} "
                          f"(download lines in tests/gold/README.md)")
@unittest.skipIf(sys.hash_info.algorithm != gold.HASH_ALGORITHM,
                 f"snapshot needs Python 3.11 or newer ({gold.HASH_ALGORITHM} string hashing), "
                 f"this Python uses {sys.hash_info.algorithm}")
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
