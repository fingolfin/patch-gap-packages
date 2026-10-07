"""The package clones below gap-packages/ and others/, and how to publish to them.

A change to a clone in gap-packages/ is pushed to its default branch if the
package is in push-direct.txt; otherwise, or if branch protection rejects the
push, it goes to a branch of the repository, for a pull request. A change to a
clone in others/ always goes to a branch of our fork of it.

Pull requests are opened afterwards with `gh`, which is not installed here;
`pr_command` prints what to run.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TOP = Path(__file__).resolve().parent
GROUPS = ("gap-packages", "others")

# the GitHub account holding our forks, also the name of the remote for them
FORK_OWNER = "fingolfin"

DIRECT_LIST = TOP / "push-direct.txt"
SKIP_LIST = TOP / "skip.txt"


@dataclass(frozen=True)
class Repo:
    path: Path
    group: str  # "gap-packages" or "others"
    direct: bool  # whether we push to its default branch

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def upstream(self) -> str:
        """`owner/repo` of origin."""
        url = run(["git", "remote", "get-url", "origin"], self.path).strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if not m:
            raise ValueError(f"{self.name}: origin is not on GitHub: {url}")
        return f"{m[1]}/{m[2]}"


def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True,
                          errors="replace").stdout


def format_command_error(error: subprocess.CalledProcessError) -> str:
    parts = [f"command failed: {' '.join(error.cmd)}", f"exit {error.returncode}"]
    if error.stdout:
        parts.append(f"stdout: {error.stdout.strip()}")
    if error.stderr:
        parts.append(f"stderr: {error.stderr.strip()}")
    return "; ".join(parts)


def all_repos(names: list[str] | None = None, groups: tuple[str, ...] = GROUPS) -> list[Repo]:
    """Return the clones of `groups`, without those in skip.txt.

    `names` restricts them to the given directory names.
    """
    direct = set(DIRECT_LIST.read_text(encoding="utf-8").split())
    skip = set(SKIP_LIST.read_text(encoding="utf-8").split())
    repos = []
    for group in groups:
        for path in sorted((TOP / group).iterdir(), key=lambda p: p.name.lower()):
            if not (path / ".git").exists() or path.name in skip:
                continue
            if names and path.name not in names:
                continue
            repos.append(Repo(path, group, group == "gap-packages" and path.name in direct))
    return repos


def fork_remote(repo: Repo) -> str:
    """Return the name of the remote for our fork of `repo`, adding it if needed."""
    remotes = run(["git", "remote"], repo.path).split()
    if FORK_OWNER not in remotes:
        fork = f"https://github.com/{FORK_OWNER}/{repo.upstream.split('/')[1]}"
        run(["git", "remote", "add", FORK_OWNER, fork], repo.path)
    return FORK_OWNER


def publish(repo: Repo, branch: str, commit: Callable[[], None], debug: bool = False) -> str:
    """Run `commit` and push its commits; return "DONE" or "PR".

    "DONE" means they are on the default branch of origin, "PR" that they are
    on `branch`, of origin or of our fork, awaiting a pull request. With
    `debug` nothing is pushed. The clone ends up on its default branch.
    """
    default = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo.path).strip()
    if not repo.direct:
        run(["git", "switch", "-c", branch], repo.path)
    commit()
    if debug:
        return "DONE" if repo.direct else "PR"

    if repo.direct:
        try:
            run(["git", "push", "--quiet"], repo.path)
            return "DONE"
        except subprocess.CalledProcessError as e:
            if "GH013" not in e.stderr and "protected branch" not in e.stderr:
                raise
        # branch protection: move the commits to the branch
        run(["git", "branch", branch], repo.path)
        run(["git", "reset", "--hard", "@{u}"], repo.path)
        run(["git", "switch", branch], repo.path)

    remote = "origin" if repo.group == "gap-packages" else fork_remote(repo)
    run(["git", "push", "--quiet", "-u", remote, branch], repo.path)
    run(["git", "switch", default], repo.path)
    return "PR"


def pr_command(repo: Repo, branch: str, title: str) -> str:
    """Return the `gh` command opening the pull request for `branch`."""
    head = branch if repo.group == "gap-packages" else f"{FORK_OWNER}:{branch}"
    return (f"gh pr create --repo {repo.upstream} --head {head} "
            f"--title {title!r} --body-file BODY.md")
