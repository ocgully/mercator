"""Dart/Flutter stack — Layer 1 via `pubspec.yaml` walk.

Monorepos are common in the Dart ecosystem (melos, pub workspaces). We walk
the tree for every `pubspec.yaml` and treat each one as a system. Deps come
from the top-level `dependencies:` + `dev_dependencies:` + `dependency_overrides:`
blocks.

We parse YAML as a minimal subset — no PyYAML dependency — since we only need
top-level keys and nested map keys under a handful of known block names.
This is sufficient for 99% of pubspec.yaml files in the wild; unusual YAML
gymnastics (flow-style, anchors) are noted in the tool-note.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePath
from typing import List, Optional

from mercator import SCHEMA_VERSION


SKIP_DIRS = {".dart_tool", "build", ".pub-cache", "node_modules", ".git"}


def _find_pubspecs(project_root: Path) -> List[Path]:
    results: List[Path] = []
    # Always include the root pubspec if present.
    root_pub = project_root / "pubspec.yaml"
    if root_pub.is_file():
        results.append(root_pub)
    # Walk for nested pubspecs, skipping generated/vendored dirs.
    def walk(d: Path):
        for entry in d.iterdir():
            if entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                walk(entry)
            elif entry.name == "pubspec.yaml" and entry != root_pub:
                results.append(entry)
    try:
        walk(project_root)
    except (PermissionError, OSError):
        pass
    results = sorted(set(results))
    return results


def _parse_pubspec(text: str) -> dict:
    """Parse the subset we need: top-level scalar keys + dependency-block keys.

    Returns {"name": str, "version": str, "dependencies": [names],
             "dev_dependencies": [names], "dependency_overrides": [names]}.
    """
    out = {"name": "", "version": "", "dependencies": [], "dev_dependencies": [], "dependency_overrides": []}
    current_block: Optional[str] = None
    block_indent = -1

    for raw in text.splitlines():
        # Drop comments.
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        # Top-level scalar?
        m_top = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if m_top and (line[0] != " " and line[0] != "\t"):
            key, val = m_top.group(1), m_top.group(2).strip()
            if key in ("dependencies", "dev_dependencies", "dependency_overrides"):
                current_block = key
                block_indent = -1
                continue
            else:
                current_block = None
            if key == "name":
                out["name"] = val
            elif key == "version":
                out["version"] = val
            continue

        # Nested under a dependency block.
        if current_block is None:
            continue
        m_item = re.match(r"^(\s+)([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if not m_item:
            continue
        indent = len(m_item.group(1))
        if block_indent < 0:
            block_indent = indent
        if indent != block_indent:
            # Nested (e.g. path:/version: sub-keys of a single dep) — skip.
            continue
        out[current_block].append(m_item.group(2))

    return out


def build_systems(project_root: Path) -> dict:
    pubspecs = _find_pubspecs(project_root)
    systems: List[dict] = []
    for p in pubspecs:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_pubspec(text)
        name = parsed["name"] or p.parent.name
        rel_manifest = PurePath(str(p.relative_to(project_root))).as_posix()
        rel_scope = PurePath(str(p.parent.relative_to(project_root))).as_posix() or "."

        deps = []
        for n in parsed["dependencies"]:
            deps.append({"name": n, "kind": None, "optional": False})
        for n in parsed["dev_dependencies"]:
            deps.append({"name": n, "kind": "dev", "optional": False})
        for n in parsed["dependency_overrides"]:
            deps.append({"name": n, "kind": "override", "optional": False})

        systems.append({
            "name": name,
            "version": parsed["version"] or None,
            "manifest_path": rel_manifest,
            "scope_dir": rel_scope,
            "kind": ["pubspec"],
            "dependencies": deps,
        })

    systems.sort(key=lambda s: s["name"])

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "systems",
        "stack": "dart",
        "workspace_root": ".",
        "systems": systems,
    }
