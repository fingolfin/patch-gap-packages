# Project context

This repository contains a Python script for bulk-editing many local GAP package repository clones.

Typical usage context:
- The script is run from a directory containing many git repository clones.
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