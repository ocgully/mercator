"""Tests for codeatlas.stacks.python — Layer 1 (packages) + Layer 2 (contract)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from codeatlas.stacks import python as pystack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _pyproject(name: str = "myproj", version: str = "0.1.0") -> str:
    return f'[project]\nname = "{name}"\nversion = "{version}"\n'


def _system(doc: dict, name: str) -> Optional[dict]:
    for s in doc.get("systems", []):
        if s["name"] == name:
            return s
    return None


# ---------------------------------------------------------------------------
# build_systems — layout discovery
# ---------------------------------------------------------------------------

def test_build_systems_flat_layout(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("flat"))
    _write(tmp_path / "flat" / "__init__.py", "")
    _write(tmp_path / "flat" / "core.py", "")

    doc = pystack.build_systems(tmp_path)
    names = {s["name"] for s in doc["systems"]}
    assert "flat" in names


def test_build_systems_src_layout(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("srclayout"))
    _write(tmp_path / "src" / "srclayout" / "__init__.py", "")
    _write(tmp_path / "src" / "srclayout" / "mod.py", "")

    doc = pystack.build_systems(tmp_path)
    names = {s["name"] for s in doc["systems"]}
    assert "srclayout" in names


def test_build_systems_subpackage_detected_as_separate_system(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "sub" / "__init__.py", "")

    doc = pystack.build_systems(tmp_path)
    names = {s["name"] for s in doc["systems"]}
    assert "pkg" in names
    assert "pkg.sub" in names


def test_build_systems_skips_pycache_and_venv(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    # SKIP_DIRS members — should not surface as systems.
    _write(tmp_path / "__pycache__" / "__init__.py", "")
    _write(tmp_path / ".venv" / "lib" / "site-packages" / "junk" / "__init__.py", "")

    doc = pystack.build_systems(tmp_path)
    names = {s["name"] for s in doc["systems"]}
    assert "pkg" in names
    assert "__pycache__" not in names
    assert ".venv" not in names
    # Note: nothing under .venv should appear at all.
    assert not any(n.startswith(".venv") for n in names)
    assert not any("site-packages" in n for n in names)


def test_build_systems_tests_dir_is_detected_deliberately(tmp_path: Path) -> None:
    """`tests` is NOT in SKIP_DIRS — confirm it surfaces as a system when
    it has __init__.py. This is intentional behaviour (sometimes tests are
    a real package). Documenting it via a regression test."""
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "tests" / "__init__.py", "")

    doc = pystack.build_systems(tmp_path)
    names = {s["name"] for s in doc["systems"]}
    assert "tests" in names


# ---------------------------------------------------------------------------
# Intra-project import edges
# ---------------------------------------------------------------------------

def test_intra_project_absolute_import_edge(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "foo.py", "from pkg.sub import X\n")
    _write(tmp_path / "pkg" / "sub" / "__init__.py", "")

    doc = pystack.build_systems(tmp_path)
    pkg = _system(doc, "pkg")
    sub = _system(doc, "pkg.sub")
    assert pkg is not None and sub is not None
    pkg_deps = {d["name"] for d in pkg["dependencies"]}
    sub_deps = {d["name"] for d in sub["dependencies"]}
    assert "pkg.sub" in pkg_deps
    # Reverse edge must NOT exist — sub doesn't import pkg.
    assert "pkg" not in sub_deps


def test_relative_imports_resolve_to_internal_edges(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "sub" / "__init__.py", "")
    _write(tmp_path / "pkg" / "sibling" / "__init__.py", "")
    # `from . import bar` inside pkg/sub — resolves to pkg.sub.bar (no system),
    # so longest-prefix-match returns pkg.sub (self) — must NOT be an edge.
    # `from ..sibling import baz` inside pkg/sub — resolves to pkg.sibling →
    # edge pkg.sub → pkg.sibling.
    _write(
        tmp_path / "pkg" / "sub" / "mod.py",
        "from . import bar\n"
        "from ..sibling import baz\n",
    )

    doc = pystack.build_systems(tmp_path)
    sub = _system(doc, "pkg.sub")
    assert sub is not None
    deps = {d["name"] for d in sub["dependencies"]}
    assert "pkg.sibling" in deps
    # Self-edge from `from . import bar` must not be present.
    assert "pkg.sub" not in deps


def test_external_imports_recorded_not_edges(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(
        tmp_path / "pkg" / "io.py",
        "import os\n"
        "import json\n"
        "import requests\n"
        "from collections import OrderedDict\n",
    )

    doc = pystack.build_systems(tmp_path)
    pkg = _system(doc, "pkg")
    assert pkg is not None
    ext = set(pkg["external_imports"])
    assert "os" in ext
    assert "json" in ext
    assert "requests" in ext
    assert "collections" in ext
    # No intra edges — none of those are workspace systems.
    assert pkg["dependencies"] == []


# ---------------------------------------------------------------------------
# build_contract — public surface
# ---------------------------------------------------------------------------

def _contract(root: Path, system: str) -> dict:
    # build_contract takes a manifest_rel; the python stack only uses it for
    # the same return-shape convention. Pass the package's __init__.py path.
    parts = system.split(".")
    manifest = "/".join(parts) + "/__init__.py"
    return pystack.build_contract(root, system, manifest)


def test_contract_function_extracted(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "mod.py", "def public(): pass\n")

    doc = _contract(tmp_path, "pkg")
    items = {it["name"]: it for it in doc["items"]}
    assert "public" in items
    assert items["public"]["kind"] == "fn"


def test_contract_async_function_extracted(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "mod.py", "async def io(): pass\n")

    doc = _contract(tmp_path, "pkg")
    items = {it["name"]: it for it in doc["items"]}
    assert "io" in items
    assert items["io"]["kind"] == "async fn"


def test_contract_class_with_bases(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "mod.py",
           "class Foo: pass\n"
           "class Bar(Foo): pass\n")

    doc = _contract(tmp_path, "pkg")
    items = {it["name"]: it for it in doc["items"]}
    assert items["Foo"]["kind"] == "class"
    assert items["Foo"]["signature"] == "class Foo"
    assert items["Bar"]["kind"] == "class"
    assert "Foo" in items["Bar"]["signature"]
    assert "(Foo)" in items["Bar"]["signature"]


def test_contract_excludes_private_and_dunder(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(
        tmp_path / "pkg" / "mod.py",
        "def _private(): pass\n"
        "def __dunder__(): pass\n"
        "class _Hidden: pass\n"
        "def public(): pass\n",
    )

    doc = _contract(tmp_path, "pkg")
    names = {it["name"] for it in doc["items"]}
    assert "public" in names
    assert "_private" not in names
    assert "__dunder__" not in names
    assert "_Hidden" not in names


def test_contract_module_level_const(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(
        tmp_path / "pkg" / "mod.py",
        "CONST = 1\n"
        "_HIDDEN = 2\n",
    )

    doc = _contract(tmp_path, "pkg")
    items = {it["name"]: it for it in doc["items"]}
    assert "CONST" in items
    assert items["CONST"]["kind"] == "const"
    assert "CONST = 1" in items["CONST"]["signature"]
    assert "_HIDDEN" not in items


def test_contract_signature_includes_annotations_and_defaults(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(
        tmp_path / "pkg" / "mod.py",
        "def f(a: int, b: str = 'x') -> bool: return True\n",
    )

    doc = _contract(tmp_path, "pkg")
    items = {it["name"]: it for it in doc["items"]}
    sig = items["f"]["signature"]
    assert "a: int" in sig
    assert "b: str" in sig
    assert "= 'x'" in sig
    assert "-> bool" in sig


def test_contract_excludes_subpackage_files(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _pyproject("pkg"))
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "top.py", "def top_fn(): pass\n")
    _write(tmp_path / "pkg" / "sub" / "__init__.py", "")
    _write(tmp_path / "pkg" / "sub" / "deep.py", "def deep_fn(): pass\n")

    doc_pkg = _contract(tmp_path, "pkg")
    names_pkg = {it["name"] for it in doc_pkg["items"]}
    assert "top_fn" in names_pkg
    # `deep_fn` belongs to pkg.sub — must not show up in pkg's contract.
    assert "deep_fn" not in names_pkg

    doc_sub = _contract(tmp_path, "pkg.sub")
    names_sub = {it["name"] for it in doc_sub["items"]}
    assert "deep_fn" in names_sub
    assert "top_fn" not in names_sub
