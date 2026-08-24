"""Persistent manual risk-level overrides for weedeat."""

from __future__ import annotations

import json
import os
from pathlib import Path


TAG_VERSION = 1
TAG_FILE = Path(".synapse") / "weedeat-tags.json"


def empty_tags() -> dict:
    return {"version": TAG_VERSION, "branches": {}, "worktrees": {}}


def read_tags(root: str) -> dict:
    path = Path(root) / TAG_FILE
    if not path.is_file():
        return empty_tags()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_tags()

    tags = empty_tags()
    for kind in ("branches", "worktrees"):
        values = raw.get(kind, {})
        if not isinstance(values, dict):
            continue
        tags[kind] = {
            str(target): level for target, level in values.items()
            if isinstance(level, int) and 0 <= level <= 4
        }
    return tags


def worktree_key(root: str, path: str) -> str:
    """Return a repository-relative, slash-normalized tag key."""
    absolute = os.path.abspath(path)
    try:
        key = os.path.relpath(absolute, os.path.abspath(root))
    except ValueError:
        # Windows cannot express a relative path across drive letters.
        key = absolute
    return key.replace("\\", "/")


def set_tag(root: str, kind: str, target: str, level: int) -> None:
    if level not in range(5):
        raise ValueError("tag level must be between 0 and 4")
    key = _kind_key(kind)
    tags = read_tags(root)
    tags[key][target] = level
    _write_tags(root, tags)


def remove_tag(root: str, kind: str, target: str) -> bool:
    key = _kind_key(kind)
    tags = read_tags(root)
    removed = tags[key].pop(target, None) is not None
    if removed:
        _write_tags(root, tags)
    return removed


def _kind_key(kind: str) -> str:
    if kind == "branch":
        return "branches"
    if kind == "worktree":
        return "worktrees"
    raise ValueError(f"unknown tag kind: {kind}")


def _write_tags(root: str, tags: dict) -> None:
    path = Path(root) / TAG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(tags, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
