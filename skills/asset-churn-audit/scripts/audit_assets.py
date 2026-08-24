#!/usr/bin/env python3
"""Classify every binary asset in a branch diff as feature-needed or churn.

An asset the branch's own feature needs belongs in it; art that merely happened
to be dirty in the same session does not. That question is mostly mechanical,
and this answers the mechanical part -- whether the content actually changed,
and whether anything in the diff references the asset.

Repo-specific knowledge (which extensions are assets, which files can reference
one, which format analyzers apply) comes from `.synapse/weedeat.md`, with the
baseline branch from `.synapse/identity.md`. Without them the audit falls back
to generic defaults: common art and audio extensions, reference-scanning across
every tracked file, no format analyzers.

Read-only. It prints verdicts and the revert commands; it never writes to the
repo.

Usage:
    python scripts/audit_assets.py
    python scripts/audit_assets.py --base origin/main
    python scripts/audit_assets.py --include-worktree
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

DEFAULT_ART = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".psd",
               ".aseprite", ".pxo", ".xcf"]
DEFAULT_AUDIO = [".ogg", ".wav", ".mp3", ".flac", ".aup3"]

# Pixelorama stores these in data.json and rewrites them on any save, including
# a save with no edit. A .pxo whose only change is here has no art change in it.
PXO_MACHINE_KEYS = {
    "export_directory_path", "export_file_name", "current_layer", "current_frame",
    "export_file_format", "save_path", "window_size", "current_tag",
}


def run(*args: str, binary: bool = False):
    result = subprocess.run(["git", *args], capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def repo_root() -> str:
    return (run("rev-parse", "--show-toplevel") or "").strip()


def parse_sections(path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse one .synapse/*.md into {section: {key: [values]}}.

    Sections are `## Heading`, entries are `key: value`. Repeated keys
    accumulate, so a section can carry several `flag:` lines. Code fences are
    skipped, so the fenced and bare styles both parse the same.
    """
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


def read_manifest(root: str) -> dict[str, dict[str, list[str]]]:
    """Read only what this tool needs: shared identity plus its own file.

    `.synapse/bandaids.md` is deliberately not read — no reason to load another
    tool's configuration. There is no fallback to a root SYNAPSE.md either: a
    stale file nobody remembers is worse than a clean set of defaults.
    """
    base = Path(root) / ".synapse"
    merged: dict[str, dict[str, list[str]]] = {}
    for name in ("identity.md", "weedeat.md"):
        for section, entries in parse_sections(base / name).items():
            merged.setdefault(section, {}).update(entries)
    return merged


def one(section: dict, key: str) -> str | None:
    values = section.get(key)
    return values[-1] if values else None


def csv(section: dict, key: str, default: list[str] | None = None) -> list[str]:
    value = one(section, key)
    if value is None:
        return list(default) if default is not None else []
    return [item.strip() for item in value.split(",") if item.strip()]


def assets_config(manifest: dict) -> dict:
    """The `## Assets` section of .synapse/weedeat.md, shaped for Audit."""
    section = manifest.get("assets", {})
    if not section:
        return {}
    flags = []
    for entry in section.get("flag", []):
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) >= 2 and parts[0]:
            flags.append({"ext": parts[0], "verdict": parts[1],
                          "reason": parts[2] if len(parts) > 2 else
                                    "flagged by .synapse/weedeat.md"})
    return {
        "base": one(section, "base"),
        "art": csv(section, "art", DEFAULT_ART),
        "audio": csv(section, "audio", DEFAULT_AUDIO),
        "sidecar": csv(section, "sidecar"),
        "reference_globs": csv(section, "references"),
        "resource_prefix": one(section, "resource-prefix") or "",
        "analyzers": csv(section, "analyzers"),
        "flag": flags,
    }


def identity_base(manifest: dict) -> str | None:
    """The `base:` line from `.synapse/identity.md`, not configured twice."""
    value = one(manifest.get("identity", {}), "base")
    return f"origin/{value}" if value else None


