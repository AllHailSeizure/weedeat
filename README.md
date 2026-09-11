# weedeat

Clear the weeds: things that accumulate on their own in a repo and nobody
planted — art that rode along in a branch it doesn't belong to, and the
worktrees and branches that pile up once agents start working in parallel.

Two read-only survey skills, dispatched by the `/weedeat` command, each end in
a report plus exact commands — never an automatic delete:

- **asset-churn-audit** — separates art a branch's feature actually needs from
  churn (regenerated caches, sidecar rewrites) that happened to be dirty in the
  same worktree. See [`skills/asset-churn-audit/SKILL.md`](skills/asset-churn-audit/SKILL.md).
- **worktree-cleanup** — surveys worktrees, local branches, and orphaned
  checkout directories, classifies each by a numeric removal-safety level, and
  reports the tiers. See [`skills/worktree-cleanup/SKILL.md`](skills/worktree-cleanup/SKILL.md).

Extracted from [Synapse](https://github.com/AllHailSeizure/synapse) to stand
on its own — install it independently of the rest of that workflow system.

## Install as a Claude Code plugin

Add this repo as a marketplace and install the `weedeat` plugin from it; the
`/weedeat` command and both skills become available.

## Repo configuration

Both skills read repo-specific configuration from `.synapse/weedeat.md` in the
*target* repo — `## Assets` and `## Worktrees` sections — plus
`.synapse/identity.md` for the baseline branch. Schema and example:
[`docs/TEMPLATES/weedeat.md`](docs/TEMPLATES/weedeat.md). Without that file
each survey still runs, but on generic defaults, and says so in its own
output.

## Weedeat command interface

Install the standalone package with `pip install -e .`, then run `weedeat run`
from a Git repository. The prompt lists branches by numeric risk:

```text
0  protected — never trimmed
1  safe — merged and clean
2  stale — no merged or open PR
3  review — merged but carrying local changes
4  hold — active, unknown, or carrying unmerged work
```

Nothing is removed on launch. `trim 1` removes confirmed level-1 entries;
`trim 2` includes levels 1 and 2, and so on. Every trim previews its work and
requires confirmation. Use `branch <name> tag <0-4>` or
`worktree <path> tag <0-4>` for a persistent override. A level-0 entry cannot
be removed by any trim command. Tags are written to
`.synapse/weedeat-tags.json`; attached branches and worktrees share one tag.

`shear <branch>` fetches and compares that branch to `origin/<branch>`. Local
working-tree changes whose content already matches the remote are reverted
(tracked files restore to `HEAD`; untracked duplicates of remote files are
removed). Local-only edits are left alone. Like trim, shear previews and asks
before writing.

## Development

```bash
pip install -e .
pip install pytest
pytest
```
