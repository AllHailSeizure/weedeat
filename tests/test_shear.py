from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from weedeat.shear import execute_shear, plan_shear


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


def make_repo_with_remote() -> tuple[Path, Path]:
    """Create a bare origin and a clone on master with one committed file."""
    base = Path(tempfile.mkdtemp())
    remote = base / "remote.git"
    repo = base / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "master", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "weedeat@example.invalid")
    git(repo, "config", "user.name", "Weedeat Test")
    (repo / "tracked.txt").write_text("v1\n", encoding="utf-8")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-m", "root")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "master")
    return repo, remote


def advance_remote(repo: Path, remote: Path, **files: str) -> None:
    other = repo.parent / "other"
    if other.exists():
        subprocess.run(["rm", "-rf", str(other)], check=True)
    git(repo.parent, "clone", str(remote), str(other))
    git(other, "config", "user.email", "weedeat@example.invalid")
    git(other, "config", "user.name", "Weedeat Test")
    for name, content in files.items():
        (other / name).write_text(content, encoding="utf-8")
    git(other, "add", *files)
    git(other, "commit", "-m", "remote advance")
    git(other, "push", "origin", "master")


class ShearPlanTest(unittest.TestCase):
    def test_plans_local_dirt_that_already_matches_remote(self) -> None:
        repo, remote = make_repo_with_remote()
        advance_remote(
            repo, remote,
            **{"tracked.txt": "v2-on-remote\n", "new-on-remote.txt": "remote-only\n"},
        )

        (repo / "tracked.txt").write_text("v2-on-remote\n", encoding="utf-8")
        (repo / "new-on-remote.txt").write_text("remote-only\n", encoding="utf-8")
        (repo / "local-only.txt").write_text("keep me\n", encoding="utf-8")

        plan = plan_shear(str(repo), "master")

        self.assertEqual(plan.branch, "master")
        self.assertEqual(plan.remote_ref, "origin/master")
        self.assertEqual(sorted(plan.paths), ["new-on-remote.txt", "tracked.txt"])
        self.assertNotIn("local-only.txt", plan.paths)

    def test_keeps_local_only_modifications(self) -> None:
        repo, _remote = make_repo_with_remote()
        (repo / "tracked.txt").write_text("local-only-edit\n", encoding="utf-8")

        plan = plan_shear(str(repo), "master")

        self.assertEqual(plan.paths, [])

    def test_unknown_branch_raises(self) -> None:
        repo, _remote = make_repo_with_remote()
        with self.assertRaises(ValueError):
            plan_shear(str(repo), "does-not-exist")


class ShearExecuteTest(unittest.TestCase):
    def test_execute_reverts_shearable_paths_and_keeps_local_only(self) -> None:
        repo, remote = make_repo_with_remote()
        advance_remote(
            repo, remote,
            **{"tracked.txt": "v2-on-remote\n", "new-on-remote.txt": "remote-only\n"},
        )

        (repo / "tracked.txt").write_text("v2-on-remote\n", encoding="utf-8")
        (repo / "new-on-remote.txt").write_text("remote-only\n", encoding="utf-8")
        (repo / "local-only.txt").write_text("keep me\n", encoding="utf-8")

        plan = plan_shear(str(repo), "master")
        outcomes = execute_shear(str(repo), plan)

        self.assertTrue(all(success for _path, success, _msg in outcomes))
        self.assertEqual((repo / "tracked.txt").read_text(encoding="utf-8"), "v1\n")
        self.assertFalse((repo / "new-on-remote.txt").exists())
        self.assertEqual((repo / "local-only.txt").read_text(encoding="utf-8"), "keep me\n")
        status = git(repo, "status", "--porcelain")
        self.assertNotIn("tracked.txt", status)
        self.assertIn("local-only.txt", status)


if __name__ == "__main__":
    unittest.main()
