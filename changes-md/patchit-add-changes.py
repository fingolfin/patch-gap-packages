#!/usr/bin/env python3
"""Add CHANGES.md, drafted from the git history, to packages without a changelog.

Reads drafts/<repo>.md for each repo in groupD.txt and checks its release
headers: well-formed, newest first. Push/PR handling as in patchit-changes-md.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET = Path("CHANGES.md")
DIRECT_LIST = Path("push-direct.txt")
BRANCH = "mh-claude/changes-md"

COMMIT_SUBJECT = "Add CHANGES.md"
COMMIT_BODY = (
    "List each release with a `## VERSION (YYYY-MM-DD)` header, newest first, "
    "so that scripts can extract the release notes. The notes for releases "
    "since 2020 are summarised from the git history; older releases have only "
    "their header. Dates are those in PackageInfo.g at the release tag, or of "
    "the tagged commit."
)
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"

HEADER = re.compile(r"^## (?:Unreleased|\S+ \((?:\d{4}-\d{2}-\d{2}|unreleased)\))$")


def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True,
                          errors="replace").stdout


def package_name(repo: Path) -> str:
    text = (repo / "PackageInfo.g").read_text(errors="replace")
    m = re.search(r'PackageName\s*:=\s*"([^"]+)"', text)
    return m[1] if m else repo.name


def check(name: str) -> tuple[str | None, str]:
    """Return (error, draft text)."""
    draft_path = Path("drafts") / f"{name}.md"
    if not draft_path.exists():
        return "no draft", ""
    draft = draft_path.read_text()
    headers = [l for l in draft.splitlines() if l.startswith("#")]
    if not draft.startswith("## "):
        return "draft does not start with a header", draft
    if bad := [l for l in headers if not HEADER.match(l)]:
        return f"malformed headers: {bad[:3]}", draft
    dates = re.findall(r"\((\d{4}-\d\d-\d\d)\)$", "\n".join(headers), re.M)
    if dates != sorted(dates, reverse=True):
        return "release dates not newest first", draft
    return None, draft


def process_repo(repo: Path, direct: bool, debug: bool, dry_run: bool) -> str:
    error, draft = check(repo.name)
    if error:
        return f"FAIL {repo.name}: {error}"
    if (repo / TARGET).exists():
        return f"OK   {repo.name}: already has CHANGES.md"
    text = f"This file describes changes in the {package_name(repo)} package.\n\n" + draft
    if dry_run:
        return f"DRY  {repo.name} ({'direct' if direct else 'PR'})\n{text}"

    if run(["git", "status", "--porcelain"], repo).strip():
        return f"FAIL {repo.name}: working tree not clean"
    try:
        default = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
        if not direct:
            run(["git", "switch", "-c", BRANCH], repo)
        (repo / TARGET).write_text(text, encoding="utf-8")
        run(["git", "add", str(TARGET)], repo)
        run(["git", "commit", "-m", COMMIT_SUBJECT,
             "-m", textwrap.fill(COMMIT_BODY, width=72), "-m", COMMIT_TRAILER], repo)
        if debug:
            return f"{'DONE' if direct else 'PR  '} {repo.name}: not pushed"
        if direct:
            try:
                run(["git", "push", "--quiet"], repo)
                return f"DONE {repo.name}"
            except subprocess.CalledProcessError as e:
                if "GH013" not in e.stderr and "protected branch" not in e.stderr:
                    raise
            run(["git", "branch", BRANCH], repo)
            run(["git", "reset", "--hard", "@{u}"], repo)
            run(["git", "switch", BRANCH], repo)
        run(["git", "push", "--quiet", "-u", "origin", BRANCH], repo)
        run(["git", "switch", default], repo)
        return f"PR   {repo.name}"
    except subprocess.CalledProcessError as e:
        return f"FAIL {repo.name}: {' '.join(e.cmd)}: {e.stderr.strip()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="commit in the first repo, without pushing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="only validate the drafts")
    parser.add_argument("repos", nargs="*")
    args = parser.parse_args()

    direct = set(DIRECT_LIST.read_text().split())
    names = args.repos or Path("groupD.txt").read_text().split()

    if args.check:
        for name in names:
            error, _ = check(name)
            print(f"{'FAIL' if error else 'OK  '} {name}" + (f": {error}" if error else ""))
        return
    jobs = [(Path.cwd() / n, n in direct) for n in names]
    if args.debug or args.dry_run:
        for repo, is_direct in jobs:
            result = process_repo(repo, is_direct, args.debug, args.dry_run)
            print(result, flush=True)
            if args.debug and not result.startswith(("OK ", "FAIL ")):
                break
        return
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(process_repo, repo, d, False, False) for repo, d in jobs]
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
