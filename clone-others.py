#!/usr/bin/env python3
"""Clone the repositories listed in others-repos.txt into others/, if missing."""
from __future__ import annotations

import subprocess
from pathlib import Path

TOP = Path(__file__).resolve().parent


def main() -> None:
    target = TOP / "others"
    target.mkdir(exist_ok=True)
    for repo in (TOP / "others-repos.txt").read_text(encoding="utf-8").split():
        if not (target / repo.split("/")[1]).is_dir():
            subprocess.run(["git", "clone", f"https://github.com/{repo}"], cwd=target, check=False)


if __name__ == "__main__":
    main()
