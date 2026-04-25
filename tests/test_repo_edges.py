"""Tests for mercator.repo_edges — implicit cross-project edge resolution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from mercator import paths
from mercator.projects import write_projects
from mercator.repo_edges import compute_edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _cargo(name: str, deps: Optional[dict] = None) -> str:
    text = f'[package]\nname = "{name}"\nversion = "0.1.0"\n'
    if deps:
        text += "\n[dependencies]\n"
        for dep_name, ver in deps.items():
            text += f'{dep_name} = "{ver}"\n'
    return text


def _pyproject(name: str) -> str:
    return f'[project]\nname = "{name}"\nversion = "0.1.0"\n'


def _pkg_json(name: str, deps: Optional[dict] = None) -> str:
    doc: dict = {"name": name, "version": "0.1.0"}
    if deps:
        doc["dependencies"] = deps
    return json.dumps(doc)


def _setup_storage(tmp_path: Path, storage_dir: Path) -> None:
    """Redirect mercator storage into tmp dir and run project detection."""
    paths.set_storage_override(storage_dir)
    write_projects(tmp_path, storage_dir)


def _write_systems(
    storage_dir: Path,
    project_id: str,
    stack: str,
    systems: list,
) -> None:
    """Hand-craft a minimal systems.json for a project."""
    proj_storage = paths.ensure_project_storage_dir(storage_dir, project_id)
    doc = {
        "schema_version": "1",
        "layer": "systems",
        "stack": stack,
        "systems": systems,
    }
    (proj_storage / "systems.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _clear_storage_override():
    """Ensure each test starts and ends with no storage override leakage."""
    paths.set_storage_override(None)
    yield
    paths.set_storage_override(None)


# ---------------------------------------------------------------------------
# Degenerate cases
# ---------------------------------------------------------------------------

def test_empty_repo_no_crash(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    paths.set_storage_override(storage)
    storage.mkdir()

    doc = compute_edges(tmp_path)

    assert doc["edge_count"] == 0
    assert doc["edges"] == []
    assert doc["project_count"] == 0


def test_single_project_no_edges(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _cargo("solo"))
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)
    _write_systems(storage, "solo", "rust", [
        {"name": "solo", "dependencies": []},
    ])

    doc = compute_edges(tmp_path)

    assert doc["project_count"] == 1
    assert doc["edge_count"] == 0


# ---------------------------------------------------------------------------
# TS cross-project edge
# ---------------------------------------------------------------------------

def test_ts_npm_dependency_edge(tmp_path: Path) -> None:
    _write(
        tmp_path / "apps" / "web" / "package.json",
        _pkg_json("web", deps={"shared": "*"}),
    )
    _write(
        tmp_path / "packages" / "shared" / "package.json",
        _pkg_json("shared"),
    )
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)

    # web consumes "shared"; shared publishes itself.
    _write_systems(storage, "apps-web", "ts", [
        {"name": "web", "dependencies": [{"name": "shared"}]},
    ])
    _write_systems(storage, "packages-shared", "ts", [
        {"name": "shared", "dependencies": []},
    ])

    doc = compute_edges(tmp_path)

    assert doc["edge_count"] == 1
    edge = doc["edges"][0]
    assert edge["from"] == "apps-web"
    assert edge["to"] == "packages-shared"
    assert edge["via"] == "shared"
    assert edge["kind"] == "npm-dependency"


# ---------------------------------------------------------------------------
# Python cross-project edge
# ---------------------------------------------------------------------------

def test_python_import_edge(tmp_path: Path) -> None:
    _write(
        tmp_path / "services" / "api" / "pyproject.toml",
        _pyproject("api"),
    )
    _write(
        tmp_path / "packages" / "pyutils" / "pyproject.toml",
        _pyproject("pyutils"),
    )
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)

    # api imports pyutils; pyutils publishes itself.
    _write_systems(storage, "services-api", "python", [
        {"name": "api", "external_imports": ["pyutils"]},
    ])
    _write_systems(storage, "packages-pyutils", "python", [
        {"name": "pyutils", "external_imports": []},
    ])

    doc = compute_edges(tmp_path)

    assert doc["edge_count"] == 1
    edge = doc["edges"][0]
    assert edge["from"] == "services-api"
    assert edge["to"] == "packages-pyutils"
    assert edge["via"] == "pyutils"
    assert edge["kind"] == "python-import"


# ---------------------------------------------------------------------------
# Unmatched external dep — no edge
# ---------------------------------------------------------------------------

def test_rust_unmatched_external_dep_dropped(tmp_path: Path) -> None:
    _write(
        tmp_path / "apps" / "cli" / "Cargo.toml",
        _cargo("cli", deps={"shared": "*"}),
    )
    # Only the cli exists. "shared" is not published anywhere.
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)
    _write_systems(storage, "apps-cli", "rust", [
        {"name": "cli", "dependencies": [{"name": "shared"}]},
    ])

    doc = compute_edges(tmp_path)

    assert doc["edge_count"] == 0


# ---------------------------------------------------------------------------
# Cross-stack name collision — deterministic disambiguation
# ---------------------------------------------------------------------------

def test_cross_stack_name_collision_deterministic(tmp_path: Path) -> None:
    # Both a TS and a Rust project publish "shared". The resolver assigns
    # the name to whichever project comes first in the projects.json sort
    # order (category, root). categories derived from paths:
    #   apps/*     -> app
    #   packages/* -> lib
    # Sort by (category, root) -> "app" before "lib" -> the rust app-cli
    # would win category-wise only if it published "shared". Here we keep
    # the TS shared under packages/ts-shared (category lib), and the rust
    # shared under packages/rust-shared (also category lib) — so the
    # tiebreaker is root order: "packages/rust-shared" < "packages/ts-shared".
    _write(
        tmp_path / "packages" / "rust-shared" / "Cargo.toml",
        _cargo("shared"),
    )
    _write(
        tmp_path / "packages" / "ts-shared" / "package.json",
        _pkg_json("shared"),
    )
    # A consumer that depends on "shared" via npm.
    _write(
        tmp_path / "apps" / "web" / "package.json",
        _pkg_json("web", deps={"shared": "*"}),
    )
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)

    _write_systems(storage, "apps-web", "ts", [
        {"name": "web", "dependencies": [{"name": "shared"}]},
    ])
    _write_systems(storage, "packages-rust-shared", "rust", [
        {"name": "shared", "dependencies": []},
    ])
    _write_systems(storage, "packages-ts-shared", "ts", [
        {"name": "shared", "dependencies": []},
    ])

    doc = compute_edges(tmp_path)

    # Exactly one edge — the deterministic winner.
    assert doc["edge_count"] == 1
    edge = doc["edges"][0]
    assert edge["from"] == "apps-web"
    assert edge["via"] == "shared"
    # The first project (in projects.json iteration order) that publishes
    # "shared" wins the mapping. Sort key is (category, root); both are
    # category "lib" so root decides: "packages/rust-shared" < "packages/ts-shared".
    assert edge["to"] == "packages-rust-shared"


# ---------------------------------------------------------------------------
# Self-edges suppressed
# ---------------------------------------------------------------------------

def test_self_edges_suppressed(tmp_path: Path) -> None:
    # A single rust project whose system "pretends" to depend on its own
    # manifest name. Since that name resolves back to the same project id,
    # no edge must be emitted.
    _write(tmp_path / "Cargo.toml", _cargo("solo"))
    storage = tmp_path / "storage"
    _setup_storage(tmp_path, storage)

    # The system "sub" declares a dependency named "solo" — which is the
    # project's own manifest name. The resolver maps "solo" -> project "solo"
    # and must drop it because from == to.
    _write_systems(storage, "solo", "rust", [
        {"name": "sub", "dependencies": [{"name": "solo"}]},
    ])

    doc = compute_edges(tmp_path)

    assert doc["edge_count"] == 0
