from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def load_patchit_module():
    module_path = Path(__file__).resolve().parents[1] / "patchit.py"
    spec = importlib.util.spec_from_file_location("patchit", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def write_workflow(repo: Path, text: str) -> Path:
    workflow = repo / ".github" / "workflows" / "CI.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(text, encoding="utf-8")
    return workflow


def commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_process_repo_dry_run_shows_diff_and_keeps_tree_clean(tmp_path: Path) -> None:
    patchit = load_patchit_module()
    repo = tmp_path / "pkg"
    repo.mkdir()
    init_git_repo(repo)

    original = """name: CI

jobs:
  test:
    strategy:
      matrix:
        gap-version:
          - 'devel'
          - '4.13'
          - '4.12'
    """
    workflow = write_workflow(repo, original)
    commit_all(repo, "Initial workflow")

    result = patchit.process_repo(repo, dry_run=True)

    assert result.startswith("DRY  pkg")
    assert "would update workflow and commit with:" in result
    assert patchit.COMMIT_SUBJECT in result
    assert "--- a/.github/workflows/CI.yml" in result
    assert "+          - 'latest'  # latest GAP release" in result
    assert workflow.read_text(encoding="utf-8") == original

    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""


def test_process_repo_reports_unmatched_gap_matrix(tmp_path: Path) -> None:
    patchit = load_patchit_module()
    repo = tmp_path / "pkg"
    repo.mkdir()
    init_git_repo(repo)

    write_workflow(
        repo,
        """name: CI

jobs:
  test:
    strategy:
      matrix:
        gap-version:
          - 'devel'
          - 'latest'
          - 'minimal'
""",
    )
    commit_all(repo, "Initial workflow")

    result = patchit.process_repo(repo, dry_run=True)

    assert result == "OK   pkg: no match found"


def test_commit_message_mentions_symbolic_versions() -> None:
    patchit = load_patchit_module()

    assert patchit.COMMIT_SUBJECT == "Use symbolic GAP versions in CI matrix"
    assert "devel, latest, and minimal" in patchit.COMMIT_BODY


def test_editable_section_markers_present() -> None:
    patchit = load_patchit_module()
    source = Path(patchit.__file__).read_text(encoding="utf-8")

    assert "# BEGIN PARTS TO EDIT" in source
    assert "# END PARTS TO EDIT" in source


def test_process_repo_reports_unmatched_partial_symbolic_matrix(tmp_path: Path) -> None:
    patchit = load_patchit_module()
    repo = tmp_path / "pkg"
    repo.mkdir()
    init_git_repo(repo)

    write_workflow(
        repo,
        """name: CI

jobs:
  test:
    strategy:
      matrix:
        note: "latest minimal"
        gap-version:
          - 'devel'
          - 'latest'
""",
    )
    commit_all(repo, "Initial workflow")

    result = patchit.process_repo(repo, dry_run=True)

    assert result == "OK   pkg: no match found"
