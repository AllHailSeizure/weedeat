from __future__ import annotations

import unittest
from unittest.mock import patch

from weedeat.trim import execute_trim, trim_candidates


def result() -> dict:
    return {
        "worktrees": [
            {"branch": "main", "path": "repo", "level": 0,
             "system_protected": True},
            {"branch": "safe", "path": "safe-tree", "level": 1,
             "system_protected": False},
            {"branch": "stale", "path": "stale-tree", "level": 2,
             "system_protected": False},
            {"branch": "hold", "path": "hold-tree", "level": 4,
             "system_protected": False},
        ],
        "branches": [
            {"branch": "main", "level": 0, "checked_out": True,
             "system_protected": True},
            {"branch": "safe", "level": 1, "checked_out": True,
             "system_protected": False},
            {"branch": "stale", "level": 2, "checked_out": True,
             "system_protected": False},
            {"branch": "orphan", "level": 2, "checked_out": False,
             "system_protected": False},
            {"branch": "hold", "level": 4, "checked_out": True,
             "system_protected": False},
        ],
    }


class TrimTest(unittest.TestCase):
    def test_threshold_selects_levels_one_through_n_and_never_zero(self) -> None:
        trees, branches = trim_candidates(result(), 2)
        self.assertEqual([row["branch"] for row in trees], ["safe", "stale"])
        self.assertEqual(
            [row["branch"] for row in branches], ["safe", "stale", "orphan"]
        )

    def test_threshold_must_be_between_one_and_four(self) -> None:
        for threshold in (0, 5):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                trim_candidates(result(), threshold)

    @patch("weedeat.trim.run_survey")
    @patch("weedeat.trim.prune_branch", return_value=(True, "branch removed"))
    @patch("weedeat.trim.prune_worktree", return_value=(True, "tree removed"))
    def test_worktrees_are_removed_before_associated_branches(
        self, remove_tree, remove_branch, survey
    ) -> None:
        refreshed = result()
        for branch in refreshed["branches"]:
            branch["checked_out"] = False
        survey.return_value = refreshed
        calls = []
        remove_tree.side_effect = lambda root, row, threshold: (
            calls.append(("worktree", row["branch"])) or (True, "tree removed")
        )
        remove_branch.side_effect = lambda root, row, threshold: (
            calls.append(("branch", row["branch"])) or (True, "branch removed")
        )

        execute_trim("repo", result(), 1)

        self.assertEqual(calls, [("worktree", "safe"), ("branch", "safe")])

    @patch("weedeat.trim.run_survey")
    @patch("weedeat.trim.prune_branch")
    @patch("weedeat.trim.prune_worktree", return_value=(False, "tree failed"))
    def test_failed_worktree_removal_protects_its_branch(
        self, _remove_tree, remove_branch, survey
    ) -> None:
        survey.return_value = result()

        outcomes = execute_trim("repo", result(), 1)

        remove_branch.assert_not_called()
        self.assertIn("branch kept because its worktree was not removed", outcomes[-1][3])

    @patch("weedeat.trim.run_survey")
    @patch("weedeat.trim.prune_branch")
    @patch("weedeat.trim.prune_worktree", return_value=(True, "tree removed"))
    def test_branch_is_kept_if_refresh_moves_it_outside_threshold(
        self, _remove_tree, remove_branch, survey
    ) -> None:
        refreshed = result()
        safe = next(row for row in refreshed["branches"] if row["branch"] == "safe")
        safe["checked_out"] = False
        safe["level"] = 4
        survey.return_value = refreshed

        outcomes = execute_trim("repo", result(), 1)

        remove_branch.assert_not_called()
        self.assertIn("classification changed", outcomes[-1][3])


if __name__ == "__main__":
    unittest.main()
