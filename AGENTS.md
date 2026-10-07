# Project context

This repository contains a Python script for bulk-editing many local GAP package repository clones.

Layout:
- `gap-packages/` holds the clones of the repositories of the gap-packages
  GitHub organisation (`clone-gap-packages.py`).
- `others/` holds the clones of the other distributed GAP packages hosted on
  GitHub, listed in `others-repos.txt` (`clone-others.py`; regenerate the list
  from PackageDistro with `list-other-repos.py`). We cannot push to these:
  changes always go to a fork and through a pull request.
- `update.sh` pulls all clones of both directories.
- `pkgrepos.py` lists the clones and publishes a change to one: pushed to the
  default branch for the packages in `push-direct.txt` (written by
  `classify-maintainers.py` from the maintainers in each `PackageInfo.g`),
  otherwise to a branch, for a pull request. `patchit-checkout.py` and
  `patchit-pending-release.py` are mass changes built on it and can be run
  from anywhere; copy one for a new change.
- `changes-md/` holds one-off scripts of a past mass change.

Typical usage context:
- The script is run from a directory containing many git repository clones,
  i.e. from inside `gap-packages/` or `others/`.
- Each subdirectory that contains `.git` is treated as one repository.
- The script edits workflow files in those repositories, commits changes, and normally pushes them.
- Operations should be safe and idempotent.

Current target task:
- Edit `.github/workflows/CI.yml` in each repository.
- Replace GAP version matrices of the form:

        gap-version:
          - 'devel'
          - '4.X'
          - '4.Y'
          ...

  with:

        gap-version:
          - 'devel'   # current GAP development version from git
          - 'latest'  # latest GAP release
          - 'minimal' # oldest GAP release supported by this package

- The number of `4.x` entries is variable.
- Only replace lists starting with `'devel'` followed by one or more quoted GAP 4.x versions.
- Do not change repositories where the pattern is absent.

Behavior:
- Commit message: `Update CI workflow`
- Use `git push --quiet`.
- Support `-j / --jobs` for parallel processing, default 4.
- Support `-d / --debug`:
  - force serial processing,
  - stop after the first repository where a change is made,
  - commit the change,
  - do not push.

Implementation constraints:
- Prefer Python.
- Keep the script idempotent.
- Print one status line per repository.
- Do not silently hide git errors; report failures per repository.