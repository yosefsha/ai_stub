#!/usr/bin/env python3
"""Copy this repository's contents to a destination folder.

The destination may already exist (e.g. an existing project root) or not
(it will be created). Files/folders are merged into the destination,
overwriting any same-named files that already exist there.

A generated project gets exactly one backend stack, and `--backend` is
required: which one a project is built on is not a detail to be inherited
from a default. `--backend python` keeps the FastAPI instructions, agent
and CI job; `--backend nestjs` keeps the NestJS ones and drops the Python
ones. The unused stack's CLAUDE.md section goes with its doc, so the
generated CLAUDE.md never imports a file that isn't there.

Every flag is mandatory, and the booleans take an explicit `--x` / `--no-x`.
What a generated project contains is not something to get by omission: the
caller states the backend, and whether infrastructure comes along.

This repo's `.git` is never copied. A destination that inherited it would
inherit this repo's history and its `origin`, and its own first commit would
be a deletion of whatever these flags excluded — see EXCLUDES below.

`--infra` covers the `infra/` folder, `docs/infra-instructions.md`, the
CLAUDE.md section importing it, and `.github/workflows/deploy.yml`, which
deploys to the stacks in `infra/` and does nothing without them. `ci.yml` and
`claude-review.yml` are not infrastructure and always copy.

Usage:
    python scripts/copy_repo.py /path/to/dest --backend python --no-infra
    python scripts/copy_repo.py /path/to/dest --backend nestjs --infra
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Never copied, with no flag to opt back in. `.git` is the one that matters:
# carrying it over would give the new project this repo's 11-commit history and
# an `origin` pointing back here, `gh repo create --remote origin` would refuse
# to add a remote that already exists, and the "initial commit" would land as a
# deletion of every file these flags excluded.
EXCLUDES = {
    ".git",
    "__pycache__",
    ".DS_Store",
    "node_modules",
    ".venv",
}

# Overlay sources for the non-default backends. Never copied as-is: the folder
# itself is dropped from every generated project, and the chosen backend's
# subtree is merged over the destination afterwards.
TEMPLATES_DIR = "templates"

# The backend whose migration command is written into the infra files as they
# sit in this repo. Not a default for --backend — there is none — only the
# starting point `swap_migration_command` rewrites away from.
IN_TREE_BACKEND = "python"

# Per-backend: the instructions doc (and, with it, the CLAUDE.md section that
# imports it), the agent definition, and the overlay applied after the copy.
BACKENDS = {
    "python": {
        "doc": "docs/backend-python-instructions.md",
        "agent": ".claude/agents/backend-engineer.md",
        "overlay": None,
    },
    "nestjs": {
        "doc": "docs/backend-nestjs-instructions.md",
        "agent": ".claude/agents/backend-engineer-nestjs.md",
        # Replaces .github/workflows/ci.yml with the NestJS backend job.
        "overlay": f"{TEMPLATES_DIR}/backend-nestjs",
    },
}

# The migration command the infra runs. It is written once per file as an
# exact literal, and swapped when the chosen backend uses a different one.
# Anchored on the literal itself rather than on surrounding prose, and a miss
# is fatal — a generated project that still shells out to alembic from a
# NestJS image would only fail at deploy time, inside a VPC, with the schema
# half-applied.
MIGRATION_COMMAND_FILES = (
    "infra/stacks/backend_stack.py",
    ".github/workflows/deploy.yml",
)
MIGRATION_COMMANDS = {
    "python": '["alembic", "upgrade", "head"]',
    "nestjs": '["npm", "run", "migration:run"]',
}

# Paths (relative to the repo root) dropped unless --infra is passed.
INFRA_DOC = "docs/infra-instructions.md"
INFRA_EXCLUDES = {"infra", INFRA_DOC, ".github/workflows/deploy.yml"}


def strip_section_importing(text: str, doc_path: str) -> str:
    """Drop the `## ` section of a markdown document that imports `doc_path`.

    Anchored on the import path rather than the heading text, so renaming the
    heading can't silently break the exclusion. The section runs from its `## `
    heading to the next `## ` heading or EOF.
    """
    sections: list[list[str]] = [[]]
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)

    kept = ["".join(s) for s in sections if doc_path not in "".join(s)]
    return "".join(kept).rstrip("\n") + "\n"


def apply_overlay(source: Path, destination: Path) -> None:
    """Merge `source` over `destination`, overwriting same-named files."""
    shutil.copytree(source, destination, dirs_exist_ok=True)


def swap_migration_command(destination: Path, backend: str) -> None:
    """Point the infra's one-off migration task at `backend`'s command."""
    current = MIGRATION_COMMANDS[IN_TREE_BACKEND]
    wanted = MIGRATION_COMMANDS[backend]
    if wanted == current:
        return

    for rel in MIGRATION_COMMAND_FILES:
        path = destination / rel
        if not path.exists():
            continue
        text = path.read_text()
        if current not in text:
            sys.exit(
                f"{rel} no longer contains the migration command {current!r}. "
                f"It has to be swapped for the {backend} backend, so refusing to "
                f"generate a project that would run the wrong one."
            )
        path.write_text(text.replace(current, wanted))


def copy_repo(
    destination: Path,
    backend: str,
    include_infra: bool,
) -> None:
    if backend not in BACKENDS:
        sys.exit(f"Unknown backend '{backend}'. Choose one of: {', '.join(BACKENDS)}.")

    # Everything belonging to a backend that wasn't chosen, plus the overlay
    # sources themselves — a generated project carries no template folder.
    unused_backends = [spec for name, spec in BACKENDS.items() if name != backend]
    unused_backend_paths = {
        path for spec in unused_backends for path in (spec["doc"], spec["agent"])
    }
    path_excludes = unused_backend_paths | {TEMPLATES_DIR}
    if not include_infra:
        path_excludes |= INFRA_EXCLUDES

    def ignore(dir_path: str, names: list[str]) -> set[str]:
        try:
            rel = Path(dir_path).resolve().relative_to(REPO_ROOT)
        except ValueError:
            rel = Path(".")
        skipped = set()
        for name in names:
            rel_name = (rel / name).as_posix().removeprefix("./")
            if name in EXCLUDES or rel_name in path_excludes:
                skipped.add(name)
        return skipped

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT, destination, ignore=ignore, dirs_exist_ok=True)

    overlay = BACKENDS[backend]["overlay"]
    if overlay:
        apply_overlay(REPO_ROOT / overlay, destination)

    if include_infra:
        swap_migration_command(destination, backend)

    # CLAUDE.md imports every doc this repo ships; drop the sections whose docs
    # were just excluded, so nothing imports a file that isn't there.
    dropped_docs = [spec["doc"] for spec in unused_backends]
    if not include_infra:
        dropped_docs.append(INFRA_DOC)

    claude_md = destination / "CLAUDE.md"
    if claude_md.exists() and dropped_docs:
        original = claude_md.read_text()
        stripped = original
        for doc in dropped_docs:
            stripped = strip_section_importing(stripped, doc)
        if stripped != original:
            claude_md.write_text(stripped)


EXAMPLES = """examples:
  # FastAPI stack into a new folder, no AWS infrastructure
  python scripts/copy_repo.py ~/dev/acme-api --backend python --no-infra

  # NestJS stack merged over an existing project, with the CDK stacks
  python scripts/copy_repo.py ~/dev/acme-api --backend nestjs --infra

