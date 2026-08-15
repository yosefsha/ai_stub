#!/usr/bin/env python3
"""Copy this repository's contents to a destination folder.

The destination may already exist (e.g. an existing project root) or not
(it will be created). Files/folders are merged into the destination,
overwriting any same-named files that already exist there.

Infrastructure (the `infra/` folder and the infrastructure section of
CLAUDE.md) is excluded by default; pass --infra to include it.

Usage:
    python scripts/copy_repo.py /path/to/destination
    python scripts/copy_repo.py /path/to/destination --include-git
    python scripts/copy_repo.py /path/to/destination --infra
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

# Top-level paths dropped unless --infra is passed.
INFRA_EXCLUDES = {"infra"}

# A `## ` heading containing this word starts the infra section of CLAUDE.md.
INFRA_HEADING_KEYWORD = "infrastructure"


def strip_infra_section(text: str) -> str:
    """Drop the `## Infrastructure...` section (and its subsections) from a
    markdown document. The section runs until the next `## ` heading or EOF."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            skipping = INFRA_HEADING_KEYWORD in line.lower()
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip("\n") + "\n"


def copy_repo(destination: Path, include_git: bool = False, include_infra: bool = False) -> None:
    excludes = set(DEFAULT_EXCLUDES)
    if include_git:
        excludes.discard(".git")

    def ignore(dir_path: str, names: list[str]) -> set[str]:
        skip = set(excludes)
        if not include_infra and Path(dir_path).resolve() == REPO_ROOT:
            skip |= INFRA_EXCLUDES
        return {name for name in names if name in skip}

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT, destination, ignore=ignore, dirs_exist_ok=True)

    if not include_infra:
        claude_md = destination / "CLAUDE.md"
        if claude_md.exists():
            original = claude_md.read_text()
            stripped = strip_infra_section(original)
            if stripped != original:
                claude_md.write_text(stripped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Target folder (created if it doesn't exist)")
    parser.add_argument(
        "--include-git",
        action="store_true",
        help="Also copy the .git directory (excluded by default)",
    )
    parser.add_argument(
        "--infra",
        action="store_true",
        help="Include infra/ and the infrastructure section of CLAUDE.md (excluded by default)",
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if destination == REPO_ROOT:
        sys.exit("Destination cannot be the repo root itself.")

    copy_repo(destination, include_git=args.include_git, include_infra=args.infra)
    print(f"Copied {REPO_ROOT} -> {destination}")


if __name__ == "__main__":
    main()
