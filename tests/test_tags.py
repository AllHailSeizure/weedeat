from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from weedeat.tags import read_tags, remove_tag, set_tag, worktree_key


class TagPersistenceTest(unittest.TestCase):
    def test_tags_round_trip_in_synapse_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            set_tag(str(root), "branch", "codex/topic", 0)
            set_tag(str(root), "worktree", "../detached tree", 3)

            tags = read_tags(str(root))
            self.assertEqual(tags["branches"], {"codex/topic": 0})
            self.assertEqual(tags["worktrees"], {"../detached tree": 3})
            stored = json.loads((root / ".synapse" / "weedeat-tags.json").read_text())
            self.assertEqual(stored["version"], 1)

            remove_tag(str(root), "branch", "codex/topic")
            self.assertNotIn("codex/topic", read_tags(str(root))["branches"])

    def test_tag_level_must_be_between_zero_and_four(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for level in (-1, 5):
                with self.subTest(level=level), self.assertRaises(ValueError):
                    set_tag(temp, "branch", "topic", level)

    def test_worktree_keys_are_relative_and_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root.parent / "tree"
            self.assertEqual(worktree_key(str(root), str(path)), "../tree")


if __name__ == "__main__":
    unittest.main()
