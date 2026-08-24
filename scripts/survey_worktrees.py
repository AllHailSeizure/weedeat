#!/usr/bin/env python3
"""Survey every git worktree and branch in this repo and classify removal safety.

Read-only by design: this prints findings and the commands that would act on
them. It never runs a removal itself, because the destructive step needs a human
who can recognize which parked WIP still matters.

Repo-specific knowledge (where worktrees live, which uncommitted paths carry no
work) comes from the `## Worktrees` section of `.synapse/weedeat.md`. Without it
the survey runs on generic defaults, which is correct but treats every
uncommitted file as real work.

Usage:
    python scripts/survey_worktrees.py [--json out.json] [--no-fetch]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Importing the shared scanner must not make the survey report its own bytecode
# cache as new work in the checkout it is inspecting.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from weedeat.scan import git, repo_root, run_survey

# The survey classifies on evidence and reports a numeric risk level; these
# are the names for a human reading the report. Another tool's worktree is not
# a level of its own - it is classified like any other and labeled with its
# owner, so a Cursor or Codex checkout nobody is using shows up as removable.
LEVEL_NAMES = {
    0: "PROTECTED - never proposed for removal",
    1: "SAFE - merged PR, clean tree, nothing unpushed",
    2: "STALE - no merged PR, no open PR, nothing uncommitted",
    3: "REVIEW - merged PR but the tree still has changes",
    4: "HOLD - work that exists only here",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="also write the full survey to this path")
    parser.add_argument("--no-fetch", action="store_true", help="skip git fetch --prune")
    args = parser.parse_args()

    # The Windows console defaults to a codepage that mangles non-ASCII output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = repo_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1

    if not args.no_fetch:
        print("Fetching origin (pruning deleted remote branches)...", file=sys.stderr)
    result = run_survey(root, no_fetch=args.no_fetch)
    surveyed = result["worktrees"]
    orphans = result["orphan_dirs"]
    branch_rows = result["branches"]
    have_gh = result["gh_available"]
    configured = result["configured"]
    local_count = len([
        branch for branch in git(
            "for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=root
        ).splitlines() if branch
    ])

    by_level: dict[int, list[dict]] = {}
    for entry in surveyed:
        by_level.setdefault(entry["level"], []).append(entry)

    print("\n# Worktree cleanup survey\n")
    print(f"{len(surveyed)} worktrees, {local_count} local branches, "
          f"{len(orphans)} orphaned directories.")
    if not configured:
        print("\n> No `## Worktrees` section in .synapse/weedeat.md - running on generic "
              "defaults. Every uncommitted file counts as real work, so worktrees "
              "dirty only with regenerated files will read as HOLD.")
    if not have_gh:
        print("\n> `gh` unavailable - merge status could not be checked, so nothing "
              "is classified SAFE. Everything needs manual review.")

    for level in (1, 2, 3, 4, 0):
        rows = by_level.get(level, [])
        if not rows:
            continue
        print(f"\n## {level} {LEVEL_NAMES[level]} ({len(rows)})")
        for row in rows:
            label = row["branch"] or "(detached)"
            owner = f" [created by {row['foreign']}]" if row.get("foreign") else ""
            print(f"- `{label}`{owner} - {row['reason']}")
            print(f"    {row['path']}")
            if row["dirty"]:
                shown = ", ".join(row["dirty"][:4])
                more = f" +{len(row['dirty']) - 4} more" if len(row["dirty"]) > 4 else ""
                print(f"    uncommitted: {shown}{more}")

    if orphans:
        print(f"\n## ORPHANED DIRECTORIES ({len(orphans)})")
        print("Full checkouts on disk that git no longer registers as worktrees.")
        for name in orphans:
            print(f"- `{name}`")

    deletable = [b for b in branch_rows
                 if b["merged"] and not b["unpushed"] and not b["checked_out"]]
    keepers = [b for b in branch_rows if not b["merged"] and not b["open_pr"]]
    print("\n## BRANCHES")
    print(f"- {len(deletable)} merged, not checked out, nothing unpushed - deletable")
    print(f"- {len(keepers)} with no merged PR and no open PR - need a look before deleting")
    for row in keepers:
        flag = f" ({row['unpushed']} unpushed)" if row["unpushed"] else ""
        print(f"    - `{row['branch']}`{flag}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            result, indent=2),
            encoding="utf-8")
        print(f"\nFull survey written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
