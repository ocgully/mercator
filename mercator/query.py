"""Query surface for agents. Every function returns a small, typed JSON slice.

Agents should prefer these over reading `.mercator/**/*.md`: the JSON is
smaller, typed, and scoped to the question. The .md views exist for humans
browsing the repo, not for agent consumption.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Set, Union

from mercator import SCHEMA_VERSION, paths, boundaries as boundaries_mod
from mercator.stacks import rust as rust_stack


def _load_systems(project_root: Path) -> dict:
    p = paths.mercator_dir(project_root) / "systems.json"
    if not p.is_file():
        raise FileNotFoundError("mercator systems.json not found — run `mercator init` first")
    return json.loads(p.read_text(encoding="utf-8"))


def _load_contract(project_root: Path, system_name: str) -> Optional[dict]:
    p = paths.mercator_dir(project_root) / "contracts" / f"{system_name}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Query: systems
# ---------------------------------------------------------------------------

def systems(project_root: Path) -> dict:
    """Full Layer 1 slice. Small — typically 10–200 KB."""
    return _load_systems(project_root)


# ---------------------------------------------------------------------------
# Query: deps
# ---------------------------------------------------------------------------

def deps(project_root: Path, target: str) -> dict:
    doc = _load_systems(project_root)
    names = {s["name"] for s in doc["systems"]}
    if target not in names:
        return {"query": "deps", "target": target, "found": False, "known": sorted(names)}
    target_sys = next(s for s in doc["systems"] if s["name"] == target)
    depends_on = sorted(
        {d["name"] for d in target_sys.get("dependencies", []) if d["name"] in names}
    )
    depended_by = sorted(
        s["name"] for s in doc["systems"]
        if target in {d["name"] for d in s.get("dependencies", [])}
    )
    return {
        "query": "deps",
        "target": target,
        "found": True,
        "stack": doc.get("stack"),
        "depends_on": depends_on,
        "depended_by": depended_by,
    }


# ---------------------------------------------------------------------------
# Query: contract
# ---------------------------------------------------------------------------

def contract(project_root: Path, system_name: str) -> dict:
    doc = _load_contract(project_root, system_name)
    if doc is None:
        return {
            "query": "contract",
            "system": system_name,
            "found": False,
            "note": "No contract file. Either the system doesn't exist, or Layer 2 isn't implemented for this stack.",
        }
    return doc


# ---------------------------------------------------------------------------
# Query: symbol
# ---------------------------------------------------------------------------

def symbol(
    project_root: Path,
    name: str,
    kinds: Union[str, Set[str]] = "any",
) -> dict:
    sys_doc = _load_systems(project_root)
    stack = sys_doc.get("stack", "")
    if stack != "rust":
        return {
            "query": "symbol",
            "name": name,
            "stack": stack,
            "not_implemented": True,
            "note": f"Layer 3 symbol lookup not yet implemented for stack '{stack}'.",
        }
    matches = rust_stack.find_symbol(project_root, sys_doc, name, kinds)
    query_kind = kinds if isinstance(kinds, str) else ",".join(sorted(kinds))
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "symbols",
        "query": {"name": name, "kind": query_kind},
        "source_tool": "rust_pub_scan (def-lookup)",
        "source_tool_note": (
            "Definition lookup only — no references/callers. For call-site resolution "
            "install rust-analyzer and use its LSP (not yet wired into this CLI)."
        ),
        "matches": matches,
        "match_count": len(matches),
    }


# ---------------------------------------------------------------------------
# Query: touches — which system owns this file path?
# ---------------------------------------------------------------------------

def touches(project_root: Path, file_path: str) -> dict:
    """Answer 'which system does this file belong to?' for an arbitrary path.

    Input is a path relative to the project root (or absolute — we normalise).
    """
    doc = _load_systems(project_root)
    stack = doc.get("stack", "")

    # Normalise to relative POSIX path.
    p = Path(file_path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(project_root.resolve())
        except ValueError:
            return {"query": "touches", "file": file_path, "found": False, "note": "file is outside project root"}
    rel = p.as_posix()

    best: Optional[dict] = None
    best_depth = -1

    if stack == "rust":
        for s in doc["systems"]:
            manifest = s.get("manifest_path", "")
            scope = manifest.rsplit("/", 1)[0] if "/" in manifest else ""
            if not scope:
                continue
            if rel == manifest or rel.startswith(scope + "/"):
                depth = scope.count("/")
                if depth > best_depth:
                    best = {"system": s["name"], "scope_dir": scope}
                    best_depth = depth
    elif stack == "unity":
        for s in doc["systems"]:
            scope = s.get("scope_dir", "")
            if not scope:
                continue
            if rel == s.get("manifest_path") or (scope and (rel == scope or rel.startswith(scope + "/"))):
                depth = scope.count("/")
                if depth > best_depth:
                    best = {"system": s["name"], "scope_dir": scope}
                    best_depth = depth
    elif stack == "dart":
        for s in doc["systems"]:
            scope = s.get("scope_dir", "")
            if scope == ".":
                if best is None:
                    best = {"system": s["name"], "scope_dir": scope}
                    best_depth = 0
                continue
            if rel == s.get("manifest_path") or rel.startswith(scope + "/"):
                depth = scope.count("/")
                if depth > best_depth:
                    best = {"system": s["name"], "scope_dir": scope}
                    best_depth = depth

    if best is None:
        return {"query": "touches", "file": rel, "stack": stack, "found": False,
                "note": "file is not within any known system's scope"}
    return {"query": "touches", "file": rel, "stack": stack, "found": True, **best}


# ---------------------------------------------------------------------------
# Query: system — composite Layer 1 + 2 slice for one system
# ---------------------------------------------------------------------------

def system(project_root: Path, name: str) -> dict:
    """Everything an agent needs to reason about one system.

    Includes its Layer 1 entry (metadata + deps), its Layer 2 contract if
    available, and forward/reverse dep edges. Bounded small — typically
    ≤ 100 KB even for big crates.
    """
    sys_doc = _load_systems(project_root)
    entry = next((s for s in sys_doc["systems"] if s["name"] == name), None)
    if entry is None:
        return {"query": "system", "name": name, "found": False,
                "known": sorted({s["name"] for s in sys_doc["systems"]})}

    deps_info = deps(project_root, name)
    contract_doc = _load_contract(project_root, name)

    return {
        "query": "system",
        "name": name,
        "found": True,
        "stack": sys_doc.get("stack"),
        "entry": entry,
        "depends_on": deps_info["depends_on"],
        "depended_by": deps_info["depended_by"],
        "contract": contract_doc,  # None if Layer 2 isn't implemented for this stack
    }


# ---------------------------------------------------------------------------
# Query: boundaries + violations — forbidden-edge (DMZ) rules
# ---------------------------------------------------------------------------

def boundaries(project_root: Path) -> dict:
    sys_doc = _load_systems(project_root)
    try:
        bnd_doc = boundaries_mod.load(project_root)
    except ValueError as exc:
        return {"query": "boundaries", "error": str(exc)}
    if not bnd_doc:
        return {
            "query": "boundaries",
            "configured": False,
            "note": "No boundaries.json found. Author one to declare forbidden system-to-system edges (DMZs).",
            "rules": [],
            "violation_count": 0,
        }
    rules = boundaries_mod.summarise_rules(sys_doc, bnd_doc)
    violations = boundaries_mod.evaluate(sys_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "boundaries",
        "configured": True,
        "rule_count": len(rules),
        "violation_count": len(violations),
        "blocking": boundaries_mod.has_blocking_violations(violations),
        "rules": rules,
    }


def violations(project_root: Path) -> dict:
    sys_doc = _load_systems(project_root)
    try:
        bnd_doc = boundaries_mod.load(project_root)
    except ValueError as exc:
        return {"query": "violations", "error": str(exc)}
    if not bnd_doc:
        return {
            "query": "violations",
            "configured": False,
            "violation_count": 0,
            "violations": [],
        }
    vs = boundaries_mod.evaluate(sys_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "violations",
        "configured": True,
        "violation_count": len(vs),
        "blocking": boundaries_mod.has_blocking_violations(vs),
        "violations": vs,
    }