def default_base(root: str) -> str | None:
    out = run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if out and out.strip():
        return out.strip()
    for candidate in ("origin/main", "origin/master"):
        if run("rev-parse", "--verify", "--quiet", candidate) is not None:
            return candidate
    return None


def changed_files(base: str, include_worktree: bool) -> list[tuple[str, str]]:
    """(status, path) for the branch diff, optionally plus uncommitted changes."""
    entries: dict[str, str] = {}
    out = run("diff", "--name-status", f"{base}...HEAD") or ""
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            entries[parts[-1]] = parts[0][0]
    if include_worktree:
        out = run("status", "--porcelain") or ""
        for line in out.splitlines():
            if len(line) < 4:
                continue
            name = line[3:].strip().strip('"')
            if " -> " in name:
                name = name.split(" -> ", 1)[1]
            entries.setdefault(name, "?" if line.startswith("??") else "M")
    return sorted((status, path) for path, status in entries.items())


def blob_at(ref: str, path: str) -> bytes | None:
    return run("show", f"{ref}:{path}", binary=True)


def current_bytes(path: str) -> bytes | None:
    p = Path(path)
    return p.read_bytes() if p.exists() else blob_at("HEAD", path)


def is_tracked(path: str) -> bool:
    return run("ls-files", "--error-unmatch", path) is not None


def paired_source(sidecar: str) -> str:
    """`sprite.png.import` -> `sprite.png`; `script.gd.uid` -> `script.gd`."""
    return sidecar[: -len(Path(sidecar).suffix)]


