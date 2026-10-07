#!/usr/bin/env python3
"""Classify each package's changelog by the style of its release headers."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import subprocess

CANDIDATE = re.compile(r"^(changes|changelog|news|history)(\.md|\.txt)?$", re.I)

VER = r"v?\d+(?:\.\d+)+[\w.+-]*"
ISO = r"\d{4}-\d{2}-\d{2}"
PENDING = r"(?:unreleased|TBD|not yet released)"

# checked in order; the first match classifies a line
SCHEMES = [
    ("md ## VER (ISO)", rf"^##\s+{VER}\s+\((?:{ISO}|{PENDING})\)\s*$"),
    ("md # VER (ISO)", rf"^#{{1,3}}\s+{VER}\s+\((?:{ISO}|{PENDING})\)\s*$"),
    ("md ## Version VER (ISO)", rf"^#{{1,3}}\s+Version\s+{VER}\s+\((?:{ISO}|{PENDING})\)\s*$"),
    ("plain VER (ISO)", rf"^{VER}\s+\((?:{ISO}|{PENDING})\)\s*$"),
    ("bullet VER (ISO)", rf"^[-*]\s+(?:Version\s+)?{VER}[,:]?\s+\(?{ISO}\)?:?\s*$"),
    ("Version VER: date", rf"^\s*Version\s+{VER}:\s+\S+"),
    ("keep-a-changelog", rf"^##\s+\[v?{VER}\]"),
    ("VER -> VER", rf"^(?:#+\s+)?(?:Changes\s+)?v?{VER}\s*->\s*{VER}"),
    ("Changes from/between X to Y", rf"(?i)^(?:#+\s+)?(?:main\s+)?changes\s+(?:from|between|for)\b.*{VER}"),
    ("VER/Version + d/m/y date", rf"^(?:#+\s+)?\s*(?:Version\s+)?{VER}.*\d{{1,2}}/\d{{1,2}}/\d{{2,4}}"),
    ("bare VER / Version VER", rf"^(?:#+\s+)?\s*(?:Version\s+)?{VER}\s*$"),
]
SCHEMES = [(name, re.compile(rx)) for name, rx in SCHEMES]

# a file counts as following a scheme if it has this many headers in it
MIN_HEADERS = 2


def changelog_files(repo: Path) -> list[str]:
    files = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                           text=True, check=True).stdout.split()
    return sorted(f for f in files if "/" not in f and CANDIDATE.match(f))


def classify(path: Path) -> tuple[str, int, Counter]:
    counts: Counter = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for name, rx in SCHEMES:
            if rx.search(line):
                counts[name] += 1
                break
    if not counts:
        return "unstructured", 0, counts
    name, n = counts.most_common(1)[0]
    if n < MIN_HEADERS:
        return "unstructured", n, counts
    return name, n, counts


def main() -> None:
    repos = sorted((p for p in Path.cwd().iterdir() if (p / ".git").exists()),
                   key=lambda p: p.name.lower())
    tally: Counter = Counter()
    for repo in repos:
        files = changelog_files(repo)
        if not files:
            print(f"{repo.name}\t-\tnone")
            tally["(none)"] += 1
            continue
        # prefer CHANGES.md, then any .md, then the rest
        files.sort(key=lambda f: (f != "CHANGES.md", not f.endswith(".md")))
        f = files[0]
        scheme, n, counts = classify(repo / f)
        other = sum(counts.values()) - n
        print(f"{repo.name}\t{f}\t{scheme}\t{n}\t{other}\t{' '.join(files[1:])}")
        tally[scheme] += 1
    print()
    for k, v in tally.most_common():
        print(f"{v:4}  {k}")


if __name__ == "__main__":
    main()
