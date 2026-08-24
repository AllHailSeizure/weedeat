---
name: worktree-cleanup
description: >-
  Survey and clean up accumulated git worktrees, stale local and remote branches,
  and orphaned worktree directories. Use whenever the user mentions worktree
  sprawl, stale or dead branches, "too many worktrees", repo housekeeping,
  running out of disk, or asks what's safe to delete — and also when a routine
  `git worktree list` or `git branch` turns up far more entries than the work in
  flight would explain. Produces a tiered report plus exact commands; never
  deletes anything on its own.
---

# Worktree cleanup

Repos that run agents accumulate worktrees fast. Several tools create them in
different places (Claude, Cursor, Codex, hand-made sibling directories), work
happens in parallel across many of them, and nothing prunes them afterward. A
survey on a busy repo routinely finds dozens of worktrees, a hundred local
branches, and a pile of orphaned directories.

The job is to sort that pile into "provably safe to remove" and "contains work
that exists nowhere else," then hand the user a list. **Never run the removals
yourself.**

## Why report-only is not excessive caution

Deleting a worktree that holds uncommitted changes or unpushed commits destroys
them with no git-recoverable trace — no reflog entry, no dangling object,
nothing to recover from. A branch you can always re-create from a PR; an
uncommitted tileset rework you cannot.

So the deal is: you do the classification work, which is tedious and error-prone
by hand, and the user makes every destructive call. Present findings and
commands, then stop and wait. If they say "go ahead and delete the safe ones,"
that's your authorization for that level only — not for REVIEW or HOLD.

## Run the survey

```bash
python <weedeat>/scripts/survey_worktrees.py --json survey.json
```

`<weedeat>` is this weedeat install — `$CLAUDE_PLUGIN_ROOT` when installed as a
plugin. Write the JSON somewhere scratch, not into the repo.

It fetches and prunes first (pass `--no-fetch` to skip), then prints a markdown
report grouped by risk level. It takes a couple of minutes on a large repo because it runs
`git status` inside every worktree. That's expected — let it finish rather than
reaching for a faster approximation.

## Repo configuration

The `## Worktrees` section of the target repo's `.synapse/weedeat.md` supplies
where worktrees get created — by any tool, not just ours — and which uncommitted
paths carry no work.
That one file is all this survey reads. Schema and example:
`docs/TEMPLATES/weedeat.md` in the weedeat repo.

The noise filter is the key entry, and see below for why. Without it the survey
still runs, but every regenerated sidecar counts as real work, and a repo whose
engine rewrites files on editor open reports nearly everything as HOLD. A
missing section is not a stop — this is a survey; it degrades and says so.

## Two things a hand-rolled survey always gets wrong

**Merge status.** Squash-merging (`gh pr merge --squash`, GitHub's squash
button) leaves the merged branch sharing no commits with the base, so
`git branch --merged` doesn't see it. On one real run that check found 19 merged
branches where the PR list found 66 — a 3× undercount that makes live branches
look abandoned and merged ones look active. Always resolve merge status from
`gh pr list --state merged`, which the script does. If `gh` is unavailable it
refuses to classify anything as SAFE rather than guessing.

**Dirty-looking worktrees that hold nothing.** Engines and editors regenerate
import caches, lockfiles, and uid sidecars whenever a project is opened, so most
worktrees show as dirty with files that carry no work at all. Counting those as
WIP marks everything unsafe and the report stops meaning anything. The script
filters whatever the config names; keep that distinction if you inspect anything
by hand.

Also: don't try to measure worktree sizes with `du`. On Windows especially it
takes longer than the entire rest of the survey and adds nothing to the
decision.

## Reading the levels

Every worktree and branch gets a numeric risk level. The number is what the
interactive `trim` acts on; the name is for reading the report.

| Level | Meaning | What to propose |
|---|---|---|
| `1` SAFE | Merged PR, clean tree, nothing unpushed | Removal, listed together as one batch |
| `2` STALE | No merged PR, no open PR, but nothing uncommitted | Removal, flagged as "abandoned, nothing lost" |
| `3` REVIEW | Merged PR but the tree still has changes | Show the file list; the work is probably leftovers, but confirm each |
| `4` HOLD | Unmerged with real uncommitted or unpushed work | Do not propose removal. Suggest committing or pushing it first |
| `0` PROTECTED | The primary checkout, a configured protected branch, or a locked worktree | Never touch |

Orphaned directories are reported separately: full checkouts on disk that git no
longer registers. They're usually safe, but check them for uncommitted files the
same way before proposing `rm -rf`, since git won't warn you about them at all.

## Worktrees other tools made

Cursor, Codex, and hand-made sibling checkouts are surveyed and classified on
exactly the same evidence as our own. They are not a level of their own and
they get no exemption: an abandoned `.codex/` worktree is the same clutter as
an abandoned `.claude/` one, and exempting them meant the tools generating the
most sprawl were the ones this survey never touched.

What the `foreign` markers buy is a label, not immunity — the report names the
owning tool on each row, so a removal that would land in someone's live session
is visible before you propose it. Name the owner when you propose it. If the
user says a tool is mid-session, park that entry with `branch <name> tag 0` in
`weedeat run` rather than reasoning about it again next survey.

The protection that matters was never tool-specific: uncommitted files,
unpushed commits, and an open PR each push an entry to HOLD regardless of who
created it.

## Presenting findings

Lead with the counts and the single most important risk, not with a wall of
paths. The user wants to know how much can go and what's in danger, in that
order.

Group the removals into copy-pasteable batches rather than one command per
worktree — there may be fifteen of them:

```bash
git worktree remove <path> && git branch -d <branch>
```

Use `git worktree remove` rather than deleting directories, so git's
administrative records get cleaned up too; `rm -rf` alone leaves exactly the
orphaned-directory problem this skill exists to find. For branches, prefer `-d`
over `-D` — it's a last-line safety check, and if it refuses, that branch
deserves a second look.

Call out anything in HOLD by name with what's actually in it. "`assets-bright-cave-tileset-rework`
has 10 uncommitted scene files and 1 unpushed commit" is the sentence that
prevents an accident; "several worktrees have pending changes" is not.

## Remote branches

Remote branches are cheap to keep and cost only clutter, so treat them as a
lower priority than worktrees. Once a PR is merged, its remote branch is
redundant — GitHub retains the PR's commits regardless. Offer the deletion list,
but don't push for it.
