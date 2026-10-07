# Changelog conversion, October 2026

One-off scripts that gave every package a `CHANGES.md` with release headers of
the form `## VERSION (YYYY-MM-DD)`. They are kept for reference: they were
written when all clones sat next to the scripts, and take their repositories
and input files from the current directory, so they need adapting to the
`gap-packages/` and `others/` layout before running again.

- `survey-changes.py` classified the existing changelogs by header style.
- `patchit-changes-md.py` converted those already close to the format
  (`groupA.tsv`).
- `patchit-changes-b.py` converted the other styles, taking missing dates from
  the git history (`groupB.tsv`, `groupC.tsv`); `readme-to-changes.py`,
  `forms-notes.py` and `json-extra.py` moved notes kept in a README or manual.
- `gen-dossiers.py` listed, for the packages without a changelog
  (`groupD.txt`), the releases and the commits of each; from these the notes
  were drafted and `patchit-add-changes.py` added the files.
  `check-untagged.py` and `find-hidden-changelogs.py` were checks on the way.
- `initial-release.py` reduces the notes of a first release to "Initial
  release"; unlike the others it works in the current layout.
- `pr-urls*.txt` list the pull requests opened.

The generated `dossiers/`, `skeleton/` and `drafts/` are not tracked.
