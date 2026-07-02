#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

# BEGIN PARTS TO EDIT
TARGET_FILE = Path(".github") / "workflows" / "CI.yml"

OLD = re.compile(
    r"""(?m)^        gap-version:\n"""
    r"""^          - 'devel'\n"""
    r"""(?:^          - '4\.\d+'\n)+"""
)

NEW = """        gap-version:
          - 'devel'   # current GAP development version from git
          - 'latest'  # latest GAP release
          - 'minimal' # oldest GAP release supported by this package
"""

COMMIT_SUBJECT = "Use symbolic GAP versions in CI matrix"
COMMIT_BODY = (
    "Replace the hard-coded GAP release list with the symbolic versions "
    "devel, latest, and minimal."
)
# END PARTS TO EDIT


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def format_command_error(error: subprocess.CalledProcessError) -> str:
    parts = [f"command failed: {' '.join(error.cmd)}", f"exit {error.returncode}"]
    if error.stdout:
        parts.append(f"stdout: {error.stdout.strip()}")
    if error.stderr:
        parts.append(f"stderr: {error.stderr.strip()}")
    return "; ".join(parts)


def build_diff(old_text: str, new_text: str) -> str:
    target = TARGET_FILE.as_posix()
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"a/{target}",
        tofile=f"b/{target}",
    )
    return "".join(diff).strip()


def process_repo(repo: Path, debug: bool = False, dry_run: bool = False) -> str:
    workflow = repo / TARGET_FILE
    if not workflow.exists():
        return f"SKIP {repo.name}: no CI workflow"

    text = workflow.read_text(encoding="utf-8")
    new_text = OLD.sub(NEW, text)

    if new_text == text:
        return f"OK   {repo.name}: no match found"

    diff = build_diff(text, new_text)

    if dry_run:
        return (
            f"DRY  {repo.name}: would update workflow and commit with: "
            f"{COMMIT_SUBJECT}\n{diff}"
        )

    workflow.write_text(new_text, encoding="utf-8")

    try:
        run(["git", "add", str(TARGET_FILE)], repo)
        run(["git", "commit", "-m", COMMIT_SUBJECT, "-m", COMMIT_BODY], repo)

        if debug:
            return f"DONE {repo.name}: committed, not pushed"

        run(["git", "push", "--quiet"], repo)
        return f"DONE {repo.name}"
    except subprocess.CalledProcessError as e:
        return f"FAIL {repo.name}: {format_command_error(e)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the workflow diff and commit message without writing changes",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    root = Path.cwd()
    repos = sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())

    if args.debug or args.dry_run:
        for repo in repos:
            result = process_repo(repo, debug=args.debug, dry_run=args.dry_run)
            print(result, flush=True)

            if args.debug and result.startswith("DONE "):
                break
    else:
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            futures = {
                executor.submit(process_repo, repo): repo
                for repo in repos
            }

            for future in as_completed(futures):
                print(future.result(), flush=True)


if __name__ == "__main__":
    main()
