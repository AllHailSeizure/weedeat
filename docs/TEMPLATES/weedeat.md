# .synapse/weedeat.md — template

Copy this to `.synapse/weedeat.md` in any repo where you run `/weedeat`, keep
the keys that apply, and delete the rest. Every key is optional; an absent file
means both surveys run on generic defaults, which is correct but blunt.

Only the `/weedeat` skills read this file, and they read nothing else except
`identity.md` for the baseline branch. Unlike a bandaid, a missing section is
not a stop — a survey degrades to defaults and prints a line saying so.

There is no fallback to a root `SYNAPSE.md`. Defaults you can read in this
template beat standards from a file nobody remembers.

---

## Assets

```
base: <baseline ref; defaults to origin/<base> from identity.md>
art: <extensions, comma-separated>
audio: <extensions, comma-separated>
sidecar: <generated companion extensions>
references: <globs for files that can reference an asset>
resource-prefix: <how references spell an in-repo asset path>
analyzers: <named format analyzers, comma-separated>
flag: <ext> | <CHURN|REVIEW|KEEP> | <reason>
```

Read by the `asset-churn-audit` skill. Absent means the audit runs on generic
defaults and says so in its own output.

`art`, `audio`, and `sidecar` are the only extensions classified — a repo whose
assets are `.glb` and `.fbx` has to say so. `references` scopes the grep that
proves an asset is used; omit it to search every tracked file, which is slower
and noisier but works anywhere.

`analyzers` opt into format-specific evidence, each encoding one tool's file
format. Without them every verdict rests on reference scanning alone.

| Analyzer | What it settles |
|----------|-----------------|
| `godot-import` | A `.import` diff that only moves `.godot/imported/` cache hashes is machine-local churn; a `uid=` change is not |
| `pixelorama-pxo` | A `.pxo` is a zip — hashing `image_data/*` apart from `data.json` tells a real pixel edit from a bare re-save |

`flag` gives a whole extension a blanket verdict before any other evidence, for
files whose presence in a feature branch is the problem regardless of what
changed inside them. Repeat the line per extension.

Example:

```
base: origin/master
art: .png, .jpg, .jpeg, .aseprite, .pxo
audio: .ogg, .wav, .mp3, .aup3
sidecar: .import, .uid
references: *.tscn, *.tres, *.gd, *.godot
resource-prefix: res://
analyzers: godot-import, pixelorama-pxo
flag: .aup3 | REVIEW | Audacity project (LFS, ~100MB) — a recording session, not a game asset; belongs on an audio branch
```

## Worktrees

```
containers: <dirs any tool creates worktrees under, relative to root>
foreign: <path fragments marking another tool's worktree — labels it, does not exempt it>
noise-suffixes: <uncommitted suffixes that carry no work>
noise-dirs: <uncommitted path prefixes that carry no work>
protected: <branches never proposed for deletion>
```

Read by the `worktree-cleanup` skill.

`foreign` names the tools, not an exemption. Cursor and Codex worktrees are
classified on the same evidence as ours and are eligible for the same removals;
the marker only makes the report say who created each one, so a removal that
would interrupt a live session is visible before it is proposed. Park a
genuinely mid-session entry with `tag 0` instead. Listing the tools' containers
under `containers` is what lets orphan detection see the directories they leave
behind.

The noise lines are the ones that matter. Without them, a repo whose engine
rewrites sidecars on every editor open reports every worktree as holding real
work, and the survey stops meaning anything.

Example:

```
containers: .claude/worktrees, .worktrees, .cursor/worktrees, .codex/worktrees
foreign: .cursor, .codex, .vscode
noise-suffixes: .import, .uid
noise-dirs: .godot/, .worktrees/, .claude/worktrees/, .cursor/worktrees/, .codex/worktrees/
protected: master, main
```

## Manual cleanup tags

The interactive `weedeat run` command writes manual numeric overrides to the
adjacent `.synapse/weedeat-tags.json` file. Do not edit that JSON while the
prompt is running; use these commands instead:

```text
branch <name> tag <0-4>
branch <name> untag
worktree <path> tag <0-4>
worktree <path> untag
```

Level `0` is protected and is never eligible for `trim`. Levels `1` through
`4` increase in risk. Tagging an attached branch or worktree updates their
shared branch tag. Primary, configured-protected, and locked entries are
system-protected and cannot be retagged into a deletable level. Another tool's
worktree is not system-protected — tag it `0` yourself for as long as that tool
is using it.
