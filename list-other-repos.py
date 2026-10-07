#!/usr/bin/env python3
"""List the GitHub repositories of distributed GAP packages outside gap-packages.

    list-other-repos.py PATH/TO/PackageDistro/packages > others-repos.txt

Prints one `owner/repo` per line, from the SourceRepository of each meta.json.
Repositories holding several packages are left out: their packages live in
subdirectories, which the scripts here do not handle.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# moved into gap-packages; GitHub redirects the old address
SKIP = {"nathancarter/jupyterviz"}
# distributed packages whose meta.json lacks SourceRepository
EXTRA = {"AG-Weitze-Schmithusen/Origami"}


def main() -> None:
    packages = defaultdict(list)
    for meta in sorted(Path(sys.argv[1]).glob("*/meta.json")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        url = (data.get("SourceRepository") or {}).get("URL", "")
        m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if m and m[1].lower() != "gap-packages":
            packages[f"{m[1]}/{m[2]}"].append(data["PackageName"])

    repos = {r for r, names in packages.items() if len(names) == 1 and r not in SKIP}
    for repo in sorted(repos | EXTRA, key=str.lower):
        print(repo)
    for repo, names in sorted(packages.items()):
        if len(names) > 1:
            print(f"skipped {repo}: {len(names)} packages", file=sys.stderr)


if __name__ == "__main__":
    main()