every argument above is required — there are no defaults to fall back on.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "destination",
        metavar="DESTINATION",
        type=Path,
        help=(
            "Target folder, e.g. ~/dev/acme-api. Created if it doesn't exist; "
            "merged into if it does, overwriting same-named files"
        ),
    )
    parser.add_argument(
        "--backend",
        metavar="{python|nestjs}",
        choices=sorted(BACKENDS),
        required=True,
        help=(
            "Backend stack to keep. "
            "python = FastAPI in backend/app/, ruff + pytest, alembic migrations. "
            "nestjs = NestJS in backend/src/, ESLint + tsc + jest, TypeORM migrations. "
            "The other stack's doc, agent and CI job are left behind"
        ),
    )
    parser.add_argument(
        "--infra",
        action=argparse.BooleanOptionalAction,
        required=True,
        help=(
            "--infra copies infra/ (the CDK stacks), docs/infra-instructions.md, its "
            "CLAUDE.md section and .github/workflows/deploy.yml, and swaps the migration "
            "command to match --backend; --no-infra leaves all four out. ci.yml and "
            "claude-review.yml copy either way"
        ),
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if destination == REPO_ROOT:
        sys.exit("Destination cannot be the repo root itself.")

    copy_repo(
        destination,
        backend=args.backend,
        include_infra=args.infra,
    )
    print(f"Copied {REPO_ROOT} -> {destination} ({args.backend} backend)")


if __name__ == "__main__":
    main()
