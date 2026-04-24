"""Unity stack — Layer 1 via `.asmdef` + `.cs` file walk.

A Unity "system" is an assembly boundary. Unity repos rarely commit `.csproj`
(the editor regenerates them), so we use the authoritative source: `.asmdef`
files. Each `.asmdef` declares an assembly name, its references, and lives
at the root of the directory subtree it owns. `.cs` files in that subtree
belong to the assembly unless shadowed by a deeper asmdef.

If no `.asmdef` files exist, we synthesise a single built-in system named
`Assembly-CSharp` (Unity's default) that owns every `.cs` file under `Assets/`.
This matches Unity's own behaviour: without asmdefs you get one giant
assembly.

Packages under `Packages/` with their own asmdefs (e.g. `Pcx.Runtime`,
`Pcx.Editor`) show up as additional systems — this is how Unity treats
embedded and local packages.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePath
from typing import Dict, List, Optional, Tuple

from mercator import SCHEMA_VERSION


def _strip_bom(text: str) -> str:
    return text.lstrip("﻿")


def _read_asmdef(path: Path) -> Optional[dict]:
    """Parse an asmdef JSON, tolerating BOM + comments."""
    try:
        text = _strip_bom(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        text = _strip_bom(path.read_text(encoding="utf-8", errors="replace"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_asmdefs(project_root: Path) -> List[Path]:
    # Unity asmdefs live under Assets/ and Packages/ (embedded packages).
    results: List[Path] = []
    for base in ("Assets", "Packages"):
        d = project_root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*.asmdef"):
            results.append(p)
    results.sort()
    return results


def _scope_owner(cs_file: Path, scope_roots: List[Tuple[str, Path]]) -> Optional[str]:
    """Pick the asmdef whose scope is the deepest ancestor of cs_file."""
    best: Optional[Tuple[int, str]] = None
    for name, root in scope_roots:
        try:
            cs_file.relative_to(root)
        except ValueError:
            continue
        depth = len(root.parts)
        if best is None or depth > best[0]:
            best = (depth, name)
    return best[1] if best else None


def build_systems(project_root: Path) -> dict:
    asmdefs = _find_asmdefs(project_root)

    systems: List[dict] = []
    scope_roots: List[Tuple[str, Path]] = []  # (assembly_name, scope_dir)
    name_to_idx: Dict[str, int] = {}

    for asmdef_path in asmdefs:
        data = _read_asmdef(asmdef_path)
        if data is None:
            continue
        name = data.get("name") or asmdef_path.stem
        references = data.get("references") or []
        include_platforms = data.get("includePlatforms") or []
        scope_dir = asmdef_path.parent

        # Strip "GUID:..." refs to bare names only (Unity uses both).
        clean_refs = []
        for r in references:
            if isinstance(r, str):
                # Unity supports either "AssemblyName" or "GUID:<hex>"
                clean_refs.append(r.split(":", 1)[-1] if r.startswith("GUID:") else r)

        rel_scope = PurePath(str(scope_dir.relative_to(project_root))).as_posix()
        rel_manifest = PurePath(str(asmdef_path.relative_to(project_root))).as_posix()
        systems.append({
            "name": name,
            "kind": ["asmdef"],
            "manifest_path": rel_manifest,
            "scope_dir": rel_scope,
            "include_platforms": include_platforms,
            "editor_only": include_platforms == ["Editor"],
            "cs_file_count": 0,  # filled below
            "dependencies": [
                {"name": r, "kind": None, "optional": False} for r in clean_refs
            ],
        })
        name_to_idx[name] = len(systems) - 1
        scope_roots.append((name, scope_dir))

    # Walk .cs files under Assets/ and Packages/ and attribute them to an owner.
    unassigned = 0
    for base in ("Assets", "Packages"):
        d = project_root / base
        if not d.is_dir():
            continue
        for cs in d.rglob("*.cs"):
            owner = _scope_owner(cs, scope_roots)
            if owner is None:
                unassigned += 1
                continue
            systems[name_to_idx[owner]]["cs_file_count"] += 1

    # If a project has unassigned .cs files under Assets/ with no asmdef
    # covering them, Unity puts them in Assembly-CSharp by default.
    if unassigned > 0:
        systems.append({
            "name": "Assembly-CSharp",
            "kind": ["unity-default"],
            "manifest_path": None,  # synthesised — no asmdef
            "scope_dir": "Assets",
            "include_platforms": [],
            "editor_only": False,
            "cs_file_count": unassigned,
            "dependencies": [],
            "synthetic": True,
            "note": "Unity's default assembly for Assets/.cs files not covered by any .asmdef.",
        })

    systems.sort(key=lambda s: s["name"])

    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "systems",
        "stack": "unity",
        "workspace_root": ".",
        "systems": systems,
    }
