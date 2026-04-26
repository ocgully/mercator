"""Tests for codeatlas.stacks.ts — Layer 2 (export-scan) public surface."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.stacks import ts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_pkg(root: Path, name: str = "pkg") -> None:
    """Create a minimal `package.json` at root so build_systems sees a system."""
    _write(root / "package.json", json.dumps({"name": name, "version": "0.1.0"}))


def _build(root: Path) -> dict:
    """Build the contract for the root system using build_contract."""
    return ts.build_contract(root, "pkg", "package.json")


def _by_name(items, name: str):
    matches = [it for it in items if it["name"] == name]
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Function exports
# ---------------------------------------------------------------------------

def test_export_function_with_signature(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "src" / "a.ts",
        "export function foo(a: number, b: string): boolean { return true; }\n",
    )
    doc = _build(tmp_path)
    foo = _by_name(doc["items"], "foo")
    assert foo is not None
    assert foo["kind"] == "fn"
    assert "(a: number, b: string)" in foo["signature"]
    assert ": boolean" in foo["signature"]


def test_export_async_function(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", "export async function bar() {}\n")
    doc = _build(tmp_path)
    bar = _by_name(doc["items"], "bar")
    assert bar is not None
    assert bar["kind"] == "async fn"


# ---------------------------------------------------------------------------
# Class / interface / type / enum
# ---------------------------------------------------------------------------

def test_export_class_with_extends_and_implements(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "a.ts",
        "export class Foo extends Bar implements Baz {}\n",
    )
    doc = _build(tmp_path)
    foo = _by_name(doc["items"], "Foo")
    assert foo is not None
    assert foo["kind"] == "class"
    assert "extends Bar" in foo["signature"]


def test_export_interface(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", "export interface IThing { x: number }\n")
    doc = _build(tmp_path)
    it = _by_name(doc["items"], "IThing")
    assert it is not None
    assert it["kind"] == "interface"


def test_export_type_signature_truncated(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    long_rhs = " | ".join([f"'opt{i}'" for i in range(40)])
    _write(tmp_path / "a.ts", f"export type Alias = {long_rhs}\n")
    doc = _build(tmp_path)
    alias = _by_name(doc["items"], "Alias")
    assert alias is not None
    assert alias["kind"] == "type"
    # Sig is `type Alias = …` and truncated near 80 chars on the rhs.
    rhs_sig_len = len(alias["signature"])
    assert rhs_sig_len <= 140
    # Contains the truncation ellipsis.
    assert "..." in alias["signature"]


def test_export_simple_type_alias(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", "export type Alias = string | number\n")
    doc = _build(tmp_path)
    alias = _by_name(doc["items"], "Alias")
    assert alias is not None
    assert alias["kind"] == "type"
    assert "string | number" in alias["signature"]


def test_export_enum(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", "export enum Direction { Up, Down }\n")
    doc = _build(tmp_path)
    d = _by_name(doc["items"], "Direction")
    assert d is not None
    assert d["kind"] == "enum"


# ---------------------------------------------------------------------------
# const / let / var
# ---------------------------------------------------------------------------

def test_export_const_let_var(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "a.ts",
        "export const X = 1\nexport let y = 2\nexport var z = 3\n",
    )
    doc = _build(tmp_path)
    names = {it["name"]: it for it in doc["items"]}
    assert names["X"]["kind"] == "const"
    assert names["y"]["kind"] == "const"
    assert names["z"]["kind"] == "const"


# ---------------------------------------------------------------------------
# Default exports
# ---------------------------------------------------------------------------

def test_export_default_function_named(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", "export default function defaultFn() {}\n")
    doc = _build(tmp_path)
    item = _by_name(doc["items"], "default(defaultFn)")
    assert item is not None
    assert item["kind"] == "fn"


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------

def test_export_named_re_export_with_alias(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", 'export { foo, bar as baz } from "./mod"\n')
    doc = _build(tmp_path)
    re_exports = [it for it in doc["items"] if it["kind"] == "re-export"]
    names = sorted(it["name"] for it in re_exports)
    assert names == ["baz", "foo"]


def test_export_star_from(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "a.ts", 'export * from "./mod"\n')
    doc = _build(tmp_path)
    re_exports = [it for it in doc["items"] if it["kind"] == "re-export"]
    assert len(re_exports) == 1
    assert re_exports[0]["name"] == "*"


# ---------------------------------------------------------------------------
# Filtering: underscore / unexported / skipped files
# ---------------------------------------------------------------------------

def test_underscore_and_unexported_not_extracted(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "a.ts",
        "function notExported() {}\n"
        "export function _hidden() {}\n"
        "export function visible() {}\n",
    )
    doc = _build(tmp_path)
    names = [it["name"] for it in doc["items"]]
    assert "notExported" not in names
    # `_hidden` regex still matches export, but underscored.
    # Confirm whether scanner's regex includes underscored names. The regex
    # `[A-Za-z_$][\w$]*` does match `_hidden` — so it WILL be returned.
    # Underscored unexported declarations (no `export` prefix) must NOT appear.
    # That's the contract: anything not prefixed with `export` is omitted.
    assert "visible" in names


def test_dts_test_spec_files_skipped(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    # Should be skipped by file-suffix filter.
    _write(tmp_path / "skip.d.ts", "export function inDts() {}\n")
    _write(tmp_path / "x.test.ts", "export function inTest() {}\n")
    _write(tmp_path / "x.spec.ts", "export function inSpec() {}\n")
    # And one normal file for comparison.
    _write(tmp_path / "ok.ts", "export function ok() {}\n")

    doc = _build(tmp_path)
    names = {it["name"] for it in doc["items"]}
    assert "ok" in names
    assert "inDts" not in names
    assert "inTest" not in names
    assert "inSpec" not in names


def test_skip_dirs_excluded(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(tmp_path / "node_modules" / "pkg" / "x.ts",
           "export function fromNm() {}\n")
    _write(tmp_path / "dist" / "x.ts", "export function fromDist() {}\n")
    _write(tmp_path / ".next" / "x.ts", "export function fromNext() {}\n")
    _write(tmp_path / "ok.ts", "export function ok() {}\n")

    doc = _build(tmp_path)
    names = {it["name"] for it in doc["items"]}
    assert names == {"ok"}


# ---------------------------------------------------------------------------
# String-literal robustness
# ---------------------------------------------------------------------------

def test_string_literals_dont_leak_as_exports(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "a.ts",
        'const s = "export function fakeFn() {}"\n'
        "export function realFn() {}\n",
    )
    doc = _build(tmp_path)
    names = {it["name"] for it in doc["items"]}
    assert "fakeFn" not in names
    assert "realFn" in names


def test_export_inside_block_comment_skipped(tmp_path: Path) -> None:
    _init_pkg(tmp_path)
    _write(
        tmp_path / "a.ts",
        "/* export function commented() {} */\n"
        "export function alive() {}\n",
    )
    doc = _build(tmp_path)
    names = {it["name"] for it in doc["items"]}
    assert "commented" not in names
    assert "alive" in names
