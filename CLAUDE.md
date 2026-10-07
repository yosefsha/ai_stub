# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Instructions

Shared coding standards — design principles (SOLID, extensibility, industry conventions), repository layout, GitHub setup, and the React/TypeScript frontend.

@docs/coding-instructions.md

## Backend — Python / FastAPI

Backend standards for the Python stack — project structure, code style, configuration, testing, and the container runtime.

@docs/backend-python-instructions.md

## Backend — TypeScript / NestJS

Backend standards for the NestJS stack — project structure, code style, configuration, testing, and the container runtime.

@docs/backend-nestjs-instructions.md

## Infrastructure & Configuration (AWS + Python CDK)

Production-grade AWS infrastructure defined as code with AWS CDK (Python) — networking, ECS/Fargate backend, S3 + CloudFront frontend, CI/CD pipeline, and monitoring.

@docs/infra-instructions.md

<!-- worktree-workflow-kit:start -->
## Branch, Worktree and Subagent Workflow

**Never commit directly to `main`.** Every task gets its own feature branch AND its own git
worktree, so several tasks can be in flight at once without fighting over one working tree.
Exception: changes that touch only documentation (`docs/**`, `*.md`, no code) may go straight to
`main` — but always `git pull --rebase origin main` immediately before pushing.

```bash
git worktree add .claude/worktrees/<short-task-name> -b <branch-name> main
```

- Branch off `main` explicitly unless the task genuinely builds on another branch. Never build on
  a branch that has already been merged.
- Name the worktree directory after the task (`fix-133-draft-ar`), never after an agent or session ID.
- Each worktree needs its own `.env` / venv symlinks if the task runs code. Shared services
  (docker-compose, the dev DB) are shared across worktrees — **never run migrations or seed
  commands from two worktrees at once**.
- Leave the primary checkout on `main` and clean, so it stays usable for reads, reviews and docs.
- When the branch is merged or abandoned: `git worktree remove <path>` then `git worktree prune`.
  Stale worktrees for merged branches cause accidental building on merged code.

**Before implementing anything**, run `git branch --show-current` **and** `git worktree list`. If a
worktree already exists for the target branch, edit files *there* (absolute paths), not in the
repo root. Never commit unrelated work onto whatever branch happens to be active.

**Subagents get a pre-created, task-named worktree — never `isolation: "worktree"`.** The
coordinating session runs `git worktree add` itself (sequentially when fanning out — parallel
creation races on the git index) and passes each subagent the absolute worktree path and branch.
The subagent works only there: it never `cd`s to the primary checkout or another worktree.
(The Agent tool's auto-isolation names dirs `agent-<id>`, breaking the naming rule, and can't push
onto a branch already checked out elsewhere.)
- Work on an existing branch (e.g. resolving PR review comments): dispatch the subagent into that
  branch's existing worktree.
- Head-to-head model comparisons: one named worktree per candidate from the same pinned commit SHA
  (e.g. `fix-135-sonnet`, `fix-135-opus`); PR bodies say "Relates to #N", not "Fixes #N".

**Never merge pull requests into `main` without explicit instruction naming the PR number.**
Approval is per-PR and per-turn. Open the PR and stop. CI passing is not sufficient on its own —
for non-trivial changes, offer to deploy and verify live first. After pushing to a PR, read its
comments (`gh pr view <n> --json comments` and `gh api repos/:owner/:repo/pulls/<n>/comments`)
and reply to every inline thread.

Skills: `/implement-issue <n>` (one issue, run in a subagent) and `/implement-milestone <name>`
(fan out one subagent per independent issue).
<!-- worktree-workflow-kit:end -->
