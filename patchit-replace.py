#!/usr/bin/env python3
"""Replace a text in every git-tracked file of every package clone.

The clones and how a change reaches them are described in pkgrepos.py.
"""
from __future__ import annotations

import argparse
import difflib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pkgrepos
from pkgrepos import Repo, format_command_error, run

# BEGIN PARTS TO EDIT
# the GPL notice reads "(at your option) any later version"
OLD = "your opinion) any later"
NEW = "your option) any later"

BRANCH = "mh-claude/license-typo"
COMMIT_SUBJECT = "Fix typo in the GPL license notice"
COMMIT_BODY = 'The notice reads "(at your option) any later version", as in the GPL.'
COMMIT_TRAILER = "Assisted-by: Generative AI"
# END PARTS TO EDIT


def matching_files(repo: Path) -> list[Path]:
    grep = subprocess.run(["git", "grep", "-lIF", OLD], cwd=repo, capture_output=True,
                          text=True)
    return [Path(f) for f in grep.stdout.splitlines()]


def process_repo(repo: Repo, debug: bool = False, dry_run: bool = False) -> str:
    label = f"{repo.group}/{repo.name}"
    changes = {}
    for path in matching_files(repo.path):
        text = (repo.path / path).read_text(encoding="utf-8")
        changes[path] = (text, text.replace(OLD, NEW))
    if not changes:
        return f"OK   {label}: no match found"

    mode = "direct" if repo.direct else "PR"
    if dry_run:
        diffs = ["".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                              f"a/{p}", f"b/{p}", n=1)).rstrip()
                 for p, (old, new) in changes.items()]
        return f"DRY  {label} ({mode}): {len(changes)} file(s)\n" + "\n".join(diffs)

    if run(["git", "status", "--porcelain"], repo.path).strip():
        return f"FAIL {label}: working tree not clean"

    def commit() -> None:
        for path, (_, new) in changes.items():
            (repo.path / path).write_text(new, encoding="utf-8")
        run(["git", "add", *map(str, changes)], repo.path)
        run(["git", "commit", "-m", COMMIT_SUBJECT, "-m", COMMIT_BODY,
             "-m", COMMIT_TRAILER], repo.path)

    try:
        status = pkgrepos.publish(repo, BRANCH, commit, debug)
    except subprocess.CalledProcessError as e:
        return f"FAIL {label}: {format_command_error(e)}"
    result = f"{status:4} {label}" + (": not pushed" if debug else "")
    if status == "PR" and not debug:
        result += "\n     " + pkgrepos.pr_command(repo, BRANCH, COMMIT_SUBJECT)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="commit in the first repo needing changes, without pushing")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the diffs without writing changes")
    parser.add_argument("--group", choices=pkgrepos.GROUPS, action="append",
                        help="only process this directory of clones (default: both)")
    parser.add_argument("repos", nargs="*", help="only process these repos")
    args = parser.parse_args()
    repos = pkgrepos.all_repos(args.repos, tuple(args.group or pkgrepos.GROUPS))

    if args.debug or args.dry_run:
        for repo in repos:
            result = process_repo(repo, args.debug, args.dry_run)
            print(result, flush=True)
            if args.debug and result.startswith(("DONE ", "PR ")):
                break
        return
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(process_repo, repo) for repo in repos]
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
