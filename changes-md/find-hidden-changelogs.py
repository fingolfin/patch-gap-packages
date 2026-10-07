"""Find changelog-like passages outside CHANGES.md in the given package clones.

A passage counts if a file has at least MIN_HITS lines that look like the
header of a release entry: `Changes from X to Y`, `Version X`, `X (date)`, ...
"""
import re
import subprocess
import sys
from pathlib import Path

MIN_HITS = 3
VER = r"v?\d+\.\d+(?:\.\d+)*[a-z]?"
HEADER = re.compile(
    rf"^\s{{0,3}}(?:[#*=-]+\s*)?(?:"
    rf"(?:main\s+)?changes?\s+(?:from|between|in|for)\b.*{VER}"
    rf"|version\s+{VER}\b"
    rf"|{VER}\s*(?:->|\(|:|-\s)"
    rf"|release\s+{VER}"
    rf"|<(?:Section|Subsection|Heading)[^>]*>[^<]*(?:version|release)\s+{VER}"
    rf")",
    re.I,
)
SKIP = re.compile(r"(^|/)(CHANGES\.md|PackageInfo\.g|\.github/|tst/|.*\.(g|gi|gd|c|h|cc|tst|html|js|css|svg|json|txt\.gz))$")

for name in sys.argv[1:]:
    repo = Path(name)
    files = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True).stdout.split()
    for f in files:
        if SKIP.search(f) or "/" in f and not f.startswith("doc/"):
            continue
        try:
            lines = (repo / f).read_text(errors="replace").splitlines()
        except (IsADirectoryError, FileNotFoundError):
            continue
        hits = [(i + 1, l.strip()) for i, l in enumerate(lines) if HEADER.match(l)]
        if len(hits) >= MIN_HITS:
            print(f"{name}/{f}: {len(hits)} hits, e.g. " + " | ".join(f"{i}:{l[:50]}" for i, l in hits[:3]))
