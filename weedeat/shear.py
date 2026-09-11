"""Shear local working-tree changes that already exist on the remote branch.

`shear <branch>` fetches, compares the local worktree for that branch to
`origin/<branch>`, and reverts any local dirt whose content is already present
on the remote. Local-only modifications are left alone.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from weedeat.scan import git, list_worktrees


@dataclass(frozen=True)
class ShearPlan:
    branch: str
    remote_ref: str
    worktree: str
    paths: list[str]


def _run(cwd: str, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    message = (result.stdout if result.returncode == 0 else result.stderr).strip()
    if not message:
        message = "completed" if result.returncode == 0 else "git command failed"
    return result.returncode == 0, message


def _ref_exists(root: str, ref: str) -> bool:
    return bool(git("rev-parse", "--verify", "--quiet", ref, cwd=root))


def _worktree_for_branch(root: str, branch: str) -> str | None:
    for tree in list_worktrees(root):
        if tree.get("branch") == branch and tree.get("path"):
            return tree["path"]
    return None


def _status_paths(worktree: str) -> list[tuple[str, str]]:
    """Return (status_code, path) pairs from `git status --porcelain`."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "-uall"], cwd=worktree,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code, name = line[:2], line[3:].strip().strip('"')
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        entries.append((code, name))
    return entries


def _blob_at_ref(root: str, ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}:{path}"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _worktree_blob(worktree: str, path: str) -> str | None:
    full = Path(worktree) / path
    if not full.is_file():
        return None
    result = subprocess.run(
        ["git", "hash-object", str(full)], cwd=worktree,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _is_untracked(code: str) -> bool:
    return code.strip() == "??" or code == "??"


def shearable_paths(root: str, worktree: str, remote_ref: str) -> list[str]:
    """Local dirt whose content already matches `remote_ref`."""
    found: list[str] = []
    for code, path in _status_paths(worktree):
        remote_blob = _blob_at_ref(root, remote_ref, path)
        missing_locally = not (Path(worktree) / path).exists()
        if missing_locally and not _is_untracked(code):
            # Local deletion that remote already made.
            if remote_blob is None:
                found.append(path)
            continue
        local_blob = _worktree_blob(worktree, path)
        if local_blob is None or remote_blob is None:
            continue
        if local_blob == remote_blob:
            found.append(path)
    return sorted(set(found))


def plan_shear(root: str, branch: str, *, fetch: bool = True) -> ShearPlan:
    if not _ref_exists(root, f"refs/heads/{branch}"):
        raise ValueError(f"Unknown local branch: {branch}")

    if fetch:
        ok, message = _run(root, "fetch", "origin", "--prune")
        if not ok:
            raise ValueError(f"git fetch failed: {message}")

    remote_ref = f"origin/{branch}"
    if not _ref_exists(root, remote_ref):
        raise ValueError(f"No remote-tracking ref {remote_ref}")

    worktree = _worktree_for_branch(root, branch)
    if worktree is None:
        raise ValueError(f"Branch {branch} is not checked out in any worktree")

    paths = shearable_paths(root, worktree, remote_ref)
    return ShearPlan(
        branch=branch, remote_ref=remote_ref, worktree=worktree, paths=paths,
    )


def execute_shear(root: str, plan: ShearPlan) -> list[tuple[str, bool, str]]:
    """Revert planned paths: restore tracked files to HEAD; remove untracked duplicates."""
    outcomes: list[tuple[str, bool, str]] = []
    worktree = plan.worktree
    status = {path: code for code, path in _status_paths(worktree)}

    for path in plan.paths:
        code = status.get(path, "  ")
        if _is_untracked(code):
            full = Path(worktree) / path
            try:
                if full.is_file() or full.is_symlink():
                    full.unlink()
                else:
                    outcomes.append((path, False, "untracked path not a removable file"))
                    continue
            except OSError as error:
                outcomes.append((path, False, str(error)))
                continue
            outcomes.append((path, True, "removed untracked duplicate of remote"))
            continue

        if not (Path(worktree) / path).exists() and _blob_at_ref(
            root, plan.remote_ref, path
        ) is None:
            ok, message = _run(worktree, "rm", "-f", "--", path)
            outcomes.append((path, ok, message))
            continue

        ok, message = _run(
            worktree, "restore", "--worktree", "--staged", "--source=HEAD", "--", path
        )
        if not ok:
            ok, message = _run(worktree, "checkout", "HEAD", "--", path)
        outcomes.append((path, ok, message))
    return outcomes
