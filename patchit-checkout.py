#!/usr/bin/env python3
"""Replace a pattern in the GitHub workflows of every package clone.

The clones and how a change reaches them are described in pkgrepos.py.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import pkgrepos
from pkgrepos import Repo, format_command_error, run

# BEGIN PARTS TO EDIT
WORKFLOW_DIR = Path(".github") / "workflows"
WORKFLOW_GLOBS = ("*.yml", "*.yaml")

# the lookahead keeps e.g. `@v6.0.1` or `@v50` untouched
OLD = re.compile(r"actions/checkout@v[56](?![\w.])")
NEW = "actions/checkout@v7"

BRANCH = "mh-claude/checkout-v7"
COMMIT_SUBJECT = "CI: update to actions/checkout@v7"
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"
# END PARTS TO EDIT


def build_diff(path: Path, old_text: str, new_text: str) -> str:
    target = path.as_posix()
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{target}",
        tofile=f"b/{target}",
    )
    return "".join(diff).strip()


def workflow_files(repo: Path) -> list[Path]:
    workflow_dir = repo / WORKFLOW_DIR
    files = {f for pattern in WORKFLOW_GLOBS for f in workflow_dir.glob(pattern)}
    return sorted(f.relative_to(repo) for f in files if f.is_file())


def process_repo(repo: Repo, debug: bool = False, dry_run: bool = False) -> str:
    label = f"{repo.group}/{repo.name}"
    files = workflow_files(repo.path)
    if not files:
        return f"SKIP {label}: no workflows"

    # path relative to repo -> new content
    changes: dict[Path, str] = {}
    diffs = []
    for path in files:
        text = (repo.path / path).read_text(encoding="utf-8")
        new_text = OLD.sub(NEW, text)
        if new_text == text:
            continue
        changes[path] = new_text
        diffs.append(build_diff(path, text, new_text))

    if not changes:
        return f"OK   {label}: no match found"

    mode = "direct" if repo.direct else "PR"
    if dry_run:
        return (
            f"DRY  {label} ({mode}): would update {len(changes)} file(s) and commit "
            f"with: {COMMIT_SUBJECT}\n" + "\n".join(diffs)
        )

    if run(["git", "status", "--porcelain"], repo.path).strip():
        return f"FAIL {label}: working tree not clean"

    def commit() -> None:
        for path, new_text in changes.items():
            (repo.path / path).write_text(new_text, encoding="utf-8")
        run(["git", "add", *map(str, changes)], repo.path)
        run(["git", "commit", "-m", COMMIT_SUBJECT, "-m", COMMIT_TRAILER], repo.path)

    try:
        status = pkgrepos.publish(repo, BRANCH, commit, debug)
    except subprocess.CalledProcessError as e:
        return f"FAIL {label}: {format_command_error(e)}"
    result = f"{status:4} {label}" + (": not pushed" if debug else "")
    if status == "PR" and not debug:
        result += "\n     " + pkgrepos.pr_command(repo, BRANCH, COMMIT_SUBJECT)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="commit in the first repo needing changes, without pushing")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the workflow diffs and commit message without writing changes",
    )
    parser.add_argument("--group", choices=pkgrepos.GROUPS, action="append",
                        help="only process this directory of clones (default: both)")
    parser.add_argument("repos", nargs="*", help="only process these repos")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    repos = pkgrepos.all_repos(args.repos, tuple(args.group or pkgrepos.GROUPS))

    if args.debug or args.dry_run:
        for repo in repos:
            result = process_repo(repo, debug=args.debug, dry_run=args.dry_run)
            print(result, flush=True)

            if args.debug and result.startswith(("DONE ", "PR ")):
                break
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = [executor.submit(process_repo, repo) for repo in repos]
            for future in as_completed(futures):
                print(future.result(), flush=True)


if __name__ == "__main__":
    main()
