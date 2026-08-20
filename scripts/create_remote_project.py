#!/usr/bin/env python3
"""Create a new GitHub repo, a new local project folder, and populate it
with this repo's contents.

Steps performed:
  1. Create a local project folder (must not already exist / must be empty).
  2. Copy this repo's contents into it (see copy_repo.py for exclusions).
  3. git init + initial commit in the new folder.
  4. `gh repo create` to create the remote repo, wire it up as `origin`,
     and push the initial commit.

Requires the GitHub CLI (`gh`) installed and authenticated (`gh auth login`).

The project folder is always created at DEFAULT_PROJECTS_DIR/<name>
(/Users/yosefshachnovsky/dev/<name>) — the folder name always matches the
repo name.

The new project gets one backend stack, chosen with --backend:
  python (default)  FastAPI on `backend/app/`, ruff + pytest in CI,
                    `alembic upgrade head` as the migration command.
  nestjs            NestJS on `backend/src/`, ESLint + tsc + jest in CI,
                    `npm run migration:run` as the migration command.
The other stack's instructions doc, agent and CI job are left behind, so the
generated repo has exactly one set and CLAUDE.md imports only what is there.

Infrastructure is excluded by default; pass --infra to include it. That covers
the `infra/` folder, `docs/infra-instructions.md`, the CLAUDE.md section
importing it, and `.github/workflows/deploy.yml`. `ci.yml` and
`claude-review.yml` always copy.

Usage:
    python scripts/create_remote_project.py my-new-project
    python scripts/create_remote_project.py my-new-project --public
    python scripts/create_remote_project.py my-new-project --infra
    python scripts/create_remote_project.py my-new-project --backend nestjs
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from copy_repo import BACKENDS, DEFAULT_BACKEND, REPO_ROOT, copy_repo

DEFAULT_PROJECTS_DIR = Path("/Users/yosefshachnovsky/dev")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def check_gh_ready() -> None:
    if shutil.which("gh") is None:
        sys.exit("GitHub CLI ('gh') not found. Install it from https://cli.github.com/")

    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("GitHub CLI is not authenticated. Run 'gh auth login' first.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="Name for the new repo and project folder (both always match)")
    parser.add_argument("--description", default=None, help="Repo description")
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--public", action="store_true", help="Create a public repo")
    visibility.add_argument("--private", action="store_true", help="Create a private repo (default)")
    parser.add_argument(
        "--include-git",
        action="store_true",
        help="Also copy this repo's .git directory (excluded by default)",
    )
    parser.add_argument(
        "--infra",
        action="store_true",
        help="Include infra/, the infra doc and its CLAUDE.md section, and deploy.yml (excluded by default)",
    )
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default=DEFAULT_BACKEND,
        help="Backend stack for the new project: python (FastAPI, default) or nestjs (TypeScript/NestJS)",
    )
    args = parser.parse_args()

    check_gh_ready()

    destination = (DEFAULT_PROJECTS_DIR / args.name).resolve()

    cwd = Path.cwd().resolve()
    if destination == cwd or cwd in destination.parents:
        sys.exit(
            f"Destination '{destination}' is the current directory or a subfolder of it "
            f"({cwd}). Refusing to nest a new repo inside the current directory."
        )
    if destination == REPO_ROOT:
        sys.exit("Destination cannot be this repo's root.")
    if destination.exists() and any(destination.iterdir()):
        sys.exit(f"Destination '{destination}' already exists and is not empty.")

    print(f"Creating project folder: {destination} ({args.backend} backend)")
    copy_repo(
        destination,
        include_git=args.include_git,
        include_infra=args.infra,
        backend=args.backend,
    )

    print("Initializing git repo and creating initial commit...")
    run(["git", "init", "-b", "main"], cwd=destination)
    run(["git", "add", "-A"], cwd=destination)
    run(["git", "commit", "-m", "Initial commit"], cwd=destination)

    visibility_flag = "--public" if args.public else "--private"

    gh_cmd = [
        "gh", "repo", "create", args.name,
        visibility_flag,
        "--source", str(destination),
        "--remote", "origin",
        "--push",
    ]
    if args.description:
        gh_cmd += ["--description", args.description]

    print(f"Creating GitHub repo '{args.name}' ({visibility_flag}) and pushing...")
    run(gh_cmd)

    print(f"Done. Project ready at {destination}")


if __name__ == "__main__":
    main()
