"""Full and incremental refresh across stacks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Set

from mercator import meta, paths
from mercator import boundaries as boundaries_mod
from mercator.detect import detect
from mercator.render import systems_md, contract_md, graph_md, boundaries_md
from mercator.stacks import rust, unity, dart, ts
from mercator.stacks import rust_assets, unity_assets, dart_assets

from mercator import SCHEMA_VERSION


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


# ---------------------------------------------------------------------------
# Layer 4 — assets + strings
# ---------------------------------------------------------------------------

def _empty_layer4(stack: str, layer: str) -> dict:
    """Placeholder payload for stacks with no Layer 4 implementation yet."""
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


def _refresh_layer4(stack: str, project_root: Path, codemap_dir: Path) -> None:
    """Write .mercator/assets.json + .mercator/strings.json for the active stack.

    Stacks without a Layer 4 module get a `status: not_implemented` payload so
    callers always find a valid JSON document at the expected path. Any
    per-stack failure is caught and swallowed into a status payload — Layer 4
    must never abort a full refresh.
    """
    assets_path = codemap_dir / "assets.json"
    strings_path = codemap_dir / "strings.json"

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
        _write_json(assets_path, mod.build_assets(project_root))
    except Exception as exc:  # noqa: BLE001 — never abort refresh
        _write_json(assets_path, {
            "schema_version": SCHEMA_VERSION,
            "layer": "assets",
            "stack": stack,
            "status": "error",
            "error": str(exc),
            "assets": [],
        })
    try:
        _write_json(strings_path, mod.build_strings(project_root))
    except Exception as exc:  # noqa: BLE001
        _write_json(strings_path, {
            "schema_version": SCHEMA_VERSION,
            "layer": "strings",
            "stack": stack,
            "status": "error",
            "error": str(exc),
            "strings": [],
        })


def refresh(project_root: Path, *, affected: Optional[Set[str]] = None) -> dict:
    """Regenerate all mercator artefacts (or only `affected` systems' Layer 2)."""
    codemap_dir = paths.ensure_mercator_dir(project_root)
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

    # Layer 4: assets + user-facing strings. Always regenerated on a full
    # refresh — asset sets shift independently of code, and the scan is fast.
    # Incremental (`affected`) refreshes skip Layer 4 to stay cheap.
    if affected is None:
        _refresh_layer4(stack, project_root, codemap_dir)

    # Visual views regenerate every refresh so `.mercator/graph.md` +
    # `boundaries.md` stay current alongside the JSON sources of truth.
    try:
        bnd_doc = boundaries_mod.load(project_root)
    except ValueError:
        bnd_doc = {}  # Keep refresh atomic — surface the error via `mercator check`.
    (codemap_dir / "graph.md").write_text(graph_md.render(systems_doc, bnd_doc), encoding="utf-8")
    (codemap_dir / "boundaries.md").write_text(boundaries_md.render(systems_doc, bnd_doc), encoding="utf-8")

    # Count Layer 4 results (read back; cheap — already written).
    assets_count = 0
    strings_count = 0
    try:
        with (codemap_dir / "assets.json").open("r", encoding="utf-8") as f:
            assets_count = len(json.load(f).get("assets") or [])
    except (OSError, ValueError):
        pass
    try:
        with (codemap_dir / "strings.json").open("r", encoding="utf-8") as f:
            strings_count = len(json.load(f).get("strings") or [])
    except (OSError, ValueError):
        pass

    return {
        "stack": stack,
        "systems_count": len(systems_doc.get("systems", [])),
        "contracts_written": contract_count,
        "assets_count": assets_count,
        "strings_count": strings_count,
    }


# ---------------------------------------------------------------------------
# Incremental refresh (hook-driven)
# ---------------------------------------------------------------------------

def files_to_affected_systems(project_root: Path, changed_files: Iterable[str]) -> Set[str]:
    """Map a list of changed file paths to the set of system names to regen."""
    systems_doc = _load_systems(paths.mercator_dir(project_root))
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
