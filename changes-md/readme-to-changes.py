#!/usr/bin/env python3
"""Move the changelog in the README of json or PatternClass into CHANGES.md.

    readme-to-changes.py REPO     (run in the gap-packages directory, on the PR branch)

The README's notes are the maintainers' own words, so they replace the notes
CHANGES.md has for the same version; versions the README lacks keep theirs.
Versions only in the README get an undated entry, placed by version number.
The README section is replaced by a pointer to CHANGES.md.
"""
import re
import sys
from pathlib import Path

ENTRY = re.compile(r"(?m)^(## .*)$")


def as_bullets(text: str) -> str:
    """Turn paragraphs into `- ` bullets; continuation lines get 2 spaces."""
    bullets = []
    for para in re.split(r"\n\s*\n", text.strip("\n")):
        lines = [l.rstrip() for l in para.splitlines() if l.strip()]
        if not lines:
            continue
        if not re.match(r"\s*[-*]\s", lines[0]):
            lines[0] = "- " + lines[0].strip()
            lines[1:] = ["  " + l.strip() for l in lines[1:]]
        # a top-level bullet's unindented continuation lines
        out = []
        for l in lines:
            if out and not re.match(r"\s*[-*]\s", l) and not l.startswith(" "):
                l = "  " + l
            out.append(l)
        bullets.append("\n".join(out))
    return "\n".join(bullets)


def json_notes(readme: str) -> tuple[dict[str, str], str]:
    """Return version -> notes, and the README with its Updates section replaced."""
    start = readme.index("\nUpdates\n=======\n")
    section = readme[start:]
    parts = re.split(r"(?m)^v(\S+)\n=+\n", section)
    notes = {}
    for ver, body in zip(parts[1::2], parts[2::2]):
        old = re.findall(r"(?m)^(\d+\.\d+\.\d+) : (.*)$", body)
        body = re.sub(r"(?m)^\d+\.\d+\.\d+ : .*\n?", "", body)
        notes[ver] = as_bullets(body)
        for v, text in old:
            notes[v] = f"- {text}"
    # released as 3.0.0; v2.3.0 and v2.4.0 tag the same commit
    notes["3.0.0"] = notes.pop("2.6.0")
    notes["2.3.0"] = notes.pop("2.4.0")
    pointer = "\nUpdates\n=======\n\nSee CHANGES.md.\n"
    return notes, readme[:start] + pointer


def patternclass_notes(readme: str) -> tuple[dict[str, str], str]:
    start = readme.index("\nChanges\n-------\n")
    section = readme[start:]
    parts = re.split(r"(?m)^Changes from (\S+) to (\S+):\s*$", section)
    notes = {}
    for old, new, body in zip(parts[1::3], parts[2::3], parts[3::3]):
        body = re.sub(r"(?m)^<<<>>>.*$", "", body)
        # "Changes from 2.4.4 to 2.4.2" lists the changes in 2.4.4
        ver = "2.4.4" if (old, new) == ("2.4.4", "2.4.2") else new
        notes[ver] = as_bullets(body)
    pointer = "\nChanges\n-------\n\nSee [CHANGES.md](CHANGES.md).\n"
    return notes, readme[:start] + pointer


def version_key(ver: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", ver))


def merge(changes: str, notes: dict[str, str]) -> str:
    parts = ENTRY.split(changes)
    preamble = parts[0].rstrip("\n")
    entries = [[h, b.strip("\n")] for h, b in zip(parts[1::2], parts[2::2])]
    seen = set()
    for e in entries:
        m = re.match(r"## (\S+)", e[0])
        if m and m[1] in notes:
            e[1] = notes[m[1]]
            seen.add(m[1])
    for ver in sorted(set(notes) - seen, key=version_key, reverse=True):
        # newest first: before the first entry with a smaller version
        at = next((i for i, (h, _) in enumerate(entries)
                   if (m := re.match(r"## (\d\S*)", h)) and version_key(m[1]) < version_key(ver)),
                  len(entries))
        entries.insert(at, [f"## {ver}", notes[ver]])
    body = "\n\n".join(h + ("\n\n" + b if b else "") for h, b in entries)
    return preamble + "\n\n" + body + "\n"


def main() -> None:
    repo = Path(sys.argv[1])
    readme_path = repo / ("README" if repo.name == "json" else "README.md")
    extract = json_notes if repo.name == "json" else patternclass_notes
    notes, readme = extract(readme_path.read_text())
    changes_path = repo / "CHANGES.md"
    changes_path.write_text(merge(changes_path.read_text(), notes))
    readme_path.write_text(readme)


if __name__ == "__main__":
    main()
