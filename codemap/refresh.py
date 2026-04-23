"""Full and incremental refresh across stacks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Set

from codemap import meta, paths
from codemap import boundaries as boundaries_mod
from codemap.detect import detect
from codemap.render import systems_md, contract_md, graph_md, boundaries_md
from codemap.stacks import rust, unity, dart, ts


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _load_systems(codemap_dir: Path) -> Optional[dict]:
    p = codemap_dir / "systems.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Full refresh
# ---------------------------------------------------------------------------

def _refresh_rust(project_root: Path, codemap_dir: Path, affected: Optional[Set[str]]):
    systems_doc = rust.build_systems(project_root)
    _write_json(codemap_dir / "systems.json", systems_doc)
    (codemap_dir / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")

    contracts_dir = codemap_dir / "contracts"
    contracts_dir.mkdir(exist_ok=True)

    written = 0
    for s in systems_doc["systems"]:
        name = s["name"]
        if affected is not None and name not in affected:
            continue
        manifest_rel = s["manifest_path"]
        doc = rust.build_contract(project_root, name, manifest_rel)
        _write_json(contracts_dir / f"{name}.json", doc)
        (contracts_dir / f"{name}.md").write_text(contract_md.render(doc), encoding="utf-8")
        written += 1

    return systems_doc, written


def _refresh_unity(project_root: Path, codemap_dir: Path, affected: Optional[Set[str]]):
    systems_doc = unity.build_systems(project_root)
    _write_json(codemap_dir / "systems.json", systems_doc)
    (codemap_dir / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")
    return systems_doc, 0  # no Layer 2 yet for Unity


def _refresh_dart(project_root: Path, codemap_dir: Path, affected: Optional[Set[str]]):
    systems_doc = dart.build_systems(project_root)
    _write_json(codemap_dir / "systems.json", systems_doc)
    (codemap_dir / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")
    return systems_doc, 0


def _refresh_ts(project_root: Path, codemap_dir: Path, affected: Optional[Set[str]]):
    systems_doc = ts.build_systems(project_root)
    _write_json(codemap_dir / "systems.json", systems_doc)
    (codemap_dir / "systems.md").write_text(systems_md.render(systems_doc), encoding="utf-8")
    return systems_doc, 0


def refresh(project_root: Path, *, affected: Optional[Set[str]] = None) -> dict:
    """Regenerate all codemap artefacts (or only `affected` systems' Layer 2)."""
    codemap_dir = paths.ensure_codemap_dir(project_root)
    stack = detect(project_root)
    meta.write(project_root, codemap_dir, stack)

    if stack == "rust":
        systems_doc, contract_count = _refresh_rust(project_root, codemap_dir, affected)
    elif stack == "unity":
        systems_doc, contract_count = _refresh_unity(project_root, codemap_dir, affected)
    elif stack == "dart":
        systems_doc, contract_count = _refresh_dart(project_root, codemap_dir, affected)
    elif stack == "ts":
        systems_doc, contract_count = _refresh_ts(project_root, codemap_dir, affected)
    elif stack == "unknown":
        raise ValueError(
            "unsupported stack — no recognised manifest found (expected one of: "
            "Cargo.toml, Assets/+ProjectSettings/+Packages/manifest.json, pubspec.yaml, "
            "package.json, pyproject.toml, go.mod)"
        )
    else:
        raise ValueError(
            f"stack '{stack}' detected but Layer 1 not yet implemented (implemented: rust, unity, dart, ts)"
        )

    # Visual views regenerate every refresh so `.codemap/graph.md` +
    # `boundaries.md` stay current alongside the JSON sources of truth.
    try:
        bnd_doc = boundaries_mod.load(project_root)
    except ValueError:
        bnd_doc = {}  # Keep refresh atomic — surface the error via `codemap check`.
    (codemap_dir / "graph.md").write_text(graph_md.render(systems_doc, bnd_doc), encoding="utf-8")
    (codemap_dir / "boundaries.md").write_text(boundaries_md.render(systems_doc, bnd_doc), encoding="utf-8")

    return {
        "stack": stack,
        "systems_count": len(systems_doc.get("systems", [])),
        "contracts_written": contract_count,
    }


# ---------------------------------------------------------------------------
# Incremental refresh (hook-driven)
# ---------------------------------------------------------------------------

def files_to_affected_systems(project_root: Path, changed_files: Iterable[str]) -> Set[str]:
    """Map a list of changed file paths to the set of system names to regen."""
    systems_doc = _load_systems(paths.codemap_dir(project_root))
    if not systems_doc:
        return set()
    stack = systems_doc.get("stack", "")
    affected: Set[str] = set()
    changed_paths = [Path(c).as_posix() for c in changed_files]

    if stack == "rust":
        # A crate's src tree is everything under <crate_root>/src.
        for s in systems_doc["systems"]:
            manifest_rel = s.get("manifest_path", "")
            if not manifest_rel:
                continue
            crate_scope = manifest_rel.rsplit("/", 1)[0] if "/" in manifest_rel else ""
            for p in changed_paths:
                if p == manifest_rel or (crate_scope and p.startswith(crate_scope + "/")):
                    affected.add(s["name"])
                    break
    elif stack == "unity":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            for p in changed_paths:
                if p == s.get("manifest_path") or (scope and (p == scope or p.startswith(scope + "/"))):
                    affected.add(s["name"])
                    break
    elif stack == "dart":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            for p in changed_paths:
                if scope in (".", "") or p == s.get("manifest_path") or p.startswith(scope + "/"):
                    affected.add(s["name"])
                    break
    elif stack == "ts":
        for s in systems_doc["systems"]:
            scope = s.get("scope_dir", "")
            manifest = s.get("manifest_path", "")
            for p in changed_paths:
                if scope in (".", "") or p == manifest or p.startswith(scope + "/"):
                    affected.add(s["name"])
                    break
    return affected
