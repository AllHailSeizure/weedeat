"""Deterministic worktree and branch survey used by every weedeat frontend."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from weedeat.tags import read_tags, worktree_key

DEFAULT_CONTAINERS = [
    ".claude/worktrees", ".worktrees", "worktrees",
    ".cursor/worktrees", ".codex/worktrees",
]

# Path fragments marking a worktree some other tool created. These name the
# owner in the report so a human can tell whose session a removal would
# interrupt, but they do not exempt anything: another tool's abandoned checkout
# is still this repo's clutter, and the evidence that protects real work —
# uncommitted files, unpushed commits, an open PR — is the same either way. A
# tool that really is mid-session gets `tag 0` for as long as that lasts.
# Tool-level rather than repo-level, so it holds up as a default anywhere.
DEFAULT_FOREIGN = [".cursor", ".codex", ".vscode"]

DEFAULT_PROTECTED = ["master", "main"]


def git(*args: str, cwd: str | None = None) -> str:
    return _git_raw(*args, cwd=cwd).strip()


def _git_raw(*args: str, cwd: str | None = None) -> str:
    """Unstripped output.

    `git status --porcelain` encodes state in fixed columns, and its first line
    often begins with a space (` M file`). Stripping the whole blob eats that
    space and shifts the filename by one character, so status parsing uses this.
    """
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout


def repo_root() -> str:
    return git("rev-parse", "--show-toplevel")


def read_manifest(root: str) -> dict[str, dict[str, list[str]]]:
    """Parse `.synapse/weedeat.md` into {section: {key: [values]}}.

    Only this tool's own file is read. It needs nothing from `identity.md` —
    the survey works off local refs and the PR list, not a baseline branch —
    and nothing at all from `bandaids.md`. There is no fallback to a root
    SYNAPSE.md: a stale file nobody remembers is worse than clean defaults.

    Sections are `## Heading`, entries are `key: value`. Repeated keys
    accumulate. Code fences are skipped, so the fenced and bare styles both
    parse the same.
    """
    path = Path(root) / ".synapse" / "weedeat.md"
    if not path.is_file():
        return {}
    sections: dict[str, dict[str, list[str]]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            sections.setdefault(current, {})
            continue
        if current is None or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key, value = key.strip().lower(), value.strip()
        # Prose in a section reads as a key when it happens to contain a colon;
        # a real entry key is a single bare word.
        if key and value and " " not in key:
            sections[current].setdefault(key, []).append(value)
    return sections


def csv(section: dict, key: str, default: list[str] | None = None) -> list[str]:
    values = section.get(key)
    if not values:
        return list(default) if default is not None else []
    return [item.strip() for item in values[-1].split(",") if item.strip()]


def worktrees_config(manifest: dict) -> dict:
    """The `## Worktrees` section of .synapse/weedeat.md, shaped for the survey."""
    section = manifest.get("worktrees", {})
    if not section:
        return {}
    return {
        "containers": csv(section, "containers", DEFAULT_CONTAINERS),
        "foreign_markers": csv(section, "foreign", DEFAULT_FOREIGN),
        "noise_suffixes": csv(section, "noise-suffixes"),
        "noise_dirs": csv(section, "noise-dirs"),
        "protected_branches": csv(section, "protected", DEFAULT_PROTECTED),
    }


def list_worktrees(root: str) -> list[dict]:
    """Parse `git worktree list --porcelain` into records."""
    out = git("worktree", "list", "--porcelain", cwd=root)
    trees, current = [], {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                trees.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "branch":
            current["branch"] = value.replace("refs/heads/", "")
        elif key == "HEAD":
            current["head"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "locked":
            current["locked"] = True
    if current:
        trees.append(current)
    return trees


def real_dirt(path: str, noise_suffixes: tuple[str, ...],
              noise_dirs: tuple[str, ...]) -> list[str]:
    """Uncommitted files in a worktree, excluding configured regenerable noise."""
    if not os.path.isdir(path):
        return []
    out = _git_raw("status", "--porcelain", cwd=path)
    dirt = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip().strip('"')
        # Renames report "old -> new"; the destination is what exists on disk.
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if noise_suffixes and name.endswith(noise_suffixes):
            continue
        if any(name.startswith(d) for d in noise_dirs):
            continue
        dirt.append(name)
    return dirt


def unpushed_count(root: str, ref: str) -> int:
    """Commits on `ref` that exist on no origin branch — unrecoverable if deleted."""
    if not ref:
        return 0
    out = git("rev-list", "--count", ref, "--not", "--remotes=origin", cwd=root)
    return int(out) if out.isdigit() else 0


def gh_pr_heads(state: str, limit: int) -> tuple[set[str], bool]:
    result = subprocess.run(
        ["gh", "pr", "list", "--state", state, "--limit", str(limit),
         "--json", "headRefName", "-q", ".[].headRefName"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        return set(), False
    return {b.strip() for b in result.stdout.split() if b.strip()}, True


def orphan_dirs(root: str, containers: list[str], registered: set[str]) -> list[str]:
    """Directories that look like worktrees but git no longer tracks as such.

    These are full checkouts consuming disk with no git registration, usually
    left when a worktree was pruned without removing its directory.
    """
    found = []
    for container in containers:
        base = Path(root) / container
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            resolved = str(child.resolve()).replace("\\", "/")
            if resolved not in registered:
                found.append(f"{container}/{child.name}")
    return found


def classify(tree: dict, root: str, merged: set[str], open_heads: set[str],
             have_gh: bool, foreign_markers: list[str],
             noise_suffixes: tuple[str, ...], noise_dirs: tuple[str, ...],
             protected_branches: set[str]) -> dict:
    path = tree.get("path", "")
    branch = tree.get("branch", "")
    norm = path.replace("\\", "/")
    is_main = os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(root))
    foreign = next((m for m in foreign_markers if m in norm), None)

    dirt = real_dirt(path, noise_suffixes, noise_dirs)
    unpushed = unpushed_count(root, branch or tree.get("head", ""))
    is_merged = branch in merged if have_gh else False
    is_open = branch in open_heads

    system_protected = False
    if is_main:
        level, why, system_protected = 0, "primary checkout", True
    elif branch in protected_branches:
        level, why, system_protected = 0, "configured protected branch", True
    elif tree.get("locked"):
        level, why, system_protected = 0, "worktree is locked", True
    elif is_open:
        level, why = 4, "branch has an open PR"
    elif dirt or unpushed:
        bits = []
        if dirt:
            bits.append(f"{len(dirt)} uncommitted file(s)")
        if unpushed:
            bits.append(f"{unpushed} unpushed commit(s)")
        level = 3 if is_merged else 4
        why = " + ".join(bits) + (" despite merged PR" if is_merged else "")
    elif is_merged:
        level, why = 1, "PR merged, tree clean, nothing unpushed"
    elif not have_gh:
        level, why = 4, "gh unavailable - merge status not checked"
    else:
        level, why = 2, "no merged PR, no open PR, nothing uncommitted"

    if foreign:
        why = f"{why} ({foreign} worktree)"

    return {
        "path": path, "branch": branch, "level": level, "foreign": foreign,
        "automatic_level": level, "tag": None, "reason": why,
        "dirty": dirt, "unpushed": unpushed, "merged": is_merged,
        "detached": tree.get("detached", False), "locked": tree.get("locked", False),
        "system_protected": system_protected,
    }


def apply_tag(row: dict, tags: dict, root: str) -> dict:
    """Apply a manual override unless the row is protected by a hard invariant."""
    result = dict(row)
    if result.get("system_protected"):
        return result
    branch = result.get("branch")
    if branch and branch in tags.get("branches", {}):
        tag = tags["branches"][branch]
    elif result.get("path"):
        tag = tags.get("worktrees", {}).get(worktree_key(root, result["path"]))
    else:
        tag = None
    if tag is not None:
        result["level"] = tag
        result["tag"] = tag
    return result


def classify_branch(branch: str, *, merged: set[str], open_heads: set[str],
                    have_gh: bool, unpushed: int, protected: set[str],
                    worktree: dict | None) -> dict:
    if worktree is not None:
        return {
            "branch": branch,
            "path": worktree["path"],
            "level": worktree["level"],
            "automatic_level": worktree["automatic_level"],
            "tag": worktree["tag"],
            "reason": worktree["reason"],
            "foreign": worktree.get("foreign"),
            "merged": worktree["merged"],
            "open_pr": branch in open_heads,
            "unpushed": worktree["unpushed"],
            "checked_out": True,
            "system_protected": worktree["system_protected"],
        }
    if branch in protected:
        level, reason, system_protected = 0, "configured protected branch", True
    elif branch in open_heads:
        level, reason, system_protected = 4, "branch has an open PR", False
    elif unpushed:
        level = 3 if branch in merged else 4
        reason = f"{unpushed} unpushed commit(s)"
        system_protected = False
    elif branch in merged:
        level, reason, system_protected = 1, "PR merged, nothing unpushed", False
    elif not have_gh:
        level, reason, system_protected = 4, "gh unavailable - merge status not checked", False
    else:
        level, reason, system_protected = 2, "no merged PR or open PR", False
    return {
        "branch": branch,
        "path": None,
        "level": level,
        "automatic_level": level,
        "tag": None,
        "reason": reason,
        "foreign": None,
        "merged": branch in merged,
        "open_pr": branch in open_heads,
        "unpushed": unpushed,
        "checked_out": False,
        "system_protected": system_protected,
    }


def run_survey(root: str, no_fetch: bool = False) -> dict:
    """Build the complete deterministic survey without rendering a report."""
    cfg = worktrees_config(read_manifest(root))
    containers = list(cfg.get("containers", DEFAULT_CONTAINERS))
    foreign_markers = list(cfg.get("foreign_markers", DEFAULT_FOREIGN))
    noise_suffixes = tuple(cfg.get("noise_suffixes", []))
    noise_dirs = tuple(cfg.get("noise_dirs", [])) or tuple(
        c if c.endswith("/") else c + "/" for c in containers)
    protected = set(cfg.get("protected_branches", DEFAULT_PROTECTED))
    tags = read_tags(root)

    if not no_fetch:
        git("fetch", "origin", "--prune", cwd=root)

    merged, have_gh = gh_pr_heads("merged", 500)
    open_heads = gh_pr_heads("open", 300)[0] if have_gh else set()
    trees = list_worktrees(root)
    registered = {str(Path(t["path"]).resolve()).replace("\\", "/")
                  for t in trees if t.get("path")}

    surveyed = [apply_tag(
        classify(t, root, merged, open_heads, have_gh, foreign_markers,
                 noise_suffixes, noise_dirs, protected), tags, root
    ) for t in trees]
    orphans = orphan_dirs(root, containers, registered)

    local = [b for b in git("for-each-ref", "--format=%(refname:short)",
                            "refs/heads", cwd=root).splitlines() if b]
    attached = {s["branch"]: s for s in surveyed if s["branch"]}
    branch_rows = []
    for branch in local:
        row = classify_branch(
            branch,
            merged=merged,
            open_heads=open_heads,
            have_gh=have_gh,
            unpushed=unpushed_count(root, branch),
            protected=protected,
            worktree=attached.get(branch),
        )
        branch_rows.append(apply_tag(row, tags, root))

    return {
        "worktrees": surveyed,
        "orphan_dirs": orphans,
        "branches": branch_rows,
        "gh_available": have_gh,
        "configured": bool(cfg),
    }
