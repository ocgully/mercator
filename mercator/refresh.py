"""Per-project refresh — drives Layer 1+2+4 generation across all detected projects.

Storage layout (always nested):

    .mercator/
    ├── projects.json                 # detected projects (this version)
    ├── meta.json                     # repo-level: schema, generated_at, git HEAD
    ├── atlas.html                    # interactive code atlas (entry point)
    └── projects/
        └── <project-id>/
            ├── meta.json             # per-project meta
            ├── systems.json          # Layer 1
            ├── systems.md            # rendered for humans
            ├── contracts/            # Layer 2 per system
            ├── boundaries.json       # user-authored DMZ rules (optional)
            ├── boundaries.md         # rendered
            ├── graph.md              # mermaid dep graph (humans)
            ├── assets.json           # Layer 4
            └── strings.json          # Layer 4

A repo with one project still uses the nested layout — the atlas decides
how to render based on `project_count`. Existing flat-layout repos
(0.4.x or earlier) auto-migrate on first refresh: regenerable artefacts
are deleted, user-authored `boundaries.json` is preserved by relocating
it under the auto-detected project's slot.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Set

from mercator import meta, paths
from mercator import boundaries as boundaries_mod
from mercator import projects as projects_mod
from mercator import repo_edges as repo_edges_mod
from mercator.detect import detect
from mercator.render import systems_md, contract_md, graph_md, boundaries_md, write_atlas
from mercator.stacks import rust, unity, dart, ts, python
from mercator.stacks import rust_assets, unity_assets, dart_assets

from mercator import SCHEMA_VERSION


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-stack Layer 1+2 dispatch
# ---------------------------------------------------------------------------

def _refresh_rust(project_dir: Path, project_storage: Path, affected: Optional[Set[str]]):
    systems_doc = rust.build_systems(project_dir)
    _write_json(project_storage / "systems.json", systems_doc)
    (project_storage / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")

    contracts_dir = project_storage / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    written = 0
    for s in systems_doc["systems"]:
        name = s["name"]
        if affected is not None and name not in affected:
            continue
        manifest_rel = s["manifest_path"]
        doc = rust.build_contract(project_dir, name, manifest_rel)
        _write_json(contracts_dir / f"{name}.json", doc)
        (contracts_dir / f"{name}.md").write_text(contract_md.render(doc), encoding="utf-8")
        written += 1
    return systems_doc, written


def _refresh_unity(project_dir: Path, project_storage: Path, affected: Optional[Set[str]]):
    systems_doc = unity.build_systems(project_dir)
    _write_json(project_storage / "systems.json", systems_doc)
    (project_storage / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")
    return systems_doc, 0


def _refresh_dart(project_dir: Path, project_storage: Path, affected: Optional[Set[str]]):
    systems_doc = dart.build_systems(project_dir)
    _write_json(project_storage / "systems.json", systems_doc)
    (project_storage / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")
    return systems_doc, 0


def _refresh_ts(project_dir: Path, project_storage: Path, affected: Optional[Set[str]]):
    systems_doc = ts.build_systems(project_dir)
    _write_json(project_storage / "systems.json", systems_doc)
    (project_storage / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")

    contracts_dir = project_storage / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    written = 0
    for s in systems_doc["systems"]:
        name = s["name"]
        if affected is not None and name not in affected:
            continue
        manifest_rel = s.get("manifest_path")
        if not manifest_rel:
            continue
        # System names may contain '/' (scoped packages like @scope/foo,
        # or path-derived tsconfig-ref names). Sanitise for the filename.
        safe_name = name.replace("/", "__").replace("\\", "__")
        try:
            doc = ts.build_contract(project_dir, name, manifest_rel)
        except (FileNotFoundError, ValueError):
            continue
        _write_json(contracts_dir / f"{safe_name}.json", doc)
        (contracts_dir / f"{safe_name}.md").write_text(
            contract_md.render(doc), encoding="utf-8"
        )
        written += 1
    return systems_doc, written


def _refresh_python(project_dir: Path, project_storage: Path, affected: Optional[Set[str]]):
    systems_doc = python.build_systems(project_dir)
    _write_json(project_storage / "systems.json", systems_doc)
    (project_storage / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")

    contracts_dir = project_storage / "contracts"
    contracts_dir.mkdir(exist_ok=True)
    written = 0
    for s in systems_doc["systems"]:
        name = s["name"]
        if affected is not None and name not in affected:
            continue
        doc = python.build_contract(project_dir, name, s["manifest_path"])
        _write_json(contracts_dir / f"{name}.json", doc)
        (contracts_dir / f"{name}.md").write_text(contract_md.render(doc), encoding="utf-8")
        written += 1
    return systems_doc, written


# ---------------------------------------------------------------------------
# Layer 4 — assets + strings
# ---------------------------------------------------------------------------

def _empty_layer4(stack: str, layer: str) -> dict:
    key = "assets" if layer == "assets" else "strings"
    return {
        "schema_version": SCHEMA_VERSION,
        "layer": layer,
        "stack": stack,
        "status": "not_implemented",
        "note": (
            f"Layer 4 {layer} enumeration is not implemented for stack '{stack}'. "
            "Returning an empty list so downstream consumers can proceed safely."
        ),
        key: [],
    }


def _refresh_layer4(stack: str, project_dir: Path, project_storage: Path) -> None:
    assets_path = project_storage / "assets.json"
    strings_path = project_storage / "strings.json"

    if stack == "rust":
        mod = rust_assets
    elif stack == "unity":
        mod = unity_assets
    elif stack == "dart":
        mod = dart_assets
    else:
        _write_json(assets_path, _empty_layer4(stack, "assets"))
        _write_json(strings_path, _empty_layer4(stack, "strings"))
        return

    try:
        _write_json(assets_path, mod.build_assets(project_dir))
    except Exception as exc:  # noqa: BLE001
        _write_json(assets_path, {
            "schema_version": SCHEMA_VERSION, "layer": "assets",
            "stack": stack, "status": "error", "error": str(exc), "assets": [],
        })
    try:
        _write_json(strings_path, mod.build_strings(project_dir))
    except Exception as exc:  # noqa: BLE001
        _write_json(strings_path, {
            "schema_version": SCHEMA_VERSION, "layer": "strings",
            "stack": stack, "status": "error", "error": str(exc), "strings": [],
        })


# ---------------------------------------------------------------------------
# Single-project refresh
# ---------------------------------------------------------------------------

_DISPATCH = {
    "rust":   _refresh_rust,
    "unity":  _refresh_unity,
    "dart":   _refresh_dart,
    "ts":     _refresh_ts,
    "python": _refresh_python,
}


def refresh_one_project(
    repo_root: Path,
    repo_storage: Path,
    project: dict,
    *,
    affected: Optional[Set[str]] = None,
) -> dict:
    """Refresh a single project. Returns a per-project result dict."""
    project_dir = (repo_root / project["root"]).resolve()
    project_storage = paths.ensure_project_storage_dir(repo_storage, project["id"])
    stack = project["stack"]

    fn = _DISPATCH.get(stack)
    if fn is None:
        # Stack detected but not yet implemented (go, etc.). Write a stub.
        stub = {
            "schema_version": SCHEMA_VERSION,
            "layer": "systems",
            "stack": stack,
            "status": "not_implemented",
            "note": f"stack '{stack}' has no Layer 1 implementation in this version",
            "systems": [],
        }
        _write_json(project_storage / "systems.json", stub)
        return {
            "id": project["id"], "stack": stack, "status": "not_implemented",
            "systems_count": 0, "contracts_written": 0,
        }

    systems_doc, contract_count = fn(project_dir, project_storage, affected)

    # Layer 4 only on full refresh.
    if affected is None:
        _refresh_layer4(stack, project_dir, project_storage)

    # Boundaries-driven visual outputs (per-project).
    try:
        bnd_doc = boundaries_mod.load_path(project_storage / "boundaries.json")
    except ValueError:
        bnd_doc = {}
    (project_storage / "graph.md").write_text(graph_md.render(systems_doc, bnd_doc), encoding="utf-8")
    (project_storage / "boundaries.md").write_text(boundaries_md.render(systems_doc, bnd_doc), encoding="utf-8")

    # Per-project meta.
    meta.write_project(repo_root, project_storage, stack)

    # Counts.
    assets_count = 0
    strings_count = 0
    try:
        with (project_storage / "assets.json").open("r", encoding="utf-8") as f:
            assets_count = len(json.load(f).get("assets") or [])
    except (OSError, ValueError):
        pass
    try:
        with (project_storage / "strings.json").open("r", encoding="utf-8") as f:
            strings_count = len(json.load(f).get("strings") or [])
    except (OSError, ValueError):
        pass

    return {
        "id": project["id"],
        "stack": stack,
        "systems_count": len(systems_doc.get("systems", [])),
        "contracts_written": contract_count,
        "assets_count": assets_count,
        "strings_count": strings_count,
    }


# ---------------------------------------------------------------------------
# Legacy flat-layout migration
# ---------------------------------------------------------------------------

_REPO_LEVEL_FILES = {"projects", "projects.json", "meta.json", "atlas.html",
                     "atlas", "repo.toml", "README.md"}


def _migrate_flat_layout_if_present(
    repo_storage: Path, projects_doc: dict
) -> Optional[str]:
    """If the legacy flat layout exists, relocate it.

    Returns the project-id we migrated into, or None if no migration needed.

    Strategy: if `<repo_storage>/systems.json` exists and `<repo_storage>/projects/`
    does not, the user is on the old flat layout. We pick the first detected
    project (deterministic — projects.json sorts by category+root) and move
    *user-authored* files (boundaries.json) into its slot. Regen-able files
    are simply deleted; the upcoming refresh recreates them.
    """
    if not (repo_storage / "systems.json").is_file():
        return None
    if (repo_storage / "projects").is_dir():
        return None  # already migrated
    candidates = projects_doc.get("projects") or []
    if not candidates:
        return None
    target_id = candidates[0]["id"]
    target = paths.ensure_project_storage_dir(repo_storage, target_id)

    # Move user-authored boundaries.json (don't regen this — it's authored).
    src_bnd = repo_storage / "boundaries.json"
    if src_bnd.is_file():
        shutil.move(str(src_bnd), str(target / "boundaries.json"))

    # Delete regenerable artefacts at the repo level (refresh will recreate
    # them under the project slot).
    for name in ("systems.json", "systems.md", "graph.md", "boundaries.md",
                 "assets.json", "strings.json"):
        p = repo_storage / name
        if p.exists():
            p.unlink()
    for d in ("contracts", "symbols", "assets"):
        p = repo_storage / d
        if p.is_dir():
            shutil.rmtree(p)
    return target_id


# ---------------------------------------------------------------------------
# Repo-level refresh — top-level entry point
# ---------------------------------------------------------------------------

def refresh(
    repo_root: Path,
    *,
    project_id: Optional[str] = None,
    affected: Optional[Set[str]] = None,
) -> dict:
    """Refresh every project in the repo (or just one, with `project_id`)."""
    repo_storage = paths.ensure_mercator_dir(repo_root)

    # 1. Detect projects (always — fast, source of truth for the repo layout).
    projects_doc = projects_mod.write_projects(repo_root, repo_storage)

    # 2. Migrate flat layout if present (one-shot, idempotent).
    migrated_into = _migrate_flat_layout_if_present(repo_storage, projects_doc)

    # 3. Refresh each project.
    project_results: List[dict] = []
    targets: Iterable[dict] = projects_doc.get("projects") or []
    if project_id:
        targets = [p for p in targets if p["id"] == project_id]
        if not targets:
            raise ValueError(
                f"unknown --project '{project_id}'. "
                f"Known: {[p['id'] for p in projects_doc.get('projects') or []]}"
            )
    for proj in targets:
        try:
            project_results.append(
                refresh_one_project(repo_root, repo_storage, proj, affected=affected)
            )
        except RuntimeError as exc:
            project_results.append({
                "id": proj["id"], "stack": proj["stack"],
                "status": "error", "error": str(exc),
            })

    # 4. Cross-project edges (only meaningful when >1 project, but compute
    # always so the file exists with edge_count=0 for single-project repos).
    try:
        repo_edges_mod.write_edges(repo_root)
    except Exception:  # noqa: BLE001
        pass

    # 5. Repo-level meta.json.
    repo_stack = (
        projects_doc["projects"][0]["stack"]
        if projects_doc["project_count"] == 1
        else "multi-project"
    )
    meta.write(repo_root, repo_storage, repo_stack)

    # 6. Atlas.
    try:
        write_atlas(repo_root)
    except Exception:  # noqa: BLE001
        pass

    return {
        "stack": repo_stack,
        "project_count": projects_doc["project_count"],
        "project_results": project_results,
        "migrated_legacy_flat_into": migrated_into,
        # Aggregate counts across projects (atlas summary).
        "systems_count": sum(r.get("systems_count", 0) for r in project_results),
        "contracts_written": sum(r.get("contracts_written", 0) for r in project_results),
    }


# ---------------------------------------------------------------------------
# Incremental refresh — map changed files to (project, affected systems)
# ---------------------------------------------------------------------------

def files_to_affected_systems(repo_root: Path, changed_files: Iterable[str]) -> dict:
    """Map changed files to {project_id: set(system_names_to_regen)}.

    A repo with multiple projects sees changes scoped to whichever project
    owns the file. Returns an empty dict if no project is affected.
    """
    repo_storage = paths.mercator_dir(repo_root)
    projects_doc = projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        return {}

    out: dict = {}
    changed_paths = [Path(c).as_posix() for c in changed_files]
    projects = projects_doc.get("projects") or []

    for proj in projects:
        proj_root = proj["root"]
        # Files belonging to this project (path-prefix match).
        if proj_root in (".", ""):
            project_files = changed_paths
        else:
            prefix = proj_root.rstrip("/") + "/"
            project_files = [c for c in changed_paths if c == proj_root or c.startswith(prefix)]
        if not project_files:
            continue

        # Re-strip the project_root prefix from each file so we can pass
        # project-relative paths to the per-stack mapper.
        rel_files: List[str] = []
        for f in project_files:
            if proj_root in (".", ""):
                rel_files.append(f)
            else:
                rel_files.append(f[len(proj_root) + 1:] if f.startswith(proj_root + "/") else "")
        rel_files = [f for f in rel_files if f]

        # Load the project's systems.json so we can attribute files to systems.
        project_storage = paths.project_storage_dir(repo_storage, proj["id"])
        sys_path = project_storage / "systems.json"
        if not sys_path.is_file():
            # Refresh would generate it; for incremental, treat as full-project.
            out[proj["id"]] = None
            continue
        try:
            systems_doc = json.loads(sys_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out[proj["id"]] = None
            continue

        affected = _affected_for_stack(systems_doc, rel_files)
        out[proj["id"]] = affected
    return out


def _affected_for_stack(systems_doc: dict, changed_rel: List[str]) -> Set[str]:
    stack = systems_doc.get("stack", "")
    affected: Set[str] = set()

    if stack == "rust":
        for s in systems_doc["systems"]:
            manifest_rel = s.get("manifest_path", "")
            if not manifest_rel:
                continue
            crate_scope = manifest_rel.rsplit("/", 1)[0] if "/" in manifest_rel else ""
            for p in changed_rel:
                if p == manifest_rel or (crate_scope and p.startswith(crate_scope + "/")):
                    affected.add(s["name"])
                    break
    elif stack == "unity":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            for p in changed_rel:
                if p == s.get("manifest_path") or (scope and (p == scope or p.startswith(scope + "/"))):
                    affected.add(s["name"])
                    break
    elif stack == "dart":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            for p in changed_rel:
                if scope in (".", "") or p == s.get("manifest_path") or p.startswith(scope + "/"):
                    affected.add(s["name"])
                    break
    elif stack == "ts":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            manifest = s.get("manifest_path", "")
            for p in changed_rel:
                if scope in (".", "") or p == manifest or p.startswith(scope + "/"):
                    affected.add(s["name"])
                    break
    elif stack == "python":
        sys_by_depth = sorted(
            systems_doc["systems"],
            key=lambda s: (s.get("scope_dir") or "").count("/"),
            reverse=True,
        )
        for p in changed_rel:
            for s in sys_by_depth:
                scope = s.get("scope_dir", "")
                if not scope:
                    continue
                if p == s.get("manifest_path") or p == scope or p.startswith(scope + "/"):
                    affected.add(s["name"])
                    break
    return affected
