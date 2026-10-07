#!/usr/bin/env python3
"""Convert a package's changelog to CHANGES.md with uniform release headers.

Target format: free preamble, then one entry per release, newest first:

    ## 1.2.3 (2026-08-12)

    - change

A pending release is `## 1.2.4 (unreleased)`, or `## Unreleased` if its version
is not known yet. Headers whose date is missing or not ISO keep that part as it
is, and are reported as WARN.

Reads `<repo> TAB <file>` lines from groupA.tsv. Repos listed in push-direct.txt
get the commit pushed to their default branch; the others, and those whose
branch protection rejects the push, get it on BRANCH and are reported as "PR".
"""
from __future__ import annotations

import argparse
import difflib
from pathlib import Path
import re
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET = Path("CHANGES.md")
INPUT_LIST = Path("groupA.tsv")
DIRECT_LIST = Path("push-direct.txt")

BRANCH = "mh-claude/changes-md"
COMMIT_SUBJECT = "Use uniform release headers in CHANGES.md"
COMMIT_BODY = (
    "Start each release entry with `## VERSION (YYYY-MM-DD)`, so that "
    "scripts can extract the release notes."
)
RENAME_SUBJECT = "Rename {old} to CHANGES.md"
RENAME_BODY = "The next commit converts it to Markdown."
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PENDING_DATES = {"unreleased", "tbd", "yyyy-mm-dd", "not yet released"}

# a release header: optional `#`s and "Version", a version or placeholder,
# optionally a date in parentheses, or a note such as `2.7: Never released`
HEADER = re.compile(
    r"^(?:#{1,3}\s+)?(?:Version\s+)?"
    r"(?P<ver>v?\d+(?:\.(?:\d+|X|Y))+[\w.+-]*|NEXT|unreleased)"
    r"(?:\s+\((?P<date>[^)]*)\)|:\s+(?P<note>never released))?\s*:?\s*$",
    re.IGNORECASE,
)

# Plain-text constructs that Markdown renders differently:
# `===` banners and `---` separators become headings or rules,
SEPARATOR = re.compile(r"^\s*(?:=+|-{3,})\s*$")
# `o` bullets are no list,
O_BULLET = re.compile(r"^(\s*)o(?=\s+\S)")
# and `<stream>` is swallowed as an HTML tag; `<https://...>`, `<a@b>` are links
HTML_TAG = re.compile(r"</?[A-Za-z][\w ]*>")


def is_placeholder_version(ver: str) -> bool:
    return ver.upper() in ("NEXT", "UNRELEASED") or bool(re.search(r"\.[XY]\b", ver))


def format_header(ver: str, date: str | None, released: set[str]) -> tuple[str, bool]:
    """Return the normalized header and whether it is fully well-formed.

    A pending entry whose version also has a dated entry becomes `Unreleased`.
    """
    pending_date = date is not None and (
        date.lower() in PENDING_DATES or bool(re.fullmatch(r"\d{4}-MM-DD", date)))
    if is_placeholder_version(ver) or (pending_date and ver in released):
        return "## Unreleased", True
    if pending_date:
        return f"## {ver} (unreleased)", True
    if date is None:
        return f"## {ver}", False
    return f"## {ver} ({date})", bool(ISO_DATE.match(date))


def dedent(lines: list[str]) -> list[str]:
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(indents, default=0)
    return [l[cut:] for l in lines]


def quote_tags(line: str) -> str:
    if "`" in line:
        return line
    return HTML_TAG.sub(lambda m: f"`{m.group(0)}`", line)


def clean_plain(lines: list[str]) -> list[str]:
    lines = [l for l in lines if not SEPARATOR.match(l)]
    lines = [O_BULLET.sub(r"\1-", l) for l in dedent(lines)]
    return [quote_tags(l) for l in lines]


def package_release(repo: Path) -> tuple[str, str] | None:
    """Return (Version, ISO Date) from PackageInfo.g, if both are found."""
    path = repo / "PackageInfo.g"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    ver = re.search(r'^\s*Version\s*:=\s*"([^"]+)"', text, re.M)
    date = re.search(r'^\s*Date\s*:=\s*"(\d\d)/(\d\d)/(\d{4})"', text, re.M)
    if not ver or not date:
        return None
    return ver[1], f"{date[3]}-{date[2]}-{date[1]}"


