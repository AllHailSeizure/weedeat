from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from weedeat.cli import run
from weedeat.scan import run_survey
from weedeat.trim import execute_trim


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


class RunIntegrationTest(unittest.TestCase):
    @patch("weedeat.scan.gh_pr_heads", return_value=(set(), False))
    @patch("weedeat.console.review")
    def test_headless_run_prints_numeric_report_without_opening_console(
        self, review, _pr_heads
    ) -> None:
        fake_stdout = Mock(wraps=sys.stdout)
        fake_stdout.isatty.return_value = False
        output = io.StringIO()
        fake_stdout.write.side_effect = output.write
        fake_stdout.flush.side_effect = lambda: None

        with patch("sys.stdout", fake_stdout):
            self.assertEqual(run(str(Path.cwd()), no_fetch=True), 0)

        self.assertIn("# weedeat", output.getvalue())
        self.assertRegex(output.getvalue(), r"[0-4]  ")
        review.assert_not_called()

    @patch("weedeat.cli.run_survey")
    @patch("weedeat.console.review")
    def test_interactive_run_opens_console_without_pruning(self, review, scan) -> None:
        result = {"branches": [], "worktrees": [], "orphan_dirs": []}
        scan.return_value = result
        fake_stdin = Mock()
        fake_stdin.isatty.return_value = True
        fake_stdout = Mock()
        fake_stdout.isatty.return_value = True

        with patch("sys.stdin", fake_stdin), patch("sys.stdout", fake_stdout):
            self.assertEqual(run("repo", no_fetch=True), 0)

        review.assert_called_once_with("repo", result)

    def test_run_never_prunes_until_a_trim_command_is_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            remote = base / "remote.git"
            repo = base / "repo"
            safe_tree = base / "safe-tree"
            hold_tree = base / "hold-tree"

            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True,
                           capture_output=True)
            git(repo, "config", "user.email", "weedeat@example.invalid")
            git(repo, "config", "user.name", "Weedeat Test")
            (repo / "README.md").write_text("root\n", encoding="utf-8")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "root")
            git(repo, "remote", "add", "origin", str(remote))
            git(repo, "push", "-u", "origin", "main")

            git(repo, "switch", "-c", "merged")
            (repo / "merged.txt").write_text("merged\n", encoding="utf-8")
            git(repo, "add", "merged.txt")
            git(repo, "commit", "-m", "merged work")
            git(repo, "push", "-u", "origin", "merged")
            git(repo, "switch", "main")
            git(repo, "merge", "--ff-only", "merged")
            git(repo, "worktree", "add", str(safe_tree), "merged")

            git(repo, "worktree", "add", "-b", "unmerged", str(hold_tree), "main")
            (hold_tree / "unmerged.txt").write_text("keep me\n", encoding="utf-8")
            git(hold_tree, "add", "unmerged.txt")
            git(hold_tree, "commit", "-m", "unmerged work")

            def pr_heads(state: str, _limit: int) -> tuple[set[str], bool]:
                return ({"merged"} if state == "merged" else set(), True)

            with patch("weedeat.scan.gh_pr_heads", side_effect=pr_heads):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(run(str(repo), no_fetch=True, dry_run=True), 0)
                self.assertIn("1  merged", output.getvalue())
                self.assertIn("4  unmerged", output.getvalue())

                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run(str(repo), no_fetch=True), 0)

            before_trees = git(repo, "worktree", "list", "--porcelain")
            before_branches = git(
                repo, "branch", "--format=%(refname:short)"
            ).splitlines()
            self.assertIn(str(safe_tree).replace("\\", "/"), before_trees)
            self.assertIn("merged", before_branches)

            with patch("weedeat.scan.gh_pr_heads", side_effect=pr_heads):
                result = run_survey(str(repo), no_fetch=True)
                outcomes = execute_trim(str(repo), result, 1)
            self.assertTrue(all(outcome[2] for outcome in outcomes))

            after_trees = git(repo, "worktree", "list", "--porcelain")
            after_branches = git(
                repo, "branch", "--format=%(refname:short)"
            ).splitlines()
            self.assertNotIn(str(safe_tree).replace("\\", "/"), after_trees)
            self.assertNotIn("merged", after_branches)
            self.assertIn(str(hold_tree).replace("\\", "/"), after_trees)
            self.assertIn("unmerged", after_branches)


if __name__ == "__main__":
    unittest.main()