class Audit:
    def __init__(self, cfg: dict, base: str):
        self.base = base
        self.art = {e.lower() for e in cfg.get("art", DEFAULT_ART)}
        self.audio = {e.lower() for e in cfg.get("audio", DEFAULT_AUDIO)}
        self.sidecar = {e.lower() for e in cfg.get("sidecar", [])}
        self.ref_globs = list(cfg.get("reference_globs", []))
        self.prefix = cfg.get("resource_prefix", "")
        self.analyzers = set(cfg.get("analyzers", []))
        self.flags = {}
        for rule in cfg.get("flag", []):
            ext = str(rule.get("ext", "")).lower()
            if ext:
                self.flags[ext] = (rule.get("verdict", "REVIEW"),
                                   rule.get("reason", "flagged by .synapse/weedeat.toml"))
        self.assets = self.art | self.audio | self.sidecar

    # -- format analyzers ---------------------------------------------------

    def godot_import_verdict(self, path: str) -> tuple[str, str]:
        """A .import diff that only moves .godot/imported/ hashes is pure churn."""
        diff = run("diff", f"{self.base}...HEAD", "--", path) or run("diff", "--", path) or ""
        changed = [l for l in diff.splitlines()
                   if (l.startswith("+") or l.startswith("-"))
                   and not l.startswith(("+++", "---"))]
        if not changed:
            return "CHURN", "sidecar with no content change"
        meaningful = [l for l in changed if ".godot/imported/" not in l]
        if not meaningful:
            return "CHURN", "only regenerated .godot/imported/ cache hashes"
        if any("uid=" in l for l in meaningful):
            return "KEEP", "uid assignment changed - required by scenes referencing it"
        return "REVIEW", "import settings changed: " + "; ".join(
            m.strip()[:60] for m in meaningful[:2])

    def pxo_verdict(self, path: str) -> tuple[str, str]:
        """Compare pixel layers inside the .pxo zip, ignoring the metadata blob.

        A .pxo is a zip: image_data/* entries hold the actual pixels, data.json
        holds editor state. Hashing the entries separates a real edit from a
        re-save.
        """
        old, new = blob_at(self.base, path), current_bytes(path)
        if old is None:
            return "KEEP", "new file - no baseline to compare"
        if new is None:
            return "REVIEW", "could not read current version"
        try:
            z_old = zipfile.ZipFile(io.BytesIO(old))
            z_new = zipfile.ZipFile(io.BytesIO(new))
        except zipfile.BadZipFile:
            return "REVIEW", "not readable as a Pixelorama archive"

        def layers(z):
            return {n: hashlib.sha256(z.read(n)).hexdigest()
                    for n in z.namelist() if n.startswith("image_data/")}

        l_old, l_new = layers(z_old), layers(z_new)
        if l_old != l_new:
            touched = len(set(l_old.items()) ^ set(l_new.items()))
            return "KEEP", f"real art edit - {touched} pixel layer(s) differ"

        try:
            d_old = json.loads(z_old.read("data.json").decode("utf-8"))
            d_new = json.loads(z_new.read("data.json").decode("utf-8"))
        except (KeyError, ValueError):
            return "CHURN", "all pixel layers identical"

        diff_keys = {k for k in set(d_old) | set(d_new) if d_old.get(k) != d_new.get(k)}
        if diff_keys and diff_keys <= PXO_MACHINE_KEYS:
            return "CHURN", ("identical pixels; only editor state changed "
                             f"({', '.join(sorted(diff_keys))})")
        if not diff_keys:
            return "CHURN", "byte-level re-encode, contents identical"
        return "REVIEW", ("identical pixels but data.json changed: "
                          f"{', '.join(sorted(diff_keys)[:3])}")

    # -- generic evidence ---------------------------------------------------

    def sidecar_verdict(self, path: str, status: str,
                        changed: dict[str, str]) -> tuple[str, str]:
        """Judge a generated companion by what it belongs to.

        A sidecar is not content, but the engine often can't load an asset
        without it: a new .png whose .import is missing imports as a broken
        resource, and scenes bind to the uid recorded there. So the same file
        is required when its asset is new and pure noise when its asset
        already exists.
        """
        src = paired_source(path)
        if src in changed and changed[src] in ("A", "?"):
            return "KEEP", f"required companion for new asset `{src}`"
        if not is_tracked(src):
            return "KEEP", f"companion for untracked asset `{src}` - commit both or neither"
        if status in ("A", "?"):
            return "REVIEW", (f"new sidecar for already-tracked `{src}` - harmless to "
                              "commit, but unrelated to this feature")
        if "godot-import" in self.analyzers:
            if Path(path).suffix.lower() == ".uid":
                return "CHURN", "regenerated by Godot; not authored content"
            return self.godot_import_verdict(path)
        return "REVIEW", (f"generated companion for existing `{src}` - probably "
                          "regenerated, but no analyzer is configured to prove it")

    def asset_uid(self, path: str) -> str | None:
        data = blob_at("HEAD", path + ".import")
        if not data:
            sidecar = Path(path + ".import")
            data = sidecar.read_bytes() if sidecar.exists() else None
        if not data:
            return None
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("uid="):
                return line.split('"')[1] if '"' in line else None
        return None

    def referencing_files(self, path: str) -> set[str]:
        """Files that point at this asset, by path or by engine uid."""
        needles = [path]
        if self.prefix:
            needles.append(f"{self.prefix}{path}")
        if "godot-import" in self.analyzers:
            uid = self.asset_uid(path)
            if uid:
                needles.append(uid)
        refs: set[str] = set()
        for needle in needles:
            args = ["grep", "-l", "-F", "-e", needle, "HEAD"]
            if self.ref_globs:
                args += ["--", *self.ref_globs]
            out = run(*args)
            if out:
                for line in out.splitlines():
                    refs.add(line.split(":", 1)[1] if ":" in line else line)
        refs.discard(path)
        return refs

    def verdict(self, status: str, path: str, changed: dict[str, str],
                code_changed: set[str]) -> tuple[str, str]:
        ext = Path(path).suffix.lower()
        if ext in self.flags:
            return self.flags[ext]
        if ext in self.sidecar:
            return self.sidecar_verdict(path, status, changed)
        if ext == ".pxo" and "pixelorama-pxo" in self.analyzers:
            return self.pxo_verdict(path)

        refs = self.referencing_files(path)
        used_here = refs & code_changed
        if status in ("A", "?"):
            if used_here:
                return "KEEP", f"new asset, wired up by {', '.join(sorted(used_here))}"
            return "REVIEW", ("new asset not referenced by anything in this diff - art "
                              "landing ahead of its wiring, or belongs in an "
                              "asset-only branch")
        if used_here:
            return "KEEP", f"referenced by changed file(s): {', '.join(sorted(used_here))}"
        if refs:
            return "REVIEW", f"modified, but only referenced by unchanged files ({len(refs)})"
        return "REVIEW", "modified and referenced by nothing in the repo"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="baseline ref; overrides .synapse/weedeat.md "
                                       "and .synapse/identity.md")
    parser.add_argument("--include-worktree", action="store_true",
                        help="also classify uncommitted changes")
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = repo_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1

    manifest = read_manifest(root)
    cfg = assets_config(manifest)
    base = (args.base or cfg.get("base") or identity_base(manifest)
            or default_base(root))
    if not base:
        print("Could not determine a baseline ref. Pass --base, or set `base:` "
              "under `## Identity` in .synapse/identity.md.", file=sys.stderr)
        return 1

    if not args.no_fetch and base.startswith("origin/"):
        print("Fetching origin...", file=sys.stderr)
        run("fetch", "origin", "--quiet")

    if run("rev-parse", "--verify", "--quiet", base) is None:
        print(f"Baseline ref '{base}' not found.", file=sys.stderr)
        return 1

    audit = Audit(cfg, base)
    files = changed_files(base, args.include_worktree)
    code_changed = {p for _, p in files if Path(p).suffix.lower() not in audit.assets}
    changed_status = {p: s for s, p in files}

    results = [(*audit.verdict(status, path, changed_status, code_changed), status, path)
               for status, path in files
               if Path(path).suffix.lower() in audit.assets]

    if not results:
        print(f"\n# Asset churn audit\n\nNo asset files in the diff against `{base}`.")
        if not cfg:
            print("\n> No `## Assets` section in .synapse/weedeat.md, so only these "
                  f"extensions were considered: {', '.join(sorted(audit.assets))}.")
        return 0

    order = {"CHURN": 0, "REVIEW": 1, "KEEP": 2}
    results.sort(key=lambda r: (order.get(r[0], 3), r[3]))

    print(f"\n# Asset churn audit\n\nBaseline: `{base}`"
          f"{' + uncommitted changes' if args.include_worktree else ''}")
    if not cfg:
        print("\n> No `## Assets` section in .synapse/weedeat.md — running on generic "
              "defaults, with no format analyzers. Verdicts rest on reference "
              "scanning alone.")
    for verdict in ("CHURN", "REVIEW", "KEEP"):
        rows = [r for r in results if r[0] == verdict]
        if not rows:
            continue
        header = {"CHURN": "CHURN - drop from this branch",
                  "REVIEW": "REVIEW - needs your judgment",
                  "KEEP": "KEEP - this feature needs it"}[verdict]
        print(f"\n## {header} ({len(rows)})")
        for _, why, status, path in rows:
            print(f"- `{path}` [{status}]\n    {why}")

    tracked_churn = [r[3] for r in results if r[0] == "CHURN" and is_tracked(r[3])]
    untracked_churn = [r[3] for r in results if r[0] == "CHURN" and not is_tracked(r[3])]
    if tracked_churn:
        print("\n## Revert the churn\n")
        print("```bash")
        for path in tracked_churn:
            print(f'git checkout {base} -- "{path}"')
        print("```")
    if untracked_churn:
        print(f"\n{len(untracked_churn)} untracked file(s) classified CHURN have no "
              "baseline to revert to - just don't stage them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
