#!/usr/bin/env python3
"""Reduce the notes of the first release in a generated CHANGES.md to "Initial release".

    initial-release.py REPO[:BRANCH] ...

Edits the oldest entry of CHANGES.md on BRANCH (default: the default branch)
of the clone gap-packages/REPO, commits and pushes to that branch of origin.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pkgrepos import TOP, run  # noqa: E402

NOTE = "- Initial release"
COMMIT_SUBJECT = 'Reduce the first release\'s notes to "Initial release"'
COMMIT_BODY = ("A first release has no earlier one to differ from, so a list of "
               "additions\nand fixes says nothing a reader could act on.")
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"


def reduce_first_release(text: str) -> str:
    start = [m.start() for m in re.finditer(r"(?m)^## ", text)][-1]
    header = text[start:].split("\n", 1)[0]
    return text[:start] + header + "\n\n" + NOTE + "\n"


def main() -> None:
    for spec in sys.argv[1:]:
        name, _, branch = spec.partition(":")
        repo = TOP / "gap-packages" / name
        if run(["git", "status", "--porcelain"], repo).strip():
            print(f"FAIL {name}: working tree not clean")
            continue
        default = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
        branch = branch or default
        run(["git", "switch", "--quiet", branch], repo)
        run(["git", "merge", "--quiet", "--ff-only", f"origin/{branch}"], repo)

        path = repo / "CHANGES.md"
        text = path.read_text(encoding="utf-8")
        new_text = reduce_first_release(text)
        if new_text == text:
            print(f"OK   {name}: nothing to do")
        else:
            path.write_text(new_text, encoding="utf-8")
            run(["git", "commit", "--quiet", "-m", COMMIT_SUBJECT, "-m", COMMIT_BODY,
                 "-m", COMMIT_TRAILER, "CHANGES.md"], repo)
            run(["git", "push", "--quiet", "origin", branch], repo)
            print(f"DONE {name} ({branch})")
        run(["git", "switch", "--quiet", default], repo)


if __name__ == "__main__":
    main()
