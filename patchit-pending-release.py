#!/usr/bin/env python3
"""Add gap-actions/check-pending-release to every package clone.

Each repo gets .github/workflows/check-pending-release.yml, and its release.yml
a job that closes the tracking issue after a release made by release-pkg.

The clones and how a change reaches them are described in pkgrepos.py.
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

import pkgrepos
from pkgrepos import Repo, format_command_error

WORKFLOW_DIR = Path(".github") / "workflows"
CHECK_FILE = WORKFLOW_DIR / "check-pending-release.yml"
RELEASE_FILE = WORKFLOW_DIR / "release.yml"

ACTION_REPO = "gap-actions/check-pending-release"
ACTION_URL = f"https://github.com/{ACTION_REPO}"
ACTION_TAG = "v1"
NEW_JOB = "close-pending-release-issue"

BRANCH = "mh-claude/check-pending-release"
COMMIT_SUBJECT = "CI: check for pending releases"
COMMIT_BODY = f"See <{ACTION_URL}>."
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"

# a checkout pinned to a commit, e.g. `actions/checkout@<sha> # v7`
PINNED_CHECKOUT = re.compile(r"actions/checkout@[0-9a-f]{40} # v\d+")

CHECK_YML = """\
name: Check for pending release

on:
  schedule:
    - cron: '0 6 * * 1'   # every Monday at 06:00 UTC
  release:
    types: [published]    # close the issue once a release is made
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: {checkout}
        with:
          fetch-depth: 0
      - uses: {action}
"""

RELEASE_JOB = """
  close-pending-release-issue:
    needs: release
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
    steps:
      - uses: {checkout}
        with:
          fetch-depth: 0
      - uses: {action}
"""


class PatchError(Exception):
    pass


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def pinned_action() -> str:
    """Return `ACTION_REPO@<sha> # ACTION_TAG`, for repos that pin their actions."""
    out = run(["git", "ls-remote", f"{ACTION_URL}.git",
               f"refs/tags/{ACTION_TAG}", f"refs/tags/{ACTION_TAG}^{{}}"])
    refs = dict(reversed(line.split("\t")) for line in out.splitlines())
    sha = refs.get(f"refs/tags/{ACTION_TAG}^{{}}") or refs[f"refs/tags/{ACTION_TAG}"]
    return f"{ACTION_REPO}@{sha} # {ACTION_TAG}"


def build_diff(path: Path, old_text: str, new_text: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{path.as_posix()}",
        tofile=f"b/{path.as_posix()}",
    )
    return "".join(diff).strip()


def uses_release_pkg(release: dict) -> bool:
    steps = release.get("jobs", {}).get("release", {}).get("steps", [])
    return any(str(s.get("uses", "")).startswith("gap-actions/release-pkg@") for s in steps)


def patch_release(text: str, uses: dict[str, str]) -> str:
    """Append NEW_JOB to release.yml, checking the result only adds that job."""
    new_text = text.rstrip("\n") + "\n" + RELEASE_JOB.format(**uses)

    old, new = yaml.safe_load(text), yaml.safe_load(new_text)
    added = new["jobs"].pop(NEW_JOB, None)
    if new != old or added is None or added.get("needs") != "release":
        raise PatchError("appending the job to release.yml changed other parts")
    return new_text


def compute_changes(repo: Path, pinned: str) -> dict[Path, str]:
    """Return the files to write, as path relative to repo -> new content."""
    workflows = [p for p in (repo / WORKFLOW_DIR).glob("*.y*ml") if p.is_file()]
    texts = {p.relative_to(repo): p.read_text(encoding="utf-8") for p in workflows}

    # follow the repo's convention of pinning actions to commits
    pin = next((m.group(0) for t in texts.values() if (m := PINNED_CHECKOUT.search(t))), None)
    if pin:
        uses = {"checkout": pin, "action": pinned}
    else:
        uses = {"checkout": "actions/checkout@v7", "action": f"{ACTION_REPO}@{ACTION_TAG}"}

    changes = {}
    has_check = any(ACTION_REPO in t for p, t in texts.items() if p != RELEASE_FILE)
    if not has_check:
        changes[CHECK_FILE] = CHECK_YML.format(**uses)

    release_text = texts.get(RELEASE_FILE)
    if release_text is not None and ACTION_REPO not in release_text \
            and uses_release_pkg(yaml.safe_load(release_text)):
        changes[RELEASE_FILE] = patch_release(release_text, uses)

    return changes


def process_repo(repo: Repo, pinned: str, debug: bool = False,
                 dry_run: bool = False) -> str:
    label = f"{repo.group}/{repo.name}"
    try:
        changes = compute_changes(repo.path, pinned)
    except (PatchError, yaml.YAMLError, AttributeError, KeyError) as e:
        return f"FAIL {label}: {e}"

    if not changes:
        return f"OK   {label}: already set up"

    mode = "direct" if repo.direct else "PR"
    if dry_run:
        diffs = []
        for path, new_text in changes.items():
            target = repo.path / path
            old = target.read_text(encoding="utf-8") if target.exists() else ""
            diffs.append(build_diff(path, old, new_text))
        return f"DRY  {label} ({mode}): {len(changes)} file(s)\n" + "\n".join(diffs)

    if run(["git", "status", "--porcelain"], repo.path).strip():
        return f"FAIL {label}: working tree not clean"

    def commit() -> None:
        for path, new_text in changes.items():
            (repo.path / path).write_text(new_text, encoding="utf-8")
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


def parse_args() -> argparse.Namespace:
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
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    repos = pkgrepos.all_repos(args.repos, tuple(args.group or pkgrepos.GROUPS))
    pinned = pinned_action()

    if args.debug or args.dry_run:
        for repo in repos:
            result = process_repo(repo, pinned, debug=args.debug, dry_run=args.dry_run)
            print(result, flush=True)
            if args.debug and not result.startswith(("OK ", "FAIL ")):
                break
        return

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(process_repo, repo, pinned) for repo in repos]
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
