from __future__ import annotations

import unittest
from unittest.mock import patch

from weedeat.prune import prune_branch, prune_worktree


class PruneGuardsTest(unittest.TestCase):
    @patch("weedeat.prune.subprocess.run")
    def test_worktree_rejects_protected_or_out_of_threshold_entries(self, run) -> None:
        cases = [
            {"level": 0, "path": "tree"},
            {"level": 2, "path": "tree"},
            {"level": 1, "path": "tree", "system_protected": True},
            {"level": 1, "path": "tree", "locked": True},
        ]
        for entry in cases:
            with self.subTest(entry=entry), self.assertRaises(AssertionError):
                prune_worktree("repo", entry, threshold=1)
        run.assert_not_called()

    @patch("weedeat.prune.subprocess.run")
    def test_branch_rejects_protected_checked_out_or_out_of_threshold_entries(self, run) -> None:
        cases = [
            {"branch": "topic", "level": 0, "checked_out": False},
            {"branch": "topic", "level": 3, "checked_out": False},
            {"branch": "topic", "level": 1, "checked_out": True},
            {"branch": "topic", "level": 1, "checked_out": False,
             "system_protected": True},
        ]
        for entry in cases:
            with self.subTest(entry=entry), self.assertRaises(AssertionError):
                prune_branch("repo", entry, threshold=2)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
