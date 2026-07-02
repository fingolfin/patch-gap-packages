#!/usr/bin/env python3
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import re

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

COMMIT_MSG = "CI: update gap-actions/build-pkg to v3"


def run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True)


def process_repo(repo: Path) -> str:
    workflow = repo / ".github" / "workflows" / "CI.yml"
    if not workflow.exists():
        return f"SKIP {repo.name}: no CI workflow"

    text = workflow.read_text()
    new_text = OLD.sub(NEW, text)


    if new_text == text:
        return f"OK   {repo.name}: no changes"

    workflow.write_text(new_text)

    try:
        run(["git", "add", str(workflow.relative_to(repo))], repo)
        run(["git", "commit", "-m", COMMIT_MSG], repo)
        run(["git", "push", "--quiet"], repo)
        return f"DONE {repo.name}"
    except subprocess.CalledProcessError as e:
        return f"FAIL {repo.name}: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    args = parser.parse_args()

    root = Path.cwd()
    repos = sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").exists())

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(process_repo, repo): repo for repo in repos}
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()