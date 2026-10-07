---
name: implement-issue
description: Implement a single GitHub issue end-to-end — its own branch, its own git worktree, a verified implementation, a review gate, and a PR. Use when asked to "implement issue X" / "work on #123" / fix one tracked issue. Also the per-issue worker the implement-milestone skill delegates to.
argument-hint: "issue number or URL, e.g. 133 or #133 — optionally with a pre-created worktree path/branch when invoked from implement-milestone"
user-invocable: true
---

# Implement a single GitHub issue

**PARAM = $ARGUMENTS**

Implement the GitHub issue named by $ARGUMENTS end to end: its own branch, its own worktree,
a verified implementation, a review gate, and an open PR. Never merge.

If $ARGUMENTS also names a worktree path and branch that already exist (this happens when
`implement-milestone` delegates to this skill), skip Step 2 and work in that worktree.

Throughout, `$REPO` means the primary checkout: `git rev-parse --show-toplevel` run from the
primary checkout (the first entry of `git worktree list`).

---

## Step 0 — This runs in a subagent, never inline

- **A user invoked this skill directly**: the current session only launches one subagent via the
  Agent tool (`subagent_type: general-purpose` — not `fork`, and **without** `isolation: "worktree"`)
  with a self-contained prompt: the issue number, and that it should follow Steps 1-7 of this skill.
  Do not view the issue, create the worktree, edit files, or open the PR in the main session. Wait
  for the subagent, then relay its Step 7 report.
- **`implement-milestone` dispatched this**: you already are that subagent. Proceed to Step 1; do
  not spawn a nested subagent.

Why: implementation noise (diffs, test runs) stays out of the coordinating session's context.

## Step 1 — Resolve the issue

```bash
gh issue view <number> --json number,title,body,labels,milestone,state
```

Read the full body. If PARAM isn't a real, open issue, stop and report. Check nothing is already
in flight:

```bash
git worktree list
gh pr list --search "<issue number> in:body" --state open
```

## Step 2 — Branch and worktree

Skip if a worktree/branch for this issue was already handed to you.

```bash
git -C "$REPO" status --short --branch
git -C "$REPO" worktree add .claude/worktrees/<short-task-name> -b <branch-name> main
```

- Branch off `main` explicitly.
- Name the directory after the task (`fix-133-draft-ar`), never after an agent or session id.
- Symlink `.env` / venv into the worktree if the task runs code.
- Leave the primary checkout on `main` and clean.

## Step 3 — Implement

- Do all work inside the worktree — never `cd` to the primary checkout or another worktree.
- Follow the project's CLAUDE.md engineering principles.
- Commit after each verified step, not one bundled commit at the end.
- **Do not run migrations or seed commands** — shared services are shared across worktrees. Write
  the migration, but report back rather than applying it.
- Verify the change actually runs (tests, build, the app itself) — not just that the diff reads right.

## Step 4 — Review gate

Run the project's security/code review skill against the branch diff if one exists (e.g.
`/security-review` or `/code-review`). Fix CRITICAL/HIGH findings on the branch before opening the PR.

## Step 5 — Open the PR

```bash
git push -u origin <branch-name>
gh pr create --base main --title "..." --body "..."
```

- Reference the issue (`Closes #<n>` if fully resolved, otherwise `Refs #<n>`).
- **Never** `gh pr merge`.
- After pushing, read both `gh pr view <n> --json comments` and
  `gh api repos/:owner/:repo/pulls/<n>/comments`, and reply to (or fix and reply to) every inline thread.

## Step 6 — Bookkeeping

Update the issue's status label / milestone and any tracking docs according to the project's
CLAUDE.md conventions.

## Step 7 — Report and stop

Report: issue number and title, branch, worktree path, PR URL, what was verified and how, and
anything left undone or spun out. Do not merge — merging needs explicit per-PR instruction.

## Cleanup (after the user merges)

```bash
git worktree remove .claude/worktrees/<name>
git worktree prune
```
