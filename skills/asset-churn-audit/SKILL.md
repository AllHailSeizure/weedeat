---
name: asset-churn-audit
description: >-
  Audit a branch's binary assets — images, audio, editor project files, and the
  sidecars engines generate next to them — to separate art the feature actually
  needs from churn that rode along in the same session. Use before opening or
  merging a PR that touches assets, whenever `git status` shows dirty sprites or
  audio projects you don't remember editing, when a PR diff looks larger than the
  work you did, or when the user asks whether an asset belongs in a branch. Also
  use when deciding what to split into an asset-only branch.
---

# Asset churn audit

Scope art into a PR by purpose: an asset the PR's own feature needs belongs in
it, while art that merely happened to be dirty in the same worktree does not.
The self-check is "would this PR's feature be broken without this file?"

The trouble is that content tools rewrite files constantly without anyone
editing them. Opening a project regenerates import caches; opening a source
file from a different worktree rewrites its stored export path. A dozen sprites
can look edited when not one pixel moved, so `git status` can't tell you the
answer.

## Run the audit

```bash
python <skill-dir>/scripts/audit_assets.py
```

`<skill-dir>` is wherever this skill is installed — the directory holding this
`SKILL.md`. Run it from anywhere inside the target repo; it resolves the repo
root itself.

It baselines against a remote ref, not local master — local master is often
several merged PRs behind, which would make already-landed assets look like new
changes in your branch. Add `--include-worktree` to also classify uncommitted
files, which is what you want before staging anything.

The script decides only what's mechanically decidable. It sorts files into
CHURN (proven identical content), KEEP (proven needed), and REVIEW — and REVIEW
is where your judgment is genuinely required, not a hedge.

## Repo configuration

Everything repo-specific lives in the `## Assets` section of the target repo's
`.synapse/weedeat.md`: which extensions count as assets, which files can
reference one, how references spell an asset path, and which format analyzers
apply. The baseline branch comes from `## Identity` in `.synapse/identity.md`.
Schema and example: `docs/TEMPLATES/weedeat.md` in the weedeat repo.

Nothing else is read — not `.synapse/bandaids.md`, and not a root `SYNAPSE.md`,
which is a stale artifact of the old single-file layout.

**Check for that section first.** Without it the audit still runs, but on
generic defaults and with no analyzers, so every verdict rests on reference
scanning alone — usable, and much blunter than it looks in the output. The
script says so in its own header when the section is missing. If a repo audits
assets more than once, write the section instead of re-reading blunt output.

Unlike a bandaid, a missing section is not a stop. This is a survey; it degrades
and announces the degrading.

## What the evidence actually is

**Content-format analyzers** settle the question outright when one applies, and
they're opt-in per repo because each encodes one tool's file format:

- `pixelorama-pxo` — a `.pxo` is a zip. `image_data/*` entries hold the pixels,
  `data.json` holds editor state. Hashing the entries separately means that if
  every pixel layer matches and only `data.json` moved, there is no art change
  in the file no matter what its byte count says. The usual cause is an export
  path flipping because the file was opened from a different worktree.
- `godot-import` — `.import` sidecars usually differ only in
  `.godot/imported/*.ctex` cache hashes, which are machine-local and carry
  nothing.

**Sidecars** are judged by what they belong to. A generated companion carries no
authored content, but it's mandatory when its asset is new — a `.png` committed
without its `.import` loads as a broken resource, and scenes bind to the uid
recorded there. So the verdict follows the asset: required alongside new art,
noise alongside art that already exists.

**Everything else** is judged by reference: an asset counts as needed when some
*changed* file in the same diff points at it, by path or by engine uid. An asset
modified while nothing referencing it changed is the classic churn signature.

**Blanket flags** in the config override all of the above for a whole extension
— for files whose presence in a feature branch is the problem regardless of what
changed inside them, like a 100MB DAW session project that the shipped product
never loads.

## The one case the script can't settle

A new asset that nothing references yet is genuinely ambiguous — it's either art
landing just ahead of the code that will wire it up (fine, and normal in repos
where art and code move in parallel) or art that wandered in from another
session and belongs in its own asset-only branch. The script flags it REVIEW
rather than guessing.

Resolve it by asking what the branch is *for*. If the branch wires up an
animation and the new sprite sheet is that animation's, it belongs. If the
branch is a dialogue fix and a new character portrait appeared, it doesn't. When
it's still unclear after that, ask — this is the user's creative work, and a
wrong guess either splits a coherent PR or smuggles unrelated art into one.

## Reporting

Lead with the counts and the revert commands, since dropping churn is the action
almost every run ends in. The script emits them ready to paste:

```bash
git checkout <base> -- "<path>"
```

For untracked churn there's nothing to revert to — those just shouldn't be
staged, so say that instead of offering a command that will fail.

Never propose deleting or overwriting a source art file outright. Reverting a
tracked file to its baseline is safe because the content is recoverable; `rm` on
an editor project holding unexported work is not. If a file looks wrong rather
than merely unrelated, flag it and ask.
