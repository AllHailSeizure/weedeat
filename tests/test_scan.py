from __future__ import annotations

import unittest
from unittest.mock import patch

from weedeat.scan import apply_tag, classify


class NumericClassificationTest(unittest.TestCase):
    def classify(self, *, merged=False, open_pr=False, dirt=None, unpushed=0,
                 tree=None, protected=()) -> dict:
        tree = tree or {"path": "tree", "branch": "topic"}
        with patch("weedeat.scan.real_dirt", return_value=dirt or []), patch(
            "weedeat.scan.unpushed_count", return_value=unpushed
        ), patch("weedeat.scan.os.path.abspath", side_effect=lambda value: value):
            return classify(
                tree,
                "repo",
                {"topic"} if merged else set(),
                {"topic"} if open_pr else set(),
                True,
                [".codex"],
                (),
                (),
                set(protected),
            )

    def test_automatic_levels_increase_with_risk(self) -> None:
        self.assertEqual(self.classify(merged=True)["level"], 1)
        self.assertEqual(self.classify()["level"], 2)
        self.assertEqual(self.classify(merged=True, dirt=["changed"])["level"], 3)
        self.assertEqual(self.classify(open_pr=True)["level"], 4)

    def test_system_protected_entries_are_level_zero(self) -> None:
        cases = (
            ({"path": "repo", "branch": "main"}, ()),
            ({"path": "tree", "branch": "release"}, ("release",)),
            ({"path": "tree", "branch": "topic", "locked": True}, ()),
        )
        for tree, protected in cases:
            with self.subTest(tree=tree):
                row = self.classify(tree=tree, protected=protected)
                self.assertEqual(row["level"], 0)
                self.assertTrue(row["system_protected"])

    def test_another_tools_worktree_is_classified_on_the_same_evidence(self) -> None:
        codex = {"path": "repo/.codex/tree", "branch": "topic"}
        merged = self.classify(tree=codex, merged=True)
        self.assertEqual(merged["level"], 1)
        self.assertFalse(merged["system_protected"])
        self.assertEqual(merged["foreign"], ".codex")
        self.assertIn(".codex", merged["reason"])

        holding = self.classify(tree=codex, dirt=["scene.tscn"])
        self.assertEqual(holding["level"], 4)

    def test_another_tools_worktree_can_be_tagged_out_of_reach(self) -> None:
        codex = self.classify(tree={"path": "repo/.codex/tree", "branch": "topic"},
                              merged=True)
        parked = apply_tag(codex, {"branches": {"topic": 0}}, "repo")
        self.assertEqual(parked["level"], 0)
        self.assertEqual(parked["tag"], 0)

    def test_manual_tag_overrides_ordinary_entry_but_not_system_protection(self) -> None:
        ordinary = self.classify()
        tagged = apply_tag(ordinary, {"branches": {"topic": 0}}, "repo")
        self.assertEqual(tagged["automatic_level"], 2)
        self.assertEqual(tagged["level"], 0)
        self.assertEqual(tagged["tag"], 0)

        protected = self.classify(tree={"path": "repo", "branch": "main"})
        ignored = apply_tag(protected, {"branches": {"main": 1}}, "repo")
        self.assertEqual(ignored["level"], 0)
        self.assertIsNone(ignored["tag"])


if __name__ == "__main__":
    unittest.main()
