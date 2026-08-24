"""Command-line entry points for the weedeat cleanup console."""

from __future__ import annotations

import argparse
import json
import sys

from weedeat.scan import repo_root, run_survey


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weedeat")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="emit the survey as JSON")
    scan_parser.add_argument(
        "--no-fetch", action="store_true", help="skip git fetch --prune"
    )

    run_parser = subparsers.add_parser("run", help="open the cleanup command prompt")
    run_parser.add_argument(
        "--no-fetch", action="store_true", help="skip git fetch --prune"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true",
        help="print the current classifications without opening the prompt",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1

    if args.command == "scan":
        result = run_survey(root, no_fetch=args.no_fetch)
        json.dump(result, sys.stdout, indent=2)
        return 0

    return run(root, no_fetch=args.no_fetch, dry_run=args.dry_run)


def run(root: str, no_fetch: bool = False, dry_run: bool = False) -> int:
    """Survey once, then open the prompt only when both streams are interactive."""
    result = run_survey(root, no_fetch=no_fetch)
    if not dry_run and sys.stdin.isatty() and sys.stdout.isatty():
        from weedeat.console import review

        review(root, result)
    else:
        print_survey(result, dry_run=dry_run)
    return 0


def print_survey(result: dict, *, dry_run: bool = False) -> None:
    print("# weedeat")
    if dry_run:
        print("# dry run — nothing was removed")
    print()
    for row in sorted(result["branches"], key=lambda item: (item["level"], item["branch"])):
        suffix = f" — {row['reason']}"
        if row.get("path"):
            suffix += f" [worktree: {row['path']}]"
        if row.get("tag") is not None:
            suffix += " [tagged]"
        print(f"{row['level']}  {row['branch']}{suffix}")
    for row in result["worktrees"]:
        if not row.get("branch"):
            print(f"{row['level']}  (detached: {row['path']}) — {row['reason']}")
    if result.get("orphan_dirs"):
        print("\nOrphan directories:")
        for path in result["orphan_dirs"]:
            print(f"- {path}")
