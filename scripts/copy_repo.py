#!/usr/bin/env python3
"""Copy this repository's contents to a destination folder.

The destination may already exist (e.g. an existing project root) or not
(it will be created). Files/folders are merged into the destination,
overwriting any same-named files that already exist there.

A generated project gets exactly one backend stack. `--backend python`
(the default) keeps the FastAPI instructions, agent and CI job;
`--backend nestjs` keeps the NestJS ones and drops the Python ones. The
unused stack's CLAUDE.md section goes with its doc, so the generated
CLAUDE.md never imports a file that isn't there.

Infrastructure is excluded by default; pass --infra to include it. That covers
the `infra/` folder, `docs/infra-instructions.md`, the CLAUDE.md section
importing it, and `.github/workflows/deploy.yml`, which deploys to the stacks
in `infra/` and does nothing without them. `ci.yml` and `claude-review.yml`
are not infrastructure and always copy.

Usage:
    python scripts/copy_repo.py /path/to/destination
    python scripts/copy_repo.py /path/to/destination --include-git
    python scripts/copy_repo.py /path/to/destination --infra
    python scripts/copy_repo.py /path/to/destination --backend nestjs
"""

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_EXCLUDES = {
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

DEFAULT_BACKEND = "python"

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
    current = MIGRATION_COMMANDS[DEFAULT_BACKEND]
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
    include_git: bool = False,
    include_infra: bool = False,
    backend: str = DEFAULT_BACKEND,
) -> None:
    if backend not in BACKENDS:
        sys.exit(f"Unknown backend '{backend}'. Choose one of: {', '.join(BACKENDS)}.")

    excludes = set(DEFAULT_EXCLUDES)
    if include_git:
        excludes.discard(".git")

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
            if name in excludes or rel_name in path_excludes:
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("destination", type=Path, help="Target folder (created if it doesn't exist)")
    parser.add_argument(
        "--include-git",
        action="store_true",
        help="Also copy the .git directory (excluded by default)",
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
        help="Backend stack to keep: python (FastAPI, default) or nestjs (TypeScript/NestJS)",
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if destination == REPO_ROOT:
        sys.exit("Destination cannot be the repo root itself.")

    copy_repo(
        destination,
        include_git=args.include_git,
        include_infra=args.infra,
        backend=args.backend,
    )
    print(f"Copied {REPO_ROOT} -> {destination} ({args.backend} backend)")


if __name__ == "__main__":
    main()
