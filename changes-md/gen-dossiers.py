#!/usr/bin/env python3
"""For packages without a changelog, list their releases and the commits of each.

Writes, for each repo in groupD.txt:
  dossiers/<repo>.txt   commits per release since NOTES_SINCE, for writing notes
  skeleton/<repo>.md    CHANGES.md with one header per release, no notes yet

Releases are the versions PackageInfo.g went through, plus tagged versions;
dev versions are skipped. A release ends at its tag, or else at the commit
that set its version. Dates come from patchit-changes-b.History.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
import re
import subprocess

spec = importlib.util.spec_from_file_location("b", "patchit-changes-b.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

NOTES_SINCE = dt.date(2020, 1, 1)
MAX_BODY_LINES = 4
# commits that never make a release note
NOISE = re.compile(r"^(Bump |Merge branch|Merge remote|\[pre-commit|pre-commit autoupdate)", re.I)


def run(cmd: list[str], cwd: Path) -> str:
    return b.run(cmd, cwd)


def version_bumps(repo: Path) -> list[tuple[str, str]]:
    """Return (version, commit setting it), oldest first, skipping dev versions."""
    out: list[tuple[str, str]] = []
    seen = set()
    commits = run(["git", "log", "--reverse", "--format=%H", "--", "PackageInfo.g"], repo).split()
    for c in commits:
        try:
            ver, _ = b.pkginfo_fields(run(["git", "show", f"{c}:PackageInfo.g"], repo))
        except subprocess.CalledProcessError:
            continue
        if ver and not b.is_dev(ver) and b.norm_ver(ver) not in seen:
            seen.add(b.norm_ver(ver))
            out.append((ver, c))
    return out


def releases(repo: Path, history: b.History) -> list[dict]:
    """Return releases oldest first: version, end commit, date."""
    rels: dict[str, dict] = {}
    for ver, commit in version_bumps(repo):
        rels[b.norm_ver(ver)] = {"ver": ver, "commit": commit, "tagged": False}
    for key, (tag, commit, _) in history.tags.items():
        if b.is_dev(key) or not re.match(r"\d", key):
            continue
        rels.setdefault(key, {"ver": key}).update(commit=commit, tagged=True)
    out = []
    for r in rels.values():
        if not history.released(r["ver"]):
            continue
        r["date"] = history.date(r["ver"]) or dt.date.fromisoformat(
            run(["git", "log", "-1", "--format=%ad", "--date=short", r["commit"]], repo).strip())
        if not r["tagged"]:
            # the version is often set long before the release
            last = run(["git", "rev-list", "-1", f"--before={r['date'] + dt.timedelta(days=1)}",
                        "HEAD"], repo).strip()
            r["commit"] = last or r["commit"]
        out.append(r)
    out.sort(key=lambda r: (r["date"], b.version_key(r["ver"])))
    return out


def commit_log(repo: Path, rng: str) -> list[str]:
    fmt = "%h %ad %s%n%b%x00"
    text = run(["git", "log", "--no-merges", "--date=short", f"--format={fmt}", rng], repo)
    lines = []
    for entry in text.split("\x00"):
        entry = entry.strip("\n")
        if not entry:
            continue
        subject, *body = entry.splitlines()
        if NOISE.match(subject.split(" ", 2)[2]):
            continue
        lines.append(f"- {subject}")
        body = [l.strip() for l in body if l.strip() and not l.startswith(("Co-authored", "Signed-off"))]
        lines += [f"    {l}" for l in body[:MAX_BODY_LINES]]
    merges = run(["git", "log", "--merges", "--format=%s%n%b%x00", rng], repo)
    for entry in merges.split("\x00"):
        parts = entry.strip("\n").splitlines()
        if parts and (m := re.match(r"Merge pull request (#\d+)", parts[0])):
            title = parts[1].strip() if len(parts) > 1 else ""
            lines.append(f"- PR {m[1]}: {title}")
    return lines


def main() -> None:
    Path("dossiers").mkdir(exist_ok=True)
    Path("skeleton").mkdir(exist_ok=True)
    for name in Path("groupD.txt").read_text().split():
        repo = Path(name)
        history = b.History(repo)
        rels = releases(repo, history)
        head = run(["git", "rev-parse", "HEAD"], repo).strip()

        dossier = [f"# {name}: {len(rels)} releases; notes for releases since {NOTES_SINCE}"]
        skeleton = []
        prev = None
        sections = []
        for r in rels:
            rng = f"{prev}..{r['commit']}" if prev else r["commit"]
            sections.append((r, rng))
            prev = r["commit"]

        pending = commit_log(repo, f"{prev}..{head}") if prev else commit_log(repo, head)
        if pending and rels:
            skeleton.append("## Unreleased")
            dossier += ["", "## Unreleased", *pending]

        for r, rng in reversed(sections):
            header = f"## {r['ver']} ({r['date'].isoformat()})"
            skeleton.append(header)
            if r["date"] >= NOTES_SINCE:
                dossier += ["", header, *commit_log(repo, rng)]

        Path(f"skeleton/{name}.md").write_text("\n\n".join(skeleton) + "\n")
        Path(f"dossiers/{name}.txt").write_text("\n".join(dossier) + "\n")
        print(f"{name}: {len(rels)} releases, dossier {len(dossier)} lines")


if __name__ == "__main__":
    main()
