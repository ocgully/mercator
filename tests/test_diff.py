"""Tests for mercator.diff — git-ref structural diff (project-aware)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import pytest

from mercator.diff import (
    LEGACY_PROJECT_ID,
    _load_ref_state,
    compute_diff,
    render_diff_md,
)


# ---------------------------------------------------------------------------
# Skip the whole module if git isn't available.
# ---------------------------------------------------------------------------

if shutil.which("git") is None:  # pragma: no cover
    pytest.skip("git not available", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    # Avoid signing/hooks/external config interfering.
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        env=_GIT_ENV,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit_all(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, env=_GIT_ENV, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _systems_doc(*systems: dict) -> str:
    return json.dumps({
        "schema_version": "1", "layer": "systems", "stack": "py",
        "systems": list(systems),
    })


def _projects_doc(*ids: str) -> str:
    return json.dumps({
        "schema_version": "1",
        "projects": [{"id": pid, "stack": "py"} for pid in ids],
    })


def _contract_doc(*items: dict) -> str:
    return json.dumps({
        "schema_version": "1", "layer": "contract", "stack": "py",
        "items": list(items),
    })


# ---------------------------------------------------------------------------
# _load_ref_state
# ---------------------------------------------------------------------------

def test_load_ref_state_empty_when_neither_layout_present(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / "README.md", "hello")
    _commit_all(repo, "init")

    state = _load_ref_state(repo, "HEAD")
    assert state == {}


def test_load_ref_state_nested_layout(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha"))
    _write(
        repo / ".mercator" / "projects" / "alpha" / "systems.json",
        _systems_doc({"name": "core", "dependencies": []}),
    )
    _write(
        repo / ".mercator" / "projects" / "alpha" / "contracts" / "core.json",
        _contract_doc({"kind": "fn", "name": "f", "signature": "fn f()"}),
    )
    _commit_all(repo, "init")

    state = _load_ref_state(repo, "HEAD")
    assert set(state.keys()) == {"alpha"}
    assert "core" in state["alpha"]["contracts"]
    items = state["alpha"]["contracts"]["core"]["items"]
    assert items[0]["name"] == "f"


def test_load_ref_state_legacy_mercator_flat_layout(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".mercator" / "systems.json",
           _systems_doc({"name": "lib", "dependencies": []}))
    _write(repo / ".mercator" / "contracts" / "lib.json",
           _contract_doc({"kind": "fn", "name": "g", "signature": "fn g()"}))
    _commit_all(repo, "init")

    state = _load_ref_state(repo, "HEAD")
    assert list(state.keys()) == [LEGACY_PROJECT_ID]
    assert "lib" in state[LEGACY_PROJECT_ID]["contracts"]


def test_load_ref_state_legacy_codemap_flat_layout(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".codemap" / "systems.json",
           _systems_doc({"name": "lib", "dependencies": []}))
    _write(repo / ".codemap" / "contracts" / "lib.json",
           _contract_doc({"kind": "fn", "name": "h", "signature": "fn h()"}))
    _commit_all(repo, "init")

    state = _load_ref_state(repo, "HEAD")
    assert list(state.keys()) == [LEGACY_PROJECT_ID]
    assert "lib" in state[LEGACY_PROJECT_ID]["contracts"]


# ---------------------------------------------------------------------------
# compute_diff — project-level adds/removes
# ---------------------------------------------------------------------------

def test_compute_diff_project_added_and_removed(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    # Ref A: alpha + beta.
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha", "beta"))
    _write(repo / ".mercator" / "projects" / "alpha" / "systems.json",
           _systems_doc({"name": "a", "dependencies": []}))
    _write(repo / ".mercator" / "projects" / "beta" / "systems.json",
           _systems_doc({"name": "b", "dependencies": []}))
    sha_a = _commit_all(repo, "ref-A")

    # Ref B: alpha + gamma. (beta removed, gamma added.)
    shutil.rmtree(repo / ".mercator" / "projects" / "beta")
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha", "gamma"))
    _write(repo / ".mercator" / "projects" / "gamma" / "systems.json",
           _systems_doc({"name": "g", "dependencies": []}))
    sha_b = _commit_all(repo, "ref-B")

    diff = compute_diff(repo, sha_a, sha_b)
    assert diff["projects"]["added"] == ["gamma"]
    assert diff["projects"]["removed"] == ["beta"]
    by_id = {e["id"]: e for e in diff["per_project"]}
    assert by_id["gamma"]["status"] == "added"
    assert by_id["gamma"]["systems"]["added"] == ["g"]
    assert by_id["beta"]["status"] == "removed"
    assert by_id["beta"]["systems"]["removed"] == ["b"]


def test_compute_diff_per_project_systems_edges_and_contracts(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    # Ref A: project alpha with system "core" only, with one contract item.
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha"))
    _write(repo / ".mercator" / "projects" / "alpha" / "systems.json",
           _systems_doc({"name": "core", "dependencies": []}))
    _write(repo / ".mercator" / "projects" / "alpha" / "contracts" / "core.json",
           _contract_doc({"kind": "fn", "name": "f1", "signature": "fn f1()"}))
    sha_a = _commit_all(repo, "ref-A")

    # Ref B: add "util" system; core gains an edge to util and a new contract item.
    _write(
        repo / ".mercator" / "projects" / "alpha" / "systems.json",
        _systems_doc(
            {"name": "core", "dependencies": [{"name": "util", "kind": "normal"}]},
            {"name": "util", "dependencies": []},
        ),
    )
    _write(
        repo / ".mercator" / "projects" / "alpha" / "contracts" / "core.json",
        _contract_doc(
            {"kind": "fn", "name": "f1", "signature": "fn f1()"},
            {"kind": "fn", "name": "f2", "signature": "fn f2()"},
        ),
    )
    _write(repo / ".mercator" / "projects" / "alpha" / "contracts" / "util.json",
           _contract_doc({"kind": "fn", "name": "u", "signature": "fn u()"}))
    sha_b = _commit_all(repo, "ref-B")

    diff = compute_diff(repo, sha_a, sha_b)
    assert diff["projects"]["added"] == []
    assert diff["projects"]["removed"] == []
    pp = diff["per_project"]
    assert len(pp) == 1
    entry = pp[0]
    assert entry["id"] == "alpha"
    assert entry["systems"]["added"] == ["util"]
    assert entry["edges"]["added"] == [{"from": "core", "to": "util", "kind": "normal"}]
    # core: f2 added; util gets no contract diff entry because it didn't exist before.
    contract_entries = {c["system"]: c for c in entry["contracts"]}
    assert "core" in contract_entries
    added_names = [it["name"] for it in contract_entries["core"]["added_items"]]
    assert added_names == ["f2"]
    # Util's contract is brand new — system-level add already covers it; no entry.
    assert "util" not in contract_entries


def test_compute_diff_skips_unchanged_per_project_entries(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha", "beta"))
    _write(repo / ".mercator" / "projects" / "alpha" / "systems.json",
           _systems_doc({"name": "a", "dependencies": []}))
    _write(repo / ".mercator" / "projects" / "beta" / "systems.json",
           _systems_doc({"name": "b", "dependencies": []}))
    sha_a = _commit_all(repo, "ref-A")

    # Ref B: change ONLY alpha. Beta unchanged → must not appear in per_project.
    _write(
        repo / ".mercator" / "projects" / "alpha" / "systems.json",
        _systems_doc(
            {"name": "a", "dependencies": []},
            {"name": "a2", "dependencies": []},
        ),
    )
    sha_b = _commit_all(repo, "ref-B")

    diff = compute_diff(repo, sha_a, sha_b)
    ids = [e["id"] for e in diff["per_project"]]
    assert "beta" not in ids
    assert "alpha" in ids


def test_compute_diff_cross_boundary_legacy_to_nested(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    # Ref A: legacy flat `.mercator/systems.json`.
    _write(repo / ".mercator" / "systems.json",
           _systems_doc({"name": "old", "dependencies": []}))
    sha_a = _commit_all(repo, "ref-A")

    # Ref B: nested layout with a project named "alpha".
    (repo / ".mercator" / "systems.json").unlink()
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha"))
    _write(repo / ".mercator" / "projects" / "alpha" / "systems.json",
           _systems_doc({"name": "new", "dependencies": []}))
    sha_b = _commit_all(repo, "ref-B")

    diff = compute_diff(repo, sha_a, sha_b)
    # Synthetic legacy project removed; real alpha added.
    assert LEGACY_PROJECT_ID in diff["projects"]["removed"]
    assert "alpha" in diff["projects"]["added"]


def test_compute_diff_scoped_system_name_with_slash(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha"))
    _write(
        repo / ".mercator" / "projects" / "alpha" / "systems.json",
        _systems_doc({"name": "@scope/foo", "dependencies": []}),
    )
    # Stored on disk as `@scope__foo.json`.
    _write(
        repo / ".mercator" / "projects" / "alpha" / "contracts" / "@scope__foo.json",
        _contract_doc({"kind": "fn", "name": "f", "signature": "fn f()"}),
    )
    sha_a = _commit_all(repo, "ref-A")

    # Ref B: add another contract item.
    _write(
        repo / ".mercator" / "projects" / "alpha" / "contracts" / "@scope__foo.json",
        _contract_doc(
            {"kind": "fn", "name": "f", "signature": "fn f()"},
            {"kind": "fn", "name": "g", "signature": "fn g()"},
        ),
    )
    sha_b = _commit_all(repo, "ref-B")

    state = _load_ref_state(repo, sha_a)
    # The system-name key in `contracts` is the original (with slash).
    assert "@scope/foo" in state["alpha"]["contracts"]

    diff = compute_diff(repo, sha_a, sha_b)
    pp = {e["id"]: e for e in diff["per_project"]}
    assert "alpha" in pp
    contracts = {c["system"]: c for c in pp["alpha"]["contracts"]}
    assert "@scope/foo" in contracts
    added = [it["name"] for it in contracts["@scope/foo"]["added_items"]]
    assert added == ["g"]


# ---------------------------------------------------------------------------
# render_diff_md
# ---------------------------------------------------------------------------

def test_render_diff_md_no_changes() -> None:
    empty = {
        "query": "diff",
        "refs": {"from": "abc", "to": "def"},
        "projects": {"added": [], "removed": []},
        "per_project": [],
    }
    md = render_diff_md(empty)
    assert "_No structural changes._" in md
    assert "abc" in md and "def" in md


def test_render_diff_md_non_empty(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init_repo(repo)
    _write(repo / ".mercator" / "projects.json", _projects_doc("alpha"))
    _write(repo / ".mercator" / "projects" / "alpha" / "systems.json",
           _systems_doc({"name": "core", "dependencies": []}))
    sha_a = _commit_all(repo, "A")

    _write(
        repo / ".mercator" / "projects" / "alpha" / "systems.json",
        _systems_doc(
            {"name": "core", "dependencies": [{"name": "util", "kind": "normal"}]},
            {"name": "util", "dependencies": []},
        ),
    )
    sha_b = _commit_all(repo, "B")

    diff = compute_diff(repo, sha_a, sha_b)
    md = render_diff_md(diff)
    assert "_No structural changes._" not in md
    assert "Project `alpha`" in md
    assert "+ `util`" in md
    assert "core -> util" in md
