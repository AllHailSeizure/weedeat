from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weedeat.console import CommandConsole
from weedeat.tags import read_tags, set_tag


def survey() -> dict:
    main_tree = {
        "branch": "main", "path": "repo", "level": 0,
        "automatic_level": 0, "tag": None, "reason": "primary checkout",
        "system_protected": True, "locked": False,
    }
    topic_tree = {
        "branch": "codex/topic", "path": "topic-tree", "level": 2,
        "automatic_level": 2, "tag": None, "reason": "stale",
        "system_protected": False, "locked": False,
    }
    detached = {
        "branch": "", "path": "detached-tree", "level": 4,
        "automatic_level": 4, "tag": None, "reason": "unpushed commits",
        "system_protected": False, "locked": False,
    }
    return {
        "worktrees": [main_tree, topic_tree, detached],
        "branches": [
            {**main_tree, "checked_out": True},
            {**topic_tree, "checked_out": True},
        ],
        "orphan_dirs": [],
        "gh_available": True,
        "configured": True,
    }


def inputs(*commands: str):
    iterator = iter(commands)
    return lambda _prompt="": next(iterator)


class CommandConsoleTest(unittest.TestCase):
    def test_launch_prints_header_and_one_line_per_branch(self) -> None:
        output = io.StringIO()
        CommandConsole("repo", survey(), inputs("quit"), output).run()

        text = output.getvalue()
        self.assertIn("weedeat\n", text)
        self.assertIn("0  main", text)
        self.assertIn("2  codex/topic", text)
        self.assertIn("4  (detached: detached-tree)", text)

    @patch("weedeat.console.run_survey", side_effect=lambda *_args, **_kwargs: survey())
    def test_branch_tag_is_persisted(self, _scan) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = io.StringIO()
            console = CommandConsole(
                temp, survey(), inputs("branch codex/topic tag 0", "quit"), output
            )
            console.run()

            self.assertEqual(read_tags(temp)["branches"]["codex/topic"], 0)
            self.assertIn("Tagged codex/topic at level 0", output.getvalue())

    @patch("weedeat.console.run_survey", side_effect=lambda *_args, **_kwargs: survey())
    def test_tagging_attached_worktree_updates_its_branch(self, _scan) -> None:
        with tempfile.TemporaryDirectory() as temp:
            CommandConsole(
                temp,
                survey(),
                inputs('worktree "topic-tree" tag 1', "quit"),
                io.StringIO(),
            ).run()

            self.assertEqual(read_tags(temp)["branches"]["codex/topic"], 1)
            self.assertEqual(read_tags(temp)["worktrees"], {})

    def test_system_protected_branch_cannot_be_made_deletable(self) -> None:
        output = io.StringIO()
        CommandConsole(
            "repo", survey(), inputs("branch main tag 1", "quit"), output
        ).run()
        self.assertIn("main is system-protected", output.getvalue())

    @patch("weedeat.console.run_survey", side_effect=lambda *_args, **_kwargs: survey())
    def test_untag_removes_override(self, _scan) -> None:
        with tempfile.TemporaryDirectory() as temp:
            set_tag(temp, "branch", "codex/topic", 0)
            CommandConsole(
                temp, survey(), inputs("branch codex/topic untag", "quit"), io.StringIO()
            ).run()
            self.assertNotIn("codex/topic", read_tags(temp)["branches"])

    @patch("weedeat.console.run_survey", side_effect=lambda *_args, **_kwargs: survey())
    @patch("weedeat.console.execute_trim", return_value=[])
    def test_trim_requires_confirmation(self, execute, _scan) -> None:
        output = io.StringIO()
        CommandConsole("repo", survey(), inputs("trim 2", "n", "quit"), output).run()
        execute.assert_not_called()
        self.assertIn("Trim cancelled", output.getvalue())

        CommandConsole("repo", survey(), inputs("trim 2", "y", "quit"), output).run()
        execute.assert_called_once()

    @patch("weedeat.console.run_survey", side_effect=lambda *_args, **_kwargs: survey())
    @patch("weedeat.console.execute_shear", return_value=[])
    @patch("weedeat.console.plan_shear")
    def test_shear_requires_confirmation(self, plan, execute, _scan) -> None:
        from weedeat.shear import ShearPlan

        plan.return_value = ShearPlan(
            branch="main",
            remote_ref="origin/main",
            worktree="repo",
            paths=["dup.txt"],
        )
        output = io.StringIO()
        CommandConsole("repo", survey(), inputs("shear main", "n", "quit"), output).run()
        execute.assert_not_called()
        self.assertIn("Shear cancelled", output.getvalue())

        CommandConsole("repo", survey(), inputs("shear main", "y", "quit"), output).run()
        execute.assert_called_once()

    def test_help_lists_shear(self) -> None:
        output = io.StringIO()
        CommandConsole("repo", survey(), inputs("help", "quit"), output).run()
        self.assertIn("shear <branch>", output.getvalue())

    def test_unknown_command_shows_help_hint(self) -> None:
        output = io.StringIO()
        CommandConsole("repo", survey(), inputs("wat", "quit"), output).run()
        self.assertIn("Unknown command. Type help.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