def convert(text: str, from_plain: bool,
            release: tuple[str, str] | None = None) -> tuple[str, list[str]]:
    """Return the converted text and warnings about irregular headers.

    A header lacking a date gets it from `release` if the versions agree.
    """
    preamble: list[str] = []
    entries: list[tuple[str, list[str]]] = []
    warnings = []

    lines = text.splitlines()
    if from_plain:
        # the files mixing tabs and spaces use 4-column tabs
        lines = [l.expandtabs(4).rstrip() for l in lines]
    released = {m["ver"] for l in lines
                if (m := HEADER.match(l)) and m["date"] and ISO_DATE.match(m["date"])}

    for line in lines:
        m = HEADER.match(line)
        if m:
            date = m["note"].lower() if m["note"] else m["date"]
            if date is None and release and m["ver"] == release[0]:
                date = release[1]
            header, ok = format_header(m["ver"], date, released)
            if not ok:
                warnings.append(f"irregular header: {line.strip()!r} -> {header!r}")
            entries.append((header, []))
        elif entries:
            entries[-1][1].append(line)
        else:
            preamble.append(line)

    if from_plain:
        preamble = [l.strip() for l in clean_plain(preamble)]

    out = list(preamble)
    while out and not out[-1].strip():
        out.pop()
    for header, body in entries:
        if from_plain:
            body = clean_plain(body)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if out:
            out.append("")
        out.append(header)
        if body:
            out.append("")
            out.extend(body)

    return "\n".join(out) + "\n", warnings


def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def format_command_error(error: subprocess.CalledProcessError) -> str:
    parts = [f"command failed: {' '.join(error.cmd)}", f"exit {error.returncode}"]
    if error.stdout:
        parts.append(f"stdout: {error.stdout.strip()}")
    if error.stderr:
        parts.append(f"stderr: {error.stderr.strip()}")
    return "; ".join(parts)


def commit_and_push(repo: Path, old: Path, new_text: str, direct: bool,
                    debug: bool) -> str:
    """Commit the change; return "DONE" if pushed to the default branch, else "PR"."""
    default = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if not direct:
        run(["git", "switch", "-c", BRANCH], repo)

    # a separate rename commit keeps the file's history traceable
    if old != TARGET:
        run(["git", "mv", str(old), str(TARGET)], repo)
        run(["git", "commit", "-m", RENAME_SUBJECT.format(old=old),
             "-m", RENAME_BODY, "-m", COMMIT_TRAILER], repo)

    (repo / TARGET).write_text(new_text, encoding="utf-8")
    run(["git", "add", str(TARGET)], repo)
    run(["git", "commit", "-m", COMMIT_SUBJECT,
         "-m", textwrap.fill(COMMIT_BODY, width=72), "-m", COMMIT_TRAILER], repo)

    if debug:
        return "DONE" if direct else "PR"

    if direct:
        try:
            run(["git", "push", "--quiet"], repo)
            return "DONE"
        except subprocess.CalledProcessError as e:
            if "GH013" not in e.stderr and "protected branch" not in e.stderr:
                raise
        # branch protection: move the commit to BRANCH
        run(["git", "branch", BRANCH], repo)
        run(["git", "reset", "--hard", "@{u}"], repo)
        run(["git", "switch", BRANCH], repo)

    run(["git", "push", "--quiet", "-u", "origin", BRANCH], repo)
    run(["git", "switch", default], repo)
    return "PR"


def process_repo(repo: Path, old: Path, direct: bool, debug: bool = False,
                 dry_run: bool = False) -> str:
    if not (repo / old).exists():
        old = TARGET  # renamed by an earlier run
    text = (repo / old).read_text(encoding="utf-8")
    from_plain = old.suffix != ".md" or not re.search(r"(?m)^#{1,3}\s+(?:Version\s+)?\S*\d", text)
    new_text, warnings = convert(text, from_plain, package_release(repo))
    notes = "".join(f"\nWARN {repo.name}: {w}" for w in warnings)

    if new_text == text and old == TARGET:
        return f"OK   {repo.name}: already uniform" + notes

    mode = "direct" if direct else "PR"
    if dry_run:
        diff = difflib.unified_diff(
            text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"a/{old}", tofile=f"b/{TARGET}")
        return f"DRY  {repo.name} ({mode})" + notes + "\n" + "".join(diff).rstrip()

    if run(["git", "status", "--porcelain"], repo).strip():
        return f"FAIL {repo.name}: working tree not clean"
    try:
        status = commit_and_push(repo, old, new_text, direct, debug)
    except subprocess.CalledProcessError as e:
        return f"FAIL {repo.name}: {format_command_error(e)}"
    return f"{status:4} {repo.name}" + (": not pushed" if debug else "") + notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="commit in the first repo needing changes, without pushing")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the diffs without writing changes")
    parser.add_argument("repos", nargs="*", help="only process these repos")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    direct = set(DIRECT_LIST.read_text(encoding="utf-8").split())
    todo = [line.split("\t") for line in INPUT_LIST.read_text(encoding="utf-8").splitlines()]
    if args.repos:
        todo = [t for t in todo if t[0] in args.repos]
    jobs = [(Path.cwd() / name, Path(f), name in direct) for name, f in todo]

    if args.debug or args.dry_run:
        for repo, old, is_direct in jobs:
            result = process_repo(repo, old, is_direct, debug=args.debug,
                                  dry_run=args.dry_run)
            print(result, flush=True)
            if args.debug and not result.startswith(("OK ", "FAIL ")):
                break
        return

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(process_repo, *job) for job in jobs]
        for future in as_completed(futures):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
