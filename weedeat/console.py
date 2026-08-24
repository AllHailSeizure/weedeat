"""Line-oriented interactive console for reviewing and trimming Git work."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, TextIO

from weedeat.scan import git, read_manifest, run_survey
from weedeat.tags import remove_tag, set_tag, worktree_key
from weedeat.trim import execute_trim, trim_candidates


InputFn = Callable[[str], str]


def review_base(root: str) -> str:
    manifest = read_manifest(root)
    configured = manifest.get("worktrees", {}).get("base", [])
    if configured:
        return configured[-1]

    identity = Path(root) / ".synapse" / "identity.md"
    if identity.is_file():
        section = ""
        for line in identity.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                section = stripped[3:].strip().lower()
            elif section == "identity" and stripped.lower().startswith("base:"):
                branch = stripped.partition(":")[2].strip()
                if branch:
                    remote = f"origin/{branch}"
                    if git("rev-parse", "--verify", "--quiet", remote, cwd=root):
                        return remote
                    return branch

    remote_head = git(
        "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", cwd=root
    )
    if remote_head:
        return remote_head
    for candidate in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", candidate, cwd=root):
            return candidate
    return "HEAD"


def branch_diff(root: str, base: str, branch: str) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base}...{branch}"], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return result.stderr.strip() or "git diff failed"
    return result.stdout or "No committed diff from the baseline."


class CommandConsole:
    def __init__(self, root: str, result: dict, input_fn: InputFn, output: TextIO) -> None:
        self.root = root
        self.result = result
        self.input = input_fn
        self.output = output

    def run(self) -> None:
        self._write("weedeat")
        self._write(f"{Path(self.root).name} — {len(self.result['branches'])} branches")
        self._write()
        self.render_list()
        self._write("\nType help for commands.")
        while True:
            try:
                raw = self.input("\n> ")
            except (EOFError, KeyboardInterrupt, StopIteration):
                self._write()
                return
            try:
                parts = shlex.split(raw)
            except ValueError as error:
                self._write(f"Invalid command: {error}")
                continue
            if not parts:
                continue
            if self.dispatch(parts):
                return

    def dispatch(self, parts: list[str]) -> bool:
        command = parts[0].lower()
        if command in ("quit", "exit") and len(parts) == 1:
            return True
        if command == "help" and len(parts) == 1:
            self.render_help()
        elif command == "list" and len(parts) == 1:
            self.render_list()
        elif command in ("branch", "worktree"):
            self._tag_command(command, parts[1:])
        elif command == "trim" and len(parts) == 2:
            self._trim_command(parts[1])
        elif command == "diff" and len(parts) == 2:
            self._diff_command(parts[1])
        else:
            self._write("Unknown command. Type help.")
        return False

    def render_list(self) -> None:
        for row in sorted(self.result["branches"], key=lambda item: (item["level"], item["branch"])):
            suffix = f" — {row['reason']}"
            if row.get("path"):
                suffix += f" [worktree: {row['path']}]"
            if row.get("tag") is not None:
                suffix += " [tagged]"
            self._write(f"{row['level']}  {row['branch']}{suffix}")
        for row in self.result["worktrees"]:
            if row.get("branch"):
                continue
            suffix = " [tagged]" if row.get("tag") is not None else ""
            self._write(
                f"{row['level']}  (detached: {row['path']}) — {row['reason']}{suffix}"
            )

    def render_help(self) -> None:
        self._write("list")
        self._write("branch <name> tag <0-4>")
        self._write("branch <name> untag")
        self._write("worktree <path> tag <0-4>")
        self._write("worktree <path> untag")
        self._write("diff <branch>")
        self._write("trim <1-4>")
        self._write("quit")

    def _tag_command(self, kind: str, args: list[str]) -> None:
        if len(args) == 3 and args[1].lower() == "tag":
            target, raw_level = args[0], args[2]
            try:
                level = int(raw_level)
            except ValueError:
                self._write("Tag level must be a number from 0 to 4.")
                return
            if level not in range(5):
                self._write("Tag level must be a number from 0 to 4.")
                return
            resolved = self._resolve_tag_target(kind, target, require_existing=True)
            if resolved is None:
                return
            tag_kind, tag_target, row = resolved
            if row.get("system_protected"):
                self._write(f"{target} is system-protected and cannot be retagged.")
                return
            set_tag(self.root, tag_kind, tag_target, level)
            self._write(f"Tagged {target} at level {level}.")
            self.refresh()
            return
        if len(args) == 2 and args[1].lower() == "untag":
            target = args[0]
            resolved = self._resolve_tag_target(kind, target, require_existing=False)
            if resolved is None:
                return
            tag_kind, tag_target, _row = resolved
            if remove_tag(self.root, tag_kind, tag_target):
                self._write(f"Removed tag from {target}.")
                self.refresh()
            else:
                self._write(f"{target} has no manual tag.")
            return
        self._write(f"Usage: {kind} <target> tag <0-4> | {kind} <target> untag")

    def _resolve_tag_target(
        self, kind: str, target: str, *, require_existing: bool
    ) -> tuple[str, str, dict] | None:
        if kind == "branch":
            row = next(
                (entry for entry in self.result["branches"] if entry["branch"] == target),
                None,
            )
            if row is None and require_existing:
                self._write(f"Unknown branch: {target}")
                return None
            return "branch", target, row or {}

        row = self._find_worktree(target)
        if row is None:
            if require_existing:
                self._write(f"Unknown worktree: {target}")
                return None
            return "worktree", worktree_key(self.root, target), {}
        if row.get("branch"):
            return "branch", row["branch"], row
        return "worktree", worktree_key(self.root, row["path"]), row

    def _find_worktree(self, target: str) -> dict | None:
        target_absolute = os.path.normcase(os.path.abspath(target))
        for row in self.result["worktrees"]:
            path = row["path"]
            if path == target:
                return row
            if os.path.normcase(os.path.abspath(path)) == target_absolute:
                return row
            if worktree_key(self.root, path) == target.replace("\\", "/"):
                return row
        return None

    def _trim_command(self, raw_level: str) -> None:
        try:
            level = int(raw_level)
            worktrees, branches = trim_candidates(self.result, level)
        except ValueError:
            self._write("Trim level must be a number from 1 to 4.")
            return
        if not worktrees and not branches:
            self._write(f"Nothing is eligible for trim {level}.")
            return
        self._write(f"trim {level} will remove:")
        for row in worktrees:
            self._write(f"- worktree {row.get('branch') or row['path']} ({row['path']})")
        for row in branches:
            self._write(f"- branch {row['branch']}")
        try:
            confirmed = self.input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt, StopIteration):
            confirmed = ""
        if confirmed not in ("y", "yes"):
            self._write("Trim cancelled.")
            return
        for kind, label, success, message in execute_trim(self.root, self.result, level):
            status = "removed" if success else "kept"
            self._write(f"{status}: {kind} {label} — {message}")
        self.refresh()

    def _diff_command(self, branch: str) -> None:
        if not any(row["branch"] == branch for row in self.result["branches"]):
            self._write(f"Unknown branch: {branch}")
            return
        base = review_base(self.root)
        self._write(f"git diff {base}...{branch}")
        self._write(branch_diff(self.root, base, branch))

    def refresh(self) -> None:
        self.result = run_survey(self.root, no_fetch=True)

    def _write(self, text: str = "") -> None:
        print(text, file=self.output)


def review(root: str, result: dict, input_fn: InputFn | None = None,
           output: TextIO | None = None) -> None:
    CommandConsole(root, result, input_fn or input, output or sys.stdout).run()
