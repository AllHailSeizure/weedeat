"""Guarded Git mutations used by an explicitly confirmed trim command."""

from __future__ import annotations

import subprocess


def _run(root: str, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    message = (result.stdout if result.returncode == 0 else result.stderr).strip()
    if not message:
        message = "completed" if result.returncode == 0 else "git command failed"
    return result.returncode == 0, message


def prune_worktree(root: str, entry: dict, threshold: int) -> tuple[bool, str]:
    """Remove one worktree selected by an explicit trim threshold."""
    assert 1 <= entry["level"] <= threshold, "worktree is outside trim threshold"
    assert not entry.get("system_protected"), "protected worktrees cannot be removed"
    assert not entry.get("locked"), "locked worktrees cannot be removed"
    return _run(root, "worktree", "remove", "--force", entry["path"])


def prune_branch(root: str, entry: dict, threshold: int) -> tuple[bool, str]:
    """Delete one unattached branch selected by an explicit trim threshold."""
    assert 1 <= entry["level"] <= threshold, "branch is outside trim threshold"
    assert not entry.get("system_protected"), "protected branches cannot be removed"
    assert not entry["checked_out"], "checked-out branches cannot be removed"
    return _run(root, "branch", "-D", entry["branch"])
