---
name: implement-milestone
description: Implement all open issues in a GitHub milestone, fanning out subagents in parallel for independent tasks. Each task gets its own branch, its own git worktree, and its own PR via the implement-issue skill. Use when asked to "implement milestone X" or work a whole workstream at once.
argument-hint: "milestone number or title"
user-invocable: true
---

# Implement a milestone in parallel

**PARAM = $ARGUMENTS**

Implement $ARGUMENTS using parallel subagents for independent tasks. Each task is one issue,
delegated to the `implement-issue` skill. This skill only resolves the milestone, builds the
dependency graph, creates worktrees, and fans out.

`$REPO` means the primary checkout (first entry of `git worktree list`).

---

## Step 1 — Resolve the milestone and its issues

```bash
git -C "$REPO" status --short --branch      # must be on main and clean
gh api repos/:owner/:repo/milestones --jq '.[] | "\(.number)\t\(.title)\t\(.open_issues) open"'
gh issue list --milestone "<resolved title>" --state open --json number,title,labels,body --limit 100
```

Read each issue body in full. If PARAM doesn't match a real milestone, stop and show the live list.

## Step 2 — Build the dependency graph

For each issue decide what it changes (files/layers) and what it depends on. Split into:

- **Independent** — no overlapping files, no ordering constraint. Run in parallel.
- **Dependent chain** — waits on another issue's PR.
- **Blocked / needs a decision** — surface to the user, don't start.

Two issues touching the same file are **not** independent. Print the graph before spawning anything.

## Step 3 — One worktree per independent task (sequentially, before spawning)

Creating worktrees from several agents at once races on the git index, so do it here, one by one:

```bash
git -C "$REPO" worktree add .claude/worktrees/<short-task-name> -b <branch-name> main
```

- Branch off `main` explicitly; name the directory after the task, never an agent/session id.
- Symlink `.env` / venv if the task runs code. Leave the primary checkout on `main` and clean.

## Step 4 — Fan out subagents

Launch all independent tasks in **one message with multiple Agent tool calls**
(`subagent_type: general-purpose`, **no** `isolation: "worktree"`). Each prompt must state:

1. Its absolute worktree path and branch, and that all work happens there — never `cd` to the
   primary checkout or another worktree.
2. To invoke the `implement-issue` skill with the issue number plus the pre-created worktree
   path/branch (so it skips worktree creation).
3. To report back: PR URL, what was verified, anything left undone.

Start dependent-chain tasks only after their prerequisite lands, same pattern.

## Step 5 — Report and stop

| Issue | Branch | Worktree | PR | Verified | Status |
|---|---|---|---|---|---|

Then list tasks not started (and what blocks each) and anything needing a user decision.
**Do not merge any PR.** Ask whether the user wants branches deployed/verified live first.

## Cleanup (after the user merges)

```bash
git worktree remove .claude/worktrees/<name>
git worktree prune
```
