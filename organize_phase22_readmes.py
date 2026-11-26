#!/usr/bin/env python3
"""Safely organize historical DataHealth AI README files (Phase 22).

Preview (no changes): python organize_phase22_readmes.py
Apply:                python organize_phase22_readmes.py --apply

Run from the DataHealth AI project root. Python 3.12, standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HISTORICAL = re.compile(r"^(?:README_PHASE.*|README_POWER_BI|PHASE21_CONTEXTUAL.*)\.md$", re.I)
LINKS = re.compile(r"(?P<before>!?\[[^\]\n]*\]\()(?P<link>[^)\n]+)(?P<after>\))")
SKIP_DIRS = {".git", ".venv", "venv", "data", "reports", "__pycache__", ".pytest_cache", "node_modules"}


def md_files(root: Path) -> list[Path]:
    result = []
    for directory, subdirs, filenames in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in SKIP_DIRS]
        for name in filenames:
            if name.lower().endswith(".md"):
                result.append(Path(directory) / name)
    return sorted(result)


def strip_suffix(link: str) -> tuple[str, str]:
    match = re.match(r"^([^?#]*)(.*)$", link)
    return match.group(1), match.group(2)


def looks_external(link: str) -> bool:
    return bool(re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#|/|\\\\)", link))


def get_plan(root: Path):
    destination = root / "docs" / "development_history"
    history = sorted(path for path in root.iterdir() if path.is_file() and HISTORICAL.fullmatch(path.name))
    if not history:
        raise RuntimeError("No historical READMEs found in the project root. Nothing to move.")
    if not (root / "docs" / "README.md").is_file() or not (root / "README.md").is_file():
        raise RuntimeError("Expected README.md and docs/README.md are missing. Verify the project root.")
    if any((destination / path.name).exists() for path in history):
        raise RuntimeError("At least one destination filename already exists. Stop to avoid overwriting files.")

    move_map = {p.resolve(): (destination / p.name).resolve() for p in history}
    originals = md_files(root)
    changed: dict[Path, tuple[Path, str, list[tuple[str, str]]]] = {}
    for source in originals:
        original = source.read_bytes().decode("utf-8-sig")
        new_source = move_map.get(source.resolve(), source.resolve())
        link_changes = []

        def rewrite(match: re.Match) -> str:
            old = match.group("link")
            # Avoid rewriting Markdown destinations with optional title strings or angle brackets.
            if looks_external(old) or any(ch in old for ch in (' ', '<', '>')):
                return match.group(0)
            path_part, suffix = strip_suffix(old)
            if not path_part:
                return match.group(0)
            original_target = (source.parent / path_part).resolve()
            new_target = move_map.get(original_target, original_target)
            if new_source == source.resolve() and new_target == original_target:
                return match.group(0)
            if not original_target.exists() and original_target not in move_map:
                # Do not rewrite unresolved paths; they may be intentionally generated later.
                return match.group(0)
            new_path = Path(os.path.relpath(new_target, new_source.parent)).as_posix()
            new_link = new_path + suffix
            if new_link != old:
                link_changes.append((old, new_link))
            return match.group("before") + new_link + match.group("after")

        updated = LINKS.sub(rewrite, original)
        if updated != original or new_source != source.resolve():
            changed[source] = (new_source, updated, link_changes)
    return history, originals, changed, destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up and perform the migration")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    history, originals, changed, destination = get_plan(root)

    print("=== DATAHEALTH AI — PHASE 22 README MIGRATION ===")
    print("Project root:", root)
    print("Mode:", "APPLY" if args.apply else "DRY RUN (NO CHANGES)")
    print(f"Historical READMEs to move: {len(history)}")
    print(f"Markdown links to rewrite: {sum(len(info[2]) for info in changed.values())}")
    for old in history:
        print("  MOVE", old.relative_to(root).as_posix(), "->", (destination / old.name).relative_to(root).as_posix())
    for source, (_, _, replacements) in changed.items():
        for old, new in replacements:
            print("  LINK", source.relative_to(root).as_posix(), f": {old} -> {new}")

    if not args.apply:
        print("\nNo files were changed. Inspect the plan before applying.")
        print("To apply: python organize_phase22_readmes.py --apply")
        return

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = root.parent / f"{root.name}_phase22_markdown_backup_{now}.zip"
    if backup.exists():
        raise RuntimeError("Backup destination already exists; try again.")
    with ZipFile(backup, "x", compression=ZIP_DEFLATED) as zipf:
        for path in originals:
            zipf.write(path, arcname=path.relative_to(root).as_posix())
    print("\nBackup created:", backup)

    destination.mkdir(parents=True, exist_ok=True)
    for old in history:
        shutil.move(str(old), str(destination / old.name))
    for original_path, (new_path, content, replacements) in changed.items():
        if replacements:
            new_path.write_bytes(content.encode("utf-8"))

    # Validate all changed local Markdown links after the move.
    missing = []
    for _, (new_source, updated, changes) in changed.items():
        for _, new_link in changes:
            part, _ = strip_suffix(new_link)
            if not (new_source.parent / part).exists():
                missing.append((str(new_source), new_link))
    if missing:
        print("WARNING: unresolved updated links:")
        for item in missing:
            print("  ", *item)
        print("Restore from backup and investigate before committing.")
        raise SystemExit(2)
    print("Historical READMEs moved; updated local links exist.")
    print("Check: git status --short")
    print("Check: git diff --check")
    print("Keep the backup until the new documentation tree is reviewed.")


if __name__ == "__main__":
    main()
