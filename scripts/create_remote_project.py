#!/usr/bin/env python3
"""Create a new GitHub repo, a new local project folder, and populate it
with this repo's contents.

Steps performed:
  1. Create a local project folder (must not already exist / must be empty).
  2. Copy this repo's contents into it (see copy_repo.py for exclusions).
     This repo's `.git` is never among them, so step 3 starts a history from
     nothing rather than continuing this one.
  3. git init + initial commit in the new folder.
  4. `gh repo create` to create the remote repo, wire it up as `origin`,
     and push the initial commit.

Requires the GitHub CLI (`gh`) installed and authenticated (`gh auth login`).

The project folder is always created at DEFAULT_PROJECTS_DIR/<name>
(/Users/yosefshachnovsky/dev/<name>) — the folder name always matches the
repo name.

The new project gets one backend stack, and --backend is required — which
stack a project is built on is not a detail to be inherited from a default:
  python   FastAPI on `backend/app/`, ruff + pytest in CI,
           `alembic upgrade head` as the migration command.
  nestjs   NestJS on `backend/src/`, ESLint + tsc + jest in CI,
           `npm run migration:run` as the migration command.
The other stack's instructions doc, agent and CI job are left behind, so the
generated repo has exactly one set and CLAUDE.md imports only what is there.

Every flag is mandatory, and `--infra` takes an explicit `--infra` /
`--no-infra`. This script creates a public-or-private repo under the user's
GitHub account on its last step; nothing about what it ships should be arrived
at by leaving an argument out.

`--infra` covers the `infra/` folder, `docs/infra-instructions.md`, the
CLAUDE.md section importing it, and `.github/workflows/deploy.yml`. `ci.yml`
and `claude-review.yml` always copy.

Usage:
    python scripts/create_remote_project.py my-app --backend python --private --desc "..." --no-infra
    python scripts/create_remote_project.py my-app --backend nestjs --public --desc "..." --infra
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from copy_repo import BACKENDS, REPO_ROOT, copy_repo

DEFAULT_PROJECTS_DIR = Path("/Users/yosefshachnovsky/dev")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def check_gh_ready() -> None:
    if shutil.which("gh") is None:
        sys.exit("GitHub CLI ('gh') not found. Install it from https://cli.github.com/")

    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("GitHub CLI is not authenticated. Run 'gh auth login' first.")


EXAMPLES = """examples:
  # Private FastAPI project, no AWS infrastructure
  python scripts/create_remote_project.py acme-api \\
      --backend python --private --desc "Acme ordering API" --no-infra

  # Public NestJS project, with the CDK stacks and deploy.yml
  python scripts/create_remote_project.py acme-api \\
      --backend nestjs --public --desc "Acme ordering API" --infra

every argument above is required — there are no defaults to fall back on.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "name",
        metavar="NAME",
        help=(
            "Name for the new repo and project folder (both always match). "
            "Lowercase kebab-case, e.g. acme-api — it becomes the GitHub repo "
            f"name and the folder {DEFAULT_PROJECTS_DIR}/NAME"
        ),
    )
    parser.add_argument(
        "--desc",
        metavar="TEXT",
        required=True,
        help='One-line repo description, e.g. --desc "Acme ordering API". Shown on the GitHub repo page',
    )
    parser.add_argument(
        "--backend",
        metavar="{python|nestjs}",
        choices=sorted(BACKENDS),
        required=True,
        help=(
            "Backend stack for the new project. "
            "python = FastAPI in backend/app/, ruff + pytest, alembic migrations. "
            "nestjs = NestJS in backend/src/, ESLint + tsc + jest, TypeORM migrations. "
            "The other stack's doc, agent and CI job are left behind"
        ),
    )
    # Who can read the repo is the one choice here with no safe default, so it
    # is stated rather than defaulted — the same reason the flags below are.
    visibility = parser.add_mutually_exclusive_group(required=True)
    visibility.add_argument("--public", action="store_true", help="Create a public repo — anyone can read it")
    visibility.add_argument("--private", action="store_true", help="Create a private repo — only you and collaborators")
    parser.add_argument(
        "--infra",
        action=argparse.BooleanOptionalAction,
        required=True,
        help=(
            "--infra ships infra/ (the CDK stacks), docs/infra-instructions.md, its "
            "CLAUDE.md section and .github/workflows/deploy.yml; --no-infra leaves all "
            "four out, for a project with no AWS deployment. ci.yml and "
            "claude-review.yml ship either way"
        ),
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
        backend=args.backend,
        include_infra=args.infra,
    )

    print("Initializing git repo and creating initial commit...")
    run(["git", "init", "-b", "main"], cwd=destination)
    run(["git", "add", "-A"], cwd=destination)
    run(["git", "commit", "-m", "Initial commit"], cwd=destination)

    visibility_flag = "--public" if args.public else "--private"

    gh_cmd = [
        "gh", "repo", "create", args.name,
        visibility_flag,
        "--description", args.desc,
        "--source", str(destination),
        "--remote", "origin",
        "--push",
    ]

    print(f"Creating GitHub repo '{args.name}' ({visibility_flag}) and pushing...")
    run(gh_cmd)

    print(f"Done. Project ready at {destination}")


if __name__ == "__main__":
    main()
