#!/usr/bin/env python3
"""Copy this repository's contents to a destination folder.

The destination may already exist (e.g. an existing project root) or not
(it will be created). Files/folders are merged into the destination,
overwriting any same-named files that already exist there.

Infrastructure is excluded by default; pass --infra to include it. That covers
the `infra/` folder, `docs/infra-instructions.md`, the CLAUDE.md section
importing it, and `.github/workflows/deploy.yml`, which deploys to the stacks
in `infra/` and does nothing without them. `ci.yml` and `claude-review.yml`
are not infrastructure and always copy.

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


def copy_repo(destination: Path, include_git: bool = False, include_infra: bool = False) -> None:
    excludes = set(DEFAULT_EXCLUDES)
    if include_git:
        excludes.discard(".git")

    def ignore(dir_path: str, names: list[str]) -> set[str]:
        try:
            rel = Path(dir_path).resolve().relative_to(REPO_ROOT)
        except ValueError:
            rel = Path(".")
        skipped = set()
        for name in names:
            rel_name = (rel / name).as_posix().removeprefix("./")
            if name in excludes:
                skipped.add(name)
            elif not include_infra and rel_name in INFRA_EXCLUDES:
                skipped.add(name)
        return skipped

    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT, destination, ignore=ignore, dirs_exist_ok=True)

    if not include_infra:
        claude_md = destination / "CLAUDE.md"
        if claude_md.exists():
            original = claude_md.read_text()
            stripped = strip_section_importing(original, INFRA_DOC)
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
        help="Include infra/, the infra doc and its CLAUDE.md section, and deploy.yml (excluded by default)",
    )
    args = parser.parse_args()

    destination = args.destination.expanduser().resolve()

    if destination == REPO_ROOT:
        sys.exit("Destination cannot be the repo root itself.")

    copy_repo(destination, include_git=args.include_git, include_infra=args.infra)
    print(f"Copied {REPO_ROOT} -> {destination}")


if __name__ == "__main__":
    main()
