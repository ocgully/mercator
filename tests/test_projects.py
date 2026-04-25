"""Tests for mercator.projects — repo walking and project detection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from mercator import SCHEMA_VERSION
from mercator.projects import _slug, detect_projects


# ---------------------------------------------------------------------------
# Helpers for building synthetic repo trees
# ---------------------------------------------------------------------------

def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _cargo(name: str, extra: str = "") -> str:
    return f'[package]\nname = "{name}"\nversion = "0.1.0"\n{extra}'


def _pyproject(name: str, extra: str = "") -> str:
    return f'[project]\nname = "{name}"\nversion = "0.1.0"\n{extra}'


def _pkg_json(name: str, deps: Optional[dict] = None) -> str:
    doc: dict = {"name": name, "version": "0.1.0"}
    if deps:
        doc["dependencies"] = deps
    return json.dumps(doc)


def _project_by_id(doc: dict, pid: str) -> Optional[dict]:
    for p in doc["projects"]:
        if p["id"] == pid:
            return p
    return None


# ---------------------------------------------------------------------------
# Single-project root
# ---------------------------------------------------------------------------

def test_single_rust_project_at_root(tmp_path: Path) -> None:
    _write(tmp_path / "Cargo.toml", _cargo("my-crate"))

    doc = detect_projects(tmp_path)

    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["project_count"] == 1
    p = doc["projects"][0]
    assert p["stack"] == "rust"
    assert p["root"] == "."
    assert p["manifest"] == "Cargo.toml"
    assert p["manifest_name"] == "my-crate"
    # Single-project-at-root derives ID from the manifest name, not the tmp
    # dir name.
    assert p["id"] == "my-crate"


def test_single_python_project_at_root(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("coolpkg"))

    doc = detect_projects(tmp_path)

    assert doc["project_count"] == 1
    p = doc["projects"][0]
    assert p["stack"] == "python"
    assert p["id"] == "coolpkg"
    assert p["manifest_name"] == "coolpkg"


# ---------------------------------------------------------------------------
# Multi-project monorepo layout
# ---------------------------------------------------------------------------

def _make_monorepo(tmp_path: Path) -> None:
    _write(tmp_path / "apps" / "web" / "package.json", _pkg_json("web"))
    _write(tmp_path / "apps" / "cli" / "Cargo.toml", _cargo("cli"))
    _write(tmp_path / "services" / "api" / "pyproject.toml", _pyproject("api"))
    _write(tmp_path / "packages" / "shared" / "package.json", _pkg_json("shared"))


def test_multi_project_detection(tmp_path: Path) -> None:
    _make_monorepo(tmp_path)

    doc = detect_projects(tmp_path)

    assert doc["project_count"] == 4
    ids = {p["id"] for p in doc["projects"]}
    assert ids == {"apps-web", "apps-cli", "services-api", "packages-shared"}

    by_id = {p["id"]: p for p in doc["projects"]}
    assert by_id["apps-web"]["stack"] == "ts"
    assert by_id["apps-cli"]["stack"] == "rust"
    assert by_id["services-api"]["stack"] == "python"
    assert by_id["packages-shared"]["stack"] == "ts"


def test_path_convention_categories(tmp_path: Path) -> None:
    _make_monorepo(tmp_path)

    doc = detect_projects(tmp_path)

    by_id = {p["id"]: p for p in doc["projects"]}
    assert by_id["apps-web"]["category"] == "app"
    assert by_id["apps-cli"]["category"] == "app"
    assert by_id["services-api"]["category"] == "service"
    assert by_id["packages-shared"]["category"] == "lib"


# ---------------------------------------------------------------------------
# Skip lists
# ---------------------------------------------------------------------------

def test_skip_dirs_not_detected_as_projects(tmp_path: Path) -> None:
    # One real project so detection has a reason to run.
    _write(tmp_path / "Cargo.toml", _cargo("real"))

    # Each of these sits under a skip dir and must NOT surface.
    _write(tmp_path / "node_modules" / "foo" / "package.json", _pkg_json("foo"))
    _write(tmp_path / "target" / "some-cargo-thing" / "Cargo.toml",
           _cargo("junk"))
    _write(tmp_path / "vendor" / "x" / "Cargo.toml", _cargo("vend"))
    _write(tmp_path / ".venv" / "lib" / "site-packages" / "foo"
           / "pyproject.toml", _pyproject("venvpkg"))
    _write(tmp_path / "examples" / "sample" / "Cargo.toml",
           _cargo("sample"))
    _write(tmp_path / "fixtures" / "junk" / "Cargo.toml", _cargo("junkfix"))

    doc = detect_projects(tmp_path)

    ids = {p["id"] for p in doc["projects"]}
    assert ids == {"real"}


# ---------------------------------------------------------------------------
# repo.toml overrides
# ---------------------------------------------------------------------------

def test_include_glob_filters_to_apps_only(tmp_path: Path) -> None:
    _make_monorepo(tmp_path)
    _write(
        tmp_path / ".mercator" / "repo.toml",
        'include = ["apps/*"]\n',
    )

    doc = detect_projects(tmp_path)

    ids = {p["id"] for p in doc["projects"]}
    assert ids == {"apps-web", "apps-cli"}


def test_exclude_glob_removes_one(tmp_path: Path) -> None:
    _make_monorepo(tmp_path)
    _write(
        tmp_path / ".mercator" / "repo.toml",
        'exclude = ["apps/cli"]\n',
    )

    doc = detect_projects(tmp_path)

    ids = {p["id"] for p in doc["projects"]}
    assert "apps-cli" not in ids
    assert ids == {"apps-web", "services-api", "packages-shared"}


def test_per_project_name_and_category_override(tmp_path: Path) -> None:
    _make_monorepo(tmp_path)
    _write(
        tmp_path / ".mercator" / "repo.toml",
        (
            '[projects."apps-web"]\n'
            'name = "Web"\n'
            'category = "tool"\n'
            'tags = ["public"]\n'
        ),
    )

    doc = detect_projects(tmp_path)
    web = _project_by_id(doc, "apps-web")
    assert web is not None
    assert web["name"] == "Web"
    assert web["category"] == "tool"
    assert web["tags"] == ["public"]


# ---------------------------------------------------------------------------
# ID collisions, nested projects, manifest precedence
# ---------------------------------------------------------------------------

def test_id_disambiguation_on_slug_collision(tmp_path: Path) -> None:
    # Both paths slug to "a-b".
    _write(tmp_path / "a" / "b" / "Cargo.toml", _cargo("alpha"))
    _write(tmp_path / "a-b" / "Cargo.toml", _cargo("beta"))

    doc = detect_projects(tmp_path)

    assert doc["project_count"] == 2
    ids = sorted(p["id"] for p in doc["projects"])
    # First (deterministic sort of found dirs) keeps "a-b"; the second gets
    # "a-b-2".
    assert ids == ["a-b", "a-b-2"]


def test_nested_project_not_detected_inside_outer(tmp_path: Path) -> None:
    # Outer rust project with an inner rust crate. Only the outer should be
    # detected because the walker stops descending once it hits a manifest.
    _write(tmp_path / "apps" / "web" / "Cargo.toml", _cargo("web"))
    _write(tmp_path / "apps" / "web" / "internal" / "Cargo.toml",
           _cargo("internal"))

    doc = detect_projects(tmp_path)

    ids = {p["id"] for p in doc["projects"]}
    assert ids == {"apps-web"}


def test_manifest_precedence_rust_wins_over_ts(tmp_path: Path) -> None:
    # Same directory — rust precedes ts in MANIFEST_PRECEDENCE.
    _write(tmp_path / "apps" / "hybrid" / "Cargo.toml", _cargo("hybrid"))
    _write(tmp_path / "apps" / "hybrid" / "package.json",
           _pkg_json("hybrid-npm"))

    doc = detect_projects(tmp_path)
    hybrid = _project_by_id(doc, "apps-hybrid")
    assert hybrid is not None
    assert hybrid["stack"] == "rust"
    assert hybrid["manifest"].endswith("Cargo.toml")


# ---------------------------------------------------------------------------
# _slug correctness
# ---------------------------------------------------------------------------

def test_slug_handles_weird_paths() -> None:
    # Lowercase and dedupe dashes.
    assert _slug("Apps/Web") == "apps-web"
    # Backslashes normalise.
    assert _slug("apps\\web") == "apps-web"
    # Junk chars collapse; no leading/trailing dashes.
    assert _slug("apps//  web") == "apps-web"
    assert _slug("///weird!!path///") == "weird-path"
    # No double-dashes.
    assert "--" not in _slug("a///b---c")
    # Empty → "root".
    assert _slug("") == "root"
    assert _slug("///") == "root"
    # Already clean.
    assert _slug("packages-shared") == "packages-shared"
