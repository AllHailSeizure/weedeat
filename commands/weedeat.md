---
description: Survey what's overgrown in this repo — asset churn in the branch, worktree and branch sprawl — and report; never delete
---

# /weedeat

Clear the weeds: things that accumulated on their own and nobody planted. Two
agents cover the two kinds, and both are read-only surveys that end in a
report plus commands for the user to run.

| Argument | Agent |
|---|---|
| `assets`, `churn`, `branch`, `diff`, `pr` | `asset-churn-audit` |
| `worktrees`, `branches`, `sprawl`, `repo` | `worktree-cleanup` |
| none | both, asset churn first |

Pick from the user's words when the argument doesn't match the table — "is this
PR too big" is the asset audit, "what can I delete" is the cleanup. When it's
genuinely ambiguous, dispatch both; they don't interfere.

## Dispatching

Before spawning an agent, resolve the absolute path to its script so the agent
doesn't have to guess: `skills/asset-churn-audit/scripts/audit_assets.py` for
the audit, `scripts/survey_worktrees.py` for the cleanup, both relative to
this weedeat install (`$CLAUDE_PLUGIN_ROOT` when installed as a plugin). Pass
that resolved path, plus the target repository path, in the agent's prompt.

Both agents read repo-specific configuration from `.synapse/weedeat.md` —
`## Assets` and `## Worktrees` — plus `.synapse/identity.md` for the baseline
branch. They read nothing else, and there is no fallback to a root
`SYNAPSE.md`. If the relevant section is missing, they say so once in their
own report rather than silently running blunt; offer to write one from
`docs/TEMPLATES/weedeat.md` if the user wants to fix that going forward.

## The boundary

**Report, then stop.** Neither agent deletes, reverts, or stages anything, and
neither do you under this command. Present the findings and the exact commands,
and wait.

This boundary describes the agent-dispatched report path specifically. When
the `weedeat` CLI is installed and the session is interactive, a human may run
`weedeat run` directly: it opens a line-oriented prompt showing numeric risk
levels and removes nothing until the human enters and confirms `trim N`.
Level `0` is never deletable. That path is human-invoked; the agent never
starts it on the user's behalf.

If the user then authorizes a tier — "drop the churn", "remove the safe ones" —
that authorizes exactly that tier for that run. It is not authorization for
REVIEW or HOLD, and it does not carry to the next invocation.

When both agents run, report them as two sections under one summary. Lead with
the counts and the single most important risk in each, not a wall of paths.
