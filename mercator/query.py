"""Query surface for agents — project-aware.

Every function returns a small, typed JSON slice. With nested storage
(`.mercator/projects/<id>/...`), a query needs to know which project to
read. The default rule is gentle: if there's exactly one project in the
repo, use it; if there are multiple, the caller must pass `project_id`
or get an error listing the choices.

Agents should prefer these JSON queries over reading `.mercator/**/*.md`:
the JSON is smaller, typed, and scoped to the question.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Set, Union

from mercator import SCHEMA_VERSION, paths, boundaries as boundaries_mod
from mercator import projects as projects_mod
from mercator.stacks import rust as rust_stack


# ---------------------------------------------------------------------------
# Project resolution
# ---------------------------------------------------------------------------

def resolve_project(repo_root: Path, project_id: Optional[str] = None) -> dict:
    """Pick the project this query targets. Raises ValueError if ambiguous."""
    repo_storage = paths.mercator_dir(repo_root)
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        # No projects.json yet — try detecting on the fly so unrefreshed
        # repos still work for queries that touch only systems.json.
        projects_doc = projects_mod.detect_projects(repo_root)
    candidates = projects_doc.get("projects") or []
    if not candidates:
        raise ValueError("no projects detected — run `mercator init` to bootstrap")
    if project_id:
        for p in candidates:
            if p["id"] == project_id:
                return p
        raise ValueError(
            f"unknown project '{project_id}'. Known: {[p['id'] for p in candidates]}"
        )
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        f"this repo has {len(candidates)} projects; pass --project <id>. "
        f"Choices: {[p['id'] for p in candidates]}"
    )


def _project_storage(repo_root: Path, project_id: Optional[str]) -> tuple[Path, dict]:
    proj = resolve_project(repo_root, project_id)
    repo_storage = paths.mercator_dir(repo_root)
    return paths.project_storage_dir(repo_storage, proj["id"]), proj


def _load_systems(repo_root: Path, project_id: Optional[str] = None) -> dict:
    storage, _proj = _project_storage(repo_root, project_id)
    p = storage / "systems.json"
    if not p.is_file():
        raise FileNotFoundError(
            f"systems.json not found for project '{_proj['id']}' — run `mercator refresh`"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _load_contract(repo_root: Path, system_name: str,
                   project_id: Optional[str] = None) -> Optional[dict]:
    storage, _proj = _project_storage(repo_root, project_id)
    p = storage / "contracts" / f"{system_name}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Repo-level queries
# ---------------------------------------------------------------------------

def projects(repo_root: Path) -> dict:
    """Return the repo-level projects manifest."""
    repo_storage = paths.mercator_dir(repo_root)
    doc = projects_mod.load_projects(repo_storage)
    if doc is None:
        doc = projects_mod.detect_projects(repo_root)
    return doc


def repo_edges(repo_root: Path) -> dict:
    """Return implicit cross-project edges (computed on-demand if missing)."""
    from mercator import repo_edges as repo_edges_mod
    repo_storage = paths.mercator_dir(repo_root)
    doc = repo_edges_mod.load_edges(repo_storage)
    if doc is None:
        doc = repo_edges_mod.compute_edges(repo_root)
    return doc


def repo_boundaries(repo_root: Path) -> dict:
    """Return repo-level (cross-project) DMZ rules + per-rule pass/fail."""
    from mercator import repo_boundaries as repo_bnd_mod
    from mercator import repo_edges as repo_edges_mod
    repo_storage = paths.mercator_dir(repo_root)
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        projects_doc = projects_mod.detect_projects(repo_root)
    edges_doc = repo_edges_mod.load_edges(repo_storage) or repo_edges_mod.compute_edges(repo_root)
    try:
        bnd_doc = repo_bnd_mod.load(repo_storage)
    except ValueError as exc:
        return {"query": "repo-boundaries", "error": str(exc)}
    if not bnd_doc:
        return {
            "query": "repo-boundaries", "configured": False,
            "note": "No repo-boundaries.json. Run `mercator boundaries init --repo` to scaffold one.",
            "rules": [], "violation_count": 0,
        }
    rules = repo_bnd_mod.summarise_rules(projects_doc, edges_doc, bnd_doc)
    violations = repo_bnd_mod.evaluate(projects_doc, edges_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "repo-boundaries", "configured": True,
        "rule_count": len(rules), "violation_count": len(violations),
        "blocking": repo_bnd_mod.has_blocking_violations(violations),
        "rules": rules,
    }


def repo_violations(repo_root: Path) -> dict:
    """Return cross-project violations only (the failing rules)."""
    from mercator import repo_boundaries as repo_bnd_mod
    from mercator import repo_edges as repo_edges_mod
    repo_storage = paths.mercator_dir(repo_root)
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        projects_doc = projects_mod.detect_projects(repo_root)
    edges_doc = repo_edges_mod.load_edges(repo_storage) or repo_edges_mod.compute_edges(repo_root)
    try:
        bnd_doc = repo_bnd_mod.load(repo_storage)
    except ValueError as exc:
        return {"query": "repo-violations", "error": str(exc)}
    if not bnd_doc:
        return {"query": "repo-violations", "configured": False,
                "violation_count": 0, "violations": []}
    vs = repo_bnd_mod.evaluate(projects_doc, edges_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "repo-violations", "configured": True,
        "violation_count": len(vs),
        "blocking": repo_bnd_mod.has_blocking_violations(vs),
        "violations": vs,
    }


# ---------------------------------------------------------------------------
# Per-project queries
# ---------------------------------------------------------------------------

def systems(repo_root: Path, project_id: Optional[str] = None) -> dict:
    return _load_systems(repo_root, project_id)


def deps(repo_root: Path, target: str, project_id: Optional[str] = None) -> dict:
    doc = _load_systems(repo_root, project_id)
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
        "query": "deps", "target": target, "found": True,
        "stack": doc.get("stack"),
        "depends_on": depends_on, "depended_by": depended_by,
    }


def contract(repo_root: Path, system_name: str,
             project_id: Optional[str] = None) -> dict:
    doc = _load_contract(repo_root, system_name, project_id)
    if doc is None:
        return {
            "query": "contract", "system": system_name, "found": False,
            "note": "No contract file. Either the system doesn't exist, or Layer 2 isn't implemented for this stack.",
        }
    return doc


def symbol(repo_root: Path, name: str,
           kinds: Union[str, Set[str]] = "any",
           project_id: Optional[str] = None) -> dict:
    sys_doc = _load_systems(repo_root, project_id)
    stack = sys_doc.get("stack", "")
    proj = resolve_project(repo_root, project_id)
    project_dir = (repo_root / proj["root"]).resolve()
    if stack == "rust":
        matches = rust_stack.find_symbol(project_dir, sys_doc, name, kinds)
        source_tool = "rust_pub_scan (def-lookup)"
        source_tool_note = (
            "Definition lookup only — no references/callers. For call-site resolution "
            "install rust-analyzer and use its LSP (not yet wired into this CLI)."
        )
    elif stack == "python":
        from mercator.stacks import python as python_stack
        matches = python_stack.find_symbol(project_dir, sys_doc, name, kinds)
        source_tool = "python_ast_scan (def-lookup)"
        source_tool_note = (
            "Definition lookup only — no references/callers. Walks every .py file "
            "owned by a system (top-level def/class/const + one level into class "
            "bodies for methods). Methods are surfaced under their bare name, so "
            "`symbol foo` may match both a top-level `foo()` and `Bar.foo()`; "
            "disambiguate via the `system` and `file` fields on each match. "
            "Underscore-prefixed names are included (Python convention, not "
            "enforcement). For real call-site resolution use a language server."
        )
    else:
        return {
            "query": "symbol", "name": name, "stack": stack,
            "not_implemented": True,
            "note": f"Layer 3 symbol lookup not yet implemented for stack '{stack}'.",
        }
    query_kind = kinds if isinstance(kinds, str) else ",".join(sorted(kinds))
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": "symbols",
        "query": {"name": name, "kind": query_kind},
        "source_tool": source_tool,
        "source_tool_note": source_tool_note,
        "matches": matches,
        "match_count": len(matches),
    }


def touches(repo_root: Path, file_path: str,
            project_id: Optional[str] = None) -> dict:
    """Answer 'which system does this file belong to?' for an arbitrary path.

    Without `project_id` and with multiple projects in the repo, we search
    all projects and return the first match (project + system). With a
    project_id, we constrain to that project's systems.
    """
    repo_storage = paths.mercator_dir(repo_root)
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        projects_doc = projects_mod.detect_projects(repo_root)

    p = Path(file_path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(repo_root.resolve())
        except ValueError:
            return {"query": "touches", "file": file_path, "found": False,
                    "note": "file is outside repo root"}
    rel_repo = p.as_posix()

    candidates = projects_doc.get("projects") or []
    if project_id:
        candidates = [p for p in candidates if p["id"] == project_id]

    for proj in candidates:
        proj_root = proj["root"]
        if proj_root in (".", ""):
            rel = rel_repo
        elif rel_repo == proj_root or rel_repo.startswith(proj_root + "/"):
            rel = rel_repo[len(proj_root) + 1:] if rel_repo.startswith(proj_root + "/") else ""
        else:
            continue
        try:
            sys_doc = _load_systems(repo_root, proj["id"])
        except (FileNotFoundError, ValueError):
            continue
        stack = sys_doc.get("stack", "")
        best, best_depth = None, -1

        if stack == "rust":
            for s in sys_doc["systems"]:
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
            for s in sys_doc["systems"]:
                scope = s.get("scope_dir", "")
                if not scope:
                    continue
                if rel == s.get("manifest_path") or rel == scope or rel.startswith(scope + "/"):
                    depth = scope.count("/")
                    if depth > best_depth:
                        best = {"system": s["name"], "scope_dir": scope}
                        best_depth = depth
        elif stack == "dart":
            for s in sys_doc["systems"]:
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
        elif stack == "python":
            for s in sys_doc["systems"]:
                scope = s.get("scope_dir", "")
                if not scope:
                    continue
                if rel == s.get("manifest_path") or rel == scope or rel.startswith(scope + "/"):
                    depth = scope.count("/")
                    if depth > best_depth:
                        best = {"system": s["name"], "scope_dir": scope}
                        best_depth = depth

        if best is not None:
            return {
                "query": "touches", "file": rel_repo, "stack": stack,
                "found": True, "project": proj["id"], **best,
            }

    return {"query": "touches", "file": rel_repo, "found": False,
            "note": "file is not within any known system's scope"}


def system(repo_root: Path, name: str,
           project_id: Optional[str] = None) -> dict:
    sys_doc = _load_systems(repo_root, project_id)
    entry = next((s for s in sys_doc["systems"] if s["name"] == name), None)
    if entry is None:
        return {"query": "system", "name": name, "found": False,
                "known": sorted({s["name"] for s in sys_doc["systems"]})}

    deps_info = deps(repo_root, name, project_id)
    contract_doc = _load_contract(repo_root, name, project_id)

    return {
        "query": "system", "name": name, "found": True,
        "stack": sys_doc.get("stack"),
        "entry": entry,
        "depends_on": deps_info["depends_on"],
        "depended_by": deps_info["depended_by"],
        "contract": contract_doc,
    }


def boundaries(repo_root: Path, project_id: Optional[str] = None) -> dict:
    storage, _proj = _project_storage(repo_root, project_id)
    sys_doc = _load_systems(repo_root, project_id)
    try:
        bnd_doc = boundaries_mod.load_path(storage / "boundaries.json")
    except ValueError as exc:
        return {"query": "boundaries", "error": str(exc)}
    if not bnd_doc:
        return {
            "query": "boundaries", "configured": False,
            "note": "No boundaries.json found. Author one to declare forbidden system-to-system edges (DMZs).",
            "rules": [], "violation_count": 0,
        }
    rules = boundaries_mod.summarise_rules(sys_doc, bnd_doc)
    violations = boundaries_mod.evaluate(sys_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "boundaries", "configured": True,
        "rule_count": len(rules), "violation_count": len(violations),
        "blocking": boundaries_mod.has_blocking_violations(violations),
        "rules": rules,
    }


def violations(repo_root: Path, project_id: Optional[str] = None) -> dict:
    storage, _proj = _project_storage(repo_root, project_id)
    sys_doc = _load_systems(repo_root, project_id)
    try:
        bnd_doc = boundaries_mod.load_path(storage / "boundaries.json")
    except ValueError as exc:
        return {"query": "violations", "error": str(exc)}
    if not bnd_doc:
        return {
            "query": "violations", "configured": False,
            "violation_count": 0, "violations": [],
        }
    vs = boundaries_mod.evaluate(sys_doc, bnd_doc)
    return {
        "schema_version": SCHEMA_VERSION,
        "query": "violations", "configured": True,
        "violation_count": len(vs),
        "blocking": boundaries_mod.has_blocking_violations(vs),
        "violations": vs,
    }
