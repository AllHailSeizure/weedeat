"""Plan and execute explicitly confirmed numeric trim operations."""

from __future__ import annotations

from weedeat.prune import prune_branch, prune_worktree
from weedeat.scan import run_survey


Outcome = tuple[str, str, bool, str]


def trim_candidates(result: dict, threshold: int) -> tuple[list[dict], list[dict]]:
    if threshold not in range(1, 5):
        raise ValueError("trim level must be between 1 and 4")

    def selected(row: dict) -> bool:
        return (
            not row.get("system_protected")
            and 1 <= row.get("level", 0) <= threshold
        )

    return (
        [row for row in result["worktrees"] if selected(row)],
        [row for row in result["branches"] if selected(row)],
    )


def execute_trim(root: str, result: dict, threshold: int) -> list[Outcome]:
    """Remove selected worktrees, refresh, then remove their branches."""
    worktrees, branches = trim_candidates(result, threshold)
    outcomes: list[Outcome] = []
    worktree_success: dict[str, bool] = {}

    for entry in worktrees:
        success, message = prune_worktree(root, entry, threshold)
        label = entry.get("branch") or entry["path"]
        outcomes.append(("worktree", label, success, message))
        if entry.get("branch"):
            worktree_success[entry["branch"]] = success

    if not branches:
        return outcomes

    refreshed = run_survey(root, no_fetch=True)
    refreshed_branches = {row["branch"]: row for row in refreshed["branches"]}
    for candidate in branches:
        branch = candidate["branch"]
        if branch in worktree_success and not worktree_success[branch]:
            outcomes.append((
                "branch", branch, False,
                "branch kept because its worktree was not removed",
            ))
            continue
        entry = refreshed_branches.get(branch)
        if entry is None:
            outcomes.append(("branch", branch, False, "branch no longer exists"))
            continue
        if entry["checked_out"]:
            outcomes.append(("branch", branch, False, "branch is still checked out"))
            continue
        if (
            entry.get("system_protected")
            or not 1 <= entry.get("level", 0) <= threshold
        ):
            outcomes.append((
                "branch", branch, False,
                "branch kept because its classification changed",
            ))
            continue
        success, message = prune_branch(root, entry, threshold)
        outcomes.append(("branch", branch, success, message))
    return outcomes
