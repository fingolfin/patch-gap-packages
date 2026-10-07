#!/usr/bin/env python3
"""Decide which clones in gap-packages/ we may push to directly.

Reads the maintainers from each PackageInfo.g via list-maintainers.g and writes
one repo name per line to push-direct.txt and skip.txt; pkgrepos.py reads
those. Every other clone gets its changes through a pull request.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess

# a maintainer whose name matches one of these makes a package "ours"
OUR_MAINTAINERS = re.compile(r"^(Max Horn|The GAP Team|\w+ Konovalov) <")

# repos whose PackageInfo.g lacks maintainer data
FORCE_DIRECT = {"AttributeScheduler", "xgap"}
SKIP = {"certification", "ve"}

TOP = Path(__file__).resolve().parent
CLONES = TOP / "gap-packages"
OUTPUTS = {
    "direct": TOP / "push-direct.txt",
    "skip": TOP / "skip.txt",
}


def read_maintainers() -> dict[str, list[str]]:
    result = subprocess.run(
        ["gap", "-q", "-A", "-b", str(TOP / "list-maintainers.g")],
        cwd=CLONES,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    maintainers = {}
    for line in result.stdout.splitlines():
        repo, _, people = line.partition("\t")
        maintainers[repo] = [p for p in people.split("; ") if p]
    return maintainers


def classify(repo: str, people: list[str]) -> str:
    if repo in SKIP:
        return "skip"
    if repo in FORCE_DIRECT:
        return "direct"
    if any(OUR_MAINTAINERS.match(p) for p in people):
        return "direct"
    return "pr"


def main() -> None:
    maintainers = read_maintainers()
    repos = sorted(p.name for p in CLONES.iterdir() if (p / ".git").exists())

    groups: dict[str, list[str]] = {"direct": [], "pr": [], "skip": []}
    for repo in repos:
        groups[classify(repo, maintainers.get(repo, []))].append(repo)

    for key, path in OUTPUTS.items():
        path.write_text("".join(f"{r}\n" for r in groups[key]), encoding="utf-8")
        print(f"{len(groups[key]):4} {key:6} -> {path.name}")
    print(f"{len(groups['pr']):4} via pull request")


if __name__ == "__main__":
    main()
