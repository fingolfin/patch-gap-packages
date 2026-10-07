#!/usr/bin/env python3
"""Convert the "group B" changelogs to CHANGES.md with uniform release headers.

Same target format as patchit-changes-md.py (`## VERSION (YYYY-MM-DD)`, newest
first), but the input headers come in many styles: `X -> Y`, `Changes from X
to Y`, `Version X: date`, bare `X`, keep-a-changelog, ... Dates that are
missing, or given only to the month, are taken from the git history: the Date
in PackageInfo.g at the release tag, or the date of the tagged commit.

Reads `<repo> TAB <file>` lines from groupB.tsv, or the file given by --input. Push/PR handling as in
patchit-changes-md.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
from pathlib import Path
import re
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed

TARGET = Path("CHANGES.md")
INPUT_LIST = Path("groupB.tsv")
DIRECT_LIST = Path("push-direct.txt")

BRANCH = "mh-claude/changes-md"
COMMIT_SUBJECT = "Use uniform release headers in CHANGES.md"
COMMIT_BODY = (
    "Start each release entry with `## VERSION (YYYY-MM-DD)`, newest first, "
    "so that scripts can extract the release notes. Missing or partial "
    "dates are taken from the git history."
)
RENAME_SUBJECT = "Rename {old} to CHANGES.md"
RENAME_BODY = "The next commit makes its release headers uniform."
COMMIT_TRAILER = "Assisted-by: Claude Code (Opus 5.5)"

# bodies listing one item per line, without list markers
BULLETIZE = {"biogap", "sgpdec", "subsemi", "rig"}

# Markdown files whose bodies are indented like plain text
PLAIN = {"singular"}

# files whose headers carry the start of the entry: `2.1 * Obsolete ...`
NOTE_HEADERS = {"fr", "laguna"}

# header lines the patterns cannot read, rewritten before parsing
HEADER_FIXES = {
    ("anupq", "Version 3.1 (2013-09-24; never publicly announced)"):
        "Version 3.1: (2013-09-24) never publicly announced",
    # US dates
    ("toric", "Toric 1.4 - (2-26-2008):"): "Toric 1.4 - (2008-02-26):",
    ("toric", "Toric 1.3 - (3-7-2006)"): "Toric 1.3 - (2006-03-07)",
    ("toric", "Toric 1.2 - (10-1-2005) now accepted as a GAP package"):
        "Version 1.2: (2005-10-01) now accepted as a GAP package",
    ("toric", "Toric 1.0, 1.1 - initial releases"): "Version 1.1: initial releases (1.0 and 1.1)",
    ("AutoDoc", "## 2016-01-21:"): "## 2016.01.21",
    ("laguna", "1.0 - 2.0"): "Version 2.0: Versions 1.0 to 2.0:",
    ("laguna", "3.1 * Accepted version of the LAGUNA package (June 2003)"):
        "Version 3.1: (June 2003) * Accepted version of the LAGUNA package",
    ("laguna", "3.2.1 * Interface improvements (July 2003):"):
        "Version 3.2.1: (July 2003) * Interface improvements:",
    ("laguna", "3.2.2 * Minor updates for coming GAP 4.4 release (April 2004):"):
        "Version 3.2.2: (April 2004) * Minor updates for coming GAP 4.4 release:",
    ("laguna", "3.6.1 (May 2012), 3.6.2 (January 2013), 3.6.3 (February 2013)"):
        "Version 3.6.3: (February 2013) Changes in 3.6.1 (May 2012), 3.6.2 (January 2013) and 3.6.3:",
    # the entry's text: "Version 1.12 was prepared for the 4.* release at
    # November 2015"
    ("xmodalg", "## initial release"): "## Version 1.12 (November 2015)",
    # tagged as v1.0
    ("numericalsgps", "0.980 -> 1"): "0.980 -> 1.0",
}

# dates the file and history get wrong
DATE_FIXES = {
    # PackageInfo.g said 2024-05-05; 2.3.9 "typo in release date corrected"
    # was released the same day, 2026-05-05
    ("CaratInterface", "2.3.8"): dt.date(2026, 5, 5),
}

PENDING_DATES = {"unreleased", "tbd", "not yet released"}

# a history date this far from the date in the file is reported
MAX_DATE_SKEW = dt.timedelta(days=45)

VER = r"(?:\d+(?:\.\d+)+(?:\.x|[a-z]+\d*|-dev|\s?dev)?|1(?=\s*$))"
MONTHS = {m.lower(): i for i, m in enumerate(
    "January February March April May June July August September October "
    "November December".split(), 1)}
MONTHS["juli"] = 7

HEADER_PATTERNS = [
    # Changes from 1.36 to 1.37 / Main changes from DESIGN 1.4 to DESIGN 1.5 /
    # Changes between RCWA 4.10.0 and RCWA 4.10.1 (September 8, 2026)
    re.compile(rf"^(?:main\s+)?changes?\s+(?:from|between)\s+(?:version\s+|\w+\s+)?v?{VER}"
               rf"\s+(?:to|and)\s+(?:version\s+|\w+\s+)?v?(?P<ver>{VER})(?P<rest>.*)$", re.I),
    # Changes for 1.1.0 (2024-08-29)
    re.compile(rf"^changes\s+for\s+v?(?P<ver>{VER})(?P<rest>.*)$", re.I),
    # 1.16 -> 1.17 / Changes v4.1 -> 4.2 / 2.98 -> 2.99 (19/08/2026)
    re.compile(rf"^(?:changes\s+)?v?{VER}\s*->\s*v?(?P<ver>{VER})(?P<rest>.*)$", re.I),
    # [v1.2.4] - 2026-04-28
    re.compile(rf"^\[v?(?P<ver>{VER}|unreleased)\]\s*(?:-\s*)?(?P<rest>.*)$", re.I),
    # Toric 1.9.6 - (2024-07-04)
    re.compile(rf"^toric\s+(?P<ver>{VER})\s+-\s*(?P<rest>.*)$", re.I),
    # Release of RCWA 1.0.0: April 26, 2005
    re.compile(rf"^release\s+of\s+\w+\s+(?P<ver>{VER}):?(?P<rest>.*)$", re.I),
    # Version 4.4.1: 2025-06-20 / 0.2.5 / v1.1.0 / Version 0.3 (released 22/10/2022)
    re.compile(rf"^(?:version\s+)?v?(?P<ver>{VER})(?P<rest>(?:[\s:,(].*)?)$", re.I),
]

# what may follow the version in a header
REST = re.compile(
    r"^\s*:?\s*(?P<extra>(?:ready\s+)?for\s+GAP\s+[\d.]+)?\s*[:,]?\s*"
    r"(?:\(\s*(?:released\s+)?(?P<pdate>[^()]*?)\s*\)|(?P<date>[^()]*?))\s*:?\s*"
    r"(?P<summary>\*\s*brief summary\s*\*)?\s*$", re.I)

SEPARATOR = re.compile(r"^\s*#?\s*(?:=+|-{3,})\s*$")
GAP_BOX = re.compile(r"^#{2,}")
O_BULLET = re.compile(r"^(\s*)o(?=\s+\S)")
LIST_ITEM = re.compile(r"^\s*(?:[-*+o]|\d+[.)])\s")
HTML_TAG = re.compile(r"</?[A-Za-z][\w ]*>")


def run(cmd: list[str], cwd: Path) -> str:
    # old PackageInfo.g files are often Latin-1
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True,
                          text=True, errors="replace").stdout


# ---------------------------------------------------------------- dates

def parse_date(text: str) -> tuple[dt.date | None, str]:
    """Return (date, precision) with precision "day", "month", "year" or ""."""
    s = text.strip().rstrip(".:,")
    if not s:
        return None, ""

    def mk(y, m, d):
        y = int(y)
        if y < 100:
            y += 2000 if y < 70 else 1900
        try:
            return dt.date(y, int(m), int(d))
        except ValueError:
            return None

    for rx, order in [
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", "ymd"),
        (r"(\d{1,2})/(\d{1,2})/(\d{2,4})", "dmy"),
    ]:
        if m := re.fullmatch(rx, s):
            parts = dict(zip(order, m.groups()))
            d = mk(parts["y"], parts["m"], parts["d"])
            return d, "day" if d else ""
    if m := re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", s):      # September 8, 2026
        if m[1].lower() in MONTHS:
            return mk(m[3], MONTHS[m[1].lower()], m[2]), "day"
    if m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s):       # 06 September 2025
        if m[2].lower() in MONTHS:
            return mk(m[3], MONTHS[m[2].lower()], m[1]), "day"
    if m := re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", s):                    # November 2024
        if m[1].lower() in MONTHS:
            return dt.date(int(m[2]), MONTHS[m[1].lower()], 1), "month"
    if m := re.fullmatch(r"(\d{1,2})-(\d{4})", s):                        # 2-2026
        return dt.date(int(m[2]), int(m[1]), 1), "month"
    return None, ""


def pkginfo_fields(text: str) -> tuple[str | None, dt.date | None]:
    ver = re.search(r'^\s*Version\s*:=\s*"([^"]+)"', text, re.M)
    date = re.search(r'^\s*Date\s*:=\s*"([^"]+)"', text, re.M)
    return (ver[1] if ver else None), (parse_date(date[1])[0] if date else None)


class History:
    """Release dates of a package, from its tags and PackageInfo.g history."""

    def __init__(self, repo: Path):
        self.repo = repo
        # version -> (tag, commit, commit date)
        self.tags: dict[str, tuple[str, str, dt.date]] = {}
        refs = run(["git", "for-each-ref", "refs/tags",
                    "--format=%(refname:short) %(*objectname) %(objectname)"], repo)
        for line in refs.splitlines():
            tag, *objs = line.split()
            commit = objs[0]  # the peeled commit of an annotated tag comes first
            if m := re.fullmatch(r"(?:v|Version-|v-)?\.?(.+)", tag):
                date = dt.date.fromisoformat(
                    run(["git", "log", "-1", "--format=%ad", "--date=short", commit], repo).strip())
                self.tags.setdefault(norm_ver(m[1]), (tag, commit, date))
        # tags created in bulk, e.g. when importing old releases, do not date them
        per_date: dict[dt.date, int] = {}
        for _, _, date in self.tags.values():
            per_date[date] = per_date.get(date, 0) + 1
        self.bulk_dates = {d for d, n in per_date.items() if n >= 3}
        self.current_ver, self.current_date = pkginfo_fields(
            (repo / "PackageInfo.g").read_text(errors="replace"))

        # newest commit first, so the first date seen for a version wins
        self.pkginfo_dates: dict[str, dt.date] = {}
        log = run(["git", "log", "--format=%H", "--", "PackageInfo.g"], repo).split()
        for commit in log:
            try:
                text = run(["git", "show", f"{commit}:PackageInfo.g"], repo)
            except subprocess.CalledProcessError:
                continue
            ver, date = pkginfo_fields(text)
            if ver and date:
                self.pkginfo_dates.setdefault(norm_ver(ver), date)

    def released(self, ver: str) -> bool:
        if norm_ver(ver) in self.tags:
            return True
        if not self.current_ver or is_dev(self.current_ver):
            return version_key(ver) < version_key(self.current_ver or "0")
        return version_key(ver) <= version_key(self.current_ver)

    def date(self, ver: str) -> dt.date | None:
        key = norm_ver(ver)
        if key in self.tags:
            tag, commit, tag_date = self.tags[key]
            try:
                _, pkg_date = pkginfo_fields(run(["git", "show", f"{commit}:PackageInfo.g"], self.repo))
            except subprocess.CalledProcessError:
                pkg_date = None
            if tag_date in self.bulk_dates:
                # an imported release keeps its own PackageInfo.g, unless all
                # tags point at one commit
                shared = sum(1 for _, c, _ in self.tags.values() if c == commit) > 1
                return None if shared or not pkg_date or pkg_date > tag_date else pkg_date
            # PackageInfo.g is sometimes not updated for a release
            if pkg_date and tag_date - MAX_DATE_SKEW <= pkg_date <= tag_date + dt.timedelta(days=5):
                return pkg_date
            return tag_date
        if key == norm_ver(self.current_ver or "") and self.current_date:
            return self.current_date
        return self.pkginfo_dates.get(key)


def norm_ver(ver: str) -> str:
    return re.sub(r"\s+", "", ver.lower())


def is_dev(ver: str) -> bool:
    return bool(re.search(r"dev|\.x$", ver, re.I))


def version_key(ver: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", ver.split("dev")[0]))


# ---------------------------------------------------------------- parsing

# `Version 2.4: (6-2005) Minor bug fix` carries the start of its entry
VERSION_WITH_NOTE = re.compile(
    rf"^version\s+(?P<ver>{VER}):\s*(?:\((?P<date>[^)]*)\)\s*)?(?P<note>.*\S)\s*$", re.I)
# the same without "Version", for NOTE_HEADERS
BARE_WITH_NOTE = re.compile(rf"^(?P<ver>{VER})\s+(?P<note>\S.*?)\s*$")


def match_header(line: str, notes: bool = False
                 ) -> tuple[str, str | None, str | None, str | None] | None:
    """Return (version, raw date, extra text, note) if `line` is a release header.

    With `notes`, a version followed by text also counts, the text being the
    entry's first line.
    """
    if not line.strip() or line[:1] in " \t" and not line.startswith(" Version"):
        return None
    s = re.sub(r"^#+\s*", "", line.strip())
    s = re.sub(r"^[-*]\s+", "", s)
    h = match_plain_header(s)
    if h:
        return h + (None,)
    m = VERSION_WITH_NOTE.match(s)
    if m and (not m["date"] or parse_date(m["date"])[0]):
        return m["ver"], m["date"], None, m["note"]
    if notes and (m := BARE_WITH_NOTE.match(s)):
        return m["ver"], None, None, m["note"]
    return None


def match_plain_header(s: str) -> tuple[str, str | None, str | None] | None:
    for rx in HEADER_PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        rest = REST.match(m["rest"])
        if not rest:
            return None
        raw = rest["pdate"] if rest["pdate"] is not None else rest["date"]
        raw = (raw or "").strip()
        if raw and not parse_date(raw)[0] and raw.lower() not in PENDING_DATES | {"never released"} \
                and not raw.startswith(","):
            return None
        return m["ver"].strip(), raw or None, rest["extra"]
    return None


def deboxed_preamble(lines: list[str]) -> list[str]:
    """Turn a GAP comment box into plain text, without the file name on `#W`."""
    if not any(GAP_BOX.match(l) and len(l.strip()) >= 10 and set(l.strip()) == {"#"}
               for l in lines):
        return lines
    out = []
    for l in lines:
        if set(l.strip()) <= {"#"}:
            continue
        if m := re.match(r"^#W\s+\S+\s+(.*)", l):
            l = m[1]
        elif l.startswith("#"):
            l = re.sub(r"^#+[A-Z]?\s*", "", l)
        # each line of the box is a paragraph of its own; drop the alignment
        out += [re.sub(r"\s{2,}", " ", l.strip()), ""]
    return out


def clean_body(lines: list[str], plain: bool, bulletize: bool) -> list[str]:
    lines = [l for l in lines if not SEPARATOR.match(l)]
    if not plain:
        return lines
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(indents, default=0)
    lines = [O_BULLET.sub(r"\1-", l[cut:]) for l in lines]
    if bulletize and not any(LIST_ITEM.match(l) for l in lines):
        lines = [f"- {l}" if l.strip() else l for l in lines]
    return [l if "`" in l else HTML_TAG.sub(lambda m: f"`{m.group(0)}`", l) for l in lines]


def convert(name: str, text: str, plain: bool, history: History, bulletize: bool
            ) -> tuple[str, list[str]]:
    lines = text.splitlines()
    if plain:
        lines = [l.expandtabs(4).rstrip() for l in lines]

    preamble: list[str] = []
    entries: list[dict] = []
    for line in lines:
        line = HEADER_FIXES.get((name, line.strip()), line)
        h = match_header(line, name in NOTE_HEADERS)
        if h:
            ver, raw, extra, note = h
            entries.append({"ver": ver, "raw": raw, "extra": extra, "line": line.strip(),
                            "note": note, "body": []})
        elif entries:
            entries[-1]["body"].append(line)
        else:
            preamble.append(line)

    warnings = []

    # an empty entry repeating a version is a stray copy
    seen = [e["ver"] for e in entries]
    for e in list(entries):
        if not any(l.strip() for l in e["body"]) and seen.count(e["ver"]) > 1:
            entries.remove(e)
            seen.remove(e["ver"])
            warnings.append(f"dropped empty duplicate entry {e['ver']}")

    # a dev entry below a release holds the details of that release
    for i in range(len(entries) - 1, 0, -1):
        if is_dev(entries[i]["ver"]):
            e = entries.pop(i)
            entries[i - 1]["body"] += ["", f"### {e['line'].lstrip('#').strip()}", ""] + e["body"]
            warnings.append(f"merged dev entry {e['ver']!r} into {entries[i - 1]['ver']}")
    keys = [version_key(e["ver"]) for e in entries if version_key(e["ver"])]
    if len(keys) >= 2 and keys[0] < keys[-1]:
        entries.reverse()
        warnings.append("entries were oldest first; reversed")

    resolve_dates(name, entries, history, warnings)
    for e in entries:
        e["header"] = header_for(e)

    preamble = deboxed_preamble(preamble)
    preamble = [l for l in preamble if not SEPARATOR.match(l)]
    if plain:
        preamble = [l.strip() for l in preamble]
    # headings in the preamble, e.g. `## ToDo:`, are not release entries; the
    # first one is the title
    first = next((i for i, l in enumerate(preamble) if l.strip()), None)
    preamble = [re.sub(r"^#{2,}\s+(.*?)\s*$", r"# \1" if i == first else r"**\1**", l)
                for i, l in enumerate(preamble)]
    while preamble and not preamble[-1].strip():
        preamble.pop()
    while preamble and not preamble[0].strip():
        preamble.pop(0)

    out = list(preamble)
    for e in entries:
        body = clean_body(e["body"], plain, bulletize)
        if e["note"]:
            body.insert(0, e["note"])
        # headings in an entry must not look like release headers
        body = [re.sub(r"^#{1,2}(?=\s)", "###", l) for l in body]
        if e["extra"]:
            extra = e["extra"][0].upper() + e["extra"][1:]
            body = [f"{extra}.", ""] + body
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if out:
            out.append("")
        out.append(e["header"])
        if body:
            out += [""] + body
    return "\n".join(out) + "\n", warnings


def resolve_dates(name: str, entries: list[dict], history: History,
                  warnings: list[str]) -> None:
    """Set e["status"] and e["date"] for each entry."""
    for e in entries:
        ver, raw = e["ver"], e["raw"]
        e["date"] = None
        if (name, ver) in DATE_FIXES:
            e["status"], e["date"] = "released", DATE_FIXES[(name, ver)]
            continue
        if is_dev(ver) or (raw or "").startswith(","):
            e["status"] = "pending-unknown"
            continue
        if raw and raw.lower() in PENDING_DATES:
            e["status"] = "pending"
            continue
        if raw and raw.lower() == "never released":
            e["status"] = "never"
            continue
        if not history.released(ver):
            e["status"] = "pending"
            continue
        e["status"] = "released"
        if m := re.fullmatch(r"(\d{4})\.(\d\d)\.(\d\d)", ver):
            e["date"] = dt.date(int(m[1]), int(m[2]), int(m[3]))
            continue
        given, precision = parse_date(raw or "")
        known = history.date(ver)
        e["known"] = known
        if precision == "day":
            e["date"] = given
            if known and abs(known - given) > MAX_DATE_SKEW:
                warnings.append(f"{ver}: file says {raw}, history says {known}; kept the file's")
        elif precision == "month":
            if known and abs(known - given) <= MAX_DATE_SKEW:
                e["date"] = known
            else:
                e["month"] = given
        elif known:
            e["date"] = known
        else:
            warnings.append(f"{ver}: no date in file or history")

    # a date earlier than that of the release before is a typo, e.g. 2002
    # for 2022; take the history's date if it fits between the neighbours
    dated = [e for e in entries if e.get("date")]
    for newer, e, older in zip([None] + dated[:-1], dated, dated[1:] + [None]):
        if older and e["date"] < older["date"]:
            known = e.get("known")
            fits = known and known >= older["date"] and (not newer or known <= newer["date"])
            if fits:
                warnings.append(f"{e['ver']}: file says {e['raw']}, before the previous "
                                f"release; used history {known}")
                e["date"] = known
            else:
                warnings.append(f"{e['ver']}: file says {e['raw']}, before the previous release")


def header_for(e: dict) -> str:
    ver = e["ver"]
    if e["status"] == "pending-unknown":
        return "## Unreleased"
    if e["status"] == "never":
        return f"## {ver} (never released)"
    if e["status"] == "pending":
        return f"## {ver} (unreleased)"
    if e.get("date"):
        return f"## {ver} ({e['date'].isoformat()})"
    if e.get("month"):
        return f"## {ver} ({e['month']:%Y-%m})"
    return f"## {ver}"


# ---------------------------------------------------------------- git

def update_references(repo: Path, old: Path) -> list[Path]:
    """Point mentions of the old file name at CHANGES.md; return changed files."""
    pathspec = ["--", ".", f":!{old}", f":!{TARGET}", ":!*.html", ":!doc/*.txt"]
    grep = subprocess.run(["git", "grep", "-lIwF", str(old), *pathspec], cwd=repo,
                          capture_output=True, text=True)
    # `CHANGES.guava` and the like are other files
    rx = re.compile(rf"(?<![\w.]){re.escape(str(old))}(?![\w.]|\.\w)")
    changed = []
    for f in grep.stdout.split():
        path = repo / f
        text = path.read_text(encoding="utf-8")
        new = rx.sub("CHANGES.md", text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(Path(f))
    return changed


def commit_and_push(repo: Path, old: Path, new_text: str, direct: bool, debug: bool) -> str:
    default = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if not direct:
        run(["git", "switch", "-c", BRANCH], repo)

    if old != TARGET:
        run(["git", "mv", str(old), str(TARGET)], repo)
        refs = update_references(repo, old)
        if refs:
            run(["git", "add", *map(str, refs)], repo)
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
        run(["git", "branch", BRANCH], repo)
        run(["git", "reset", "--hard", "@{u}"], repo)
        run(["git", "switch", BRANCH], repo)
    run(["git", "push", "--quiet", "-u", "origin", BRANCH], repo)
    run(["git", "switch", default], repo)
    return "PR"


def format_command_error(error: subprocess.CalledProcessError) -> str:
    parts = [f"command failed: {' '.join(error.cmd)}", f"exit {error.returncode}"]
    if error.stderr:
        parts.append(f"stderr: {error.stderr.strip()}")
    return "; ".join(parts)


def process_repo(repo: Path, old: Path, direct: bool, debug: bool = False,
                 dry_run: bool = False) -> str:
    if not (repo / old).exists():
        old = TARGET  # renamed by an earlier run
    text = (repo / old).read_text(encoding="utf-8")
    plain = old.suffix != ".md" or repo.name in PLAIN
    new_text, warnings = convert(repo.name, text, plain, History(repo), repo.name in BULLETIZE)
    notes = "".join(f"\nWARN {repo.name}: {w}" for w in warnings)

    if new_text == text and old == TARGET:
        return f"OK   {repo.name}: already uniform" + notes
    mode = "direct" if direct else "PR"
    if dry_run:
        diff = difflib.unified_diff(text.splitlines(keepends=True),
                                    new_text.splitlines(keepends=True),
                                    fromfile=f"a/{old}", tofile=f"b/{TARGET}")
        return f"DRY  {repo.name} ({mode})" + notes + "\n" + "".join(diff).rstrip()

    if run(["git", "status", "--porcelain"], repo).strip():
        return f"FAIL {repo.name}: working tree not clean"
    try:
        status = commit_and_push(repo, old, new_text, direct, debug)
    except subprocess.CalledProcessError as e:
        return f"FAIL {repo.name}: {format_command_error(e)}"
    return f"{status:4} {repo.name}" + (": not pushed" if debug else "") + notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--jobs", type=int, default=4)
    parser.add_argument("-d", "--debug", action="store_true",
                        help="commit in the first repo needing changes, without pushing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print", action="store_true",
                        help="print the converted files instead of diffs")
    parser.add_argument("--input", type=Path, default=INPUT_LIST,
                        help="file with `<repo> TAB <changelog>` lines")
    parser.add_argument("repos", nargs="*")
    args = parser.parse_args()

    direct = set(DIRECT_LIST.read_text().split())
    todo = [l.split("\t") for l in args.input.read_text().splitlines()]
    if args.repos:
        todo = [t for t in todo if t[0] in args.repos]
    jobs = [(Path.cwd() / n, Path(f), n in direct) for n, f in todo]

    if args.print:
        for repo, old, _ in jobs:
            text = (repo / old).read_text(encoding="utf-8")
            new, warnings = convert(repo.name, text,
                                    old.suffix != ".md" or repo.name in PLAIN,
                                    History(repo), repo.name in BULLETIZE)
            print(f"########## {repo.name}")
            print("".join(f"WARN {w}\n" for w in warnings) + new)
        return
    if args.debug or args.dry_run:
        for job in jobs:
            result = process_repo(*job, debug=args.debug, dry_run=args.dry_run)
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
