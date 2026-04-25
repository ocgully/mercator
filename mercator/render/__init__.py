"""Deterministic rendered views. Humans browse these; agents use the CLI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from mercator import __version__ as _version, SCHEMA_VERSION as _schema
from mercator import paths as _paths
from mercator import boundaries as _boundaries_mod
from mercator import projects as _projects_mod
from mercator import repo_edges as _repo_edges_mod
from mercator.render import atlas as _atlas_html


def _read_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_project(repo_storage: Path, project: dict) -> dict:
    """Bundle every per-project artefact a renderer might need."""
    ps = _paths.project_storage_dir(repo_storage, project["id"])
    systems_doc = _read_json(ps / "systems.json") or {"systems": [], "stack": project.get("stack", "unknown")}
    meta_doc = _read_json(ps / "meta.json") or {}
    assets_doc = _read_json(ps / "assets.json")
    strings_doc = _read_json(ps / "strings.json")

    contracts: Dict[str, dict] = {}
    contracts_dir = ps / "contracts"
    if contracts_dir.is_dir():
        for cp in sorted(contracts_dir.glob("*.json")):
            try:
                contracts[cp.stem] = json.loads(cp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue

    try:
        bnd_doc = _boundaries_mod.load_path(ps / "boundaries.json") or {}
    except ValueError:
        bnd_doc = {}
    violations = (
        _boundaries_mod.evaluate(systems_doc, bnd_doc) if bnd_doc else []
    )

    return {
        "project": project,
        "systems": systems_doc,
        "contracts": contracts,
        "boundaries": bnd_doc,
        "violations": violations,
        "assets": assets_doc,
        "strings": strings_doc,
        "meta": meta_doc,
    }


def write_atlas(repo_root: Path) -> Path:
    """Write the entry-point atlas HTML.

    1-project repo: `atlas.html` is the project's full atlas (single file).
    Multi-project repo: `atlas.html` is the repo overview; per-project
    atlases live at `atlas/projects/<id>.html`.
    """
    repo_storage = _paths.mercator_dir(repo_root)
    repo_storage.mkdir(parents=True, exist_ok=True)
    projects_doc = _projects_mod.load_projects(repo_storage)
    if projects_doc is None:
        projects_doc = _projects_mod.detect_projects(repo_root)

    repo_meta = _read_json(repo_storage / "meta.json") or {}
    projects = projects_doc.get("projects") or []

    if len(projects) <= 1:
        # Single-project (or empty) repo — atlas.html is just the project's atlas.
        if projects:
            bundle = _read_project(repo_storage, projects[0])
        else:
            bundle = {
                "project": {"id": "(none)", "name": "(no project)", "stack": "unknown",
                            "root": ".", "category": "unknown", "tags": []},
                "systems": {"systems": [], "stack": "unknown"},
                "contracts": {}, "boundaries": {}, "violations": [],
                "assets": None, "strings": None, "meta": {},
            }
        html = _atlas_html.render_single_project(
            bundle=bundle,
            mercator_version=_version,
            schema_version=_schema,
            repo_meta=repo_meta,
            projects_doc=projects_doc,
        )
        out = repo_storage / "atlas.html"
        out.write_text(html, encoding="utf-8")
        return out

    # Multi-project repo: per-project pages + an index.
    per_project_dir = repo_storage / "atlas" / "projects"
    per_project_dir.mkdir(parents=True, exist_ok=True)
    bundles: List[dict] = []
    for proj in projects:
        bundle = _read_project(repo_storage, proj)
        bundles.append(bundle)
        html = _atlas_html.render_single_project(
            bundle=bundle,
            mercator_version=_version,
            schema_version=_schema,
            repo_meta=repo_meta,
            projects_doc=projects_doc,
            href_back="../../atlas.html",
        )
        (per_project_dir / f"{proj['id']}.html").write_text(html, encoding="utf-8")

    repo_edges_doc = _repo_edges_mod.load_edges(repo_storage) or _repo_edges_mod.compute_edges(repo_root)
    from mercator import repo_boundaries as _repo_bnd_mod
    try:
        repo_bnd_doc = _repo_bnd_mod.load(repo_storage)
    except ValueError:
        repo_bnd_doc = {}
    repo_bnd_violations = (
        _repo_bnd_mod.evaluate(projects_doc, repo_edges_doc, repo_bnd_doc) if repo_bnd_doc else []
    )
    repo_bnd_rules = (
        _repo_bnd_mod.summarise_rules(projects_doc, repo_edges_doc, repo_bnd_doc) if repo_bnd_doc else []
    )
    index_html = _atlas_html.render_repo_index(
        bundles=bundles,
        mercator_version=_version,
        schema_version=_schema,
        repo_meta=repo_meta,
        projects_doc=projects_doc,
        repo_edges=repo_edges_doc,
        repo_boundaries={"rules": repo_bnd_rules, "violations": repo_bnd_violations}
                       if repo_bnd_doc else None,
    )
    out = repo_storage / "atlas.html"
    out.write_text(index_html, encoding="utf-8")
    return out
