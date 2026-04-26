"""Rust Layer 4 — assets + user-facing strings.

**Assets**: scan a conventional set of asset directories (`assets/`, `res/`,
`resources/`, `static/`) at the workspace root and at each crate root.
Classify by extension. No owning-system attribution for root-level asset
dirs (Rust has no concept of crate-owned `Assets/` like Unity); crate-owned
assets are tagged with that crate's name.

**Strings**: scan `.rs` files for string literals passed to a small allow-list
of common UI setter methods (`.text(`, `.title(`, `.label(`, `.placeholder(`,
`.tooltip(`, `.button(`). This deliberately **excludes** `println!`, `format!`,
logging macros, and generic literals — those are dev output or too
low-signal. Bias: high precision, low recall. Agents that need fuller
coverage can extend the pattern list per-project.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Tuple

from codeatlas import SCHEMA_VERSION
from codeatlas.stacks._asset_common import classify, safe_size


ASSET_DIRS = ("assets", "res", "resources", "static")
SKIP_DIRS = {"target", ".git", "node_modules", ".cargo", ".codeatlas", ".mercator", ".codemap"}

# UI setter methods that conventionally take a user-facing string.
# Matched as `.<ident>(` followed by a string literal. Extremely conservative.
UI_SETTER_RE = re.compile(
    r'\.(text|title|label|placeholder|tooltip|button|heading|caption|hint|message|description)\s*\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
)


def _crate_roots(project_root: Path) -> List[Tuple[str, Path]]:
    """Return (crate_name, crate_root) for every Cargo.toml in the tree.

    Stops descending into `target/` and VCS dirs. Name is parsed by a tiny
    regex on `[package] name = "..."`; if missing, use the directory name.
    Kept self-contained so asset scanning doesn't require cargo on PATH.
    """
    out: List[Tuple[str, Path]] = []
    name_re = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.MULTILINE)
    for cargo in project_root.rglob("Cargo.toml"):
        if any(part in SKIP_DIRS for part in cargo.relative_to(project_root).parts):
            continue
        try:
            text = cargo.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Only match under a [package] section. Quick heuristic: slice from
        # the first [package] header to the next [section] header or EOF.
        if "[package]" in text:
            start = text.index("[package]")
            rest = text[start:]
            end = rest.find("\n[", 1)
            section = rest if end == -1 else rest[:end]
            m = name_re.search(section)
            name = m.group(1) if m else cargo.parent.name
        else:
            # A pure workspace Cargo.toml has no [package]; skip.
            continue
        out.append((name, cargo.parent))
    return out


def _walk_asset_dir(base: Path, project_root: Path,
                    owning_system: Optional[str]) -> List[dict]:
    assets: List[dict] = []
    if not base.is_dir():
        return assets
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(project_root).parts):
            continue
        kind = classify(p)
        if kind is None:
            continue
        rel = PurePath(str(p.relative_to(project_root))).as_posix()
        entry: dict = {
            "path": rel,
            "kind": kind,
            "size_bytes": safe_size(p),
        }
        if owning_system:
            entry["owning_system"] = owning_system
        assets.append(entry)
    return assets


def build_assets(project_root: Path) -> dict:
    seen: Dict[str, dict] = {}

    # Root-level conventional dirs (no owning system).
    for d in ASSET_DIRS:
        for e in _walk_asset_dir(project_root / d, project_root, None):
            seen.setdefault(e["path"], e)

    # Per-crate conventional dirs.
    for crate_name, crate_root in _crate_roots(project_root):
        if crate_root == project_root:
            continue
        for d in ASSET_DIRS:
            for e in _walk_asset_dir(crate_root / d, project_root, crate_name):
                # If already captured at root level, don't shadow with the
                # crate attribution — first write wins (root is more general).
                seen.setdefault(e["path"], e)

    assets = sorted(seen.values(), key=lambda a: a["path"])
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "assets",
        "stack": "rust",
        "source_tool": "rust_asset_dir_walk",
        "source_tool_note": (
            "Walks assets/, res/, resources/, static/ at the workspace root "
            "and at each crate root. Classified by file extension. "
            "Assets embedded via include_bytes!/include_str!() outside these "
            "dirs are not enumerated."
        ),
        "assets": assets,
    }


def _scan_rs_strings(path: Path, project_root: Path) -> List[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    results: List[dict] = []
    rel = PurePath(str(path.relative_to(project_root))).as_posix()
    # Walk line by line so we can emit line numbers cheaply.
    for i, line in enumerate(text.splitlines(), start=1):
        # Skip comments quickly (approximate — good enough for allow-list match).
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for m in UI_SETTER_RE.finditer(line):
            text_val = m.group(2)
            # Drop trivially empty / single-char / format-placeholder-only.
            if not text_val or text_val.strip() in ("", "{}", "{:?}"):
                continue
            results.append({
                "key": None,
                "text": text_val,
                "file": rel,
                "line": i,
                "kind": "literal",
                "via": f".{m.group(1)}(",
            })
    return results


def build_strings(project_root: Path) -> dict:
    strings: List[dict] = []
    for rs in project_root.rglob("*.rs"):
        parts = rs.relative_to(project_root).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if any(p in ("tests", "examples", "benches") for p in parts):
            continue
        strings.extend(_scan_rs_strings(rs, project_root))
    strings.sort(key=lambda s: (s["file"], s["line"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "strings",
        "stack": "rust",
        "source_tool": "rust_ui_setter_scan",
        "source_tool_note": (
            "Scans .rs files for string literals passed to an allow-list of "
            "UI setter methods (.text/.title/.label/.placeholder/.tooltip/"
            ".button/.heading/.caption/.hint/.message/.description). "
            "High precision / low recall by design; println!/format!/log "
            "macros and generic literals are intentionally excluded."
        ),
        "strings": strings,
    }
